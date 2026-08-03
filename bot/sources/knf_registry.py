"""Źródło: Rejestr Krótkiej Sprzedaży KNF (Moduł 2B ze "Speed-Bota").

KNF (Komisja Nadzoru Finansowego) publikuje jawny rejestr pozycji krótkiej sprzedaży
(≥0.5% kapitału spółki, zgodnie z Rozporządzeniem UE nr 236/2012) na rss.knf.gov.pl —
system jest jednak notorycznie zawodny (błędy JSF-a, brak publicznego API/exportu).
Zamiast walczyć z oficjalnym systemem, korzystamy z shorty.pl — niezależnego
monitora, który już odświeża dane z rejestru KNF co ~15 min i publikuje je jako
czytelny kanał RSS (https://shorty.pl/api/events.rss). Ten sam wzorzec co
sources/gpw_espi.py, który zamiast surowego systemu ESPI/PAP korzysta z
przyjaźniejszego mirrora bankier.pl.

Dlaczego to ma znaczenie (realna przewaga nawet wobec dużych graczy jak XTB):
gdy duży fundusz (np. Marshall Wace) ZAMYKA dużą pozycję krótką na spadającej
spółce, to często zapowiedź "short squeeze" — zniknięcie presji podażowej ze
strony shortów potrafi wywołać gwałtowny ruch w górę, zanim to zauważy reszta
rynku. Odwrotnie: duży fundusz OTWIERAJĄCY/ZWIĘKSZAJĄCY shorta = ktoś z dostępem
do analizy uznał spółkę za przewartościowaną.

Ticker NIE jest tu rozpoznawany programowo (shorty.pl podaje nazwę emitenta, a nie
zawsze 1:1 symbol maklerski Saxo) — tekst zdarzenia leci normalną ścieżką LLM
(source="gpw_espi"), tak jak reszta polskich newsów; AI zna popularne spółki GPW
i samo dobiera ticker (patrz prompts.py, sekcja "polish" — tam też reguły
interpretacji zamknięcia/zwiększenia pozycji).
"""

import logging
import time
from datetime import datetime, timezone

import feedparser

log = logging.getLogger("knf_registry")

KNF_FEED = "https://shorty.pl/api/events.rss"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
}

# fragment tytułu (shorty.pl, WIELKIMI literami) -> etykieta do tekstu newsa dla AI
_ACTION_LABELS = [
    ("ZAMKNIĘCIE", "ZAMKNIĘCIE POZYCJI SHORT — fundusz w całości wyszedł z shorta (potencjalny short squeeze)"),
    ("PONOWNE UJAWNIENIE", "PONOWNE UJAWNIENIE — administracyjne odświeżenie, bez realnej zmiany wielkości"),
    ("ZMNIEJSZENIE", "ZMNIEJSZENIE POZYCJI SHORT — częściowe wyjście z shorta"),
    ("ZWIĘKSZENIE", "ZWIĘKSZENIE POZYCJI SHORT — fundusz dokłada do shorta"),
    ("NOWA POZYCJA", "NOWA POZYCJA SHORT — fundusz otworzył nowego shorta"),
]

_seen: set[str] = set()


def fetch_new_knf_events(max_age_minutes: float = 60) -> list[dict]:
    """Zwraca nowe zdarzenia z rejestru krótkiej sprzedaży KNF (mirror: shorty.pl)."""
    out = []
    now_ts = time.time()
    try:
        parsed = feedparser.parse(KNF_FEED, request_headers=_HEADERS)
    except Exception as e:
        log.warning("Błąd pobierania feedu KNF (shorty.pl): %s", e)
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
        if not title:
            continue
        summary = getattr(entry, "summary", getattr(entry, "description", "")).strip()

        title_up = title.upper()
        action = next((label for key, label in _ACTION_LABELS if key in title_up),
                      "ZMIANA POZYCJI SHORT")

        text = f"[KNF REJESTR KRÓTKIEJ SPRZEDAŻY] {action}. {title} — {summary}"
        out.append({
            "id": f"knf_{entry_id}",
            "text": text[:1500],
            "created_at": dt.isoformat(),
            "_age_seconds": age_seconds,
            "source": "gpw_espi",
            "url": getattr(entry, "link", ""),
            "ticker": None,  # AI wyznaczy ticker GPW z nazwy emitenta
        })
        log.info("Nowe zdarzenie KNF (%.0f min): %.100s", age_seconds / 60, title)

    if len(_seen) > 5000:
        _seen.clear()
    return out


def prime():
    """Oznacz obecne zdarzenia jako przeczytane — nie gramy na starych przy starcie."""
    try:
        fetch_new_knf_events(max_age_minutes=0)
    except Exception:
        pass
