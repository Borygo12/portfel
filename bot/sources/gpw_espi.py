"""Źródło: GPW / NewConnect — raporty ESPI/EBI (komunikaty cenotwórcze spółek).

To polski odpowiednik amerykańskiego SEC 8-K: spółki notowane na GPW mają PRAWNY
obowiązek natychmiast publikować informacje poufne (cenotwórcze) w systemie ESPI.

ŹRÓDŁA (kolejność = prędkość):
  1. PAP Biznes (biznes.pap.pl/rss) — PRIMARY. PAP to oficjalny DYSTRYBUTOR ESPI:
     dostaje raport praktycznie w chwili publikacji przez spółkę. Bankier i reszta
     portali dopiero KOPIUJĄ z PAP, więc PAP = realny sufit prędkości dla darmowego
     dostępu. (Test 2026-07-13: raport ACTION miał na gpw.pl znacznik 13:43:18; przez
     opóźniony RSS Bankiera dostawaliśmy go dopiero ~14:08 — 25 min straty. PAP zdejmuje
     to opóźnienie.)
  2. Bankier (bankier.pl/rss/espi.xml) — FALLBACK, tylko gdy PAP nie odpowie.

UWAGA o PAP: feed /rss to firehose (raporty spółek + newsy + wyceny funduszy/OFE), nie
czysty ESPI jak feed Bankiera. Dlatego filtrujemy do raportów ESPI/EBI: wzorzec numeru
raportu "(NN/RRRR)" w tytule + link /wiadomosci/firmy/ + wycięcie szumu wycen funduszy.

Tytuł ma format "NAZWA SPÓŁKI (NN/RRRR) temat raportu" — sam w sobie jest zwięzłym
sygnałem. AI wyznacza z nazwy spółki ticker GPW i ocenia materialność.

Przewaga: gdy giełda w USA jest zamknięta, GPW handluje już od rana, a konkurencja
w tradowaniu na newsach jest tu znacznie mniejsza.
"""

import logging
import re
import time
from datetime import datetime, timezone

import feedparser
import requests

log = logging.getLogger("gpw_espi")

# PRIMARY: oficjalny dystrybutor ESPI. FALLBACK: opóźniony eksport Bankiera.
PAP_FEED = "https://biznes.pap.pl/rss"
BANKIER_FEED = "https://www.bankier.pl/rss/espi.xml"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# numer raportu ESPI/EBI w tytule PAP, np. "ACTION S.A. (34/2026) ..." — bez tego to nie raport
_REPORT_NO_RE = re.compile(r"\(\d+/\d{4}\)")
# tylko firmowy dział PAP (raporty spółek); odsiewa newsy makro/międzynarodowe
_PAP_FIRMY = "/wiadomosci/firmy/"
# szum PAP: wyceny funduszy/jednostek (formalnie ESPI, ale bez wartości do tradowania)
_PAP_NOISE = (
    "wycenie wartości aktywów netto",
    "wartości aktywów netto funduszu",
    "wartość jednostki rozrachunkowej",
    "wartości jednostki rozrachunkowej",
    "wartość aktywów netto na certyfikat",
)

# boilerplate, który Bankier wkleja do każdego streszczenia — wycinamy jako szum
_BOILER = (
    "Spis treści",
    "Poniższe streszczenie ma charakter wyłącznie informacyjny",
    "MESSAGE (ENGLISH VERSION)",
    "INFORMACJE O PODMIOCIE",
    "PODPISY OSÓB REPREZENTUJĄCYCH SPÓŁKĘ",
)

_seen: set[str] = set()


def _clean_summary(html: str) -> str:
    """Usuwa tagi HTML i firmowy boilerplate ze streszczenia ESPI."""
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", html or "")).strip()
    for junk in _BOILER:
        idx = text.find(junk)
        if idx != -1:
            text = text[:idx].strip()
    return text[:600]


def _fetch(url: str):
    """Pobiera feed z browserowym UA i parsuje. PAP odrzuca domyślny UA feedparsera,
    więc ściągamy przez requests i podajemy surowe bajty."""
    r = requests.get(url, headers=_HEADERS, timeout=15)
    r.raise_for_status()
    return feedparser.parse(r.content)


def _is_pap_espi(entry) -> bool:
    """Czy wpis z firehose'u PAP to raport ESPI/EBI spółki (a nie news/wycena funduszu)?"""
    title = getattr(entry, "title", "") or ""
    if not _REPORT_NO_RE.search(title):
        return False                      # brak numeru raportu -> to nie ESPI/EBI
    link = (getattr(entry, "link", "") or "").lower()
    if _PAP_FIRMY not in link:
        return False                      # nie firmowy dział -> odsiewamy
    low = title.lower()
    if any(n in low for n in _PAP_NOISE):
        return False                      # wyceny funduszy/jednostek -> szum
    return True


def _emit(entry, now_ts: float, max_age_minutes: float, source: str,
          want_summary: bool) -> dict | None:
    """Wspólna obróbka wpisu: dedup, filtr wieku, złożenie sygnału w kształcie dla runnera."""
    entry_id = getattr(entry, "id", None) or getattr(entry, "link", None)
    if not entry_id or entry_id in _seen:
        return None

    published_parsed = getattr(entry, "published_parsed", None) or \
        getattr(entry, "updated_parsed", None)
    if published_parsed:
        dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
        age_seconds = now_ts - dt.timestamp()
    else:
        dt = datetime.now(timezone.utc)
        age_seconds = 0

    if age_seconds > max_age_minutes * 60:
        _seen.add(entry_id)
        return None

    _seen.add(entry_id)

    title = getattr(entry, "title", "").strip()
    if not title:
        return None

    text = f"[ESPI] {title}"
    if want_summary:
        # streszczenie dokładamy tylko gdy wnosi treść ponad tytuł (PAP dubluje tytuł w opisie)
        summary = _clean_summary(getattr(entry, "summary",
                                         getattr(entry, "description", "")))
        if summary and len(summary) > 20 and summary.lower() not in title.lower():
            text += f" — {summary}"

    log.info("Nowy ESPI (%.1f min, %s): %.90s", age_seconds / 60, source, title)
    return {
        "id": f"gpw_{entry_id}",
        "text": text[:2000],
        "created_at": dt.isoformat(),
        "_age_seconds": age_seconds,
        "source": "gpw_espi",
        "url": getattr(entry, "link", ""),
        "ticker": None,   # AI wyznaczy ticker GPW z nazwy spółki
    }


def fetch_new_gpw_reports(max_age_minutes: float = 30) -> list[dict]:
    """Zwraca nowe raporty ESPI/EBI młodsze niż max_age_minutes.

    Najpierw PAP (szybki, filtrowany do raportów spółek). Gdy PAP padnie —
    fallback na Bankier (wolniejszy, ale to czysty feed ESPI, bez filtrowania).
    """
    now_ts = time.time()
    out = []

    # --- PRIMARY: PAP ---
    try:
        parsed = _fetch(PAP_FEED)
        for entry in parsed.entries:
            if not _is_pap_espi(entry):
                continue
            rep = _emit(entry, now_ts, max_age_minutes, "PAP", want_summary=False)
            if rep:
                out.append(rep)
        if len(_seen) > 5000:
            _seen.clear()
        return out
    except Exception as e:
        log.warning("PAP niedostępny (%s) — fallback na Bankier", e)

    # --- FALLBACK: Bankier (czysty feed ESPI, ale opóźniony) ---
    try:
        parsed = _fetch(BANKIER_FEED)
        for entry in parsed.entries:
            rep = _emit(entry, now_ts, max_age_minutes, "Bankier", want_summary=True)
            if rep:
                out.append(rep)
    except Exception as e:
        log.warning("Błąd pobierania feedu Bankier: %s", e)

    if len(_seen) > 5000:
        _seen.clear()
    return out


def prime():
    """Oznacz obecne raporty jako przeczytane — nie gramy na starych przy starcie."""
    try:
        fetch_new_gpw_reports(max_age_minutes=0)
    except Exception:
        pass
