"""Zdjęcia person po stronie serwera: kadrowanie, wersja rozmyta, pobieranie portretów.

Dwa źródła zdjęć, w tej kolejności:
1. **Zdjęcia właściciela** — `bot/static/insiders/{id}.jpg`, wrzucane przez
   `insiders/zdjecia.py` i trzymane w repozytorium. Zawsze wygrywają.
2. **Oficjalne portrety Kongresu** — z repozytorium `unitedstates/images`
   (zdjęcia z Biuletynu Kongresu, utwory rządu USA = domena publiczna).
   Pobierane w tle do katalogu danych serwera, NIE do repozytorium: to kilkaset
   plików, które da się w każdej chwili odtworzyć.

Kadr: kwadrat z górnej części portretu (twarz siedzi w górnej trzeciej).
Wersja rozmyta: dwa przejścia na małym obrazku — z twarzy zostaje plama
koloru, której nie da się odwrócić; nazwa pliku to skrót z solą (`people.blur_name`).
"""

from __future__ import annotations

import io
import logging
import os
import time

import requests

import paths
from . import people

log = logging.getLogger("insiders.photos")

ROZMIAR = 320
KATALOG = paths.data_path("insiders_foto", ".keep")
KATALOG = os.path.dirname(KATALOG)
PORTRET_KONGRESU = "https://unitedstates.github.io/images/congress/450x550/{bioguide}.jpg"


def kadruj(img):
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(img).convert("RGB")
    w, h = img.size
    bok = min(w, h)
    lewo = (w - bok) // 2
    gora = int((h - bok) * 0.22) if h > w else 0
    return img.crop((lewo, gora, lewo + bok, gora + bok)).resize((ROZMIAR, ROZMIAR), Image.LANCZOS)


def rozmyj(img):
    from PIL import Image, ImageFilter
    male = img.resize((48, 48), Image.BILINEAR).filter(ImageFilter.GaussianBlur(5))
    return male.resize((160, 160), Image.BILINEAR).filter(ImageFilter.GaussianBlur(8))


def zapisz(pid: str, dane: bytes, katalog: str) -> bool:
    """Kadruje i zapisuje zdjęcie persony razem z wersją rozmytą."""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(dane)) as src:
            kw = kadruj(src)
    except Exception as e:  # noqa: BLE001 — uszkodzony plik to brak zdjęcia, nie awaria
        log.info("Zdjęcie %s nieczytelne: %s", pid, e)
        return False
    os.makedirs(os.path.join(katalog, "b"), exist_ok=True)
    kw.save(os.path.join(katalog, f"{pid}.jpg"), "JPEG", quality=86, optimize=True, progressive=True)
    rozmyj(kw).save(os.path.join(katalog, "b", f"{people.blur_name(pid)}.jpg"), "JPEG",
                    quality=70, optimize=True)
    return True


def pobierz_portrety(pary: list[tuple[str, str]], stop=None) -> dict:
    """[(id persony, bioguide)] → pobiera brakujące portrety Kongresu."""
    stat = {"pobrane": 0, "brak": 0, "pominiete": 0}
    for pid, bioguide in pary:
        if stop is not None and stop.is_set():
            break
        if not bioguide or os.path.isfile(os.path.join(KATALOG, f"{pid}.jpg")):
            stat["pominiete"] += 1
            continue
        if people.foto_wlasciciela(pid):
            stat["pominiete"] += 1
            continue
        try:
            r = requests.get(PORTRET_KONGRESU.format(bioguide=bioguide), timeout=20)
        except requests.RequestException:
            continue
        if r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff" and zapisz(pid, r.content, KATALOG):
            stat["pobrane"] += 1
        else:
            stat["brak"] += 1
        time.sleep(0.15)
    people.odswiez_zdjecia()
    return stat
