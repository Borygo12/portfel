"""Dane pojedynczych spółek — wyszukiwarka, profil, wskaźniki i porównanie z branżą.

Źródło: Yahoo Finance. Moduł `quoteSummary` wymaga od 2023 r. pary ciasteczko+crumb,
więc trzymamy sesję z odnawianym crumbem (przy 401 bierzemy nowy i próbujemy raz jeszcze).
Wykresy i notowania idą tą samą drogą co reszta portfela (prices.py).

Katalog wskaźników (METRICS) jest CELOWO deklaratywny: dołożenie kolejnej pozycji to
jeden wpis — etykieta, skąd wziąć liczbę, jak ją sformatować, co znaczy i czy „więcej
znaczy lepiej". Aplikacja renderuje to generycznie, więc nie trzeba jej ruszać.
"""

import logging
import threading
import time

import requests

from . import prices, store

log = logging.getLogger("portfolio.market")

PROFILE_TTL = 6 * 3600     # fundamenty zmieniają się raz na kwartał
PEERS_TTL = 24 * 3600
_session = requests.Session()
_session.headers.update(prices.UA)
_crumb = {"value": "", "at": 0.0}
_lock = threading.Lock()
_cache: dict = {}          # klucz -> (czas, dane)

MODULES = "assetProfile,summaryDetail,financialData,defaultKeyStatistics,price"


def _cached(key: str, ttl: int, build):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    data = build()
    if data is not None:
        _cache[key] = (now, data)
    return data


def _get_crumb(force: bool = False) -> str:
    with _lock:
        if not force and _crumb["value"] and time.time() - _crumb["at"] < 3600:
            return _crumb["value"]
        try:
            _session.cookies.clear()
            _session.get("https://fc.yahoo.com", timeout=10)
            r = _session.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10)
            value = (r.text or "").strip()
            if r.status_code == 200 and value and "<" not in value:
                _crumb.update(value=value, at=time.time())
                return value
        except Exception as e:  # noqa: BLE001
            log.warning("Crumb: %s", e)
        return ""


def _quote_summary(symbol: str) -> dict | None:
    """Surowy quoteSummary — przy 401 odnawia crumb i próbuje raz jeszcze."""
    for attempt in (0, 1):
        crumb = _get_crumb(force=bool(attempt))
        if not crumb:
            return None
        try:
            r = _session.get(
                f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/"
                f"{requests.utils.quote(symbol)}?modules={MODULES}"
                f"&crumb={requests.utils.quote(crumb)}", timeout=15)
            if r.status_code == 401 and attempt == 0:
                continue
            r.raise_for_status()
            result = (r.json().get("quoteSummary") or {}).get("result") or []
            return result[0] if result else None
        except Exception as e:  # noqa: BLE001
            log.warning("quoteSummary %s: %s", symbol, e)
            if attempt:
                return None
    return None


def _raw(node, key):
    """Yahoo pakuje liczby w {"raw": x, "fmt": "..."} — wyciągamy samą liczbę."""
    v = (node or {}).get(key)
    if isinstance(v, dict):
        v = v.get("raw")
    return v if isinstance(v, (int, float)) else None


# ---------------- katalog wskaźników ----------------
#
# fmt: money = kwota w walucie spółki, ratio = krotność (x), pct = procent,
#      num = zwykła liczba. better: low/high/none — czy niższa wartość jest lepsza.

METRICS = [
    {"key": "marketCap", "label": "Kapitalizacja", "fmt": "money", "better": "none",
     "group": "skala", "src": ("price", "marketCap"),
     "desc": "Ile kosztuje dziś cała spółka na giełdzie — cena akcji razy liczba akcji."},
    {"key": "revenue", "label": "Przychody (sales)", "fmt": "money", "better": "none",
     "group": "skala", "src": ("financialData", "totalRevenue"),
     "desc": "Suma sprzedaży z ostatnich 12 miesięcy. To wpływy, jeszcze przed kosztami."},
    {"key": "ebitda", "label": "EBITDA", "fmt": "money", "better": "none",
     "group": "skala", "src": ("financialData", "ebitda"),
     "desc": "Zysk z podstawowej działalności, zanim odejmiemy amortyzację, odsetki "
             "i podatek. Pokazuje, ile firma zarabia na tym, co robi."},
    {"key": "fcf", "label": "Wolne przepływy (FCF)", "fmt": "money", "better": "none",
     "group": "skala", "src": ("financialData", "freeCashflow"),
     "desc": "Gotówka, która zostaje po opłaceniu działalności i inwestycji. "
             "Z tego biorą się dywidendy i skup akcji."},

    {"key": "pe", "label": "C/Z (P/E)", "fmt": "ratio", "better": "low",
     "group": "wycena", "src": ("summaryDetail", "trailingPE"),
     "desc": "Ile lat obecnego zysku kosztuje akcja. Niżej zwykle znaczy taniej, "
             "ale niska wartość bywa też sygnałem, że rynek spodziewa się spadku zysków."},
    {"key": "forwardPe", "label": "C/Z prognozowane", "fmt": "ratio", "better": "low",
     "group": "wycena", "src": ("summaryDetail", "forwardPE"),
     "desc": "To samo, ale liczone z zysku prognozowanego przez analityków na przyszły rok."},
    {"key": "evEbitda", "label": "EV/EBITDA", "fmt": "ratio", "better": "low",
     "group": "wycena", "src": ("defaultKeyStatistics", "enterpriseToEbitda"),
     "desc": "Wartość firmy razem z długiem podzielona przez EBITDA. Uczciwszy od C/Z "
             "przy porównaniach, bo uwzględnia zadłużenie."},
    {"key": "evSales", "label": "EV/Przychody", "fmt": "ratio", "better": "low",
     "group": "wycena", "src": ("defaultKeyStatistics", "enterpriseToRevenue"),
     "desc": "Ile płacisz za złotówkę rocznej sprzedaży. Używane, gdy firma nie ma "
             "jeszcze zysków."},
    {"key": "pb", "label": "C/WK (P/B)", "fmt": "ratio", "better": "low",
     "group": "wycena", "src": ("defaultKeyStatistics", "priceToBook"),
     "desc": "Cena wobec wartości księgowej — majątku firmy po odjęciu długów."},

    {"key": "grossMargin", "label": "Marża brutto", "fmt": "pct", "better": "high",
     "group": "rentowność", "src": ("financialData", "grossMargins"),
     "desc": "Ile zostaje ze sprzedaży po kosztach wytworzenia. Wysoka marża to zwykle "
             "silna pozycja wobec konkurencji."},
    {"key": "operatingMargin", "label": "Marża operacyjna", "fmt": "pct", "better": "high",
     "group": "rentowność", "src": ("financialData", "operatingMargins"),
     "desc": "Ile zostaje po wszystkich kosztach prowadzenia biznesu."},
    {"key": "profitMargin", "label": "Marża netto", "fmt": "pct", "better": "high",
     "group": "rentowność", "src": ("financialData", "profitMargins"),
     "desc": "Ile z każdej złotówki sprzedaży zostaje jako czysty zysk."},
    {"key": "roe", "label": "ROE", "fmt": "pct", "better": "high",
     "group": "rentowność", "src": ("financialData", "returnOnEquity"),
     "desc": "Ile zysku firma wyciska z kapitału właścicieli. Powyżej ~15% uchodzi za dobre."},

    {"signed": True, "key": "revenueGrowth", "label": "Wzrost przychodów", "fmt": "pct", "better": "high",
     "group": "wzrost", "src": ("financialData", "revenueGrowth"),
     "desc": "Zmiana sprzedaży rok do roku."},
    {"signed": True, "key": "earningsGrowth", "label": "Wzrost zysku", "fmt": "pct", "better": "high",
     "group": "wzrost", "src": ("financialData", "earningsGrowth"),
     "desc": "Zmiana zysku rok do roku."},

    {"key": "debt", "label": "Zadłużenie", "fmt": "money", "better": "low",
     "group": "bilans", "src": ("financialData", "totalDebt"),
     "desc": "Całkowity dług firmy."},
    {"key": "cash", "label": "Gotówka", "fmt": "money", "better": "high",
     "group": "bilans", "src": ("financialData", "totalCash"),
     "desc": "Środki na kontach i krótkie inwestycje — poduszka na gorsze czasy."},
    {"key": "debtToEquity", "label": "Dług / kapitał", "fmt": "num", "better": "low",
     "group": "bilans", "src": ("financialData", "debtToEquity"),
     "desc": "Ile długu przypada na 100 jednostek kapitału własnego. Powyżej 100 "
             "oznacza, że firma jest finansowana głównie długiem."},

    {"key": "dividendYield", "label": "Dywidenda", "fmt": "pct", "better": "high",
     "group": "dla akcjonariusza", "src": ("summaryDetail", "dividendYield"),
     "desc": "Roczna dywidenda w stosunku do ceny akcji."},
    {"key": "beta", "label": "Beta", "fmt": "num", "better": "none",
     "group": "dla akcjonariusza", "src": ("summaryDetail", "beta"),
     "desc": "Jak mocno kurs rusza się względem rynku. 1,0 = jak rynek, powyżej = mocniej."},
]

# wskaźniki, które da się uczciwie porównać między spółkami (krotności i marże)
COMPARABLE = {m["key"] for m in METRICS if m["fmt"] in ("ratio", "pct")}


def _extract(data: dict) -> dict:
    """{klucz wskaźnika: wartość} z odpowiedzi quoteSummary."""
    out = {}
    for m in METRICS:
        node, field = m["src"]
        v = _raw(data.get(node), field)
        if v is not None:
            out[m["key"]] = v
    return out


# ---------------- wyszukiwarka ----------------

def search(query: str, limit: int = 15) -> list:
    """Spółki, ETF-y i krypto pasujące do zapytania — z całego świata."""
    q = (query or "").strip()
    if len(q) < 1:
        return []

    def build():
        try:
            r = _session.get(
                "https://query1.finance.yahoo.com/v1/finance/search"
                f"?q={requests.utils.quote(q)}&quotesCount=25&newsCount=0"
                "&enableFuzzyQuery=true", timeout=12)
            r.raise_for_status()
            out = []
            for it in r.json().get("quotes", []):
                sym = it.get("symbol")
                typ = (it.get("quoteType") or "").upper()
                if not sym or typ not in ("EQUITY", "ETF", "CRYPTOCURRENCY", "INDEX", "MUTUALFUND"):
                    continue
                out.append({
                    "symbol": sym,
                    "name": it.get("longname") or it.get("shortname") or sym,
                    "type": typ,
                    "exchange": it.get("exchDisp") or it.get("exchange") or "",
                    "sector": it.get("sector") or "",
                    "industry": it.get("industry") or "",
                })
            return out
        except Exception as e:  # noqa: BLE001
            log.warning("Search %s: %s", q, e)
            return []

    return _cached(f"search:{q.lower()}", 600, build)[:limit]


# ---------------- profil spółki ----------------

def _peers(symbol: str) -> list:
    def build():
        try:
            r = _session.get(
                "https://query1.finance.yahoo.com/v6/finance/recommendationsbysymbol/"
                f"{requests.utils.quote(symbol)}", timeout=12)
            r.raise_for_status()
            res = (r.json().get("finance") or {}).get("result") or []
            return [x.get("symbol") for x in (res[0].get("recommendedSymbols") or [])
                    if x.get("symbol")][:6] if res else []
        except Exception as e:  # noqa: BLE001
            log.warning("Peers %s: %s", symbol, e)
            return []
    return _cached(f"peers:{symbol}", PEERS_TTL, build) or []


def _median(values: list):
    vals = sorted(v for v in values if isinstance(v, (int, float)))
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def resolve(symbol: str) -> str:
    """Symbol Yahoo dla dowolnego zapisu — także tickera XTB („NVDA.US" → „NVDA")."""
    return prices.resolved_symbol(symbol) or (symbol or "").strip().upper()


def company(symbol: str, with_peers: bool = True) -> dict:
    """Pełny profil: notowanie, opis, wskaźniki i mediana podobnych spółek."""
    sym = resolve(symbol)
    if not sym:
        return {"error": "Brak symbolu"}

    def build():
        data = _quote_summary(sym)
        if not data:
            return None
        ap = data.get("assetProfile") or {}
        pr = data.get("price") or {}
        sd = data.get("summaryDetail") or {}
        fd = data.get("financialData") or {}
        return {
            "symbol": sym,
            "name": pr.get("longName") or pr.get("shortName") or sym,
            "currency": pr.get("currency") or "",
            "exchange": pr.get("exchangeName") or "",
            "type": pr.get("quoteType") or "",
            "sector": ap.get("sector") or "",
            "industry": ap.get("industry") or "",
            "country": ap.get("country") or "",
            "employees": ap.get("fullTimeEmployees"),
            "website": ap.get("website") or "",
            "summary": ap.get("longBusinessSummary") or "",
            "price": _raw(pr, "regularMarketPrice"),
            # Yahoo podaje zmianę jako ułamek (0,0134), reszta aplikacji liczy w procentach
            "change_pct": (lambda v: round(v * 100, 2) if v is not None else None)(
                _raw(pr, "regularMarketChangePercent")),
            "prev_close": _raw(pr, "regularMarketPreviousClose"),
            "day_low": _raw(pr, "regularMarketDayLow"),
            "day_high": _raw(pr, "regularMarketDayHigh"),
            "week52_low": _raw(sd, "fiftyTwoWeekLow"),
            "week52_high": _raw(sd, "fiftyTwoWeekHigh"),
            "target_price": _raw(fd, "targetMeanPrice"),
            "recommendation": fd.get("recommendationKey") or "",
            "analysts": _raw(fd, "numberOfAnalystOpinions"),
            "values": _extract(data),
        }

    base = _cached(f"company:{sym}", PROFILE_TTL, build)
    if not base:
        return {"error": "Nie udało się pobrać danych spółki", "symbol": sym}

    out = dict(base)
    out["metrics"] = [
        {**{k: m[k] for k in ("key", "label", "fmt", "better", "group", "desc")},
         # znak ma sens tylko przy zmianach — „marża +18%" czytałoby się jak wzrost
         "signed": bool(m.get("signed")),
         "value": base["values"].get(m["key"])}
        for m in METRICS
    ]

    if with_peers:
        peers = _peers(sym)
        rows, medians = [], {}
        for p in peers:
            pdata = _cached(f"company:{p}", PROFILE_TTL,
                            lambda p=p: (lambda d: {"symbol": p, "values": _extract(d),
                                                    "name": ((d.get("price") or {}).get("shortName") or p)}
                                         if d else None)(_quote_summary(p)))
            if pdata:
                rows.append(pdata)
        for key in COMPARABLE:
            med = _median([r["values"].get(key) for r in rows])
            if med is not None:
                medians[key] = med
        out["peers"] = [{"symbol": r["symbol"], "name": r["name"]} for r in rows]
        for m in out["metrics"]:
            m["peer"] = medians.get(m["key"])
    return out


# ---------------- wykres instrumentu ----------------

RANGES = {
    "1d": ("1d", "5m"), "5d": ("5d", "15m"), "1m": ("1mo", "1d"), "3m": ("3mo", "1d"),
    "6m": ("6mo", "1d"), "ytd": ("ytd", "1d"), "1y": ("1y", "1d"),
    "5y": ("5y", "1wk"), "max": ("max", "1mo"),
}


def chart(symbol: str, rng: str = "1y") -> dict:
    """Notowania instrumentu w podanym zakresie — znaczniki czasu i ceny zamknięcia."""
    sym = resolve(symbol)
    yrange, interval = RANGES.get(rng, RANGES["1y"])

    def build():
        try:
            r = _session.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(sym)}"
                f"?range={yrange}&interval={interval}", timeout=15)
            r.raise_for_status()
            res = (r.json().get("chart") or {}).get("result") or []
            if not res:
                return None
            node = res[0]
            meta = node.get("meta") or {}
            currency, divisor = prices._norm(meta)
            stamps = node.get("timestamp") or []
            closes = ((node.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
            ts, cl, last = [], [], None
            for t, c in zip(stamps, closes):
                if c is None:
                    c = last
                if c is None:
                    continue
                last = c
                ts.append(int(t))
                cl.append(round(float(c) / divisor, 6))
            if not ts:
                return None
            prev = meta.get("chartPreviousClose")
            return {
                "symbol": sym, "range": rng, "currency": currency,
                "ts": ts, "values": cl,
                "prev_close": round(float(prev) / divisor, 6) if prev else cl[0],
                "intraday": interval.endswith("m"),
            }
        except Exception as e:  # noqa: BLE001
            log.warning("Chart %s %s: %s", sym, rng, e)
            return None

    ttl = 60 if interval.endswith("m") else 900
    return _cached(f"chart:{sym}:{rng}", ttl, build) or {"error": "Brak notowań", "symbol": sym}


# ---------------- obserwowane ----------------

def watchlist() -> list:
    rows = store.query("SELECT * FROM watchlist ORDER BY added_at DESC")
    if not rows:
        return []
    quotes = prices._quotes_for([r["symbol"] for r in rows])
    prev = _prev_closes([r["symbol"] for r in rows])
    out = []
    for r in rows:
        q = quotes.get(r["symbol"])
        base = prev.get(r["symbol"])
        price = q["price"] if q else None
        change = ((price / base - 1) * 100) if price and base else None
        out.append({
            **r,
            "price": price,
            "currency": (q or {}).get("currency") or r.get("currency") or "",
            "quote_ts": (q or {}).get("ts"),
            "prev_close": base,
            "change_pct": round(change, 2) if change is not None else None,
            "change_abs": round(price - base, 4) if price and base else None,
        })
    return out


def _prev_closes(symbols: list) -> dict:
    """Zamknięcie poprzedniej sesji — do dziennej zmiany na liście obserwowanych."""
    out = {}
    for sym, entry in prices._spark(symbols, "5d", "1d").items():
        _, closes, _ = prices._clean_bars(entry)
        meta = entry.get("meta") or {}
        _, divisor = prices._norm(meta)
        if len(closes) >= 2:
            out[sym] = closes[-2]
        elif meta.get("chartPreviousClose"):
            out[sym] = float(meta["chartPreviousClose"]) / divisor
    return out


def watch_add(symbol: str, name: str = "", extra: dict | None = None) -> dict:
    sym = (symbol or "").strip().upper()
    if not sym:
        return {"ok": False, "error": "Brak symbolu"}
    e = extra or {}
    store.watch_add(sym, name or sym, e.get("type", ""), e.get("exchange", ""),
                    e.get("currency", ""))
    return {"ok": True, "symbol": sym}


def watch_remove(symbol: str) -> dict:
    store.watch_remove((symbol or "").strip().upper())
    return {"ok": True}
