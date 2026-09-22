"""Wynik persony: „ile zarobiłbyś, kopiując jej zakupy z ostatniego roku".

Nikt z nich nie publikuje całego portfela z wyceną — publikują TRANSAKCJE.
Liczymy więc portfel odtworzony z transakcji z okna 12 miesięcy:

* zakup = wkładamy kwotę po cenie z dnia transakcji (SEC podaje cenę wprost;
  Kongres i OGE podają tylko przedział kwot, więc bierzemy jego środek i kurs
  zamknięcia z tego dnia);
* sprzedaż = zdejmujemy akcje kupione wcześniej W TYM OKNIE i zapisujemy
  gotówkę; sprzedaży akcji kupionych przed oknem nie da się rozliczyć, bo nie
  znamy ceny zakupu — pomijamy je zamiast zgadywać;
* wynik = (wartość dziś + gotówka ze sprzedaży) / suma zakupów − 1.

Opcje liczymy jak akcje, na których są wystawione. Prawdziwy wynik opcji bywa
wielokrotnie większy albo zerowy — to zaznaczamy w aplikacji, zamiast udawać,
że znamy cenę opcji z dnia zakupu.

Kwoty z przedziałów to szacunek i aplikacja mówi to wprost („≈"). Dla Trumpa,
który ma tysiące pozycji, wyceniamy tylko największe (`MAX_TICKEROW`) —
pokrycie wyniku (jaka część pieniędzy weszła do rachunku) idzie razem z nim.
"""

from __future__ import annotations

import bisect
import datetime as dt
import logging
from concurrent.futures import ThreadPoolExecutor

import requests

from . import store

log = logging.getLogger("insiders.perf")

MAX_TICKEROW = 120
_UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")}
_ses = requests.Session()
_ses.headers.update(_UA)


def srodek(t: dict) -> float:
    lo, hi = t.get("amt_lo"), t.get("amt_hi")
    if lo is None and hi is None:
        return 0.0
    if hi is None:
        return float(lo)
    if lo is None:
        return float(hi)
    return (float(lo) + float(hi)) / 2


def notowania(ticker: str) -> dict | None:
    """Dzienne zamknięcia z dwóch lat: {"d": [daty], "c": [kursy]}. Cache pół doby."""
    from earnings import cache as e_cache

    klucz = f"ins-px-{ticker}"
    hit = e_cache.get(klucz, 12 * 3600)
    if hit is not None:
        return hit or None
    wynik: dict = {}
    try:
        r = _ses.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
                     f"?range=2y&interval=1d", timeout=15)
        if r.status_code == 200:
            res = ((r.json().get("chart") or {}).get("result") or [None])[0]
            if res:
                ts = res.get("timestamp") or []
                cl = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
                d, c = [], []
                for t, v in zip(ts, cl):
                    if v is None:
                        continue
                    d.append(dt.datetime.utcfromtimestamp(t).date().isoformat())
                    c.append(round(float(v), 4))
                if d:
                    wynik = {"d": d, "c": c, "cur": (res.get("meta") or {}).get("currency", "USD")}
    except Exception as e:  # noqa: BLE001
        log.debug("Notowania %s: %s", ticker, e)
    # pusty wynik też zapisujemy — spółka wycofana z obrotu nie ma notowań i nie
    # ma sensu pytać o nią przy każdym otwarciu profilu
    e_cache.put(klucz, wynik)
    return wynik or None


def kurs_z_dnia(px: dict, dzien: str) -> float | None:
    """Zamknięcie z tego dnia albo najbliższego wcześniejszego (weekend, święto)."""
    i = bisect.bisect_right(px["d"], dzien) - 1
    if i < 0:
        return None
    # dzień sprzed więcej niż tygodnia to już nie ten moment rynku
    try:
        if (dt.date.fromisoformat(dzien) - dt.date.fromisoformat(px["d"][i])).days > 7:
            return None
    except ValueError:
        return None
    return px["c"][i]


def policz(pid: str, transakcje: list[dict] | None = None, dni: int = 365) -> dict:
    """Statystyki persony. Wolne przy pierwszym razie (notowania), potem z cache."""
    dzis = dt.date.today()
    od = (dzis - dt.timedelta(days=dni)).isoformat()
    wszystkie = transakcje if transakcje is not None else store.trades_for_person(pid, limit=40000)
    okno = [t for t in wszystkie if t["date"] >= od and t.get("ticker")]

    kupna = [t for t in okno if t["side"] == "buy"]
    sprzedaze = [t for t in okno if t["side"] == "sell"]
    kupione = sum(_kwota(t) for t in kupna)
    sprzedane = sum(_kwota(t) for t in sprzedaze)
    szacunek = any(t.get("source") != "sec" for t in okno)

    # ---- struktura zakupów (wykres kołowy): okno roku, a gdy puste — cała historia
    podstawa = kupna or [t for t in wszystkie if t["side"] == "buy" and t.get("ticker")]
    sumy: dict[str, float] = {}
    nazwy: dict[str, str] = {}
    for t in podstawa:
        sumy[t["ticker"]] = sumy.get(t["ticker"], 0.0) + _kwota(t)
        if t.get("asset") and t["ticker"] not in nazwy:
            nazwy[t["ticker"]] = t["asset"]
    razem = sum(sumy.values()) or 1.0
    ranking = sorted(sumy.items(), key=lambda x: -x[1])
    struktura = [{"ticker": k, "name": nazwy.get(k, ""), "value": round(v, 2),
                  "pct": round(v / razem * 100, 2)} for k, v in ranking[:9]]
    reszta = sum(v for _, v in ranking[9:])
    if reszta > 0:
        struktura.append({"ticker": "", "name": f"pozostałe ({len(ranking) - 9})",
                          "value": round(reszta, 2), "pct": round(reszta / razem * 100, 2)})

    # ---- wynik portfela odtworzonego z transakcji
    wynik, pokrycie, wycenione = None, 0.0, 0
    if kupna:
        wagi: dict[str, float] = {}
        for t in kupna:
            wagi[t["ticker"]] = wagi.get(t["ticker"], 0.0) + _kwota(t)
        do_wyceny = [k for k, _ in sorted(wagi.items(), key=lambda x: -x[1])[:MAX_TICKEROW]]
        with ThreadPoolExecutor(max_workers=6) as pool:
            kursy = dict(zip(do_wyceny, pool.map(notowania, do_wyceny)))
        wlozone = wartosc = 0.0
        for sym in do_wyceny:
            px = kursy.get(sym)
            if not px:
                continue
            akcje, zl, got = 0.0, 0.0, 0.0
            for t in sorted((x for x in okno if x["ticker"] == sym), key=lambda x: x["date"]):
                cena = t.get("price") or kurs_z_dnia(px, t["date"])
                if not cena:
                    continue
                kw = _kwota(t)
                if t["side"] == "buy":
                    akcje += kw / cena
                    zl += kw
                elif akcje > 0:
                    sprzed = min(akcje, kw / cena)
                    akcje -= sprzed
                    got += sprzed * cena
            if zl <= 0:
                continue
            wycenione += 1
            wlozone += zl
            wartosc += akcje * px["c"][-1] + got
        if wlozone > 0:
            wynik = round((wartosc / wlozone - 1) * 100, 2)
            pokrycie = round(min(1.0, wlozone / (kupione or wlozone)), 3)

    daty = [t["date"] for t in wszystkie]
    return {
        "ret_12m": wynik, "coverage": pokrycie, "priced": wycenione,
        "buys": len(kupna), "sells": len(sprzedaze),
        "bought": round(kupione, 2), "sold": round(sprzedane, 2),
        "estimated": szacunek,
        "options": sum(1 for t in okno if t.get("options")),
        "last": max(daty) if daty else None, "first": min(daty) if daty else None,
        "total": len(wszystkie),
        "alloc": struktura, "alloc_basis": "12m" if kupna else "all",
        "tickers_12m": len({t["ticker"] for t in okno}),
    }


def _kwota(t: dict) -> float:
    if t.get("source") == "sec" and t.get("amt_lo"):
        return float(t["amt_lo"])
    return srodek(t)


def statystyki(pid: str, max_wiek: float = 12 * 3600, wymus: bool = False) -> dict:
    if not wymus:
        hit = store.stats_get(pid, max_wiek)
        if hit is not None:
            return hit
    s = policz(pid)
    store.stats_set(pid, s)
    return s
