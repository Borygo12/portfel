"""Powiadomienia „insider kupił albo sprzedał spółkę, którą masz".

`follow.py` dzwoni, gdy ruszy się OSOBA, którą ktoś obserwuje. Ten moduł
patrzy od drugiej strony: dzwoni, gdy ruszy się SPÓŁKA z czyjegoś portfela
albo listy obserwowanych — bez względu na to, kto handlował. To działa tak samo
dla GPW (powiadomienia MAR, kwoty w złotówkach) jak dla USA (Form 4, Kongres,
rząd, 13F), bo wszystkie źródła lądują w jednej tabeli z tickerem Yahoo.

Kto dostaje co — to jest haczyk sprzedażowy, więc świadomie:

* **premium** — pełna treść: kto, jaka funkcja, za ile, ile sztuk po ile, dzień
  transakcji i czy w spółce kupuje więcej insiderów naraz;
* **bez premium** — ZAPOWIEDŹ: że w spółce X prezes/członek rady kupił albo
  sprzedał, bez nazwiska i kwoty. Dotknięcie prowadzi do strony sprzedażowej
  insiderów. Najwyżej jedna dziennie — to ma zachęcać, a nie zasypywać, bo
  zasypany człowiek wyłącza powiadomienia zamiast kupić.

Co pomijamy, żeby telefon nie dzwonił o szumie:
* transakcje ujawnione dawniej niż `follow.SWIEZOSC_DNI` temu;
* sprzedaże z planu 10b5-1 (ustalone z góry, nic nie mówią o nastrojach),
  sprzedaże przy wykonaniu opcji i drobnicę poniżej progów `PROGI`.

Wyłącznik po stronie konta: `notification_prefs.insider_holdings` (migracja 0008),
domyślnie włączony — także dla kont bez premium.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging

from . import follow, store

log = logging.getLogger("insiders.moje_spolki")

FEATURE = "tools.insiders"
MAX_POJEDYNCZYCH = 3          # więcej nowych transakcji naraz dla jednego konta — jedno zbiorcze
DNI_KLASTRA = 30              # „kupuje więcej insiderów" liczymy z tylu dni

# Minimalna wartość transakcji (w walucie zgłoszenia), żeby w ogóle dzwonić.
# Kupno jest rzadsze i ciekawsze od sprzedaży, więc ma niższy próg. Na GPW
# progi są niższe, bo to mniejsze spółki i mniejsze pakiety.
PROGI = {
    "gpw":   {"buy": 5_000, "sell": 20_000},
    "sec":   {"buy": 10_000, "sell": 100_000},
    "f13":   {"buy": 1_000_000, "sell": 1_000_000},
    "house": {"buy": 0, "sell": 15_000},       # Kongres podaje widełki, `amt_lo` to dół
    "senat": {"buy": 0, "sell": 15_000},
    "oge":   {"buy": 0, "sell": 15_000},
}

# Kto handlował — w zapowiedzi zamiast nazwiska. Formy męskie, bo stoją przed
# „kupił/sprzedał" i muszą się zgadzać gramatycznie.
_KTO_GPW = {"Prezes": "Prezes spółki", "Zarząd": "Członek zarządu", "Rada": "Członek rady nadzorczej",
            "Bliski": "Ktoś z otoczenia zarządu", "Akcjonariusz": "Duży akcjonariusz"}
_KTO_ZRODLO = {"house": "Kongresmen USA", "senat": "Senator USA", "oge": "Członek rządu USA",
               "f13": "Znany fundusz"}


def etykieta(ticker: str) -> str:
    """„CDR.WA" → „CDR" — tak mówi o spółce człowiek, a nie Yahoo."""
    t = (ticker or "").upper()
    return t[:-3] if t.endswith(".WA") else t


def _warianty(ticker: str) -> set[str]:
    """Pod jakimi symbolami ta spółka może siedzieć w `user_symbols`."""
    t = (ticker or "").strip().upper()
    if not t:
        return set()
    out = {t}
    if t.endswith(".WA"):
        out.add(t[:-3])
    try:
        from portfolio import prices as pf_prices
        r = (pf_prices.resolved_symbol(t) or "").upper()
        if r:
            out.add(r)
    except Exception as e:  # noqa: BLE001 — brak mapowania nie blokuje wysyłki
        log.debug("Nie rozwiązano symbolu %s: %s", t, e)
    return out


def istotna(t: dict) -> bool:
    if not t.get("ticker") or t.get("side") not in ("buy", "sell"):
        return False
    if t["side"] == "sell" and (t.get("planned") or t.get("options")):
        return False
    prog = PROGI.get(t.get("source") or "", {"buy": 0, "sell": 0})[t["side"]]
    wartosc = t.get("amt_lo") or t.get("amt_hi") or 0
    return wartosc >= prog if prog else True


def _kto(t: dict, osoba: dict) -> str:
    if t.get("source") in _KTO_ZRODLO:
        return _KTO_ZRODLO[t["source"]]
    extra = osoba.get("extra") or {}
    if t.get("source") == "gpw":
        return _KTO_GPW.get(extra.get("short") or "", "Insider spółki")
    if extra.get("klasa") == "wlasciciele":
        return "Duży udziałowiec"
    return "Członek władz spółki"


def _czasownik(side: str) -> str:
    return "kupił" if side == "buy" else "sprzedał"


def _liczba_szt(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ")


def _cena_txt(t: dict) -> str:
    px = t.get("price")
    if not px:
        return ""
    w = follow._waluta(t)
    x = f"{px:,.2f}".replace(",", " ").replace(".", ",")
    return f"po {x} {w}"


def _klaster(ticker: str) -> int:
    """Ilu RÓŻNYCH insiderów kupiło tę spółkę w ostatnich tygodniach.

    Pojedynczy zakup bywa gestem; kilku ludzi z zarządu kupujących naraz to już
    sygnał, na który patrzą zawodowcy — warto go wypisać wprost."""
    od = (dt.date.today() - dt.timedelta(days=DNI_KLASTRA)).isoformat()
    try:
        rows = store.trades_for_tickers([ticker], od, limit=400)
    except Exception:  # noqa: BLE001
        return 0
    return len({r["person"] for r in rows if r["side"] == "buy" and r["source"] in ("gpw", "sec")})


# ------------------------------------------------------------------- treść


def tresc_pelna(t: dict, osoba: dict, nazwa: str) -> tuple[str, str]:
    et = etykieta(t["ticker"])
    kwota = follow._kwota_txt(t)
    tytul = f"{et}: {nazwa} {_czasownik(t['side'])} akcje" + (f" za {kwota}" if kwota else "")
    rola = (osoba.get("role") or "").strip()
    szt = f"{_liczba_szt(t['shares'])} szt. {_cena_txt(t)}".strip() if t.get("shares") else ""
    czesci = [rola[:60], szt, f"transakcja z {follow._data_pl(t['date'])}"]
    if t.get("owner"):
        # Kongres i rząd: „małżonek", „dziecko" — samo słowo nic by nie mówiło
        czesci.append(t["owner"] if t.get("source") in ("gpw", "sec", "f13") else f"konto: {t['owner']}")
    if t["side"] == "buy":
        n = _klaster(t["ticker"])
        if n >= 2:
            czesci.append(f"{n} insiderów kupuje w ostatnim miesiącu")
    return tytul[:120], " · ".join(c for c in czesci if c)[:240]


def tresc_zapowiedzi(t: dict, osoba: dict) -> tuple[str, str]:
    et = etykieta(t["ticker"])
    tytul = f"{et}: {_kto(t, osoba)} {_czasownik(t['side'])} akcje"
    tresc = ("Spółka z Twojego portfela. Kto dokładnie, za ile i po jakiej cenie — "
             "zobaczysz w Portevo Premium.")
    return tytul[:120], tresc


def _odm(n: int, jeden: str, dwa: str, piec: str) -> str:
    """Polska odmiana po liczebniku: 1 kupno, 3 kupna, 5 kupień, 22 kupna."""
    if n == 1:
        return f"{n} {jeden}"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} {dwa}"
    return f"{n} {piec}"


def tresc_zbiorcza(trans: list[dict]) -> tuple[str, str]:
    wg: dict[str, list[int]] = {}
    for t in trans:
        k = wg.setdefault(etykieta(t["ticker"]), [0, 0])
        k[0 if t["side"] == "buy" else 1] += 1
    czesci = []
    for et, (k, s) in wg.items():
        opis = ", ".join(x for x in (_odm(k, "kupno", "kupna", "kupień") if k else "",
                                     _odm(s, "sprzedaż", "sprzedaże", "sprzedaży") if s else "") if x)
        czesci.append(f"{et}: {opis}")
    tytul = ("Insiderzy w Twoich spółkach: "
             + _odm(len(trans), "nowa transakcja", "nowe transakcje", "nowych transakcji"))
    return tytul, " · ".join(czesci)[:240]


# ------------------------------------------------------------------ rozsyłka


def powiadom(nowe: list[dict], nazwy: dict[str, str]) -> dict:
    """Rozsyła powiadomienia o nowych transakcjach w spółkach użytkowników."""
    wynik = {"pelne": 0, "zapowiedzi": 0}
    granica = (dt.date.today() - dt.timedelta(days=follow.SWIEZOSC_DNI)).isoformat()
    swieze = [t for t in nowe if (t.get("filed") or "") >= granica and istotna(t)]
    if not swieze:
        return wynik

    # wariant symbolu → transakcje tej spółki
    po_symbolu: dict[str, list[dict]] = {}
    for t in swieze:
        for w in _warianty(t["ticker"]):
            po_symbolu.setdefault(w, []).append(t)

    from notify import engine
    from notify import store as nstore
    try:
        trafienia = nstore.kogo_obchodzi(set(po_symbolu))
    except Exception as e:  # noqa: BLE001
        log.warning("Nie sprawdzono, kogo obchodzą transakcje insiderów: %s", e)
        return wynik
    if not trafienia:
        return wynik

    per_konto: dict[str, dict[str, dict]] = {}
    for r in trafienia:
        for t in po_symbolu.get((r["symbol"] or "").upper(), []):
            per_konto.setdefault(str(r["user_id"]), {})[t["uid"]] = t
    wylaczone = nstore.bez_insiderow(list(per_konto))
    premium = nstore.tylko_premium(list(per_konto))
    osoby = store.people_rows(list({t["person"] for t in swieze}))
    dzis = dt.date.today().isoformat()

    for uid, wg_uid in per_konto.items():
        if uid in wylaczone:
            continue
        trans = sorted(wg_uid.values(),
                       key=lambda t: (t["side"] == "buy", t.get("amt_hi") or t.get("amt_lo") or 0),
                       reverse=True)
        try:
            if uid not in premium:
                # jedna zapowiedź dziennie — najciekawsza transakcja (kupno przed sprzedażą)
                t = trans[0]
                tytul, tresc = tresc_zapowiedzi(t, osoby.get(t["person"]) or {})
                if engine.powiadom(uid, "insider", tytul, tresc, f"insider-zapowiedz:{dzis}",
                                   symbol=t["ticker"],
                                   meta={"locked": True, "feature": FEATURE, "side": t["side"]}):
                    wynik["zapowiedzi"] += 1
                continue
            if len(trans) > MAX_POJEDYNCZYCH:
                tytul, tresc = tresc_zbiorcza(trans)
                klucz = "insider:moje:" + hashlib.sha1(
                    "|".join(sorted(t["uid"] for t in trans)).encode()).hexdigest()[:20]
                if engine.powiadom(uid, "insider", tytul, tresc, klucz, symbol=trans[0]["ticker"],
                                   meta={"holdings": True, "count": len(trans)}):
                    wynik["pelne"] += 1
                continue
            for t in trans:
                osoba = osoby.get(t["person"]) or {}
                tytul, tresc = tresc_pelna(t, osoba, nazwy.get(t["person"]) or osoba.get("name") or "Insider")
                # ten sam klucz co w `follow.py`: kto obserwuje osobę I ma spółkę, dostaje raz
                if engine.powiadom(uid, "insider", tytul, tresc, f"insider:{t['uid']}"[:200],
                                   symbol=t["ticker"],
                                   meta={"person": t["person"], "holdings": True, "side": t["side"]}):
                    wynik["pelne"] += 1
        except Exception as e:  # noqa: BLE001 — jedno konto nie zatrzymuje reszty
            log.warning("Powiadomienie o insiderze dla %s: %s", uid, e)

    if wynik["pelne"] or wynik["zapowiedzi"]:
        log.info("Insiderzy w spółkach użytkowników: %s", wynik)
    return wynik
