"""Źródło: Komunikaty i decyzje KNF — OGÓLNE (nie rejestr krótkiej sprzedaży,
patrz sources/knf_registry.py dla tego).

KNF publikuje WSZYSTKIE komunikaty/decyzje/kary jako jeden RSS na
https://www.knf.gov.pl/api/rss — to firehose: miesza rutynowe wpisy
administracyjne (rejestracje, szablony raportowania, ogólne stanowiska bez
nazwy spółki) z realnie rynkotwórczymi decyzjami (kara na spółkę notowaną na
GPW, cofnięcie zezwolenia, wszczęcie postępowania). Przykład z życia: kara
20 mln zł na XTB S.A. (30.03.2026, spółka notowana na GPW) — komunikat
poruszył kurs. Feed jest oficjalny i bezpośredni (bez pośrednika, w
odróżnieniu od knf_registry.py, gdzie oficjalny system KNF jest zbyt zawodny).

Tani pre-filtr słów kluczowych (ten sam wzorzec co _squawk_noise_filter w
analyzer.py) odsiewa oczywistą rutynę PRZED wysłaniem do AI — reszta (podmiot
+ działanie regulacyjne w tytule) leci normalną ścieżką LLM
(source="gpw_espi"), która sama oceni, czy podmiot jest tradowalną spółką GPW
i jak silny to sygnał (patrz prompts.py, sekcja "polish").
"""

import logging
import time
from datetime import datetime, timezone

import feedparser
import requests

log = logging.getLogger("knf_announcements")

KNF_RSS = "https://www.knf.gov.pl/api/rss"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
}

# rdzenie słów wskazujące na DZIAŁANIE REGULACYJNE wobec nazwanego podmiotu —
# odsiewa rutynę (rejestracje, szablony, ogólne stanowiska) bez wysyłania jej do AI
_MATERIAL_KEYWORDS = ("KAR", "POSTĘPOWANI", "DECYZJ", "COFNIĘ", "ZEZWOLEN",
                      "LICENCJ", "ZAKAZ", "WYKREŚLEN", "OSTRZEŻEN", "SANKCJ")

_seen: set[str] = set()


def _is_material(title: str) -> bool:
    up = title.upper()
    return any(k in up for k in _MATERIAL_KEYWORDS)


def fetch_new_knf_announcements(max_age_minutes: float = 120) -> list[dict]:
    """Zwraca nowe, potencjalnie rynkotwórcze komunikaty/decyzje KNF."""
    out = []
    now_ts = time.time()
    try:
        # feedparser.parse(url) robi własne żądanie przez stdlib ssl, które na
        # certyfikacie knf.gov.pl wywala CERTIFICATE_VERIFY_FAILED (niekompletny
        # łańcuch po stronie serwera) — requests+certifi ma pełniejszy zestaw CA
        # i pobiera bez problemu, więc pobieramy sami i podajemy feedparserowi gotowe bajty.
        resp = requests.get(KNF_RSS, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception as e:
        log.warning("Błąd pobierania feedu komunikatów KNF: %s", e)
        return out

    for entry in parsed.entries:
        entry_id = getattr(entry, "id", None) or getattr(entry, "link", None)
        if not entry_id or entry_id in _seen:
            continue

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
            continue
        _seen.add(entry_id)

        title = getattr(entry, "title", "").strip()
        if not title or not _is_material(title):
            continue  # rutyna administracyjna — nie wysyłamy do AI

        summary = getattr(entry, "summary", getattr(entry, "description", "")).strip()
        text = f"[KNF KOMUNIKAT] {title}. {summary}"
        out.append({
            "id": f"knfann_{entry_id}",
            "text": text[:1500],
            "created_at": dt.isoformat(),
            "_age_seconds": age_seconds,
            "source": "gpw_espi",
            "url": getattr(entry, "link", ""),
            "ticker": None,  # AI wyznaczy ticker, jeśli podmiot to spółka GPW
        })
        log.info("Nowy komunikat KNF (%.0f min): %.100s", age_seconds / 60, title)

    if len(_seen) > 5000:
        _seen.clear()
    return out


def prime():
    """Oznacz obecne komunikaty jako przeczytane — nie gramy na starych przy starcie."""
    try:
        fetch_new_knf_announcements(max_age_minutes=0)
    except Exception:
        pass
