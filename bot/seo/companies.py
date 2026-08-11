"""Katalog spółek, z których powstają podstrony wyników finansowych.

Skąd wzięła się lista: kandydatów (WIG20, mWIG40, sWIG80 oraz najpopularniejsze
spółki z giełd amerykańskich) przepuszczono przez Yahoo Finance i **zostawiono
tylko te, dla których dane naprawdę wracają**. Symbole spółek wycofanych
z obrotu, przejętych albo takich, których dostawca nie zna, odpadły. To nie jest
pedanteria: strona bez danych to strona bez treści, a kilkadziesiąt takich
adresów w sitemapie obniża ocenę całej domeny — Google mierzy jakość witryny,
nie pojedynczej podstrony.

Katalog jest CELOWO ręczny i skończony (266 spółek), a nie generowany na żądanie
dla dowolnego tickera z adresu. Adres, pod którym da się wygenerować nieskończenie
wiele stron, jest klasycznym wzorcem spamerskim i tak właśnie bywa traktowany.

`companies.json` jest plikiem danych, żeby dało się go odświeżyć bez ruszania
kodu. Gdy dokładasz spółki: dopisz wpis z symbolem Yahoo (`CDR.WA` dla GPW,
`AAPL` dla USA), unikalnym slugiem i polską nazwą — taką, jakiej ludzie używają
w wyszukiwarce, a nie pełną formą z KRS. „Orlen”, nie „Polski Koncern Naftowy
ORLEN Spółka Akcyjna”.
"""

from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("seo.companies")

_PLIK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "companies.json")

#: Nazwy giełd po polsku — Yahoo podaje je po angielsku.
GIELDY = {
    "Warsaw": "Giełda Papierów Wartościowych w Warszawie",
    "NasdaqGS": "Nasdaq",
    "NasdaqGM": "Nasdaq",
    "NasdaqCM": "Nasdaq",
    "NYSE": "New York Stock Exchange",
    "NYSEArca": "NYSE Arca",
    "BATS": "Cboe BZX",
}

#: Kraje po polsku — pojawiają się w opisie spółki.
KRAJE = {
    "Poland": "Polska", "United States": "Stany Zjednoczone",
    "Ireland": "Irlandia", "Netherlands": "Holandia", "Taiwan": "Tajwan",
    "China": "Chiny", "Singapore": "Singapur", "Argentina": "Argentyna",
    "Canada": "Kanada", "United Kingdom": "Wielka Brytania", "Israel": "Izrael",
    "Hungary": "Węgry", "Switzerland": "Szwajcaria", "Uruguay": "Urugwaj",
    "Cyprus": "Cypr", "Luxembourg": "Luksemburg", "Germany": "Niemcy",
    "Spain": "Hiszpania", "Bermuda": "Bermudy", "Jersey": "Jersey",
}


def _wczytaj() -> list[dict]:
    try:
        with open(_PLIK, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        # Brak katalogu nie może wywalić serwera — reszta stron ma działać dalej.
        log.error("Katalog spółek niedostępny (%s): %s", _PLIK, e)
        return []


SPOLKI: list[dict] = _wczytaj()
PO_SLUGU: dict[str, dict] = {s["slug"]: s for s in SPOLKI}
PO_SYMBOLU: dict[str, dict] = {s["symbol"].upper(): s for s in SPOLKI}


def po_slugu(slug: str) -> dict | None:
    return PO_SLUGU.get((slug or "").strip().lower())


def po_symbolu(symbol: str) -> dict | None:
    """Spółka po symbolu Yahoo albo po samym tickerze („CDR” → „CDR.WA”)."""
    s = (symbol or "").strip().upper()
    if not s:
        return None
    trafienie = PO_SYMBOLU.get(s)
    if trafienie:
        return trafienie
    return PO_SYMBOLU.get(s + ".WA")


def rynek(nazwa: str) -> list[dict]:
    """Spółki z jednego rynku: „GPW” albo „USA”."""
    return [s for s in SPOLKI if s["market"] == nazwa]


def sektory(m: str = "") -> dict[str, list[dict]]:
    """Spółki pogrupowane po sektorze (polska nazwa sektora jako klucz)."""
    grupy: dict[str, list[dict]] = {}
    for s in SPOLKI:
        if m and s["market"] != m:
            continue
        klucz = s.get("sector_pl") or "pozostałe"
        grupy.setdefault(klucz, []).append(s)
    return dict(sorted(grupy.items(), key=lambda kv: -len(kv[1])))


def sasiedzi(spolka: dict, ile: int = 8) -> list[dict]:
    """Spółki z tego samego sektora — najpierw z tego samego rynku.

    Po co: pojedyncza podstrona spółki bez linków wychodzących jest ślepym
    zaułkiem dla robota i dla człowieka. Linkowanie do sąsiadów z branży rozkłada
    „moc” strony po całym katalogu i daje czytelnikowi naturalny następny krok —
    porównanie z konkurencją to dokładnie to, po co się na taką stronę wchodzi.
    """
    sektor = spolka.get("sector")
    if not sektor:
        wynik = [s for s in SPOLKI
                 if s["market"] == spolka["market"] and s["slug"] != spolka["slug"]]
        return wynik[:ile]
    ten_sam_rynek, inny = [], []
    for s in SPOLKI:
        if s["slug"] == spolka["slug"] or s.get("sector") != sektor:
            continue
        (ten_sam_rynek if s["market"] == spolka["market"] else inny).append(s)
    return (ten_sam_rynek + inny)[:ile]


def adres(spolka: dict) -> str:
    return "/wyniki-finansowe/" + spolka["slug"]


def adresy() -> list[str]:
    """Wszystkie adresy podstron spółek — do sitemapy."""
    return [adres(s) for s in SPOLKI]


def gielda_pl(spolka: dict) -> str:
    return GIELDY.get(spolka.get("exchange") or "",
                      spolka.get("exchange") or
                      ("GPW" if spolka["market"] == "GPW" else "giełda w USA"))


def kraj_pl(spolka: dict) -> str:
    return KRAJE.get(spolka.get("country") or "", spolka.get("country") or "")


def ticker(spolka: dict) -> str:
    """Ticker bez końcówki giełdy — tak, jak spółkę nazywa się w prasie."""
    return spolka["symbol"].split(".")[0]
