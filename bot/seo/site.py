"""Adres kanoniczny i dane marki — jedno źródło prawdy dla całej warstwy SEO.

Każdy `<link rel="canonical">`, każdy wpis w sitemapie i każdy adres w llms.txt
bierze się stąd. Literówka w jednym miejscu rozjeżdża indeks, więc adres składa
się dokładnie raz, w `absolute()`.

Dlaczego adres NIE jest brany wprost z `PUBLIC_URL`, którego używa `legal.py`:

Na Railway `PUBLIC_URL` bywa ustawiony na adres hostingu
(`portfel-production.up.railway.app`). Dla dokumentów prawnych to bez znaczenia —
one mają się otworzyć pod jakimkolwiek działającym adresem. Dla SEO to katastrofa:
canonical wskazujący domenę hostingu każe Google zaindeksować `up.railway.app`
zamiast `portevo.pl`, a wtedy cała praca buduje pozycję cudzej domenie i powstaje
klasyczna duplikacja treści pod dwoma adresami.

Stąd kolejność: `CANONICAL_URL` (jeśli ustawisz), potem `PUBLIC_URL` — ale tylko
gdy NIE wygląda na adres hostingu albo maszyny lokalnej — a na końcu domena
docelowa. Dzięki temu zapomniana zmienna środowiskowa nie psuje indeksowania.

Adres jest z `www`, bo goła `portevo.pl` nie działa: Railway daje wyłącznie CNAME,
a CNAME jest niedozwolony na apeksie domeny. Gdy DNS przeniesie się do Cloudflare
(CNAME flattening), wystarczy zmienić tę jedną stałą i sitemapa oraz wszystkie
canonicale pójdą za nią.
"""

from __future__ import annotations

import os

#: Domena docelowa. Zmiana tutaj przestawia canonical, sitemapę i llms.txt naraz.
DEFAULT_URL = "https://www.portevo.pl"

#: Fragmenty adresów, które NIGDY nie mogą trafić do canonicala — to nie są
#: adresy publiczne serwisu, tylko hosting, podgląd albo praca na komputerze.
_NIE_KANONICZNE = ("railway.app", "localhost", "127.0.0.1", "0.0.0.0",
                   "vercel.app", "ngrok", "onrender.com", "[::1]", ".local")


def _wybierz_adres() -> str:
    for kandydat in (os.environ.get("CANONICAL_URL"), os.environ.get("PUBLIC_URL")):
        adres = (kandydat or "").strip().rstrip("/")
        if not adres:
            continue
        if any(zly in adres.lower() for zly in _NIE_KANONICZNE):
            continue
        return adres
    return DEFAULT_URL


URL = _wybierz_adres()

#: Host bez schematu — do porównania z nagłówkiem `Host` przychodzącego żądania.
HOST = URL.split("//", 1)[-1].split("/", 1)[0].lower()

NAME = "Portevo"
FULL_NAME = "Portevo — kalendarz wyników spółek i portfel inwestycyjny"
TAGLINE = "Kalendarz wyników spółek i portfel inwestycyjny w jednym miejscu"

DESCRIPTION = (
    "Kalendarz wyników spółek z GPW i giełd amerykańskich, prognozy analityków "
    "i śledzenie portfela inwestycyjnego. Po polsku, za darmo, w przeglądarce "
    "i na telefonie."
)

LOCALE = "pl_PL"
LANG = "pl"

#: Adres kontaktowy — ten sam, który widnieje w dokumentach prawnych.
EMAIL = os.environ.get("LEGAL_EMAIL") or os.environ.get("OWNER_EMAIL") or "kontakt@portevo.pl"

#: Data uruchomienia serwisu — wchodzi do danych strukturalnych Organization.
FOUNDED = "2026"

#: Dzień ostatniej zmiany w stronach formalnych (regulamin, prywatność, kontakt) —
#: `lastmod` w sitemapie. Podnieś przy zmianie treści (patrz `guides.ZMIENIONO`).
ZMIENIONO = "2026-08-11"

#: Domyślny obrazek podglądu (Facebook, X, Slack, Discord, LinkedIn).
OG_IMAGE = "/static/seo/og-portevo.png"
OG_IMAGE_W, OG_IMAGE_H = 1200, 630


def absolute(path: str = "/") -> str:
    """Adres bezwzględny ze ścieżki. Jedyne miejsce, gdzie sklejamy adresy."""
    sciezka = path if path.startswith("/") else "/" + path
    return URL + ("" if sciezka == "/" else sciezka.rstrip("/"))


def kanoniczny_host(host: str) -> bool:
    """Czy żądanie przyszło pod właściwą domenę.

    Serwer odpowiada pod kilkoma adresami naraz: domeną, adresem Railway,
    a lokalnie także `localhost`. Treść jest wszędzie ta sama, więc gdyby robot
    trafił pod adres hostingu, powstałaby druga kopia serwisu w indeksie.
    Strony spod niekanonicznego hosta dostają nagłówek `X-Robots-Tag: noindex` —
    canonical sam w sobie jest tylko sugestią, nagłówek jest poleceniem.
    """
    return (host or "").split(":", 1)[0].lower() == HOST
