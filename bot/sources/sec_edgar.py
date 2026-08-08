"""Źródło: SEC EDGAR — raporty 8-K (zdarzenia bieżące) i 10-Q (kwartalne).

Darmowy, oficjalny feed SEC (near-real-time, ~1 min od złożenia). Wymaga tylko
nagłówka User-Agent z kontaktem (zasady SEC) i limitu <10 req/s.

Kluczowe dla KOSZTÓW: zanim wyślemy cokolwiek do AI, odsiewamy zgłoszenia spółek,
którymi NIE handlujemy (broker ich nie ma) — to ~90% wolumenu. Do AI trafiają tylko
zgłoszenia tradowalnych spółek.
"""

import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

log = logging.getLogger("edgar")

UA = {"User-Agent": os.environ.get("SEC_USER_AGENT", "NewsTrader borygoo45@gmail.com")}
CURRENT_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
NS = {"a": "http://www.w3.org/2005/Atom"}

_seen: set[str] = set()
_cik2ticker: dict[str, str] = {}
_ticker_loaded_at = 0.0


def _load_ticker_map():
    """CIK -> ticker (odświeżane raz dziennie)."""
    global _cik2ticker, _ticker_loaded_at
    if _cik2ticker and time.time() - _ticker_loaded_at < 86400:
        return
    try:
        r = requests.get(TICKERS_URL, headers=UA, timeout=15)
        r.raise_for_status()
        _cik2ticker = {str(v["cik_str"]).zfill(10): v["ticker"].upper() for v in r.json().values()}
        _ticker_loaded_at = time.time()
        log.info("Załadowano mapowanie CIK→ticker: %d spółek", len(_cik2ticker))
    except Exception as e:
        log.warning("Nie udało się pobrać mapowania tickerów: %s", e)


def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&#160;|&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    return re.sub(r"\s+", " ", text).strip()


def _fetch_filing_text(index_url: str) -> str:
    """Z indeksu zgłoszenia wyciąga treść głównego dokumentu (body 8-K/10-Q)."""
    try:
        r = requests.get(index_url, headers=UA, timeout=12)
        r.raise_for_status()
        # w indeksie znajdź pierwszy dokument .htm, który jest właściwym raportem
        docs = re.findall(r'href="([^"]+\.htm)"', r.text, re.I)
        base = index_url.rsplit("/", 1)[0]
        for d in docs:
            name = d.lower()
            if "index" in name or name.endswith("-index.htm"):
                continue
            doc_url = d if d.startswith("http") else f"{base}/{d.lstrip('/').split('/')[-1]}"
            time.sleep(0.15)  # etykieta SEC: <10 req/s
            rd = requests.get(doc_url, headers=UA, timeout=12)
            if rd.ok and len(rd.text) > 200:
                return _strip_html(rd.text)[:6000]
    except Exception as e:
        log.warning("Nie udało się pobrać treści zgłoszenia %s: %s", index_url, e)
    return ""


def fetch_new_filings(max_age_minutes: float = 30, form: str = "8-K",
                      tradable: set | None = None) -> list[dict]:
    """Nowe zgłoszenia danego typu, tylko dla spółek, którymi handlujemy."""
    _load_ticker_map()
    try:
        r = requests.get(CURRENT_URL, headers=UA, timeout=12, params={
            "action": "getcurrent", "type": form, "company": "", "dateb": "",
            "owner": "include", "count": "100", "output": "atom"})
        r.raise_for_status()
        entries = ET.fromstring(r.content).findall("a:entry", NS)
    except Exception as e:
        log.warning("Feed EDGAR %s zawiódł: %s", form, e)
        return []

    out = []
    for e in entries:
        title = e.findtext("a:title", "", NS)
        entry_id = e.findtext("a:id", "", NS)
        if not entry_id or entry_id in _seen:
            continue

        # wiek zgłoszenia
        updated = e.findtext("a:updated", "", NS)
        age = None
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(updated)).total_seconds()
        except ValueError:
            pass
        if age is not None and age > max_age_minutes * 60:
            _seen.add(entry_id)
            continue

        # CIK -> ticker; jeśli spółki nie da się tradować, odrzuć BEZ AI (oszczędność)
        m = re.search(r"\((\d{10})\)", title)
        ticker = _cik2ticker.get(m.group(1)) if m else None
        if not ticker or (tradable and ticker not in tradable):
            _seen.add(entry_id)
            continue

        link_el = e.find("a:link", NS)
        index_url = link_el.get("href") if link_el is not None else ""
        _seen.add(entry_id)

        body = _fetch_filing_text(index_url) if index_url else ""
        text = f"[{form}] {ticker} — {title}. {body}".strip()
        out.append({
            "id": entry_id, "text": text, "ticker": ticker,
            "created_at": updated, "_age_seconds": age,
            "source": "sec_edgar", "url": index_url,
        })
        log.info("Nowe %s dla tradowalnej spółki %s (%.0f min): %.70s",
                 form, ticker, (age or 0) / 60, title)

    return out


def prime(tradable: set | None = None):
    """Oznacz istniejące zgłoszenia jako widziane — nie analizujemy starych."""
    try:
        fetch_new_filings(max_age_minutes=0, tradable=tradable)
    except Exception:
        log.warning("Prime EDGAR nieudany — pierwsze pobranie oznaczy stare zgłoszenia")
