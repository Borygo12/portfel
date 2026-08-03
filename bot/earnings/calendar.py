"""Kalendarz wyników — kto raportuje którego dnia.

Dwa źródła, bo żadne nie pokrywa obu rynków:

  * **Nasdaq** (`api.nasdaq.com/api/calendar/earnings`) — cały rynek amerykański
    i spółki zagraniczne notowane w USA. Jedno zapytanie = jeden dzień, ~350 pozycji.
  * **Yahoo** (`quoteSummary/calendarEvents`) — GPW. Nasdaq nie zna warszawskich
    spółek, więc dla blue chipów z `gpw_tickers.LIQUID_GPW` (plus tego, co owner ma
    w portfelu i obserwowanych) pytamy Yahoo o datę publikacji raportu.

Ranking „popularne" liczymy sami — patrz `score()`. Nasdaq nie daje żadnej miary
zainteresowania, ale kapitalizacja razem z liczbą prognoz analityków jest dobrym
przybliżeniem: mała spółka, którą śledzi 20 analityków, jest ciekawsza od dużej,
której nie śledzi nikt.
"""

import concurrent.futures as futures
import datetime as dt
import logging
import math
import re
import time

import requests

from . import cache

log = logging.getLogger("earnings.calendar")

NASDAQ_URL = "https://api.nasdaq.com/api/calendar/earnings"
YAHOO_SUMMARY = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/"

# przeszłość już się nie zmieni, przyszłość owszem — stąd dwa czasy życia
TTL_PAST = 14 * 24 * 3600
TTL_FUTURE = 3 * 3600
TTL_TODAY = 900
TTL_GPW = 12 * 3600

_session = requests.Session()
_session.headers.update(cache.UA)

# Nasdaq nazywa pory dnia po swojemu; my mówimy „przed otwarciem / po zamknięciu"
_TIME_MAP = {
    "time-pre-market": "bmo",
    "time-after-hours": "amc",
    "time-not-supplied": "tbd",
}

FILTERS = {
    # klucz -> (etykieta, minimalna kapitalizacja, czy tylko „popularne")
    "all": ("Wszystkie", 0, False),
    "popular": ("Popularne", 0, True),
    "cap100b": ("Kapitalizacja 100 mld+", 100e9, False),
    "cap10b": ("Kapitalizacja 10 mld+", 10e9, False),
    "cap1b": ("Kapitalizacja 1 mld+", 1e9, False),
}

SORTS = {
    "popular": "Popularność",
    "time": "Godzina publikacji",
    "cap": "Kapitalizacja",
    "estimates": "Liczba prognoz",
    "alpha": "Alfabetycznie",
}


# ---------------- parsowanie odpowiedzi Nasdaqa ----------------

def _money(text) -> float | None:
    """„$1,468,793,814,873" → 1468793814873.0, „N/A" → None."""
    if not isinstance(text, str):
        return float(text) if isinstance(text, (int, float)) else None
    t = text.strip()
    if not t or t.upper() in ("N/A", "NA", "--"):
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = re.sub(r"[^0-9.\-]", "", t)
    if not t or t in (".", "-"):
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _int(text) -> int | None:
    v = _money(text)
    return int(v) if v is not None else None


def _row(raw: dict) -> dict | None:
    sym = (raw.get("symbol") or "").strip().upper()
    if not sym:
        return None
    return {
        "symbol": sym,
        "name": (raw.get("name") or sym).strip(),
        "time": _TIME_MAP.get(raw.get("time") or "", "tbd"),
        "market_cap": _money(raw.get("marketCap")),
        "eps_forecast": _money(raw.get("epsForecast")),
        "estimates": _int(raw.get("noOfEsts")) or 0,
        "last_year_eps": _money(raw.get("lastYearEPS")),
        "last_year_date": (raw.get("lastYearRptDt") or "").replace("N/A", ""),
        "fiscal_quarter": (raw.get("fiscalQuarterEnding") or "").replace("N/A", ""),
        "market": "US",
        "currency": "USD",
    }


def _ttl_for(date: str) -> int:
    today = dt.date.today().isoformat()
    if date < today:
        return TTL_PAST
    return TTL_TODAY if date == today else TTL_FUTURE


def _day_key(date: str) -> str:
    return f"nasdaq-earnings-{date}"


def fetch_day(date: str) -> list:
    """Surowa lista spółek raportujących danego dnia (Nasdaq), z cache."""
    def build():
        r = _session.get(NASDAQ_URL, params={"date": date}, timeout=25)
        r.raise_for_status()
        data = (r.json() or {}).get("data") or {}
        rows = data.get("rows") or []
        out = [x for x in (_row(it) for it in rows) if x]
        # Nasdaq zwraca `rows: null` dla weekendów, świąt i dat dalszych niż ~6 tygodni
        # (terminy nie są jeszcze ogłoszone). Pusta lista jest wtedy poprawną
        # odpowiedzią, nie błędem, więc zapisujemy ją do cache.
        return out

    return cache.cached(_day_key(date), _ttl_for(date), build) or []


def cached_day(date: str):
    """Dane z cache albo None, gdy trzeba by je dopiero pobrać. Nigdy nie sieciuje."""
    return cache.get(_day_key(date), _ttl_for(date))


# ---------------- GPW przez Yahoo ----------------

def _yahoo_earnings_date(symbol: str) -> dict | None:
    """Data publikacji raportu i konsensus dla jednej spółki (Yahoo)."""
    from portfolio import market as pf_market   # import tu, żeby nie robić cyklu

    def build():
        crumb = pf_market._get_crumb()
        if not crumb:
            return None
        r = pf_market._session.get(
            f"{YAHOO_SUMMARY}{requests.utils.quote(symbol)}"
            f"?modules=calendarEvents,price&crumb={requests.utils.quote(crumb)}",
            timeout=20)
        if r.status_code == 401:
            crumb = pf_market._get_crumb(force=True)
            r = pf_market._session.get(
                f"{YAHOO_SUMMARY}{requests.utils.quote(symbol)}"
                f"?modules=calendarEvents,price&crumb={requests.utils.quote(crumb)}",
                timeout=20)
        r.raise_for_status()
        res = (r.json().get("quoteSummary") or {}).get("result") or []
        if not res:
            return None
        node = res[0]
        ev = ((node.get("calendarEvents") or {}).get("earnings") or {})
        dates = [d.get("fmt") for d in (ev.get("earningsDate") or []) if d.get("fmt")]
        if not dates:
            return None
        pr = node.get("price") or {}
        return {
            "symbol": symbol,
            "name": pr.get("longName") or pr.get("shortName") or symbol,
            "date": dates[0],
            "estimate_date": bool(ev.get("isEarningsDateEstimate")),
            "market_cap": pf_market._raw(pr, "marketCap"),
            "eps_forecast": pf_market._raw(ev, "earningsAverage"),
            "currency": pr.get("currency") or "",
        }

    return cache.cached(f"yahoo-earn-date-{symbol}", TTL_GPW, build)


def gpw_days(symbols: list) -> dict:
    """{data: [spółka, ...]} dla podanych symboli warszawskich."""
    out: dict = {}
    syms = sorted({s for s in symbols if s})
    if not syms:
        return out
    with futures.ThreadPoolExecutor(max_workers=6) as pool:
        for res in pool.map(_yahoo_earnings_date, syms):
            if not res:
                continue
            out.setdefault(res["date"], []).append({
                "symbol": res["symbol"],
                "name": res["name"],
                # Yahoo nie mówi, czy raport idzie przed sesją czy po niej —
                # GPW publikuje najczęściej rano, ale zgadywać nie będziemy
                "time": "tbd",
                "market_cap": res["market_cap"],
                "eps_forecast": res["eps_forecast"],
                "estimates": 0,
                "last_year_eps": None,
                "last_year_date": "",
                "fiscal_quarter": "",
                "market": "PL",
                "currency": res["currency"] or "PLN",
                "estimate_date": res["estimate_date"],
            })
    return out


def gpw_universe(extra: list | None = None) -> list:
    """Symbole GPW, o które pytamy Yahoo: blue chipy + to, co owner trzyma/obserwuje."""
    try:
        from gpw_tickers import LIQUID_GPW
        base = [f"{t}.WA" for t in LIQUID_GPW]
    except Exception:  # noqa: BLE001
        base = []
    for s in extra or []:
        s = (s or "").strip().upper()
        if s.endswith(".WA"):
            base.append(s)
    return sorted(set(base))


# ---------------- ranking i filtry ----------------

def score(row: dict, mine: dict) -> float:
    """Miara „jak bardzo to kogoś obchodzi". Wyżej = wcześniej na liście.

    Kolejność jest celowa: najpierw to, co owner naprawdę ma, potem to, co
    obserwuje, a dopiero na końcu ranking rynkowy. Dzięki temu własna spółka
    nigdy nie ucieknie pod fałdę „+44".
    """
    sym = row["symbol"]
    if sym in mine.get("positions", ()):
        return 1000.0
    if sym in mine.get("watchlist", ()):
        return 900.0
    cap = row.get("market_cap") or 0
    est = row.get("estimates") or 0
    # log10 kapitalizacji: 1 mld = 9, 100 mld = 11, 3 bln = 12,5 — ładnie ściśnięta skala
    s = math.log10(cap) if cap > 0 else 0.0
    # liczba prognoz to sygnał uwagi rynku; pierwiastek, żeby 40 analityków
    # nie przebiło samą liczbą wszystkiego innego
    s += math.sqrt(est) * 0.55
    if row.get("market") == "PL":
        # warszawskie blue chipy są małe w skali świata, ale dla ownera istotne
        s += 2.0
    return s


def is_popular(row: dict, mine: dict) -> bool:
    sym = row["symbol"]
    if sym in mine.get("positions", ()) or sym in mine.get("watchlist", ()):
        return True
    if row.get("market") == "PL":
        return True
    cap = row.get("market_cap") or 0
    est = row.get("estimates") or 0
    return cap >= 10e9 or (cap >= 1e9 and est >= 5) or est >= 12


_SORT_KEYS = {
    "time": lambda r: ({"bmo": 0, "amc": 1, "tbd": 2}.get(r["time"], 3), -(r.get("_score") or 0)),
    "cap": lambda r: -(r.get("market_cap") or 0),
    "estimates": lambda r: (-(r.get("estimates") or 0), -(r.get("market_cap") or 0)),
    "alpha": lambda r: r["symbol"],
    "popular": lambda r: -(r.get("_score") or 0),
}


def prepare(rows: list, mine: dict, flt: str, sort: str) -> tuple:
    """Filtruje, punktuje i sortuje listę jednego dnia. Zwraca (lista, ile było)."""
    _, min_cap, only_popular = FILTERS.get(flt, FILTERS["popular"])
    total = len(rows)
    out = []
    for r in rows:
        r = dict(r)
        sym = r["symbol"]
        r["owned"] = sym in mine.get("positions", ())
        r["watched"] = sym in mine.get("watchlist", ())
        if not (r["owned"] or r["watched"]):
            if min_cap and (r.get("market_cap") or 0) < min_cap:
                continue
            if only_popular and not is_popular(r, mine):
                continue
        r["_score"] = score(r, mine)
        out.append(r)
    out.sort(key=_SORT_KEYS.get(sort, _SORT_KEYS["popular"]))
    return out, total


# ---------------- złożenie zakresu ----------------

def _dates(start: str, end: str) -> list:
    d0 = dt.date.fromisoformat(start)
    d1 = dt.date.fromisoformat(end)
    if d1 < d0:
        d0, d1 = d1, d0
    # bezpiecznik — nikt nie potrzebuje pół roku naraz, a Nasdaq to jedno zapytanie/dzień
    d1 = min(d1, d0 + dt.timedelta(days=92))
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def range_days(start: str, end: str, skip_weekends: bool = True,
               budget_sec: float = 25.0) -> tuple:
    """({data: [spółki]}, [dni jeszcze niegotowe]) dla całego zakresu.

    Miesiąc to trzydzieści osobnych zapytań do Nasdaqa — na zimnym cache nie ma
    szans zmieścić się w czasie, w którym telefon jeszcze czeka. Dlatego zamiast
    „wszystko albo nic":

      1. bierzemy z cache to, co już jest (natychmiast),
      2. brakujące dni dociągamy równolegle, ale tylko do wyczerpania budżetu czasu,
      3. czego nie zdążyliśmy — zwracamy jako `pending`, a wątki dokończą pracę
         w tle i zapiszą wynik do cache; następne wejście dostanie komplet.

    Dzięki temu użytkownik od razu widzi to, co wiadomo, i nie ogląda pustego ekranu.
    """
    days = _dates(start, end)
    ask = [d for d in days
           if not (skip_weekends and dt.date.fromisoformat(d).weekday() >= 5)]
    result = {d: [] for d in days}

    missing = []
    for date in ask:
        hit = cached_day(date)
        if hit is None:
            missing.append(date)
        else:
            result[date] = list(hit)

    if not missing:
        return result, []

    pool = futures.ThreadPoolExecutor(max_workers=8)
    jobs = {pool.submit(fetch_day, d): d for d in missing}
    done = set()
    try:
        for fut in futures.as_completed(list(jobs), timeout=max(0.5, budget_sec)):
            date = jobs[fut]
            try:
                result[date] = list(fut.result() or [])
            except Exception as e:  # noqa: BLE001
                log.warning("Dzień %s: %s", date, e)
            done.add(date)
    except futures.TimeoutError:
        log.info("Kalendarz %s–%s: budżet %.0fs wyczerpany, zostało %d dni",
                 start, end, budget_sec, len(missing) - len(done))
    finally:
        # bez czekania — reszta wątków dogrywa w tle i wypełnia cache na później
        pool.shutdown(wait=False)

    return result, [d for d in missing if d not in done]
