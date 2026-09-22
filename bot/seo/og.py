"""Obrazki podglądu linku (Open Graph) dla profili insiderów.

Po co: link wklejony na forum, w komentarzu pod filmem albo w wiadomości
pokazuje kartę z obrazkiem. Domyślna grafika serwisu jest na każdej stronie
taka sama, więc nie mówi nic; karta ze ZDJĘCIEM Pelosi i jej wynikiem mówi
wszystko i jest klikana wielokrotnie częściej. To jedyne miejsce w warstwie SEO,
gdzie generujemy obrazek — reszta wykresów jest w SVG, bo tam liczy się
szybkość strony, a tu format narzuca Facebook i reszta (PNG/JPG, 1200×630).

Obrazek powstaje raz i leży w katalogu danych (wolumin), więc przy kolejnym
wejściu robota jest gotowy. Nazwa pliku zawiera skrót z danych — zmiana wyniku
albo zdjęcia daje nowy plik i podgląd nie utknie w pamięci Facebooka.

Font: obraz produkcyjny to `python:3.12-slim`, który nie ma ŻADNEGO fontu —
stąd `fonts-dejavu-core` w Dockerfile. Na Windows (praca lokalna) bierzemy
Segoe UI. Bez fontu obrazka nie rysujemy wcale, zamiast pisać krzaczkami.
"""

from __future__ import annotations

import hashlib
import logging
import os

import paths

log = logging.getLogger("seo.og")

SZER, WYS = 1200, 630
KATALOG = paths.data_path("og")
TLO = (8, 11, 17)
KARTA = (20, 25, 38)
TEKST = (238, 241, 247)
SZARY = (154, 163, 184)
ZIELONY = (47, 212, 138)
CZERWONY = (255, 92, 108)
ZLOTY = (245, 196, 81)

_FONTY = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
)


def _font(rozmiar: int, gruby: bool = True):
    from PIL import ImageFont
    kolejka = _FONTY if gruby else tuple(reversed(_FONTY))
    for sciezka in kolejka:
        if os.path.isfile(sciezka):
            try:
                return ImageFont.truetype(sciezka, rozmiar)
            except OSError:
                continue
    return None


def _kolo(obraz, rozmiar: int):
    """Zdjęcie przycięte do koła — maska zamiast ramki, bo PNG z alfą bywa
    wyświetlane na białym tle w podglądach."""
    from PIL import Image, ImageDraw
    obraz = obraz.convert("RGB").resize((rozmiar, rozmiar))
    maska = Image.new("L", (rozmiar * 4, rozmiar * 4), 0)
    ImageDraw.Draw(maska).ellipse((0, 0, rozmiar * 4 - 1, rozmiar * 4 - 1), fill=255)
    maska = maska.resize((rozmiar, rozmiar), Image.LANCZOS)
    return obraz, maska


def _skroc(tekst: str, font, rysownik, maks: int) -> str:
    if not font:
        return tekst
    t = tekst
    while t and rysownik.textlength(t, font=font) > maks:
        t = t[:-1]
    return t if t == tekst else t.rstrip() + "…"


def zbuduj(nazwa: str, rola: str, wynik: str | None, zdjecie: str, dopisek: str) -> bytes | None:
    """PNG 1200×630 albo None, gdy w systemie nie ma żadnego fontu."""
    from PIL import Image, ImageDraw

    duzy = _font(66)
    if not duzy:
        log.info("Brak fontu — pomijam obrazek podglądu")
        return None
    sredni, maly, wielki = _font(32, False), _font(27, False), _font(84)

    img = Image.new("RGB", (SZER, WYS), TLO)
    d = ImageDraw.Draw(img)
    # poświata w rogu — ten sam gest co w aplikacji, tanio: kilka elips
    for i in range(26):
        p = i / 26
        r = int(520 * (1 - p)) + 60
        c = (int(8 + 30 * p * 0.5), int(11 + 60 * p * 0.5), int(17 + 45 * p * 0.5))
        d.ellipse((-260 - r // 2, -220 - r // 2, -260 + r, -220 + r), fill=c)
    d.rounded_rectangle((56, 56, SZER - 56, WYS - 56), radius=34, fill=KARTA,
                        outline=(45, 55, 80), width=2)

    x = 108
    if zdjecie and os.path.isfile(zdjecie):
        try:
            with Image.open(zdjecie) as foto:
                kolo, maska = _kolo(foto, 260)
            d.ellipse((x - 6, 185 - 6, x + 266, 185 + 266), fill=ZLOTY)
            img.paste(kolo, (x, 185), maska)
            x += 310
        except Exception as e:  # noqa: BLE001 — brak zdjęcia to nie powód, by nie zrobić karty
            log.info("Zdjęcie do OG %s: %s", zdjecie, e)
    if x == 108:                                   # bez zdjęcia: inicjały w kole
        d.ellipse((x, 185, x + 260, 445), fill=(26, 32, 48), outline=(45, 55, 80), width=3)
        inicjaly = "".join(c[0] for c in nazwa.split()[:2]).upper() or "?"
        szer = d.textlength(inicjaly, font=wielki)
        d.text((x + 130 - szer / 2, 255), inicjaly, font=wielki, fill=SZARY)
        x += 310

    d.text((x, 150), _skroc("PORTEVO · TRANSAKCJE INSIDERÓW", maly, d, SZER - x - 110),
           font=maly, fill=ZIELONY)
    d.text((x, 200), _skroc(nazwa, duzy, d, SZER - x - 110), font=duzy, fill=TEKST)
    d.text((x, 295), _skroc(rola, sredni, d, SZER - x - 110), font=sredni, fill=SZARY)
    if wynik:
        dodatni = not wynik.startswith("-")
        kolor = ZIELONY if dodatni else CZERWONY
        szer = d.textlength(wynik, font=duzy)
        d.rounded_rectangle((x, 360, x + szer + 46, 452), radius=22,
                            fill=(16, 44, 34) if dodatni else (48, 20, 26))
        d.text((x + 23, 372), wynik, font=duzy, fill=kolor)
        d.text((x, 470), _skroc(dopisek, maly, d, SZER - x - 110), font=maly, fill=SZARY)
    else:
        d.text((x, 370), _skroc(dopisek, sredni, d, SZER - x - 110), font=sredni, fill=SZARY)

    d.text((108, WYS - 108), "portevo.pl", font=maly, fill=SZARY)
    import io
    bufor = io.BytesIO()
    img.save(bufor, "PNG", optimize=True)
    return bufor.getvalue()


def plik(slug: str, podpis: str, buduj) -> str | None:
    """Ścieżka gotowego pliku; rysuje go przy pierwszym pytaniu. `podpis` to
    skrót danych — zmiana wyniku daje nową nazwę i nowy podgląd."""
    znak = hashlib.sha1(podpis.encode("utf-8")).hexdigest()[:10]
    sciezka = os.path.join(KATALOG, f"{slug}-{znak}.png")
    if os.path.isfile(sciezka):
        return sciezka
    dane = buduj()
    if not dane:
        return None
    try:
        os.makedirs(KATALOG, exist_ok=True)
        tmp = sciezka + ".tmp"
        with open(tmp, "wb") as f:
            f.write(dane)
        os.replace(tmp, sciezka)
        # stare wersje tego samego profilu do kosza — inaczej katalog rośnie bez końca
        for stary in os.listdir(KATALOG):
            if stary.startswith(f"{slug}-") and stary != os.path.basename(sciezka):
                try:
                    os.remove(os.path.join(KATALOG, stary))
                except OSError:
                    pass
    except OSError as e:
        log.info("Zapis obrazka OG: %s", e)
        return None
    return sciezka
