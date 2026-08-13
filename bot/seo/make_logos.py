"""Pobranie znaków firmowych spółek do repozytorium.

Uruchom RĘCZNIE po dopisaniu spółek do katalogu:

    python bot/seo/make_logos.py

Skąd i po co: aplikacja pokazuje logo prosto z
`financialmodelingprep.com/image-stock/SYMBOL.png` (patrz `earnings/report.py`).
Dla ekranu aplikacji to w porządku — obrazek dogrywa się po starcie i nikomu
nie przeszkadza. Dla podstrony pozycjonowanej już nie: obrazek z cudzej domeny
leży w krytycznej ścieżce rysowania, a jego awaria zostawia dziurę na stronie,
którą Google i tak zdąży zobaczyć. Dlatego 266 plików pobieramy raz i trzymamy
u siebie, a `logos.py` sięga po adres zewnętrzny tylko dla spółek, których tu
zabrakło.

Obrazki są zmniejszane do 96 px i zapisywane jako PNG z paletą — całość waży
wtedy ułamek tego, co oryginały, a przy rozmiarze wyświetlania 24–56 px
różnicy nie widać. Skrypt wymaga Pillow i sieci, więc chodzi wyłącznie na
komputerze; obraz produkcyjny go nie uruchamia (patrz `bot/requirements.txt`).
"""

from __future__ import annotations

import concurrent.futures as futures
import io
import os
import sys

import requests
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from seo import companies  # noqa: E402

CEL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "static", "seo", "logos")
ZRODLO = "https://financialmodelingprep.com/image-stock/{}.png"
BOK = 96

_sesja = requests.Session()
_sesja.headers.update({"User-Agent": "Mozilla/5.0 (Portevo asset fetch)"})


def _pobierz(symbol: str) -> tuple[str, str]:
    """(symbol, komunikat). Wyjątek nigdy nie wychodzi — jedna spółka nie może
    przerwać pobierania pozostałych."""
    cel = os.path.join(CEL, f"{symbol}.png")
    try:
        r = _sesja.get(ZRODLO.format(symbol), timeout=20)
        if r.status_code != 200 or not r.content:
            return symbol, f"brak ({r.status_code})"
        im = Image.open(io.BytesIO(r.content)).convert("RGBA")
        # Serwis potrafi oddać przezroczysty placeholder 1×1 zamiast czterysta
        # czwórki — taki plik jest gorszy niż jego brak, bo przykryłby monogram
        # pustym kwadratem.
        if im.width < 16 or im.height < 16:
            return symbol, "obrazek zastępczy — pomijam"
        im.thumbnail((BOK, BOK), Image.LANCZOS)
        im.save(cel, "PNG", optimize=True)
        return symbol, f"{im.width}x{im.height}"
    except Exception as e:  # noqa: BLE001
        return symbol, f"błąd: {e}"


def main() -> None:
    os.makedirs(CEL, exist_ok=True)
    symbole = [s["symbol"] for s in companies.SPOLKI]
    print(f"Pobieram {len(symbole)} logotypów do {os.path.relpath(CEL)}")

    ok = 0
    with futures.ThreadPoolExecutor(max_workers=8) as pula:
        for symbol, info in pula.map(_pobierz, symbole):
            if info[0].isdigit():
                ok += 1
            else:
                print(f"  {symbol:10} {info}")
    print(f"\nGotowe: {ok} z {len(symbole)}. Reszta pokaże monogram albo adres zewnętrzny.")


if __name__ == "__main__":
    main()
