"""Klasyfikacja instrumentów — klasa aktywów, rynek, sektor.

Dane z wyszukiwarki Yahoo (quoteType + sector/industry dla akcji), cache w SQLite.
ETF-y nie mają sektora u Yahoo, więc rozpoznajemy je z nazwy (złoto, biotech, indeks…).
Wszystkie etykiety po polsku — trafiają wprost do UI.
"""

import datetime
import logging
import re

import requests

from . import store
from .prices import UA, yahoo_symbol

log = logging.getLogger("portfolio.classify")

_session = requests.Session()
_session.headers.update(UA)

# sufiks XTB -> (kod rynku, etykieta)
MARKETS = {
    "US": "Akcje USA", "PL": "GPW", "DE": "Niemcy", "UK": "Wielka Brytania",
    "FR": "Francja", "ES": "Hiszpania", "IT": "Włochy", "NL": "Holandia",
    "CH": "Szwajcaria", "SE": "Szwecja", "DK": "Dania", "NO": "Norwegia",
    "FI": "Finlandia", "AT": "Austria", "CZ": "Czechy", "HU": "Węgry",
    "BE": "Belgia", "PT": "Portugalia",
}

# sektory Yahoo -> polskie etykiety
SECTORS = {
    "Technology": "Technologia",
    "Communication Services": "Media i komunikacja",
    "Healthcare": "Ochrona zdrowia",
    "Financial Services": "Finanse",
    "Consumer Cyclical": "Dobra konsumpcyjne",
    "Consumer Defensive": "Dobra podstawowe",
    "Industrials": "Przemysł",
    "Energy": "Energia",
    "Basic Materials": "Surowce",
    "Utilities": "Usługi komunalne",
    "Real Estate": "Nieruchomości",
}

# rozpoznawanie tematyki ETF-ów po nazwie (kolejność ma znaczenie)
ETF_THEMES = [
    (r"gold|złot|miners", "ETF — złoto i kopalnie"),
    (r"biotech|healthcare|health", "ETF — ochrona zdrowia"),
    (r"nasdaq|technolog|semiconduct|innovat", "ETF — technologia"),
    (r"s&p|sp500|msci|acwi|world|emerging|em imi", "ETF — szeroki rynek"),
    (r"wig|swig|mwig|poland|polsk", "ETF — polski rynek"),
    (r"bond|oblig|treasury|govie", "ETF — obligacje"),
    (r"silver|srebr|oil|gas|commodit|surow", "ETF — surowce"),
]

SCHEMA_EXTRA = """
CREATE TABLE IF NOT EXISTS instrument_meta (
    ticker     TEXT PRIMARY KEY,
    quote_type TEXT DEFAULT '',
    sector     TEXT DEFAULT '',
    industry   TEXT DEFAULT '',
    long_name  TEXT DEFAULT '',
    fetched_at TEXT DEFAULT ''
);
"""


def init() -> None:
    store.init()
    store.execute_script(SCHEMA_EXTRA)


def _fetch_meta(ticker: str) -> dict:
    """Pobiera quoteType/sector z wyszukiwarki Yahoo dla jednego tickera."""
    ysym = yahoo_symbol(ticker)
    res = store.get_price_meta(f"res:{ticker.upper()}")
    if res and res.get("status"):
        ysym = res["status"]
    base = ysym.split(".")[0]
    try:
        r = _session.get(
            f"https://query1.finance.yahoo.com/v1/finance/search?q={requests.utils.quote(ysym)}"
            "&quotesCount=6&newsCount=0", timeout=12)
        r.raise_for_status()
        quotes = r.json().get("quotes", [])
    except Exception as e:  # noqa: BLE001
        log.warning("Yahoo search %s: %s", ysym, e)
        return {}
    exact = [q for q in quotes if (q.get("symbol") or "").upper() == ysym.upper()]
    same_base = [q for q in quotes if (q.get("symbol") or "").split(".")[0].upper() == base.upper()]
    q = (exact or same_base or quotes or [{}])[0]
    return {
        "quote_type": q.get("quoteType") or "",
        "sector": q.get("sector") or "",
        "industry": q.get("industry") or "",
        "long_name": q.get("longname") or q.get("shortname") or "",
    }


def meta(ticker: str, refresh_days: int = 30) -> dict:
    """Metadane instrumentu z cache (dociąga z Yahoo, gdy brak lub stare)."""
    init()
    rows = store.query("SELECT * FROM instrument_meta WHERE ticker=?", (ticker,))
    if rows:
        row = rows[0]
        try:
            age = (datetime.datetime.utcnow()
                   - datetime.datetime.strptime(row["fetched_at"], "%Y-%m-%dT%H:%M:%S")).days
        except (ValueError, TypeError):
            age = 9999
        if age < refresh_days:
            return row
    got = _fetch_meta(ticker)
    row = {"ticker": ticker, "fetched_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
           "quote_type": got.get("quote_type", ""), "sector": got.get("sector", ""),
           "industry": got.get("industry", ""), "long_name": got.get("long_name", "")}
    store.execute(
        """INSERT INTO instrument_meta(ticker, quote_type, sector, industry, long_name, fetched_at)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(ticker) DO UPDATE SET quote_type=excluded.quote_type, sector=excluded.sector,
             industry=excluded.industry, long_name=excluded.long_name, fetched_at=excluded.fetched_at""",
        (row["ticker"], row["quote_type"], row["sector"], row["industry"],
         row["long_name"], row["fetched_at"]))
    return row


def asset_class(ticker: str, m: dict, name: str = "") -> str:
    """AKCJE / ETF / KRYPTO / SUROWCE — po polsku, gotowe do wyświetlenia."""
    t = (ticker or "").upper()
    qt = (m.get("quote_type") or "").upper()
    if qt == "CRYPTOCURRENCY" or t in ("BITCOIN", "ETHEREUM", "SOLANA", "RIPPLE"):
        return "Kryptowaluty"
    if t in ("GOLD", "SILVER", "OIL.WTI", "NATGAS") or qt == "FUTURE":
        return "Surowce"
    if qt == "ETF" or "ETF" in t or "ETF" in (name or "").upper():
        return "ETF"
    if qt == "INDEX":
        return "Indeksy"
    return "Akcje"


def market(ticker: str) -> str:
    """Rynek notowań — z sufiksu tickera XTB."""
    m = re.match(r"^.+\.([A-Z]{2})$", (ticker or "").upper())
    if m and m.group(1) in MARKETS:
        return MARKETS[m.group(1)]
    return "Inne"


def sector(ticker: str, m: dict, name: str = "") -> str:
    """Sektor: dla akcji z Yahoo, dla ETF-ów rozpoznany z nazwy."""
    cls = asset_class(ticker, m, name)
    if cls == "Akcje":
        return SECTORS.get(m.get("sector") or "", (m.get("sector") or "").strip() or "Pozostałe")
    if cls == "ETF":
        hay = f"{name} {m.get('long_name', '')} {ticker}".lower()
        for rx, label in ETF_THEMES:
            if re.search(rx, hay):
                return label
        return "ETF — inne"
    return cls


def describe(ticker: str, name: str = "") -> dict:
    """Komplet etykiet dla jednego instrumentu."""
    m = meta(ticker)
    return {
        "asset_class": asset_class(ticker, m, name),
        "market": market(ticker),
        "sector": sector(ticker, m, name),
        "industry": m.get("industry") or "",
        "quote_type": m.get("quote_type") or "",
    }
