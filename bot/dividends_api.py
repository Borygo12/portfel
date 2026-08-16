"""API narzędzia „Inwestowanie dywidendowe" — skaner, kalendarz, kalkulator, ryzyko.

Podział na darmowe i płatne jest tu świadomy i wygląda tak:

* **Za darmo, ale po zalogowaniu:** skaner z pełnymi filtrami, kalendarz wypłat
  i kalkulator dochodu. To są rzeczy, dla których ktoś w ogóle tu przychodzi
  z wyszukiwarki — zablokowane nie sprzedałyby niczego, bo nie dałoby się
  ocenić, czy narzędzie jest cokolwiek warte.
* **Premium:** ocena bezpieczeństwa dywidendy, porównywarka aktywów, dopasowanie
  do portfela i realne dywidendy z wgranego raportu. Czyli to, co wymaga
  policzenia czegoś ponad przepisanie danych.

**Wszystko wymaga zalogowania**, także część darmowa. Podstrony pozycjonowane
zostają publiczne i to one odpowiadają na pytanie z wyszukiwarki; narzędzie
jest tym, po co się zakłada konto.

Wydajność: wiersz skanera dla jednej spółki wymaga historii wypłat (dysk),
bieżącej stopy (dysk) i metryk (liczenie). Dla trzystu spółek to zbyt dużo na
jedno żądanie, więc **gotowa tabela stoi w pamięci procesu** i odświeża się
w tle, tym samym mechanizmem co reszta warstwy (`seo/pamiec.py`). Braki
w historii dociąga osobny przebieg po starcie serwera.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request

import dividend_lab as lab
from account_api import require_login, require_premium
from seo import companies, pamiec

log = logging.getLogger("dividends_api")

router = APIRouter()

#: Przerwa między pobraniami przy uzupełnianiu historii w tle. Historia leży
#: w cache tydzień, więc ten przebieg schodzi raz na parę dni — może iść wolno.
PRZERWA_S = 3.0


# --------------------------------------------------------------- tabela


def _stopa_i_wyplata(symbol: str) -> tuple:
    """Bieżąca stopa i wskaźnik wypłaty z tego, co zebrał moduł SEO. Bez sieci."""
    from seo import dividends as seo_div

    dyw = seo_div.surowa(symbol)
    if not isinstance(dyw, dict):
        return None, None, "", False
    return (dyw.get("stopa_pct"), dyw.get("wyplata_pct"),
            dyw.get("bez_dywidendy") or "", bool(dyw.get("przyszla")))


def _kurs_i_kapitalizacja(symbol: str) -> tuple:
    try:
        from earnings import cache as e_cache
    except Exception:  # noqa: BLE001
        return None, None, ""
    r = e_cache.get(f"report-{symbol}", 30 * 24 * 3600) or {}
    return r.get("price"), r.get("market_cap"), r.get("currency") or ""


def _wiersz(s: dict) -> dict | None:
    """Jeden wiersz skanera. None, gdy spółka nie płaci albo nic o niej nie wiemy."""
    symbol = s["symbol"]
    m = lab.metryki(symbol)
    if not m.get("znane") or not m.get("placi"):
        return None

    stopa, wyplata, bez_dyw, przyszla = _stopa_i_wyplata(symbol)
    kurs, kap, waluta = _kurs_i_kapitalizacja(symbol)

    # Gdy Yahoo nie oddało bieżącej stopy, liczymy ją sami z ostatniego pełnego
    # roku wypłat i kursu. Lepsza policzona niż żadna — a bez stopy wiersz jest
    # dla kogoś szukającego dywidendy bezużyteczny.
    policzona = False
    if not isinstance(stopa, (int, float)) and kurs and m.get("suma_ostatni_pelny"):
        stopa = round(m["suma_ostatni_pelny"] / kurs * 100, 2)
        policzona = True

    if not isinstance(stopa, (int, float)) or stopa <= 0:
        return None

    dni_do = None
    if bez_dyw:
        try:
            dni_do = (dt.date.fromisoformat(bez_dyw) - dt.date.today()).days
        except ValueError:
            dni_do = None

    bezp = lab.bezpieczenstwo(m, stopa, wyplata)

    return {
        "symbol": symbol,
        "slug": s["slug"],
        "nazwa": s["name"],
        "ticker": companies.ticker(s),
        "rynek": s["market"],
        "sektor": s.get("sector_pl") or "",
        "sektor_en": s.get("sector") or "",
        "waluta": waluta or s.get("currency") or "",
        "kurs": kurs,
        "kapitalizacja": kap,
        "adres": companies.adres(s),
        "stopa": round(float(stopa), 2),
        "stopa_policzona": policzona,
        "wyplata": wyplata,
        "bez_dywidendy": bez_dyw,
        "dni_do_ex": dni_do,
        "ex_przyszla": przyszla,
        "seria_wzrostow": m.get("seria_wzrostow") or 0,
        "obcinala": bool(m.get("obcinala")),
        "wzrost_3l": m.get("wzrost_3l"),
        "wzrost_5l": m.get("wzrost_5l"),
        "lat_danych": m.get("lat_danych") or 0,
        "czestotliwosc": m.get("czestotliwosc") or 0,
        "czestotliwosc_pl": lab.czestotliwosc_pl(m.get("czestotliwosc") or 0),
        "na_akcje_rok": m.get("suma_ostatni_pelny"),
        "ocena": bezp.get("ocena"),
        "poziom": bezp.get("poziom"),
    }


def _zbuduj_tabele() -> list[dict]:
    wiersze = []
    for s in companies.SPOLKI:
        try:
            w = _wiersz(s)
        except Exception as e:  # noqa: BLE001
            log.warning("Wiersz dywidendowy %s: %s", s["symbol"], e)
            w = None
        if w:
            wiersze.append(w)
    wiersze.sort(key=lambda w: -w["stopa"])
    return wiersze


def tabela() -> list[dict]:
    return pamiec.zapamietane("dyw-tabela", _zbuduj_tabele)


# --------------------------------------------------------------- uzupełnianie


_uzupelnianie = threading.Lock()


def dopobierz_historie(przerwa_s: float = PRZERWA_S, limit: int = 0) -> int:
    """Ściąga historię wypłat dla spółek, które jej jeszcze nie mają.

    Ten sam powód co przy pozostałych przebiegach: kontener nie ma woluminu,
    więc po każdym wdrożeniu cache jest pusty, a bez historii skaner nie ma
    czego pokazać. Klucz Yahoo zdobywamy przed pętlą — bez tego cały przebieg
    odbijałby się od jego braku, co już raz nas kosztowało pół dnia.
    """
    if not _uzupelnianie.acquire(blocking=False):
        return 0
    try:
        from earnings import cache as e_cache

        brakujace = [s for s in companies.SPOLKI
                     if e_cache.get(f"divhist-{s['symbol']}", lab.TTL_HISTORII) is None]
        if limit:
            brakujace = brakujace[:limit]
        if not brakujace:
            return 0
        if not pamiec.poczekaj_na_yahoo():
            log.warning("Historia dywidend: brak klucza Yahoo")
            return 0

        log.info("Historia dywidend: dociągam %d spółek co %.1f s",
                 len(brakujace), przerwa_s)
        ile = 0
        for i, s in enumerate(brakujace):
            if i:
                time.sleep(przerwa_s)
            try:
                if lab.historia(s["symbol"]) is not None:
                    ile += 1
            except Exception as e:  # noqa: BLE001
                log.warning("Historia %s: %s", s["symbol"], e)
            if ile and (i + 1) % 25 == 0:
                pamiec.zapisz("dyw-tabela", _zbuduj_tabele())
                log.info("Historia dywidend: %d/%d", i + 1, len(brakujace))
        pamiec.zapisz("dyw-tabela", _zbuduj_tabele())
        log.info("Historia dywidend: gotowe %d z %d", ile, len(brakujace))
        return ile
    except Exception as e:  # noqa: BLE001
        log.warning("Dociąganie historii dywidend: %s", e)
        return 0
    finally:
        _uzupelnianie.release()


def rozgrzej_zadania():
    return (
        ("tabela dywidendowa z cache", tabela),
        ("historia wypłat — dociąganie", dopobierz_historie),
    )


# --------------------------------------------------------------- filtrowanie


def _filtruj(wiersze, q) -> list[dict]:
    """Zawężenie listy parametrami zapytania. Każdy filtr jest opcjonalny."""
    def liczba(nazwa):
        try:
            v = q.get(nazwa)
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    rynek = (q.get("rynek") or "").upper()
    sektor = (q.get("sektor") or "").strip().lower()
    szukaj = (q.get("szukaj") or "").strip().lower()
    czest = q.get("czestotliwosc")
    tylko_rosnace = (q.get("rosnace") or "") in ("1", "true")
    bez_obcinania = (q.get("bez_obcinania") or "") in ("1", "true")

    min_stopa, max_stopa = liczba("min_stopa"), liczba("max_stopa")
    max_wyplata = liczba("max_wyplata")
    min_seria = liczba("min_seria")
    min_wzrost = liczba("min_wzrost")
    min_ocena = liczba("min_ocena")

    out = []
    for w in wiersze:
        if rynek and w["rynek"] != rynek:
            continue
        if sektor and (w["sektor"] or "").lower() != sektor:
            continue
        if szukaj and szukaj not in w["nazwa"].lower() and szukaj not in w["ticker"].lower():
            continue
        if min_stopa is not None and w["stopa"] < min_stopa:
            continue
        if max_stopa is not None and w["stopa"] > max_stopa:
            continue
        if max_wyplata is not None:
            # Spółka bez znanego wskaźnika wypłaty NIE przechodzi tego filtru:
            # skoro ktoś świadomie ogranicza wypłatę, brak danych jest bliżej
            # „nie wiem, więc nie pokazuj" niż „na pewno mieści się w progu".
            if not isinstance(w["wyplata"], (int, float)) or w["wyplata"] > max_wyplata:
                continue
        if min_seria is not None and w["seria_wzrostow"] < min_seria:
            continue
        if min_wzrost is not None:
            v = w["wzrost_5l"] if w["wzrost_5l"] is not None else w["wzrost_3l"]
            if not isinstance(v, (int, float)) or v < min_wzrost:
                continue
        if min_ocena is not None and (w["ocena"] is None or w["ocena"] < min_ocena):
            continue
        if czest not in (None, "", "0") and str(w["czestotliwosc"]) != str(czest):
            continue
        if tylko_rosnace and w["seria_wzrostow"] < 1:
            continue
        if bez_obcinania and w["obcinala"]:
            continue
        out.append(w)
    return out


SORTOWANIA = {
    "stopa": lambda w: -w["stopa"],
    "seria": lambda w: (-w["seria_wzrostow"], -w["stopa"]),
    "wzrost": lambda w: -(w["wzrost_5l"] if w["wzrost_5l"] is not None
                          else (w["wzrost_3l"] if w["wzrost_3l"] is not None else -999)),
    "ocena": lambda w: (-(w["ocena"] if w["ocena"] is not None else -1), -w["stopa"]),
    "nazwa": lambda w: w["nazwa"].lower(),
    "termin": lambda w: (w["dni_do_ex"] if isinstance(w["dni_do_ex"], int)
                         and w["dni_do_ex"] >= 0 else 10 ** 6),
}


# --------------------------------------------------------------- endpointy


@router.get("/api/dividends/meta")
def meta(_v=Depends(require_login)):
    """Słowniki do filtrów plus stan zbierania danych."""
    w = tabela()
    sektory = sorted({x["sektor"] for x in w if x["sektor"]})
    return {
        "gotowe": len(w),
        "w_katalogu": len(companies.SPOLKI),
        "rynki": [{"id": "", "nazwa": "Wszystkie"},
                  {"id": "GPW", "nazwa": "GPW"},
                  {"id": "USA", "nazwa": "USA"}],
        "sektory": sektory,
        "czestotliwosci": [
            {"id": "", "nazwa": "Dowolna"},
            {"id": "12", "nazwa": "Co miesiąc"},
            {"id": "4", "nazwa": "Co kwartał"},
            {"id": "2", "nazwa": "Co pół roku"},
            {"id": "1", "nazwa": "Raz w roku"},
        ],
        "sortowania": [
            {"id": "stopa", "nazwa": "Najwyższa stopa"},
            {"id": "ocena", "nazwa": "Najbezpieczniejsza"},
            {"id": "seria", "nazwa": "Najdłuższa seria podwyżek"},
            {"id": "wzrost", "nazwa": "Najszybszy wzrost wypłaty"},
            {"id": "termin", "nazwa": "Najbliższy dzień bez dywidendy"},
            {"id": "nazwa", "nazwa": "Alfabetycznie"},
        ],
        "podatek": {"belka_pct": lab.PODATEK_PL, "zrodlo_usa_pct": lab.PODATEK_ZRODLO_USA},
    }


@router.get("/api/dividends/screen")
def screen(request: Request, _v=Depends(require_login)):
    q = request.query_params
    wiersze = _filtruj(tabela(), q)
    klucz = SORTOWANIA.get(q.get("sort") or "stopa", SORTOWANIA["stopa"])
    wiersze = sorted(wiersze, key=klucz)

    try:
        limit = max(1, min(int(q.get("limit") or 40), 200))
        offset = max(0, int(q.get("offset") or 0))
    except ValueError:
        limit, offset = 40, 0

    return {"total": len(wiersze), "rows": wiersze[offset:offset + limit],
            "offset": offset, "limit": limit}


@router.get("/api/dividends/calendar")
def calendar(dni: int = 120, rynek: str = "", _v=Depends(require_login)):
    """Nadchodzące dni bez dywidendy, pogrupowane po miesiącach."""
    dni = max(7, min(int(dni or 120), 400))
    dzis = dt.date.today()
    poz = [w for w in tabela()
           if isinstance(w["dni_do_ex"], int) and 0 <= w["dni_do_ex"] <= dni
           and (not rynek or w["rynek"] == rynek.upper())]
    poz.sort(key=lambda w: (w["dni_do_ex"], -w["stopa"]))

    miesiace: dict[str, list] = {}
    for w in poz:
        miesiace.setdefault(w["bez_dywidendy"][:7], []).append(w)

    return {
        "od": dzis.isoformat(),
        "dni": dni,
        "razem": len(poz),
        "miesiace": [{"miesiac": k, "pozycje": v} for k, v in sorted(miesiace.items())],
        # Historyczne terminy z ostatniego roku — po nich widać sezonowość,
        # czyli kiedy w ogóle warto się rozglądać za wypłatami na GPW.
        "sezonowosc": _sezonowosc(rynek),
    }


def _sezonowosc(rynek: str = "") -> list[dict]:
    """Ile spółek wypłacało w danym miesiącu — na podstawie ostatniego pełnego roku."""
    licznik = {m: 0 for m in range(1, 13)}
    for w in tabela():
        if rynek and w["rynek"] != rynek.upper():
            continue
        wyplaty = lab.historia(w["symbol"]) or []
        rok = dt.date.today().year - 1
        for p in wyplaty:
            if int(p["data"][:4]) == rok:
                licznik[int(p["data"][5:7])] += 1
    return [{"miesiac": m, "ile": licznik[m]} for m in range(1, 13)]


@router.get("/api/dividends/asset/{symbol}")
def asset(symbol: str, _v=Depends(require_login)):
    """Karta jednego aktywa: historia wypłat, miary i ocena bezpieczeństwa."""
    s = companies.po_symbolu(symbol) or companies.po_slugu(symbol)
    if not s:
        raise HTTPException(404, "Nie ma takiego aktywa w katalogu")

    m = lab.metryki(s["symbol"])
    stopa, wyplata, bez_dyw, przyszla = _stopa_i_wyplata(s["symbol"])
    kurs, kap, waluta = _kurs_i_kapitalizacja(s["symbol"])
    return {
        "symbol": s["symbol"],
        "nazwa": s["name"],
        "ticker": companies.ticker(s),
        "rynek": s["market"],
        "sektor": s.get("sector_pl") or "",
        "waluta": waluta or s.get("currency") or "",
        "kurs": kurs,
        "adres": companies.adres(s),
        "stopa": stopa,
        "wyplata": wyplata,
        "bez_dywidendy": bez_dyw,
        "ex_przyszla": przyszla,
        "metryki": m,
        "bezpieczenstwo": lab.bezpieczenstwo(m, stopa, wyplata),
    }


@router.post("/api/dividends/calculator")
async def calculator(request: Request, _v=Depends(require_login)):
    """Projekcja dochodu z dywidend. Przyjmuje albo gotowe parametry, albo koszyk."""
    body = await request.json()

    koszyk = body.get("koszyk") or []
    kwota = float(body.get("kwota") or 0)
    lat = int(body.get("lat") or 10)
    reinwestycja = bool(body.get("reinwestycja", True))
    doplata = float(body.get("doplata_roczna") or 0)
    w8ben = bool(body.get("w8ben", True))

    if koszyk:
        # Koszyk: każda pozycja ma symbol i udział procentowy. Liczymy średnią
        # ważoną stopy i wzrostu, a podatek bierzemy z przewagi rynku — inaczej
        # trzeba by robić osobną projekcję na pozycję i sumować wykresy, co przy
        # czterech aktywach daje wykres nie do odczytania.
        po_symbolu = {w["symbol"]: w for w in tabela()}
        suma_udzialow = 0.0
        stopa_w = wzrost_w = 0.0
        usa_udzial = 0.0
        skladniki = []
        for poz in koszyk[:8]:
            w = po_symbolu.get((poz.get("symbol") or "").upper())
            if not w:
                continue
            udzial = max(float(poz.get("udzial") or 0), 0.0)
            if udzial <= 0:
                continue
            wzrost = w["wzrost_5l"] if w["wzrost_5l"] is not None else (w["wzrost_3l"] or 0)
            stopa_w += w["stopa"] * udzial
            wzrost_w += (wzrost or 0) * udzial
            if w["rynek"] == "USA":
                usa_udzial += udzial
            suma_udzialow += udzial
            skladniki.append({"symbol": w["symbol"], "nazwa": w["nazwa"],
                              "udzial": udzial, "stopa": w["stopa"],
                              "wzrost": wzrost, "rynek": w["rynek"]})
        if not suma_udzialow:
            raise HTTPException(400, "Koszyk jest pusty albo nie zawiera znanych aktywów")
        stopa = stopa_w / suma_udzialow
        wzrost = wzrost_w / suma_udzialow
        rynek = "USA" if usa_udzial / suma_udzialow > 0.5 else "GPW"
    else:
        stopa = float(body.get("stopa") or 0)
        wzrost = float(body.get("wzrost") or 0)
        rynek = (body.get("rynek") or "GPW").upper()
        skladniki = []

    wynik = lab.projekcja(kwota, stopa, wzrost, lat=lat, reinwestycja=reinwestycja,
                          rynek=rynek, doplata_roczna=doplata, w8ben=w8ben)
    wynik["skladniki"] = skladniki
    wynik["stopa_koszyka"] = round(stopa, 2)
    wynik["wzrost_koszyka"] = round(wzrost, 2)
    return wynik


@router.post("/api/dividends/compare")
async def compare(request: Request, _v=Depends(require_premium("tools.dividends"))):
    """Porównanie do czterech aktywów obok siebie, z historią wypłat do wykresu."""
    body = await request.json()
    symbole = [str(s).upper() for s in (body.get("symbole") or [])][:4]
    if not symbole:
        raise HTTPException(400, "Podaj od jednego do czterech symboli")

    out = []
    for sym in symbole:
        s = companies.po_symbolu(sym) or companies.po_slugu(sym.lower())
        if not s:
            continue
        m = lab.metryki(s["symbol"])
        stopa, wyplata, bez_dyw, _ = _stopa_i_wyplata(s["symbol"])
        kurs, _, waluta = _kurs_i_kapitalizacja(s["symbol"])
        out.append({
            "symbol": s["symbol"], "nazwa": s["name"], "ticker": companies.ticker(s),
            "rynek": s["market"], "sektor": s.get("sector_pl") or "",
            "waluta": waluta or s.get("currency") or "", "kurs": kurs,
            "stopa": stopa, "wyplata": wyplata, "bez_dywidendy": bez_dyw,
            "lata": m.get("lata") or {},
            "seria_wzrostow": m.get("seria_wzrostow") or 0,
            "obcinala": bool(m.get("obcinala")),
            "wzrost_5l": m.get("wzrost_5l"), "wzrost_3l": m.get("wzrost_3l"),
            "czestotliwosc_pl": lab.czestotliwosc_pl(m.get("czestotliwosc") or 0),
            "bezpieczenstwo": lab.bezpieczenstwo(m, stopa, wyplata),
        })
    if not out:
        raise HTTPException(404, "Żaden z podanych symboli nie jest w katalogu")

    # Wspólne lata, żeby wykres porównawczy miał tę samą oś dla wszystkich.
    lata = sorted({r for a in out for r in (a["lata"] or {})})
    return {"aktywa": out, "lata": lata}


# --------------------------------------------------------------- twój portfel


def _pozycje_z_katalogiem():
    """Pozycje portfela sparowane z katalogiem. [(pozycja, spółka, wiersz)]."""
    from portfolio import engine as pf_engine
    from portfolio import market as pf_market

    d = pf_engine.compute()
    if d.get("empty"):
        return [], d
    po_symbolu = {w["symbol"]: w for w in tabela()}

    pary = []
    for p in d.get("positions", []):
        if p.get("no_price"):
            continue
        try:
            sym = pf_market.resolve(p["ticker"])
        except Exception:  # noqa: BLE001
            sym = (p.get("ticker") or "").upper()
        s = companies.po_symbolu(sym)
        pary.append((p, s, po_symbolu.get(sym) if s else None))
    return pary, d


@router.get("/api/dividends/portfolio")
def portfolio(_v=Depends(require_premium("tools.dividends"))):
    """Ile dywidend realnie płyną z tego, co masz w portfelu.

    Roczną wypłatę liczymy jako **wartość pozycji razy stopa dywidendy**, a nie
    z kwoty na akcję. Powód jest prozaiczny: wartość pozycji jest już
    przeliczona na złotówki po dzisiejszym kursie walutowym, a kwota na akcję
    przychodzi w walucie notowania. Idąc drugą drogą trzeba by przewalutowywać
    ręcznie i o pomyłkę byłoby łatwo, a wynik jest ten sam.

    Yield on cost porównuje tę wypłatę z tym, co REALNIE wydałeś (`cost_pln`),
    a nie z dzisiejszą wyceną. To jest sedno inwestowania dywidendowego: spółka
    kupiona dziesięć lat temu potrafi dziś płacić kilkanaście procent Twojego
    wkładu, choć w tabelach widnieje przy niej skromne trzy procent.
    """
    pary, d = _pozycje_z_katalogiem()
    if not pary:
        return {"empty": True}

    pozycje, bez_dywidendy, poza_katalogiem = [], [], []
    roczna = koszt_placacych = wartosc_placacych = 0.0

    for p, s, w in pary:
        if s is None:
            poza_katalogiem.append({"ticker": p["ticker"], "nazwa": p.get("name") or p["ticker"],
                                    "wartosc": p["value_pln"]})
            continue
        if w is None:
            bez_dywidendy.append({"ticker": p["ticker"], "nazwa": s["name"],
                                  "wartosc": p["value_pln"], "adres": companies.adres(s)})
            continue

        rocznie = p["value_pln"] * w["stopa"] / 100
        koszt = p.get("cost_pln") or 0.0
        podatek = lab.po_podatku(rocznie, w["rynek"])
        roczna += rocznie
        koszt_placacych += koszt
        wartosc_placacych += p["value_pln"]

        pozycje.append({
            "ticker": p["ticker"],
            "symbol": w["symbol"],
            "nazwa": w["nazwa"],
            "adres": w["adres"],
            "rynek": w["rynek"],
            "wartosc": round(p["value_pln"], 2),
            "koszt": round(koszt, 2),
            "stopa": w["stopa"],
            "rocznie_brutto": round(rocznie, 2),
            "rocznie_netto": podatek["netto"],
            "miesiecznie_netto": round(podatek["netto"] / 12, 2),
            "yield_on_cost": round(rocznie / koszt * 100, 2) if koszt > 1e-9 else None,
            "seria_wzrostow": w["seria_wzrostow"],
            "ocena": w["ocena"],
            "poziom": w["poziom"],
            "bez_dywidendy": w["bez_dywidendy"],
            "dni_do_ex": w["dni_do_ex"],
            "czestotliwosc_pl": w["czestotliwosc_pl"],
        })

    pozycje.sort(key=lambda x: -x["rocznie_brutto"])
    netto = sum(x["rocznie_netto"] for x in pozycje)
    wartosc_calosci = sum(p["value_pln"] for p, _, _ in pary)

    najblizsze = sorted(
        [x for x in pozycje if isinstance(x["dni_do_ex"], int) and x["dni_do_ex"] >= 0],
        key=lambda x: x["dni_do_ex"])[:6]

    return {
        "empty": False,
        "pozycje": pozycje,
        "bez_dywidendy": bez_dywidendy,
        "poza_katalogiem": poza_katalogiem,
        "podsumowanie": {
            "rocznie_brutto": round(roczna, 2),
            "rocznie_netto": round(netto, 2),
            "miesiecznie_netto": round(netto / 12, 2),
            "podatek_rocznie": round(roczna - netto, 2),
            "stopa_portfela": round(roczna / wartosc_calosci * 100, 2) if wartosc_calosci else 0.0,
            "stopa_placacych": round(roczna / wartosc_placacych * 100, 2) if wartosc_placacych else 0.0,
            "yield_on_cost": round(roczna / koszt_placacych * 100, 2) if koszt_placacych > 1e-9 else None,
            "wartosc_calosci": round(wartosc_calosci, 2),
            "wartosc_placacych": round(wartosc_placacych, 2),
            "udzial_placacych_pct": round(wartosc_placacych / wartosc_calosci * 100, 1) if wartosc_calosci else 0.0,
            "pozycji_placacych": len(pozycje),
            "pozycji_bez": len(bez_dywidendy),
        },
        "najblizsze_wyplaty": najblizsze,
    }


@router.get("/api/dividends/fit")
def fit(limit: int = 8, _v=Depends(require_premium("tools.dividends"))):
    """Czego brakuje portfelowi, żeby dochód z dywidend stał na szerszej podstawie.

    **Jak dobieramy i czego tu NIE ma.** Podpowiedzi opierają się na branży,
    rynku i jakości wypłaty, a nie na zmierzonej korelacji z Twoimi pozycjami.
    Policzenie korelacji trzystu kandydatów z każdą pozycją naraz oznaczałoby
    kilkaset serii notowań przy jednym kliknięciu — tego się nie da zrobić
    w czasie jednego żądania i nie warto udawać, że się da. Zmierzoną korelację
    tego, co JUŻ masz, pokazuje Mapa korelacji; tutaj chodzi o kierunek
    poszukiwań, a nie o wyrocznię.

    Zasada doboru jest prosta i jawna: premiujemy branże, których w portfelu
    nie ma albo jest ich mało, oraz spółki z długą serią podwyżek i bez
    obcięcia w historii. Karzemy skrajnie wysokie stopy, bo te najczęściej
    biorą się ze spadku kursu.
    """
    pary, _ = _pozycje_z_katalogiem()
    if not pary:
        return {"empty": True}

    wartosc = sum(p["value_pln"] for p, _, _ in pary) or 1.0
    udzial_branz: dict[str, float] = {}
    udzial_rynkow: dict[str, float] = {}
    mam: set[str] = set()
    for p, s, _w in pary:
        if not s:
            continue
        mam.add(s["symbol"])
        b = s.get("sector_pl") or "inne"
        udzial_branz[b] = udzial_branz.get(b, 0.0) + p["value_pln"] / wartosc
        udzial_rynkow[s["market"]] = udzial_rynkow.get(s["market"], 0.0) + p["value_pln"] / wartosc

    najwieksza_branza = max(udzial_branz.items(), key=lambda x: x[1]) if udzial_branz else ("", 0.0)

    propozycje = []
    for w in tabela():
        if w["symbol"] in mam or w["ocena"] is None:
            continue
        branza = w["sektor"] or "inne"
        ma_branze = udzial_branz.get(branza, 0.0)

        punkty = w["ocena"] * 0.5
        # Branża, której nie masz wcale, jest wartościowsza niż dołożenie do tej,
        # w której siedzi już połowa portfela.
        punkty += 25 if ma_branze == 0 else max(0.0, 20 * (1 - ma_branze * 4))
        # Rynek niedoważony — walutowo to inna noga, nawet przy tej samej branży.
        punkty += 10 * (1 - udzial_rynkow.get(w["rynek"], 0.0))
        punkty += min(w["seria_wzrostow"], 12) * 1.2
        if w["obcinala"]:
            punkty -= 12
        if w["stopa"] > 10:
            punkty -= 15

        powod = (f"Branża „{branza}”, której nie masz w portfelu" if ma_branze == 0
                 else f"Branża „{branza}” to dopiero {ma_branze * 100:.0f}% portfela")
        if w["seria_wzrostow"] >= 5:
            powod += f"; podnosi dywidendę {w['seria_wzrostow']} lat z rzędu"

        propozycje.append({**w, "punkty": round(punkty, 1), "powod": powod})

    propozycje.sort(key=lambda x: -x["punkty"])

    ostrzezenia = []
    if najwieksza_branza[1] > 0.4:
        ostrzezenia.append(
            f"Branża „{najwieksza_branza[0]}” to {najwieksza_branza[1] * 100:.0f}% portfela. "
            "Dywidendy z jednej branży wysychają razem — banki obcięły je jednocześnie "
            "w 2020 roku, bo tak zdecydował nadzór, a nie każdy bank osobno.")
    for rynek, udzial in udzial_rynkow.items():
        if udzial > 0.85:
            ostrzezenia.append(
                f"Prawie cały portfel ({udzial * 100:.0f}%) to jeden rynek: {rynek}. "
                "Przy wypłatach w jednej walucie kurs walutowy staje się drugim, "
                "niewidocznym źródłem wahań Twojego dochodu.")

    return {
        "empty": False,
        "udzial_branz": [{"branza": k, "udzial": round(v * 100, 1)}
                         for k, v in sorted(udzial_branz.items(), key=lambda x: -x[1])],
        "udzial_rynkow": [{"rynek": k, "udzial": round(v * 100, 1)}
                          for k, v in sorted(udzial_rynkow.items(), key=lambda x: -x[1])],
        "ostrzezenia": ostrzezenia,
        "propozycje": propozycje[:max(1, min(int(limit or 8), 20))],
        "metoda": ("Dobór po branży, rynku i jakości wypłaty — nie po zmierzonej "
                   "korelacji. Korelację tego, co już masz, liczy Mapa korelacji."),
    }
