"""Generator grafiki dla warstwy SEO — ikony, obrazek podglądu, logo w nagłówku.

Uruchom RĘCZNIE po zmianie znaku firmowego:

    python bot/seo/make_assets.py

Dlaczego nie w czasie działania serwera: obraz produkcyjny świadomie nie zawiera
Pillow (patrz komentarz w `bot/requirements.txt` — biblioteki graficznej używa
tylko generator ikony na pulpit). Gotowe pliki leżą w repozytorium, więc serwer
podaje je jak każdy inny zasób statyczny i nie potrzebuje niczego doinstalowywać.

Decyzja projektowa, którą warto znać przed zmianą: **ikona kwadratowa to WYCINEK
znaku firmowego, nie cały znak.** Pełny znak (łódź plus wykres) ma proporcje
3:1 i po wpisaniu w kwadrat 32×32 zamienia się w nieczytelną plamę — sprawdzone
na podglądzie. Sam wykres ze strzałką zostaje rozpoznawalny do 32 pikseli i to
on trafia na ikony. Pełny znak zostaje tam, gdzie jest miejsce: w obrazku
podglądu linku.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(BOT)
ZNAK = os.path.join(REPO, "mobile", "assets", "logo-portevo-mark.png")
CEL = os.path.join(BOT, "static", "seo")

TLO = (8, 11, 17, 255)          # --bg z motywu aplikacji
TEKST = (238, 241, 247, 255)
SZARY = (154, 163, 184, 255)
ZIELONY = (47, 212, 138, 255)

FONTY = "C:/Windows/Fonts"


def _font(nazwa: str, rozmiar: int):
    try:
        return ImageFont.truetype(os.path.join(FONTY, nazwa), rozmiar)
    except OSError:
        return ImageFont.load_default()


def _znak() -> Image.Image:
    im = Image.open(ZNAK).convert("RGBA")
    return im.crop(im.getbbox())


def _kafel(rozmiar: int, motyw: Image.Image, wypelnienie: float = 0.78,
           przezroczyste_rogi: bool = True) -> Image.Image:
    """Zaokrąglona ciemna płytka z wyśrodkowanym motywem.

    `przezroczyste_rogi=False` dla ikony Apple — iOS sam przycina róg i na
    przezroczystości rysuje wtedy czarne tło, co daje brzydką obwódkę.
    """
    im = Image.new("RGBA", (rozmiar, rozmiar), (0, 0, 0, 0))
    if przezroczyste_rogi:
        # rysujemy zaokrąglenie w powiększeniu i zmniejszamy — brzeg wychodzi gładki
        maska = Image.new("L", (rozmiar * 4, rozmiar * 4), 0)
        ImageDraw.Draw(maska).rounded_rectangle(
            [0, 0, rozmiar * 4 - 1, rozmiar * 4 - 1],
            radius=int(rozmiar * 4 * 0.22), fill=255)
        maska = maska.resize((rozmiar, rozmiar), Image.LANCZOS)
        im.paste(Image.new("RGBA", (rozmiar, rozmiar), TLO), (0, 0), maska)
    else:
        im.paste(Image.new("RGBA", (rozmiar, rozmiar), TLO), (0, 0))

    w, h = motyw.size
    skala = min(rozmiar * wypelnienie / w, rozmiar * wypelnienie / h)
    maly = motyw.resize((max(1, int(w * skala)), max(1, int(h * skala))), Image.LANCZOS)
    im.paste(maly, ((rozmiar - maly.width) // 2, (rozmiar - maly.height) // 2), maly)
    return im


def _obrazek_podgladu(znak: Image.Image) -> Image.Image:
    """1200×630 — to widać, gdy ktoś wklei link na Facebooka, X, Slacka czy Discorda."""
    W, H = 1200, 630
    im = Image.new("RGBA", (W, H), TLO)
    d = ImageDraw.Draw(im)

    # Poświata w rogu, żeby kafel nie był płaskim prostokątem. Rozmycie jest tu
    # konieczne, nie ozdobne: elipsa wypełniona półprzezroczystym kolorem daje
    # ostrą krawędź, która na ciemnym tle wygląda jak błąd renderowania, a nie
    # jak światło.
    poswiata = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rys = ImageDraw.Draw(poswiata)
    rys.ellipse([W - 560, -220, W + 220, 420], fill=(47, 212, 138, 34))
    rys.ellipse([W - 320, 240, W + 300, 760], fill=(79, 155, 255, 26))
    im.alpha_composite(poswiata.filter(ImageFilter.GaussianBlur(150)))
    d.rectangle([0, H - 8, W, H], fill=(47, 212, 138, 255))

    szer = 470
    z = znak.resize((szer, int(znak.height * szer / znak.width)), Image.LANCZOS)
    im.paste(z, (84, 92), z)

    d.text((84, 250), "Portevo", font=_font("segoeuib.ttf", 76), fill=TEKST)
    d.text((86, 350), "Kalendarz wyników spółek", font=_font("segoeuib.ttf", 46),
           fill=ZIELONY)
    d.text((86, 412), "i portfel inwestycyjny", font=_font("segoeuib.ttf", 46),
           fill=TEKST)
    d.text((86, 500),
           "GPW i giełdy amerykańskie · prognozy analityków · po polsku",
           font=_font("segoeui.ttf", 27), fill=SZARY)
    d.text((86, 545), "portevo.pl", font=_font("segoeuib.ttf", 27), fill=SZARY)
    return im.convert("RGB")


def main() -> None:
    os.makedirs(CEL, exist_ok=True)
    znak = _znak()
    # prawa część znaku: słupki z rosnącą strzałką — czytelne nawet przy 32 px
    wykres = znak.crop((int(znak.width * 0.60), 0, znak.width, znak.height))

    def zapisz(im: Image.Image, nazwa: str, **kw) -> None:
        sciezka = os.path.join(CEL, nazwa)
        im.save(sciezka, **kw)
        print(f"  {nazwa:32} {im.size[0]}x{im.size[1]}")

    print("Ikony:")
    zapisz(_kafel(192, wykres), "icon-192.png")
    zapisz(_kafel(512, wykres), "icon-512.png")
    # maskowalna: system może przyciąć do koła, więc motyw musi zmieścić się
    # w bezpiecznym okręgu o średnicy 80% krawędzi
    maskowalna = Image.new("RGBA", (512, 512), TLO)
    m = _kafel(512, wykres, wypelnienie=0.52, przezroczyste_rogi=False)
    maskowalna.paste(m, (0, 0), m)
    zapisz(maskowalna, "icon-maskable-512.png")
    zapisz(_kafel(180, wykres, przezroczyste_rogi=False), "apple-touch-icon.png")
    zapisz(_kafel(256, wykres), "logo-portevo.png")

    ico = _kafel(48, wykres)
    ico.save(os.path.join(CEL, "favicon.ico"),
             sizes=[(16, 16), (32, 32), (48, 48)])
    print("  favicon.ico                      16/32/48")

    print("Podgląd linku:")
    zapisz(_obrazek_podgladu(znak), "og-portevo.png", quality=92)

    # Ta sama ikona dla eksportu Expo — inaczej `expo export` nadpisze
    # `web/favicon.ico` domyślną grafiką z szablonu i karta znów będzie obca.
    expo = os.path.join(REPO, "mobile", "assets", "favicon.png")
    _kafel(48, wykres).save(expo)
    print(f"\nPodmieniono też {os.path.relpath(expo, REPO)} (źródło favicona dla Expo)")


if __name__ == "__main__":
    main()
