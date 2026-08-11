"""Meta, ikony i treść zapasowa doklejane do `web/index.html` aplikacji.

Dlaczego doklejane w locie, a nie wpisane do pliku: `web/index.html` powstaje
z `npx expo export --platform web` i jest **nadpisywany przy każdej przebudowie
aplikacji**. Cokolwiek by się tam wpisało ręcznie, znika przy najbliższym
eksporcie — i znika po cichu, bo nikt nie sprawdza wygenerowanego pliku.
Doklejanie przy serwowaniu jest odporne na przebudowę i nie wymaga pamiętania
o niczym.

Co dokładamy:

* **Meta.** Expo generuje `<html lang="en">` i sam tytuł „Portevo”, bez opisu
  i bez Open Graph. Efekt: strona po polsku deklarowała angielski, a link
  wklejony na Facebooka czy Discorda pokazywał gołe „Portevo” bez obrazka.
* **Ikony i manifest.** Bez nich karta w przeglądarce jest bez znaku firmowego,
  a „dodaj do ekranu głównego” nie działa jak aplikacja.
* **Treść dla przeglądarek bez JavaScriptu** w `<noscript>`. To jedyne uczciwe
  miejsce na treść, której nie widzi użytkownik z włączonym skryptem: element
  `<noscript>` z definicji pokazuje się TYLKO wtedy, gdy skryptów nie ma, więc
  nikogo nie oszukujemy. Robot bez JS zamiast pustego `<div id="root">` dostaje
  opis serwisu i komplet linków do podstron.

Czego świadomie NIE robimy: nie podstawiamy innej treści pod User-Agenta
wyszukiwarki. To jest cloaking i kończy się wyrzuceniem domeny z indeksu.
"""

from __future__ import annotations

import html as _html
import json
import logging
import os
import threading

from . import features, glossary, guides, site

log = logging.getLogger("seo.shell")

_zamek = threading.Lock()
_pamiec: dict = {"mtime": 0.0, "html": ""}

#: Adresy zakładek aplikacji. Pod każdym serwer podaje TĘ SAMĄ aplikację, a to,
#: którą zakładkę otworzyć, aplikacja odczytuje sobie z adresu (`webRoutes.ts`).
#:
#: Po co: bez tego adres w przeglądarce zawsze brzmiał „portevo.pl" niezależnie
#: od tego, co się ogląda — nie dało się wysłać komuś linku do Alokacji ani
#: wrócić strzałką wstecz. Odświeżenie strony pod takim adresem musi jednak
#: dostać z serwera aplikację, a nie czterysta czwórkę, i po to jest ta lista.
#:
#: Te adresy są CELOWO wyłączone z indeksowania (`noindex` w routingu). Dla
#: robota są pustym pojemnikiem na JavaScript — treść pod te tematy stoi na
#: podstronach pozycjonowanych (`/analiza-portfela`, `/kalendarz-wynikow-spolek`).
#: Gdyby weszły do indeksu, konkurowałyby z nimi o to samo zapytanie i Google
#: wybierałby jedną z dwóch, zwykle tę pustą.
SCIEZKI_APLIKACJI = (
    "/przeglad", "/alokacja", "/zamkniete", "/earnings", "/bot-newsow",
    "/narzedzia", "/wiecej",
)


def _esc(t: str) -> str:
    return _html.escape(t or "", quote=True)


def _meta() -> str:
    tytul = "Portevo — kalendarz wyników spółek i portfel inwestycyjny"
    opis = site.DESCRIPTION
    kanoniczny = site.absolute("/")
    obrazek = site.absolute(site.OG_IMAGE)

    dane = [
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "@id": site.absolute("/#organizacja"),
            "name": site.NAME,
            "url": site.URL,
            "logo": site.absolute("/static/seo/logo-portevo.png"),
            "email": site.EMAIL,
            "description": opis,
            "areaServed": {"@type": "Country", "name": "Polska"},
        },
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "@id": site.absolute("/#serwis"),
            "name": site.NAME,
            "url": site.URL,
            "inLanguage": "pl-PL",
            "description": opis,
            "publisher": {"@id": site.absolute("/#organizacja")},
        },
        {
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            "name": site.NAME,
            "url": site.URL,
            "applicationCategory": "FinanceApplication",
            "operatingSystem": "Web, iOS, Android",
            "inLanguage": "pl-PL",
            "description": opis,
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "PLN"},
        },
    ]
    skrypty = "".join(
        '<script type="application/ld+json">'
        + json.dumps(d, ensure_ascii=False, separators=(",", ":")) + "</script>"
        for d in dane)

    return f"""<meta name="description" content="{_esc(opis)}">
<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large">
<meta name="theme-color" content="#080b11">
<meta name="color-scheme" content="dark">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Portevo">
<meta name="application-name" content="Portevo">
<link rel="canonical" href="{_esc(kanoniczny)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Portevo">
<meta property="og:locale" content="pl_PL">
<meta property="og:title" content="{_esc(tytul)}">
<meta property="og:description" content="{_esc(opis)}">
<meta property="og:url" content="{_esc(kanoniczny)}">
<meta property="og:image" content="{_esc(obrazek)}">
<meta property="og:image:width" content="{site.OG_IMAGE_W}">
<meta property="og:image:height" content="{site.OG_IMAGE_H}">
<meta property="og:image:alt" content="Portevo — kalendarz wyników spółek">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{_esc(tytul)}">
<meta name="twitter:description" content="{_esc(opis)}">
<meta name="twitter:image" content="{_esc(obrazek)}">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/png" href="/static/seo/icon-192.png" sizes="192x192">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/manifest.webmanifest">
<noscript><style>
html,body{{overflow:auto!important;height:auto!important}}
#root{{display:none!important}}
</style></noscript>
{skrypty}"""


def _bez_skryptu() -> str:
    """Treść pokazywana wyłącznie wtedy, gdy przeglądarka nie wykonuje skryptów."""
    def lista(pozycje) -> str:
        return "<ul>" + "".join(
            f'<li><a href="{_esc(a)}">{_esc(t)}</a></li>' for a, t in pozycje) + "</ul>"

    funkcje = [(s, features.STRONY[s]["h1"].split(" — ")[0]) for s in features.STRONY]
    poradniki = [(f"/poradniki/{s}", guides.PORADNIKI[s]["h1"].split(" — ")[0])
                 for s in guides.KOLEJNOSC]
    hasla = [(f"/slownik/{h[0]}", h[1].split(" — ")[0]) for h in glossary.HASLA[:14]]

    return f"""<noscript>
<div class="bez-js">
<h1>Portevo — kalendarz wyników spółek i portfel inwestycyjny</h1>
<p>{_esc(site.DESCRIPTION)}</p>
<p>Sama aplikacja wymaga włączonego JavaScriptu. Poniższe strony działają bez
niego — znajdziesz na nich terminy publikacji raportów, prognozy analityków
i wyjaśnienia pojęć giełdowych.</p>
<h2>Funkcje</h2>
{lista(funkcje)}
<h2>Wyniki finansowe spółek</h2>
{lista([("/wyniki-finansowe", "Wszystkie spółki A–Z"),
        ("/wyniki-finansowe/gpw", "Spółki z GPW"),
        ("/wyniki-finansowe/usa", "Spółki z giełd amerykańskich")])}
<h2>Poradniki</h2>
{lista(poradniki)}
<h2>Słownik giełdowy</h2>
{lista(hasla + [("/slownik", "…wszystkie pojęcia")])}
<h2>Informacje</h2>
{lista([("/kontakt", "Kontakt i pomoc"), ("/regulamin", "Regulamin"),
        ("/prywatnosc", "Polityka prywatności"), ("/premium", "Wersja płatna")])}
<p class="uwaga">Portevo nie jest doradcą inwestycyjnym. Dane mają charakter
informacyjny, nie stanowią rekomendacji ani oferty kupna lub sprzedaży
instrumentów finansowych.</p>
</div>
<style>
.bez-js{{max-width:820px;margin:0 auto;padding:36px 22px 80px;
font:16px/1.65 "Segoe UI",system-ui,sans-serif;color:#eef1f7;background:#080b11}}
.bez-js h1{{font-size:30px;letter-spacing:-1px;margin:0 0 16px}}
.bez-js h2{{font-size:18px;margin:30px 0 10px;color:#eef1f7}}
.bez-js p{{color:#9aa3b8;margin:0 0 12px}}
.bez-js ul{{margin:0;padding-left:20px;display:grid;gap:6px}}
.bez-js a{{color:#2fd48a}}
.bez-js .uwaga{{margin-top:34px;font-size:13px;border-left:3px solid #ffb454;
padding-left:14px}}
</style>
</noscript>"""


def _zbuduj(surowy: str) -> str:
    """Wstrzykuje meta i treść zapasową w wyeksportowany plik aplikacji."""
    out = surowy.replace('<html lang="en">', '<html lang="pl">', 1)
    if '<html lang="pl">' not in out:
        # Expo bywa aktualizowane i potrafi zmienić ten fragment — wtedy sam
        # znacznik zostaje, ale reszta wstrzyknięcia ma zadziałać mimo to.
        log.warning("Nie znaleziono <html lang=\"en\"> w index.html — sprawdź eksport Expo")

    out = out.replace(
        "<title>Portevo</title>",
        "<title>Portevo — kalendarz wyników spółek i portfel inwestycyjny</title>", 1)

    if "</head>" in out:
        out = out.replace("</head>", _meta() + "\n</head>", 1)
    else:
        log.error("Brak </head> w index.html — meta nie zostały dodane")

    if "</body>" in out:
        out = out.replace("</body>", _bez_skryptu() + "\n</body>", 1)
    return out


def index_html(sciezka: str) -> str:
    """Zawartość strony aplikacji, z cache po czasie modyfikacji pliku.

    Cache po `mtime`, a nie na stałe: gdy podmienisz `web/` nową wersją aplikacji,
    serwer ma to zauważyć bez restartu.
    """
    try:
        mtime = os.path.getmtime(sciezka)
    except OSError:
        mtime = 0.0

    with _zamek:
        if _pamiec["html"] and _pamiec["mtime"] == mtime:
            return _pamiec["html"]

    with open(sciezka, encoding="utf-8") as f:
        surowy = f.read()
    gotowy = _zbuduj(surowy)

    with _zamek:
        _pamiec["mtime"] = mtime
        _pamiec["html"] = gotowy
    return gotowy
