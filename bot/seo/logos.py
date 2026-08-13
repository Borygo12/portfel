"""Znaki firmowe spółek na podstronach — z zapasem, który nie potrzebuje skryptu.

Ludzie nie czytają strony od pierwszego słowa, tylko ją skanują. Logo obok
nazwy spółki jest punktem zaczepienia, po którym w ułamku sekundy wiadomo, że
trafiło się na właściwą firmę — i to działa tak samo w nagłówku podstrony,
jak na liście „inne spółki z branży”.

Skąd obrazki: z tego samego źródła, którego używa aplikacja
(`earnings/report.py` → `financialmodelingprep.com/image-stock/SYMBOL.png`),
ale **pobrane raz do repozytorium** przez `make_logos.py` i podawane z naszego
serwera. Hotlink z cudzej domeny to dodatkowe rozwiązanie DNS i połączenie TLS
w krytycznej ścieżce rysowania strony, a jego awaria zostawia dziurę
w naszej stronie — dokładnie tam, gdzie robot ją zobaczy.

**Zapas bez JavaScriptu.** Standardowe `onerror="…"` w atrybucie to skrypt,
a warstwa SEO działa całkowicie bez skryptów. Zamiast tego monogram (dwie
litery na barwnym kwadracie) leży POD obrazkiem jako zwykły HTML, a obrazek
przykrywa go w całości. Gdy pobranie się nie uda, przeglądarka rysuje pusty
element z `alt=""` — i spod spodu wychodzi monogram. Nic nie miga, nic nie
trzeba wykonywać.

Kolor monogramu jest funkcją symbolu, nie losowy: ta sama spółka ma zawsze
ten sam kolor na każdej podstronie, więc oko zaczyna go kojarzyć.
"""

from __future__ import annotations

import os

from .render import esc

_KATALOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "static", "seo", "logos")
_ADRES_LOKALNY = "/static/seo/logos/{}.png"


def _pobrane() -> set[str]:
    """Nazwy plików logo leżących w repozytorium — czytane raz, przy starcie.

    Sprawdzanie istnienia pliku przy każdym żądaniu byłoby setkami wywołań
    systemu na jedną stronę spisu spółek. Katalog zmienia się wyłącznie przy
    ręcznym uruchomieniu `make_logos.py`, więc restart serwera to właściwy
    moment na odświeżenie tej listy.
    """
    try:
        return {n[:-4].lower() for n in os.listdir(_KATALOG) if n.endswith(".png")}
    except OSError:
        return set()


MAM: set[str] = _pobrane()

#: Barwy monogramów — z palety motywu, w wersji przygaszonej, żeby kwadrat
#: nie krzyczał głośniej niż treść obok.
_BARWY = ("#2b6a52", "#2a4a72", "#5c4a7a", "#6b4a34", "#3b5566",
          "#6b3f4f", "#3f5c3a", "#4a4f6b")


#: Słowa, które nie niosą rozróżnienia — monogram złożony z nich byłby taki sam
#: dla połowy katalogu.
_POMIJANE = {"of", "and", "the", "i", "w", "na", "de", "&"}


def monogram_litery(nazwa: str, symbol: str = "") -> str:
    """Dwie litery znaku zastępczego.

    Bierzemy pierwsze litery dwóch pierwszych ZNACZĄCYCH słów, a nie dwie
    pierwsze litery nazwy — inaczej „Bank Millennium”, „Bank Handlowy”
    i „Bank Ochrony Środowiska” miałyby identyczne „BA” i monogram przestałby
    cokolwiek rozróżniać. „Bank of America” → „BA”, bo „of” pomijamy.
    """
    slowa = [s for s in (nazwa or "").replace("-", " ").split() if s]
    znaczace = [s for s in slowa if s.lower() not in _POMIJANE]
    if len(znaczace) >= 2:
        return (znaczace[0][0] + znaczace[1][0]).upper()
    if znaczace:
        return znaczace[0][:2].upper()
    return (symbol or "?")[:2].upper()


def barwa(symbol: str) -> str:
    return _BARWY[sum(ord(z) for z in (symbol or "?")) % len(_BARWY)]


def adres(symbol: str) -> str:
    """Adres obrazka albo pusty napis, gdy spółka logotypu nie ma.

    Brak pliku traktujemy jako „logotypu nie ma” i pokazujemy sam monogram —
    zamiast sięgać po adres zewnętrzny. Powód jest praktyczny: `make_logos.py`
    odrzuca obrazki zastępcze (dla kilku spółek z GPW źródło oddaje przezroczysty
    kwadrat 1×1), a hotlink przyniósłby dokładnie ten pusty kwadrat i przykrył
    nim monogram. Skutek uboczny, o którym trzeba wiedzieć: **spółka dopisana do
    katalogu bez uruchomienia `make_logos.py` zostaje z monogramem.**
    """
    s = (symbol or "").strip().upper()
    if s and s.lower() in MAM:
        return _ADRES_LOKALNY.format(s)
    return ""


def znak(spolka: dict, rozmiar: int = 44, klasa: str = "") -> str:
    """Kafelek z logo spółki. `spolka` to wpis z katalogu (`companies.json`)."""
    symbol = spolka.get("symbol") or ""
    nazwa = spolka.get("name") or symbol
    litery = monogram_litery(nazwa, symbol)
    styl = f"--logo-size:{int(rozmiar)}px;--logo-bg:{barwa(symbol)}"
    dodatkowa = f" {esc(klasa)}" if klasa else ""
    obrazek = adres(symbol)
    # `alt=""` jest celowe: nazwa spółki stoi tuż obok jako tekst, więc czytnik
    # ekranu powtarzałby ją dwa razy. Obrazek jest tu ozdobą, nie treścią.
    img = (f'<img src="{esc(obrazek)}" alt="" loading="lazy" decoding="async" '
           f'width="{int(rozmiar)}" height="{int(rozmiar)}">' if obrazek else "")
    return (f'<span class="logo{dodatkowa}" style="{esc(styl)}" aria-hidden="true">'
            f"<i>{esc(litery)}</i>{img}</span>")


#: Styl kafelka — dokładany do arkusza w `render.py`.
CSS = """
.logo{position:relative;display:inline-block;flex:0 0 auto;
  width:var(--logo-size,44px);height:var(--logo-size,44px);
  border-radius:calc(var(--logo-size,44px)*.24);overflow:hidden;
  background:var(--logo-bg,#2a4a72);vertical-align:middle}
.logo i{position:absolute;inset:0;display:flex;align-items:center;
  justify-content:center;font-style:normal;font-weight:800;color:#eef1f7;
  font-size:calc(var(--logo-size,44px)*.38);letter-spacing:-.5px}
.logo img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;
  background:#fff;padding:calc(var(--logo-size,44px)*.10)}
"""
