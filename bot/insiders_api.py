"""API narzędzia „Insajderzy" — panel, twarze na wykresie spółki, profil persony.

Podział na darmowe i płatne (decyzja właściciela, wrzesień 2026):

* **Panel** (`/api/insiders/panel`) — dla KAŻDEGO, także bez konta. Ranking
  person z wynikami i świeże transakcje widać w całości; to wizytówka.
  Aplikacja sama pilnuje, że bez premium nic tam nie da się kliknąć —
  każde dotknięcie prowadzi do strony sprzedażowej.
* **Transakcje spółki** (`/api/insiders/company/…`) — dla każdego, ale bez
  premium ZREDAGOWANE po stronie serwera: zostaje dzień, kierunek i cena (żeby
  znacznik stanął we właściwym miejscu wykresu), znika to, KTO i ZA ILE.
  Zamiast zdjęcia idzie jego rozmyta kopia pod nazwą, z której nie da się
  odczytać persony — inaczej wystarczyłoby zajrzeć w ruch sieciowy.
* **Profil, podsumowanie AI i obserwowanie** — tylko premium (402).

O premium decyduje serwer (`Viewer.premium`), nigdy aplikacja. Tryb podglądu
właściciela („pokaż widok bez premium") dzieje się wyłącznie w aplikacji:
serwer oddaje mu pełne dane, a aplikacja zasłania je sama.

Ścieżki `/api/insiders/*` są publiczne w bramce logowania (`dashboard.py`),
bo gość też ma zobaczyć twarze na wykresie. Obserwowanie leży pod
`/api/insider-follows` — POZA tym przedrostkiem, bo potrzebuje tożsamości
w bazie, którą bramka ustawia tylko na ścieżkach niepublicznych.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import re
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request

import supabase_auth as sa
from account_api import require_login, require_owner, require_premium, viewer
from insiders import follow, jobs, people, store
import paths

log = logging.getLogger("insiders_api")

router = APIRouter()

FEATURE = "tools.insiders"
HISTORIA_DNI = 730


# ------------------------------------------------------------------ persony


def _osoba(pid: str, wiersz: dict | None, stat: dict | None = None,
           aktywnosc: dict | None = None) -> dict:
    """Jedna persona w formacie aplikacji: katalog + ostatnie zgłoszenie + zdjęcie."""
    k = people.curated(pid) or {}
    w = wiersz or {}
    ex = w.get("extra") or {}
    nazwa = k.get("name") or w.get("name") or pid
    kat = k.get("cat") or w.get("cat") or "rada"
    rola = w.get("role") or ""
    org = people.skroc_spolke(w.get("org") or "")
    if w.get("source") == "oge":
        # Urząd przetłumaczony razem z resortem („Sekretarz transportu") nie
        # potrzebuje już angielskiej nazwy ministerstwa obok. Zostaje tylko przy
        # funkcjach ogólnych („Dyrektor"), gdzie bez niej nie wiadomo, czego.
        rola = people.urzad(ex.get("title_en") or rola, w.get("org") or "") or rola
        if rola not in ("Dyrektor", "Administrator", "Przewodniczący", "Członek zarządu",
                        "Doradca", ex.get("title_en") or ""):
            org = ""
    out = {
        "id": pid, "name": nazwa, "cat": kat, "role": rola, "org": org,
        "short": _podpis(kat, nazwa, ex),
        "photo": people.foto(pid), "blur": people.foto_rozmyte(pid),
        "rank": k.get("rank", 0), "bio": k.get("bio", ""),
        "party": k.get("party") or ex.get("party") or "",
        "state": k.get("state") or ex.get("state") or "",
        "firma": bool(ex.get("firma")),
        # waluta kwot persony: insiderzy GPW handlują w złotówkach
        "cur": "PLN" if (w.get("source") == "gpw" or k.get("gpw")) else "USD",
        "source": w.get("source") or ("house" if k.get("house") else "oge" if k.get("oge") else "sec"),
    }
    if stat:
        out["stats"] = {x: stat.get(x) for x in
                        ("ret_12m", "coverage", "buys", "sells", "bought", "sold", "last",
                         "estimated", "options", "total", "tickers_12m")}
    if aktywnosc:
        out["activity"] = {x: aktywnosc.get(x) for x in
                           ("buys", "sells", "bought", "sold", "last", "last_filed", "tickers")}
    return out


def _podpis(kat: str, nazwa: str, ex: dict) -> str:
    """Jedno słowo pod twarzą na wykresie: nazwisko albo „Prezes", „Rada"…

    Dla osób publicznych (polityka, znani) nazwisko mówi wszystko. Dla prezesa
    nieznanej spółki nazwisko nic nie mówi — mówi funkcja."""
    if kat in ("politycy", "prezydent", "rzad", "znani"):
        return people.nazwisko(nazwa)
    if kat == "gpw" and ex.get("short"):
        return ex["short"]
    if ex.get("firma"):
        return "Fundusz" if kat == "wlasciciele" else "Firma"
    return ex.get("short") or {"prezesi": "Zarząd", "rada": "Rada",
                               "wlasciciele": "Udziałowiec"}.get(kat, "Insider")


_DOPISKI = re.compile(
    r"\s*[-–,]?\s*(\(?the\)?\s*)?((class|cl\.?|series)\s+[a-z0-9]\s+)?"
    r"(common\s+stock|common\s+shares|ordinary\s+shares|capital\s+stock|"
    r"american\s+depositary\s+shares?|adrs?|shares|stock)\s*$", re.I)


def _walor(nazwa: str) -> str:
    """„Bloom Energy Corporation Class A Common Stock" → „Bloom Energy".
    Formularz Kongresu opisuje papier, a w aplikacji wystarczy spółka."""
    s = _DOPISKI.sub("", nazwa or "").strip(" -–,")
    s = re.sub(r"\s*[-–]\s*$", "", s)
    return people.skroc_spolke(s) or (nazwa or "")


def _transakcja(t: dict) -> dict:
    return {
        "uid": t["uid"], "person": t["person"], "source": t["source"],
        "ticker": t["ticker"], "asset": _walor(t.get("asset") or ""), "side": t["side"],
        "date": t["date"], "filed": t.get("filed") or "",
        "shares": t.get("shares"), "price": t.get("price"),
        "lo": t.get("amt_lo"), "hi": t.get("amt_hi"),
        "options": bool(t.get("options")), "owner": t.get("owner") or "",
        "note": t.get("note") or "", "url": t.get("url") or "",
        "planned": bool(t.get("planned")), "cur": t.get("cur") or "USD",
    }


def _zamazana(t: dict, blur: str) -> dict:
    """Transakcja dla kogoś bez premium: gdzie i w którą stronę — nic ponad to.

    `who` to skrót z solą — pozwala aplikacji nie stawiać na wykresie dwudziestu
    twarzy tej samej osoby, a nie pozwala ustalić, kim ona jest."""
    return {
        "uid": hashlib.sha1(f"zam:{t['uid']}".encode()).hexdigest()[:16],
        "who": hashlib.sha1(f"kto:{people.blur_name(t['person'])}".encode()).hexdigest()[:10],
        "side": t["side"], "date": t["date"], "price": t.get("price"),
        "options": bool(t.get("options")), "locked": True, "blur": blur,
        "cur": t.get("cur") or "USD",
    }


def _przerzedz(trans: list[dict], na_osobe: int = 6) -> list[dict]:
    """Najwyżej kilka transakcji jednej osoby: największe i najnowsze.

    Dla widoku bez premium — tam i tak nie widać, kto to, a wykres Nvidii
    z pięćdziesięcioma zamazanymi kółkami jednej osoby niczego nie mówi."""
    wg: dict[str, list[dict]] = {}
    for t in trans:
        wg.setdefault(t["person"], []).append(t)
    zostaja = set()
    for lista in wg.values():
        if len(lista) <= na_osobe:
            zostaja.update(t["uid"] for t in lista)
            continue
        zostaja.update(t["uid"] for t in sorted(lista, key=lambda t: -_srodek(t))[:na_osobe - 2])
        zostaja.update(t["uid"] for t in sorted(lista, key=lambda t: t["date"], reverse=True)[:2])
    return [t for t in trans if t["uid"] in zostaja]


def _uid_konta(v: sa.Viewer) -> str:
    if v.user_id:
        return v.user_id
    if v.owner:
        try:
            return sa.owner_user_id()
        except Exception:  # noqa: BLE001
            return ""
    return ""


# -------------------------------------------------------------------- panel

_panel_cache: dict = {"at": 0.0, "data": None}


def _zbuduj_panel() -> dict:
    dzis = dt.date.today()
    od12 = (dzis - dt.timedelta(days=365)).isoformat()
    akt = {a["person"]: a for a in store.activity(od12)}

    # kogo pokazać w rankingu: cały katalog (jeśli ma cokolwiek w bazie)
    # + najaktywniejsi politycy + najwięksi kupujący z SEC w każdej klasie
    kandydaci: list[str] = []
    wszyscy_w_bazie = store.person_counts([p["id"] for p in people.KATALOG])
    kandydaci += [p["id"] for p in people.KATALOG if wszyscy_w_bazie.get(p["id"])]
    polityka = sorted((a for p, a in akt.items() if p.startswith(("house-", "oge-", "senat-"))),
                      key=lambda a: -(a["buys"] + a["sells"]))
    kandydaci += [a["person"] for a in polityka[:45]]

    od90 = (dzis - dt.timedelta(days=90)).isoformat()
    akt90 = [a for a in store.activity(od90, ("sec",)) if a["person"].startswith("sec-")]
    wiersze_sec = store.people_rows([a["person"] for a in akt90])
    for klasa in ("prezesi", "rada", "wlasciciele"):
        w_klasie = [a for a in akt90 if (wiersze_sec.get(a["person"]) or {}).get("cat") == klasa]
        w_klasie.sort(key=lambda a: -(a["bought"] or 0))
        kandydaci += [a["person"] for a in w_klasie[:14] if (a["bought"] or 0) > 0]
    # GPW: najwięksi kupujący z ostatnich trzech miesięcy (kwoty w złotówkach)
    akt_gpw = [a for a in store.activity(od90, ("gpw",)) if a["person"].startswith("gpw-")]
    akt_gpw.sort(key=lambda a: -(a["bought"] or 0))
    kandydaci += [a["person"] for a in akt_gpw[:18] if (a["bought"] or 0) > 0]
    kandydaci = list(dict.fromkeys(kandydaci))

    wiersze = store.people_rows(kandydaci)
    liderzy = []
    for pid in kandydaci:
        stat = store.stats_get(pid, 3 * 24 * 3600)
        liderzy.append(_osoba(pid, wiersze.get(pid), stat, akt.get(pid)))

    # świeże zgłoszenia: politycy i rząd w całości, z SEC tylko większe kwoty —
    # inaczej sto drobnych sprzedaży dziennie zasłoniłoby jedno ujawnienie Pelosi
    od_zgl = (dzis - dt.timedelta(days=45)).isoformat()
    wybrani = [p for p in kandydaci if not p.startswith(("sec-", "gpw-"))]
    feed = store.feed(od_zgl, limit=60, people=wybrani)
    feed += store.feed(od_zgl, limit=50, sides=("buy",), min_amt=100_000, sources=("sec",))
    feed += store.feed(od_zgl, limit=25, sides=("sell",), min_amt=2_000_000, sources=("sec",))
    # GPW osobno i z niższym progiem: 50 tys. zł to na naszej giełdzie już sygnał
    feed += store.feed(od_zgl, limit=30, sides=("buy",), min_amt=50_000, sources=("gpw",))
    feed += store.feed(od_zgl, limit=15, sides=("sell",), min_amt=500_000, sources=("gpw",))
    feed = list({t["uid"]: t for t in feed}.values())
    feed.sort(key=lambda t: (t.get("filed") or "", t["date"]), reverse=True)
    feed = feed[:110]
    brak = [t["person"] for t in feed if t["person"] not in wiersze]
    wiersze.update(store.people_rows(brak))
    osoby = {t["person"]: _osoba(t["person"], wiersze.get(t["person"]), None, akt.get(t["person"]))
             for t in feed}

    liczby = {k["id"]: 0 for k in people.KLASY}
    for o in liderzy:
        liczby[o["cat"]] = liczby.get(o["cat"], 0) + 1
    zliczenia = store.counts()
    return {
        "klasy": [{**k, "count": liczby.get(k["id"], 0)} for k in people.KLASY],
        "leaders": liderzy,
        "feed": [_transakcja(t) for t in feed],
        "persons": osoby,
        "updated": zliczenia.get("newest_filed"),
        "sources": {"sec": zliczenia.get("trades_sec", 0), "house": zliczenia.get("trades_house", 0),
                    "oge": zliczenia.get("trades_oge", 0), "gpw": zliczenia.get("trades_gpw", 0),
                    "f13": zliczenia.get("trades_f13", 0), "senat": zliczenia.get("trades_senat", 0)},
        "ready": bool(store.kv_get("init_done")) or zliczenia.get("trades", 0) > 0,
    }


# Panel jest WSPÓLNY dla wszystkich — ranking i świeże zgłoszenia nie zależą od
# tego, kto pyta. Liczymy go więc raz, w tle, i trzymamy gotowy: w pamięci i w
# pliku na woluminie (po restarcie serwera pierwszy użytkownik nie czeka na
# przeliczenie). Żądanie użytkownika NIGDY nie buduje panelu, jeśli jakaś wersja
# już istnieje — dostaje ją od razu, a przeliczenie rusza w tle, gdy wersja ma
# ponad PANEL_WIEK sekund. Nowe zgłoszenia pojawiają się więc najpóźniej po
# kilku minutach od wczytania ich przez zegar insiderów.
PANEL_WIEK = 120
_panel_zamek = threading.Lock()
_PANEL_PLIK = paths.data_path("insiders_panel.json")


def _przelicz_panel() -> None:
    if not _panel_zamek.acquire(blocking=False):
        return                                  # już ktoś liczy
    try:
        dane = _zbuduj_panel()
        _panel_cache["data"], _panel_cache["at"] = dane, time.time()
        try:
            tmp = _PANEL_PLIK + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"at": _panel_cache["at"], "data": dane}, f, ensure_ascii=False)
            os.replace(tmp, _PANEL_PLIK)
        except OSError as e:
            log.info("Zapis panelu insiderów: %s", e)
    except Exception:  # noqa: BLE001 — stara wersja zostaje, spróbujemy za chwilę
        log.exception("Przeliczenie panelu insiderów")
    finally:
        _panel_zamek.release()


def _wspolny_panel() -> dict:
    if not _panel_cache["data"]:
        try:
            with open(_PANEL_PLIK, encoding="utf-8") as f:
                z = json.load(f)
            _panel_cache["data"], _panel_cache["at"] = z["data"], float(z["at"])
        except (OSError, ValueError, KeyError):
            _przelicz_panel()                   # pierwszy raz w życiu woluminu
    if time.time() - _panel_cache["at"] > PANEL_WIEK:
        threading.Thread(target=_przelicz_panel, daemon=True, name="insiders-panel").start()
    return _panel_cache["data"] or {}


@router.get("/api/insiders/panel")
def panel(v: sa.Viewer = Depends(viewer)):
    data = dict(_wspolny_panel())
    uid = _uid_konta(v) if v.premium else ""
    data["follows"] = follow.moje(uid) if uid else []
    data["premium"] = bool(v.premium)
    data["logged_in"] = bool(v.logged_in)
    return data


# ------------------------------------------------------------------- spółka


def _tickery(symbol: str) -> list[str]:
    """Symbol z karty spółki → tickery w bazie. Notowania spoza USA („CDR.WA")
    nie mają zgłoszeń w SEC, więc od razu pusta lista."""
    s = (symbol or "").strip().upper()
    if s.endswith(".US"):
        s = s[:-3]
    # GPW: Yahoo „CDR.WA", XTB „CDR.PL" — w bazie trzymamy zapis Yahoo
    if s.endswith((".WA", ".PL")) and re.fullmatch(r"[A-Z0-9]{1,8}\.(WA|PL)", s):
        return [s[:-3] + ".WA"]
    if "." in s or "=" in s or s.startswith("^"):
        return []
    s = s.replace("/", "-")
    if not re.fullmatch(r"[A-Z0-9\-]{1,10}", s):
        return []
    return [s]


@router.get("/api/insiders/company/{symbol}")
def company(symbol: str, v: sa.Viewer = Depends(viewer)):
    tick = _tickery(symbol)
    od = (dt.date.today() - dt.timedelta(days=HISTORIA_DNI)).isoformat()
    trans = store.trades_for_tickers(tick, od, limit=900) if tick else []
    od12 = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    rok = [t for t in trans if t["date"] >= od12]
    kupna = [t for t in rok if t["side"] == "buy"]
    podsum = {
        "buys": len(kupna), "sells": len(rok) - len(kupna),
        "bought": round(sum(_srodek(t) for t in kupna), 2),
        "sold": round(sum(_srodek(t) for t in rok if t["side"] == "sell"), 2),
        "people": len({t["person"] for t in rok}), "total": len(trans),
        "last": trans[0]["date"] if trans else None,
        # spółka z GPW = transakcje w złotówkach, reszta w dolarach
        "cur": "PLN" if tick and tick[0].endswith(".WA") else "USD",
    }
    if not v.premium:
        return {"symbol": symbol, "tickers": tick, "locked": True, "summary": podsum,
                "trades": [_zamazana(t, people.foto_rozmyte(t["person"])) for t in _przerzedz(trans)],
                "persons": {}}
    wiersze = store.people_rows(list({t["person"] for t in trans}))
    return {"symbol": symbol, "tickers": tick, "locked": False, "summary": podsum,
            "trades": [_transakcja(t) for t in trans],
            "persons": {p: _osoba(p, wiersze.get(p)) for p in {t["person"] for t in trans}}}


def _srodek(t: dict) -> float:
    lo, hi = t.get("amt_lo"), t.get("amt_hi")
    if lo is None and hi is None:
        return 0.0
    if hi is None or lo is None:
        return float(lo or hi)
    return (lo + hi) / 2


# -------------------------------------------------------------------- profil


@router.get("/api/insiders/person/{pid}")
def person(pid: str, v: sa.Viewer = Depends(require_premium(FEATURE))):
    from insiders import perf

    wiersz = store.people_rows([pid]).get(pid)
    if not wiersz and not people.curated(pid):
        raise HTTPException(404, "Nie znamy takiej persony")
    trans = store.trades_for_person(pid, limit=40000)
    stat = perf.statystyki(pid) if trans else None
    if stat:
        stat = {**stat, "alloc": [{**a, "name": _walor(a["name"]) if a.get("ticker") else a["name"]}
                                  for a in stat.get("alloc") or []]}
    uid = _uid_konta(v)
    obserwuje = pid in (follow.moje(uid) if uid else [])
    # tickery z nazwami spółek — do listy „co kupował" i do wykresu kołowego
    return {
        "person": _osoba(pid, wiersz, stat),
        "stats": stat,
        "trades": [_transakcja(t) for t in trans[:700]],
        "total": len(trans),
        "followed": obserwuje,
        "can_follow": bool(uid),
    }


@router.get("/api/insiders/person/{pid}/ai")
def person_ai(pid: str, again: int = 0, v: sa.Viewer = Depends(require_premium(FEATURE))):
    """Wspólne podsumowanie persony (24 h). `again=1` — przycisk „Zapytaj ponownie"."""
    from insiders import ai, perf

    trans = store.trades_for_person(pid, limit=60)
    if not trans:
        return {"text": None}
    try:
        wynik = None
        if not again:
            # najczęstszy przypadek: tekst już jest — bez liczenia statystyk
            stare = ai.zapisane(pid)
            if stare and time.time() - float(stare.get("at") or 0) < ai.WAZNE_S:
                store.ai_log_add("podsumowanie", ok=True)
                wynik = {**stare, "fresh": False}
        if wynik is None:
            osoba = _osoba(pid, store.people_rows([pid]).get(pid))
            rola = " · ".join(x for x in (osoba["role"], osoba["org"]) if x)
            wynik = ai.podsumowanie(pid, osoba["name"], rola, trans, perf.statystyki(pid),
                                    ponownie=bool(again))
    except Exception as e:  # noqa: BLE001 — podsumowanie to dodatek
        log.info("Podsumowanie AI %s: %s", pid, e)
        wynik = None
    if not wynik:
        return {"text": None}
    wiek = time.time() - float(wynik.get("at") or 0)
    return {"text": wynik["text"], "at": wynik.get("at"), "fresh": bool(wynik.get("fresh")),
            # przycisk ma sens dopiero, gdy serwer faktycznie napisze nowy tekst
            "again_in": max(0, int(ai.PONOWNIE_CO - wiek))}


# ------------------------------------------------------------- obserwowanie


@router.get("/api/insider-follows")
def follows_list(v: sa.Viewer = Depends(require_login)):
    uid = _uid_konta(v)
    ids = follow.moje(uid) if uid else []
    wiersze = store.people_rows(ids)
    return {"ids": ids, "persons": {p: _osoba(p, wiersze.get(p)) for p in ids}}


@router.post("/api/insider-follows")
async def follows_set(request: Request, v: sa.Viewer = Depends(require_premium(FEATURE))):
    body = await request.json()
    pid = str(body.get("id") or "").strip()
    if not pid:
        raise HTTPException(400, "Brak identyfikatora persony")
    uid = _uid_konta(v)
    if not uid:
        raise HTTPException(401, "Zaloguj się, żeby obserwować")
    wiersz = store.people_rows([pid]).get(pid)
    nazwa = (people.curated(pid) or {}).get("name") or (wiersz or {}).get("name") or pid
    try:
        ids = follow.ustaw(uid, pid, nazwa, bool(body.get("on", True)))
    except Exception as e:  # noqa: BLE001
        log.warning("Obserwowanie %s: %s", pid, e)
        raise HTTPException(503, "Obserwowanie jest chwilowo niedostępne") from e
    return {"ids": ids}


# -------------------------------------------------------------------- zdjęcia

_NAZWA_PLIKU = re.compile(r"^[a-z0-9-]{1,90}\.jpg$")


def _jpg(sciezka: str):
    import os
    from fastapi.responses import FileResponse
    if not os.path.isfile(sciezka):
        raise HTTPException(404, "Nie ma takiego zdjęcia")
    # adres zmienia się razem z plikiem (?v=…), więc może leżeć w pamięci długo
    return FileResponse(sciezka, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=604800"})


@router.get("/api/insiders/foto/{nazwa}")
def foto(nazwa: str):
    """Portrety pobrane przez serwer (oficjalne zdjęcia Kongresu) — z dysku danych,
    bo nie leżą w repozytorium. Zdjęcia właściciela idą przez /static."""
    if not _NAZWA_PLIKU.match(nazwa):
        raise HTTPException(404, "Nie ma takiego zdjęcia")
    return _jpg(people.plik_auto(nazwa))


@router.get("/api/insiders/foto/b/{nazwa}")
def foto_rozmyte(nazwa: str):
    if not _NAZWA_PLIKU.match(nazwa):
        raise HTTPException(404, "Nie ma takiego zdjęcia")
    import os
    return _jpg(people.plik_auto(os.path.join("b", nazwa)))


# ---------------------------------------------------------------- diagnostyka


@router.get("/api/insiders/status")
def status(_v=Depends(require_owner)):
    return jobs.stan()
