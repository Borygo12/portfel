"""Źródło: Squawk (agregatory z Twittera / Bloomberga).
Korzysta z darmowego endpointu TreeNews, który błyskawicznie kopiuje paski
od @DeItaone, @FirstSquawk i innych kont typu 'red headline'.

Zoptymalizowane: persistent session z retry, connection pooling, krótki
timeout z fallbackiem.
"""

import logging
import time
import requests
from datetime import datetime, timezone
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("squawk")

# Darmowy endpoint API TreeNews
TREENEWS_API = "https://news.treeofalpha.com/api/news?limit=30"

_seen: set[str] = set()

# --- Persistent session z retry i connection pooling ---
_session: requests.Session | None = None
_consecutive_failures = 0


def _get_session() -> requests.Session:
    """Lazy-init persistent session z retry i keep-alive."""
    global _session
    if _session is None:
        _session = requests.Session()
        retry = Retry(
            total=2,                    # max 2 ponowienia (3 próby łącznie)
            backoff_factor=0.3,         # 0s, 0.3s, 0.6s
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=1,
            pool_maxsize=2,
        )
        _session.mount("https://", adapter)
        _session.mount("http://", adapter)
        _session.headers.update({
            "User-Agent": "NewsTrader/1.0",
            "Accept": "application/json",
            "Connection": "keep-alive",
        })
    return _session


def _reset_session():
    """Resetuje sesję po serii błędów (np. broken pipe)."""
    global _session
    if _session:
        try:
            _session.close()
        except Exception:
            pass
    _session = None


def fetch_new_squawks(max_age_minutes: float = 10) -> list[dict]:
    """Zwraca listę najnowszych nagłówków ze Squawka."""
    global _consecutive_failures
    
    session = _get_session()
    try:
        r = session.get(TREENEWS_API, timeout=(3.0, 6.0))  # (connect, read) timeout
        r.raise_for_status()
        data = r.json()
        _consecutive_failures = 0  # reset na sukces
    except requests.ConnectionError as e:
        _consecutive_failures += 1
        if _consecutive_failures >= 3:
            log.warning("Squawk: %d awarii z rzędu, resetuję sesję: %s", _consecutive_failures, e)
            _reset_session()
            _consecutive_failures = 0
        else:
            log.debug("Squawk connection error (%d/3): %s", _consecutive_failures, e)
        return []
    except requests.Timeout:
        _consecutive_failures += 1
        log.debug("Squawk timeout (%d/3)", _consecutive_failures)
        if _consecutive_failures >= 3:
            _reset_session()
            _consecutive_failures = 0
        return []
    except Exception as e:
        _consecutive_failures += 1
        log.warning("Błąd pobierania Squawka z TreeNews: %s", e)
        if _consecutive_failures >= 5:
            _reset_session()
            _consecutive_failures = 0
        return []

    out = []
    now_ms = time.time() * 1000

    for item in data:
        item_id = item.get("_id")
        if not item_id or item_id in _seen:
            continue
        
        timestamp_ms = item.get("time", 0)
        age_seconds = (now_ms - timestamp_ms) / 1000.0

        if age_seconds > max_age_minutes * 60:
            _seen.add(item_id)
            continue

        _seen.add(item_id)

        title = item.get("title", "").strip()
        if not title:
            continue

        dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
        
        out.append({
            "id": f"squawk_{item_id}",
            "text": title,
            "created_at": dt.isoformat(),
            "_age_seconds": age_seconds,
            "source": "squawk",
            "url": item.get("url") or f"https://news.treeofalpha.com/{item_id}",
            "ticker": None  # AI wyznaczy
        })
        log.info("Nowy Squawk (%.0f s): %.80s", age_seconds, title)
        
    # Ograniczenie rozmiaru zbioru _seen (żeby nie rósł w nieskończoność)
    if len(_seen) > 5000:
        _seen.clear()
        
    return out

def prime():
    """Oznacza obecne squawki jako przeczytane, żeby przy starcie nie analizować starych newsów."""
    try:
        fetch_new_squawks(max_age_minutes=0)
    except Exception:
        pass
