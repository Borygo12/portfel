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
  a „dodaj do ekranu głównego” nie działa jak aplikacja. Kolejność wpisów nie
  jest przypadkowa: pierwsze idą PNG 96 i 48 px, bo robot faworytów Google
  przyjmuje ikony o boku będącym wielokrotnością 48 px i sięga po nie przed
  plikiem `.ico` — a przy jego odrzuceniu w wynikach wyszukiwania widnieje
  szara kula zamiast znaku firmowego.
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
#: tytuł strony -> (mtime pliku, gotowy HTML)
_pamiec: dict = {}

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
    "/narzedzia", "/artykuly", "/wiecej", "/aplikacja",
    # Panelu dewelopera nie ma już pod własnym adresem: rozwija się w „Więcej"
    # i widzi go wyłącznie właściciel. Dostęp i tak pilnuje `require_owner`
    # przy każdym endpointcie, nie routing.
)


def _esc(t: str) -> str:
    return _html.escape(t or "", quote=True)


#: Tytuł i opis adresu głównego.
#:
#: **Muszą opisywać to, co pod „/" naprawdę widać po uruchomieniu aplikacji** —
#: a widać Przegląd z portfelem pokazowym. Wcześniej stał tu tytuł obiecujący
#: „kalendarz wyników spółek", czyli treść, której na tym ekranie nie ma:
#: robot renderujący JavaScript zastawał listę pozycji z kwotami i szukał
#: w niej kalendarza. Taki rozjazd między obietnicą a zawartością jest jedną
#: z niewielu rzeczy, które wyszukiwarka mierzy wprost, i nigdzie nie boli tak
#: jak na najmocniejszym adresie w domenie.
#:
#: Frazy „kalendarz wyników spółek" broni dziś `/kalendarz-wynikow-spolek` —
#: strona, która faktycznie o tym jest, ma prawie tysiąc słów i dane
#: strukturalne FAQ. Adres główny gra o markę i o to, czym jest sama aplikacja.
#: Zmieniając tutaj cokolwiek, sprawdź najpierw, co widać na pierwszym ekranie.
TYTUL_GLOWNY = "Portevo — aplikacja do śledzenia portfela inwestycyjnego"

#: Długość trzymamy poniżej ~155 znaków — dłuższy opis Google i tak utnie
#: wielokropkiem, zwykle w połowie zdania, i w wynikach zostaje ogon bez sensu.
OPIS_GLOWNY = (
    "Otwiera się od razu w przeglądarce, bez konta i bez instalacji. Wgraj raport "
    "maklerski i zobacz wartość pozycji, stopę zwrotu i koszty portfela."
)

#: Tytuł karty przeglądarki per adres zakładki.
#:
#: Po co, skoro te adresy i tak są `noindex`: tytuł to jedyna rzecz, po której
#: rozpoznaje się kartę wśród kilkunastu otwartych, i to on pokazuje się, gdy
#: ktoś wyśle link znajomemu. Jeden wspólny tytuł na wszystkich zakładkach
#: znaczył w praktyce tyle, co brak tytułu.
TYTULY = {
    "/": TYTUL_GLOWNY,
    "/przeglad": "Przegląd portfela — Portevo",
    "/alokacja": "Alokacja portfela — Portevo",
    "/zamkniete": "Zamknięte pozycje — Portevo",
    "/earnings": "Kalendarz wyników spółek — Portevo",
    "/bot-newsow": "Bot newsów — Portevo",
    "/narzedzia": "Narzędzia — Portevo",
    "/artykuly": "Artykuły i dane — Portevo",
    "/wiecej": "Więcej — Portevo",
    "/aplikacja": "Portevo na telefon — pobierz aplikację",
}


def tytul_dla(adres: str) -> str:
    czysty = (adres or "/").split("?")[0].split("#")[0]
    if len(czysty) > 1:
        czysty = czysty.rstrip("/")
    return TYTULY.get(czysty or "/", TYTUL_GLOWNY)


def _meta(tytul: str = TYTUL_GLOWNY) -> str:
    # Opis strony ma pasować do jej pierwszego ekranu (patrz `OPIS_GLOWNY`),
    # a `site.DESCRIPTION` opisuje CAŁY serwis i zostaje tam, gdzie faktycznie
    # chodzi o serwis: w danych `Organization` i `WebSite` niżej oraz w llms.txt.
    opis = OPIS_GLOWNY
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
            "description": site.DESCRIPTION,
            "areaServed": {"@type": "Country", "name": "Polska"},
        },
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "@id": site.absolute("/#serwis"),
            "name": site.NAME,
            "url": site.URL,
            "inLanguage": "pl-PL",
            "description": site.DESCRIPTION,
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
            "description": site.DESCRIPTION,
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
<link rel="icon" type="image/png" href="/static/seo/icon-96.png" sizes="96x96">
<link rel="icon" type="image/png" href="/static/seo/icon-48.png" sizes="48x48">
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
<h1>{_esc(TYTUL_GLOWNY)}</h1>
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


def _zbuduj(surowy: str, adres: str = "/") -> str:
    """Wstrzykuje meta i treść zapasową w wyeksportowany plik aplikacji."""
    tytul = tytul_dla(adres)
    out = surowy.replace('<html lang="en">', '<html lang="pl">', 1)
    if '<html lang="pl">' not in out:
        # Expo bywa aktualizowane i potrafi zmienić ten fragment — wtedy sam
        # znacznik zostaje, ale reszta wstrzyknięcia ma zadziałać mimo to.
        log.warning("Nie znaleziono <html lang=\"en\"> w index.html — sprawdź eksport Expo")

    out = out.replace("<title>Portevo</title>", f"<title>{_esc(tytul)}</title>", 1)

    if "</head>" in out:
        out = out.replace("</head>", _meta(tytul) + "\n</head>", 1)
    else:
        log.error("Brak </head> w index.html — meta nie zostały dodane")

    if "</body>" in out:
        out = out.replace("</body>", _bez_skryptu() + "\n</body>", 1)
    return out


def index_html(plik: str, adres: str = "/") -> str:
    """Zawartość strony aplikacji dla danego adresu, z cache.

    Cache jest po `mtime` pliku ORAZ po adresie: strony różnią się tytułem, więc
    jedna zapamiętana wersja podawałaby pod wszystkimi adresami tytuł tego,
    kto wszedł pierwszy. Wariantów jest osiem, więc pamięć to nie problem.

    `mtime` w kluczu jest po to, żeby podmiana `web/` nową wersją aplikacji była
    widoczna bez restartu serwera.
    """
    try:
        mtime = os.path.getmtime(plik)
    except OSError:
        mtime = 0.0

    klucz = tytul_dla(adres)
    with _zamek:
        zapisane = _pamiec.get(klucz)
        if zapisane and zapisane[0] == mtime:
            return zapisane[1]

    with open(plik, encoding="utf-8") as f:
        surowy = f.read()
    gotowy = _zbuduj(surowy, adres)

    with _zamek:
        _pamiec[klucz] = (mtime, gotowy)
    return gotowy
