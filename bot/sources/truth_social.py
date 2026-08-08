"""Polling nowych postów Trumpa z Truth Social — ZA DARMO, bez pośredników.

Źródła (w kolejności):
1. DIRECT  — publiczne API Truth Social (to samo, którego używa strona www;
             profil Trumpa jest widoczny bez logowania). curl_cffi podszywa się
             pod przeglądarkę Chrome, żeby przejść ochronę Cloudflare.
2. RSS     — trumpstruth.org/feed (darmowe archiwum aktualizowane co kilka minut)
             jako zapas, gdyby DIRECT przestał odpowiadać.
3. SCRAPECREATORS — płatny, tylko jeśli klucz w .env (wyłączony domyślnie).

Zasada real-time edge: post przechodzi dalej tylko gdy (a) nie widzieliśmy go
wcześniej i (b) jest młodszy niż max_post_age_minutes.
"""

import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests
from curl_cffi import requests as cffi

log = logging.getLogger("truth")

TRUMP_ACCOUNT_ID = "107780257626128497"  # stałe ID @realDonaldTrump
DIRECT_URL = f"https://truthsocial.com/api/v1/accounts/{TRUMP_ACCOUNT_ID}/statuses"
RSS_URL = "https://www.trumpstruth.org/feed"

_seen_ids: set[str] = set()


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "").replace("&amp;", "&").replace(
        "&quot;", '"').replace("&#39;", "'").strip()


def _fetch_direct() -> list[dict]:
    r = cffi.get(DIRECT_URL, params={"limit": 10, "exclude_replies": "true"},
                 impersonate="chrome", timeout=10)
    r.raise_for_status()
    return [{
        "id": p["id"],
        "text": _strip_html(p.get("content", "")),
        "created_at": p.get("created_at"),
        "source": "direct",
    } for p in r.json()]


def _fetch_rss() -> list[dict]:
    r = requests.get(RSS_URL, timeout=10, headers={"User-Agent": "portevo-bot"})
    r.raise_for_status()
    out = []
    for item in ET.fromstring(r.content).iter("item"):
        link = item.findtext("link") or ""
        pub = item.findtext("pubDate")
        try:
            created = parsedate_to_datetime(pub).isoformat() if pub else None
        except (TypeError, ValueError):
            created = None
        out.append({
            "id": link.rstrip("/").rsplit("/", 1)[-1] or link,
            "text": _strip_html(item.findtext("description") or item.findtext("title") or ""),
            "created_at": created,
            "source": "rss",
        })
    return out


def _fetch_scrapecreators() -> list[dict]:
    r = requests.get(
        "https://api.scrapecreators.com/v1/truthsocial/user/posts",
        params={"handle": "realDonaldTrump"},
        headers={"x-api-key": os.environ["SCRAPECREATORS_API_KEY"]},
        timeout=10,
    )
    r.raise_for_status()
    return [{
        "id": p.get("id"),
        "text": p.get("text") or _strip_html(p.get("content", "")),
        "created_at": p.get("created_at") or p.get("createdAt"),
        "source": "scrapecreators",
    } for p in r.json().get("posts", [])]


def _fetch_any() -> list[dict]:
    sources = [("direct", _fetch_direct), ("rss", _fetch_rss)]
    if os.environ.get("SCRAPECREATORS_API_KEY"):
        sources.append(("scrapecreators", _fetch_scrapecreators))
    last_err = None
    for name, fn in sources:
        try:
            return fn()
        except Exception as e:
            last_err = e
            log.warning("Źródło %s zawiodło (%s) — próbuję następne", name, e)
    raise RuntimeError(f"wszystkie źródła postów zawiodły: {last_err}")


def _post_age_seconds(post: dict) -> float | None:
    raw = post.get("created_at")
    if not raw:
        return None
    try:
        created = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created).total_seconds()
    except ValueError:
        return None


def fetch_new_posts(max_age_minutes: float = 10) -> list[dict]:
    """Zwraca tylko posty nowe (niewidziane) i świeże (młodsze niż max_age_minutes)."""
    new = []
    for p in _fetch_any():
        pid = p.get("id")
        if not pid or pid in _seen_ids:
            continue
        _seen_ids.add(pid)

        age = _post_age_seconds(p)
        if age is not None and age > max_age_minutes * 60:
            log.info("Pomijam stary post (%.0f min): %.80s", age / 60, p.get("text", ""))
            continue
        p["_age_seconds"] = age
        new.append(p)

    return new


def prime():
    """Pierwsze uruchomienie: oznacz istniejące posty jako widziane (starych nie analizujemy)."""
    try:
        fetch_new_posts(max_age_minutes=0)
    except RuntimeError:
        log.warning("Nie udało się zainicjalizować listy postów — pierwsze pobranie oznaczy stare posty")
