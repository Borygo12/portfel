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


PORTFEL_DNI = 730            # tyle sięgają notowania z Yahoo (range=2y)
PORTFEL_PUNKTY = 260
PORTFEL_SPOLEK = 120         # bez raportu rocznego — jak w `policz`
PORTFEL_SPOLEK_Z_RAPORTEM = 300   # z raportem: Trump ma ~1200 spółek, 300 to ~92% wartości


def portfel(pid: str, transakcje: list[dict] | None = None) -> dict:
    """Portfel odtworzony z transakcji — wycena dzień po dniu z dwóch lat.

    Dwa tryby:

    1. **Same transakcje** (Kongres, prezesi): zakup = kwota po kursie z dnia
       (SEC: cena z formularza), sprzedaż zdejmuje akcje kupione wcześniej
       W OKNIE i zamienia je na gotówkę. Sprzedaży akcji sprzed okna nie da się
       rozliczyć — nie znamy ceny zakupu.
    2. **Raport roczny + transakcje** (prezydent, rząd — `majatek.py`): start od
       stanu z najstarszego raportu w oknie (każda pozycja wyceniona środkiem
       przedziału), na to transakcje. Stan startowy liczy się jako „wkład"
       w dniu raportu, więc zysk pokazuje tylko to, co przyszło potem.
       Kolejne raporty to punkty kontrolne na wykresie (`raporty`).

    W każdym dniu: `v` — akcje × kurs + gotówka ze sprzedaży, `w` — wkład
    (start + zakupy). Zysk = v − w liczy aplikacja, także dla wybranego okresu.
    Dodatkowo: `teraz` (największe pozycje dziś), `spolki` (najlepsze
    i najgorsze), `miesiace` (kupno i sprzedaż miesiąc po miesiącu).

    Cache 12 h — pierwsze liczenie Trumpa to kilkaset zapytań o notowania.
    """
    from earnings import cache as e_cache
    from . import majatek

    # klucz zmienia się z nowym raportem rocznym albo nową transakcją — inaczej
    # wynik policzony przed wczytaniem raportu wisiałby w pamięci 12 godzin
    ile = store.person_counts([pid]).get(pid, 0)
    klucz = f"ins-portfel2-{pid}-{len(majatek.raporty(pid))}-{ile}"
    hit = e_cache.get(klucz, 12 * 3600) if transakcje is None else None
    if hit is not None:
        return hit
    dzis = dt.date.today()
    od = (dzis - dt.timedelta(days=PORTFEL_DNI)).isoformat()
    wszystkie = transakcje if transakcje is not None else store.trades_for_person(pid, limit=60000)

    # --- raporty roczne: start i punkty kontrolne
    raporty = [r for r in majatek.raporty(pid) if r.get("pozycje")]
    start = next((r for r in raporty if r["data"] >= od), None)
    if start:
        od = start["data"]
    okno = sorted((t for t in wszystkie if t["date"] > od and t.get("ticker")) if start else
                  (t for t in wszystkie if t["date"] >= od and t.get("ticker")), key=lambda t: t["date"])
    kupna = [t for t in okno if t["side"] == "buy"]

    wynik: dict = {"d": [], "v": [], "w": [], "cur": "PLN" if any(t.get("cur") == "PLN" for t in okno) else "USD",
                   "spolki": [], "teraz": [], "miesiace": _miesiace(okno), "raporty": [],
                   "pokrycie": 0.0, "wycenione": 0, "od": None, "start": None,
                   "szacunek": any(t.get("source") != "sec" for t in okno) or bool(start)}
    if not kupna and not start:
        _zapisz(e_cache, klucz, wynik, transakcje)
        return wynik

    # --- które spółki wyceniać: największe według startu + zakupów
    wagi: dict[str, float] = {}
    if start:
        for sym, (lo, hi) in start["pozycje"].items():
            wagi[sym] = wagi.get(sym, 0.0) + (lo + hi) / 2
    for t in kupna:
        wagi[t["ticker"]] = wagi.get(t["ticker"], 0.0) + _kwota(t)
    limit = PORTFEL_SPOLEK_Z_RAPORTEM if start else PORTFEL_SPOLEK
    do_wyceny = [k for k, _ in sorted(wagi.items(), key=lambda x: -x[1])[:limit]]
    with ThreadPoolExecutor(max_workers=6) as pool:
        kursy = {k: v for k, v in zip(do_wyceny, pool.map(notowania, do_wyceny)) if v}
    if not kursy:
        _zapisz(e_cache, klucz, wynik, transakcje)
        return wynik

    # --- zdarzenia: (dzień, ticker, zmiana akcji, zmiana wkładu, zmiana gotówki)
    zdarzenia: list[tuple[str, str, float, float, float]] = []
    akcje_teraz: dict[str, float] = {}
    wartosc_startu = 0.0
    if start:
        for sym, (lo, hi) in start["pozycje"].items():
            px = kursy.get(sym)
            cena = kurs_z_dnia(px, start["data"]) if px else None
            if not cena:
                continue
            kw = (lo + hi) / 2
            akcje_teraz[sym] = kw / cena
            wartosc_startu += kw
            zdarzenia.append((start["data"], sym, kw / cena, kw, 0.0))
    for t in okno:
        sym = t["ticker"]
        px = kursy.get(sym)
        if not px:
            continue
        z_wykresu = kurs_z_dnia(px, t["date"])
        cena = t.get("price") or z_wykresu
        # Form 4 podaje cenę nominalną, Yahoo — po splitach. Rozjazd ponad 30% to
        # split (albo literówka w formularzu): wtedy kurs z wykresu, inaczej wycena
        # po splicie pokazałaby „zysk" kilkuset procent.
        if cena and z_wykresu and abs(cena / z_wykresu - 1) > 0.3:
            cena = z_wykresu
        if not cena:
            continue
        kw = _kwota(t)
        if t["side"] == "buy":
            szt = kw / cena
            akcje_teraz[sym] = akcje_teraz.get(sym, 0.0) + szt
            zdarzenia.append((t["date"], sym, szt, kw, 0.0))
        elif akcje_teraz.get(sym, 0) > 0:
            szt = min(akcje_teraz[sym], kw / cena)
            akcje_teraz[sym] -= szt
            zdarzenia.append((t["date"], sym, -szt, 0.0, szt * cena))
    zdarzenia.sort(key=lambda z: z[0])
    if not zdarzenia:
        _zapisz(e_cache, klucz, wynik, transakcje)
        return wynik

    # --- wycena dzień po dniu (kurs z ostatniej sesji danej spółki)
    pierwszy = zdarzenia[0][0]
    dni = sorted({d for px in kursy.values() for d in px["d"] if d >= pierwszy})
    idx = {sym: 0 for sym in kursy}
    ostatni: dict[str, float | None] = {sym: None for sym in kursy}
    akcje: dict[str, float] = {}
    per_sym = {sym: {"w": 0.0, "g": 0.0} for sym in kursy}
    wklad = gotowka = 0.0
    j = 0
    punkty_kontrolne = {r["data"]: r for r in raporty if r is not start and r["data"] > (pierwszy or "")}
    for d in dni:
        while j < len(zdarzenia) and zdarzenia[j][0] <= d:
            _, sym, szt, kw, got = zdarzenia[j]
            akcje[sym] = akcje.get(sym, 0.0) + szt
            # Zakup najpierw zużywa gotówkę ze wcześniejszych sprzedaży — nowe
            # pieniądze to dopiero nadwyżka. Inaczej konto, które ciągle przestawia
            # pozycje (Trump), „wpłacałoby" każdą kwotę dwa razy. Zysk (v − w)
            # się od tego nie zmienia, zmienia się sens „wpłaconych".
            z_gotowki = min(gotowka, kw)
            gotowka += got - z_gotowki
            wklad += kw - z_gotowki
            per_sym[sym]["w"] += kw
            per_sym[sym]["g"] += got
            j += 1
        w_akcjach = 0.0
        for sym, szt in akcje.items():
            px = kursy[sym]
            i = idx[sym]
            while i < len(px["d"]) and px["d"][i] <= d:
                ostatni[sym] = px["c"][i]
                i += 1
            idx[sym] = i
            if szt > 0 and ostatni[sym]:
                w_akcjach += szt * ostatni[sym]
        wynik["d"].append(d)
        wynik["v"].append(round(w_akcjach + gotowka, 2))
        wynik["w"].append(round(wklad, 2))
        # punkt kontrolny: raport roczny z datą między poprzednią a tą sesją
        for data_r in [x for x in punkty_kontrolne if x <= d]:
            r = punkty_kontrolne.pop(data_r)
            lo = r["kategorie"]["akcje"][0] + r["kategorie"]["etf"][0]
            hi = r["kategorie"]["akcje"][1] + r["kategorie"]["etf"][1]
            wynik["raporty"].append({"data": data_r, "lo": lo, "hi": hi,
                                     "model": round(w_akcjach), "gotowka_modelu": round(gotowka)})

    n = len(wynik["d"])
    if n > PORTFEL_PUNKTY:
        krok = n / PORTFEL_PUNKTY
        ind = sorted({int(i * krok) for i in range(PORTFEL_PUNKTY)} | {n - 1})
        for k in ("d", "v", "w"):
            wynik[k] = [wynik[k][i] for i in ind]

    # --- pozycje: zysk na spółce i co jest w portfelu dziś
    nazwy = {t["ticker"]: t.get("asset") or "" for t in okno}
    spolki, teraz = [], []
    for sym, sumy in per_sym.items():
        if sumy["w"] <= 0:
            continue
        szt = akcje.get(sym, 0.0)
        kurs = kursy[sym]["c"][-1]
        dzis_w = szt * kurs if szt > 0 else 0.0
        spolki.append({"ticker": sym, "name": nazwy.get(sym, "")[:60], "w": round(sumy["w"], 2),
                       "z": round(dzis_w + sumy["g"] - sumy["w"], 2),
                       "pct": round(((dzis_w + sumy["g"]) / sumy["w"] - 1) * 100, 1), "trzyma": szt > 0})
        if dzis_w > 0:
            teraz.append({"ticker": sym, "name": nazwy.get(sym, "")[:60], "v": round(dzis_w, 2)})
    spolki.sort(key=lambda x: -x["z"])
    teraz.sort(key=lambda x: -x["v"])
    w_akcjach_dzis = sum(x["v"] for x in teraz) or 1.0
    for x in teraz:
        x["pct"] = round(x["v"] / w_akcjach_dzis * 100, 1)
    kupione = sum(_kwota(t) for t in kupna) + sum((lo + hi) / 2 for lo, hi in (start or {}).get("pozycje", {}).values())
    wynik.update(
        spolki=spolki[:6] + [x for x in spolki[-6:] if x["z"] < 0 and x not in spolki[:6]],
        teraz=teraz[:12], akcje_dzis=round(sum(x["v"] for x in teraz)), gotowka=round(gotowka),
        liczba_pozycji=len(teraz),
        pokrycie=round(min(1.0, sum(z[3] for z in zdarzenia) / kupione), 3) if kupione else 0.0,
        wycenione=len([s for s in per_sym.values() if s["w"] > 0]), od=dni[0] if dni else None,
        start={"data": start["data"], "wartosc": round(wartosc_startu)} if start else None,
        majatek=[{"data": r["data"], "kategorie": r["kategorie"]} for r in raporty],
    )
    _zapisz(e_cache, klucz, wynik, transakcje)
    return wynik


def _miesiace(okno: list[dict]) -> list[dict]:
    """Kupno i sprzedaż miesiąc po miesiącu (kwoty ze środka przedziałów)."""
    m: dict[str, list[float]] = {}
    for t in okno:
        k = t["date"][:7]
        para = m.setdefault(k, [0.0, 0.0])
        para[0 if t["side"] == "buy" else 1] += _kwota(t)
    return [{"m": k, "k": round(a), "s": round(b)} for k, (a, b) in sorted(m.items())]


def _zapisz(e_cache, klucz: str, wynik: dict, transakcje) -> None:
    if transakcje is None:
        e_cache.put(klucz, wynik)


def statystyki(pid: str, max_wiek: float = 12 * 3600, wymus: bool = False) -> dict:
    if not wymus:
        hit = store.stats_get(pid, max_wiek)
        if hit is not None:
            return hit
    s = policz(pid)
    store.stats_set(pid, s)
    return s
