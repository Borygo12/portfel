"""Źródło: Rządowe kanały RSS (Departament Skarbu/OFAC, Departament Stanu).
Śledzi oficjalne decyzje USA o sankcjach, polityce zagranicznej, rezerwach itp.
"""

import logging
import time
import feedparser
from datetime import datetime, timezone

log = logging.getLogger("gov_rss")

# Słownik z feedami do monitorowania
RSS_FEEDS = {
    "OFAC (Sankcje)": "https://ofac.treasury.gov/recent-actions/rss.xml",
    "State Dept": "https://www.state.gov/rss-feeds/press-releases-rss/",
    "EIA (Ropa/Energia)": "https://www.eia.gov/rss/press.xml"
}

_seen: set[str] = set()

def fetch_new_gov_news(max_age_minutes: float = 30) -> list[dict]:
    out = []
    now_ts = time.time()

    for feed_name, url in RSS_FEEDS.items():
        try:
            parsed = feedparser.parse(url)
            for entry in parsed.entries:
                entry_id = getattr(entry, "id", getattr(entry, "link", None))
                if not entry_id or entry_id in _seen:
                    continue

                # Czas publikacji
                published_parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
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
                summary = getattr(entry, "summary", getattr(entry, "description", "")).strip()

                # Czasem summary zawiera tagi HTML (feedparser próbuje je czyścić, ale może zostać brud)
                text = f"[{feed_name}] {title} - {summary}"
                if len(text) > 4000:
                    text = text[:4000]

                out.append({
                    "id": f"gov_{entry_id}",
                    "text": text,
                    "created_at": dt.isoformat(),
                    "_age_seconds": age_seconds,
                    "source": "gov_rss",
                    "url": getattr(entry, "link", ""),
                    "ticker": None
                })
                log.info("Nowy GOV RSS (%s, %.0f min): %.70s", feed_name, age_seconds / 60, title)
        except Exception as e:
            log.warning("Błąd odpytywania feedu %s (%s): %s", feed_name, url, e)

    return out

def prime():
    try:
        fetch_new_gov_news(max_age_minutes=0)
    except Exception:
        pass
