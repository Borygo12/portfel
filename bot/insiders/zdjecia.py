"""Zdjęcia person: folder właściciela → kwadratowe miniatury dla aplikacji.

Uruchamiane RĘCZNIE na komputerze (Pillow jest tylko tu, nie na serwerze):

    python bot/insiders/zdjecia.py

Skąd: `zdjęcia do apki strony/insajderzy/`. Nazwa pliku mówi, kto jest na
zdjęciu — identyfikator z listy (`nancy-pelosi.jpg`) albo po prostu imię
i nazwisko (`Nancy Pelosi.png`). Rozszerzenie dowolne: jpg, png, webp, jfif.

Dokąd: `bot/static/insiders/{id}.jpg` (320×320) oraz rozmyta kopia
w `bot/static/insiders/b/` pod nazwą, z której nie da się odczytać osoby —
tę widzi ktoś bez premium na wykresie. Wynik trzeba zacommitować; serwer podaje
pliki sam, aplikacji nie trzeba wydawać od nowa.

Kadrowanie: kwadrat z GÓRNEJ części zdjęcia portretowego. Twarz na zdjęciu
z konferencji czy oficjalnym portrecie siedzi w górnej trzeciej, a środek
kadru to zwykle krawat.
"""

from __future__ import annotations

import os
import sys

TU = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TU))

from insiders import people  # noqa: E402

REPO = os.path.dirname(os.path.dirname(TU))
ZRODLO = os.path.join(REPO, "zdjęcia do apki strony", "insajderzy")
CEL = os.path.join(os.path.dirname(TU), "static", "insiders")
ROZSZERZENIA = (".jpg", ".jpeg", ".png", ".webp", ".jfif")


def _dopasuj(nazwa_pliku: str) -> str:
    stem = os.path.splitext(nazwa_pliku)[0]
    s = people.slug(stem)
    if s in people.BY_ID:
        return s
    for p in people.KATALOG:
        if people.slug(p["name"]) == s:
            return p["id"]
    # identyfikatory spoza katalogu (sec-1234567, house-…) przyjmujemy wprost
    if s.startswith(("sec-", "house-", "oge-")):
        return s
    return ""


def main() -> int:
    os.makedirs(os.path.join(CEL, "b"), exist_ok=True)
    if not os.path.isdir(ZRODLO):
        os.makedirs(ZRODLO, exist_ok=True)
        print(f"Utworzyłem folder {ZRODLO} — wrzuć tam zdjęcia i uruchom ponownie.")
        return 0
    zrobione, nieznane = [], []
    for plik in sorted(os.listdir(ZRODLO)):
        if not plik.lower().endswith(ROZSZERZENIA):
            continue
        pid = _dopasuj(plik)
        if not pid:
            nieznane.append(plik)
            continue
        from insiders import photos
        with open(os.path.join(ZRODLO, plik), "rb") as f:
            if not photos.zapisz(pid, f.read(), CEL):
                print(f"  ! {plik}: nie udało się odczytać obrazka")
                continue
        zrobione.append(pid)
    print(f"Gotowe: {len(zrobione)} zdjęć → {CEL}")
    for pid in zrobione:
        print(f"  ✓ {pid}")
    if nieznane:
        print("Nie rozpoznałem (zmień nazwę na identyfikator z LISTA-ZDJEC.txt):")
        for p in nieznane:
            print(f"  ? {p}")
    brak = [p["id"] for p in people.KATALOG if not os.path.isfile(os.path.join(CEL, f"{p['id']}.jpg"))]
    if brak:
        print(f"Bez zdjęcia ({len(brak)}): " + ", ".join(brak))
    return 0


if __name__ == "__main__":
    sys.exit(main())
