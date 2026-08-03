"""Raport przed publikacją wyników — wszystko o jednej spółce w jednym miejscu.

Składamy z trzech źródeł, bo każde wnosi co innego:

  * **Yahoo quoteSummary** — konsensus na najbliższy kwartał (EPS i przychody wraz
    z widełkami), historia zaskoczeń, prognozy na kolejne okresy i rachunek wyników
    kwartał po kwartale (z tego liczymy marże).
  * **Nasdaq** — realne DATY publikacji poprzednich raportów oraz rewizje prognoz
    z ostatnich tygodni. Yahoo dat publikacji wstecz nie podaje, a bez nich nie da
    się policzyć, jak kurs reagował na poprzednie wyniki.
  * **Yahoo chart** — notowania dzienne, z których liczymy reakcję kursu na sesji
    po każdym raporcie. To odpowiedź na pytanie „ile ta spółka zwykle skacze".

Wszystko jest opcjonalne: gdy któreś źródło padnie, raport po prostu ma mniej sekcji.
"""

import datetime as dt
import logging
import re

import requests

from . import cache

log = logging.getLogger("earnings.report")

TTL = 3 * 3600
NASDAQ = "https://api.nasdaq.com/api"
LOGO = "https://financialmodelingprep.com/image-stock/{}.png"

MODULES = ("calendarEvents,earnings,earningsHistory,earningsTrend,"
           "incomeStatementHistoryQuarterly,price,financialData,"
           "defaultKeyStatistics,summaryDetail")

_session = requests.Session()
_session.headers.update(cache.UA)


def logo_url(symbol: str) -> str:
    """Adres logotypu. Front sam podmienia go na monogram, gdy obrazka nie ma."""
    base = (symbol or "").upper().split(".")[0]
    return LOGO.format(base) if base else ""


# ---------------- Yahoo ----------------

def _quote_summary(symbol: str) -> dict | None:
    from portfolio import market as pf_market

    for attempt in (0, 1):
        crumb = pf_market._get_crumb(force=bool(attempt))
        if not crumb:
            return None
        try:
            r = pf_market._session.get(
                "https://query2.finance.yahoo.com/v10/finance/quoteSummary/"
                f"{requests.utils.quote(symbol)}?modules={MODULES}"
                f"&crumb={requests.utils.quote(crumb)}", timeout=25)
            if r.status_code == 401 and attempt == 0:
                continue
            r.raise_for_status()
            res = (r.json().get("quoteSummary") or {}).get("result") or []
            return res[0] if res else None
        except Exception as e:  # noqa: BLE001
            log.warning("quoteSummary %s: %s", symbol, e)
            if attempt:
                return None
    return None


def _raw(node, key):
    v = (node or {}).get(key)
    if isinstance(v, dict):
        v = v.get("raw")
    return v if isinstance(v, (int, float)) else None


def _fmt_date(node) -> str:
    v = (node or {}).get("fmt")
    return v if isinstance(v, str) else ""


# ---------------- Nasdaq ----------------

def _nasdaq(path: str) -> dict | None:
    try:
        r = _session.get(f"{NASDAQ}/{path}", timeout=25)
        if r.status_code != 200:
            return None
        return (r.json() or {}).get("data")
    except Exception as e:  # noqa: BLE001
        log.debug("Nasdaq %s: %s", path, e)
        return None


def _us_date(text: str) -> str:
    """„5/5/2026" → „2026-05-05"."""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", text or "")
    if not m:
        return ""
    mth, day, year = (int(x) for x in m.groups())
    try:
        return dt.date(year, mth, day).isoformat()
    except ValueError:
        return ""


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    t = v.strip()
    if not t or t.upper() in ("N/A", "NA", "--"):
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = re.sub(r"[^0-9.\-]", "", t)
    try:
        val = float(t)
    except ValueError:
        return None
    return -val if neg else val


def _surprise_rows(symbol: str) -> list:
    data = _nasdaq(f"company/{symbol}/earnings-surprise")
    rows = ((data or {}).get("earningsSurpriseTable") or {}).get("rows") or []
    out = []
    for r in rows:
        out.append({
            "quarter": r.get("fiscalQtrEnd") or "",
            "date": _us_date(r.get("dateReported") or ""),
            "eps": _num(r.get("eps")),
            "estimate": _num(r.get("consensusForecast")),
            "surprise_pct": _num(r.get("percentageSurprise")),
        })
    return [r for r in out if r["eps"] is not None]


def _forecast_rows(symbol: str) -> dict:
    data = _nasdaq(f"analyst/{symbol}/earnings-forecast") or {}

    def take(block):
        rows = ((data.get(block) or {}).get("rows") or [])
        return [{
            "period": r.get("fiscalEnd") or r.get("fiscalYear") or "",
            "consensus": _num(r.get("consensusEPSForecast")),
            "high": _num(r.get("highEPSForecast")),
            "low": _num(r.get("lowEPSForecast")),
            "estimates": int(_num(r.get("noOfEstimates")) or 0),
            "up": int(_num(r.get("up")) or 0),
            "down": int(_num(r.get("down")) or 0),
        } for r in rows]

    return {"quarterly": take("quarterlyForecast"), "yearly": take("yearlyForecast")}


# ---------------- reakcja kursu ----------------

def _daily_closes(symbol: str) -> dict:
    """{data: zamknięcie} z ostatnich trzech lat — do liczenia reakcji na wyniki."""
    def build():
        r = _session.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(symbol)}"
            "?range=3y&interval=1d", timeout=25)
        r.raise_for_status()
        res = (r.json().get("chart") or {}).get("result") or []
        if not res:
            return None
        node = res[0]
        stamps = node.get("timestamp") or []
        closes = ((node.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        out = {}
        for t, c in zip(stamps, closes):
            if c is None:
                continue
            out[dt.datetime.utcfromtimestamp(int(t)).date().isoformat()] = float(c)
        return out

    return cache.cached(f"daily-{symbol}", 6 * 3600, build) or {}


def _reaction(closes: dict, report_date: str) -> float | None:
    """Zmiana kursu na pierwszej sesji PO raporcie, w procentach.

    Nie wiemy, czy raport wyszedł przed sesją, czy po niej, więc bierzemy ostatnie
    zamknięcie przed dniem raportu i pierwsze zamknięcie po nim — ten przedział
    obejmuje reakcję w obu wariantach.
    """
    if not closes or not report_date:
        return None
    days = sorted(closes)
    before = [d for d in days if d < report_date]
    after = [d for d in days if d > report_date]
    if not before or not after:
        return None
    a, b = closes[before[-1]], closes[after[0]]
    if not a:
        return None
    return round((b / a - 1) * 100, 2)


# ---------------- marże ----------------

_TS_FIELDS = ("TotalRevenue", "GrossProfit", "OperatingIncome", "NetIncome", "DilutedEPS")


def _timeseries(symbol: str, freq: str) -> list:
    """Rachunek wyników z `fundamentals-timeseries` — przychód, marże, EPS.

    Stary moduł `incomeStatementHistoryQuarterly` Yahoo od jakiegoś czasu oddaje
    `grossProfit: 0` i puste `operatingIncome`, więc marż z niego nie policzysz.
    Nowa końcówka timeseries ma komplet, ale trzyma tylko ~5 kwartałów wstecz —
    dlatego pytamy też o dane roczne i front pozwala przełączyć rozdzielczość.
    """
    from portfolio import market as pf_market

    types = ",".join(freq + f for f in _TS_FIELDS)

    def build():
        crumb = pf_market._get_crumb()
        if not crumb:
            return None
        now = int(dt.datetime.now().timestamp())
        r = pf_market._session.get(
            "https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/"
            f"timeseries/{requests.utils.quote(symbol)}"
            f"?symbol={requests.utils.quote(symbol)}&type={types}"
            f"&period1=1262304000&period2={now}"
            f"&crumb={requests.utils.quote(crumb)}", timeout=25)
        r.raise_for_status()
        res = (r.json().get("timeseries") or {}).get("result") or []

        by_date: dict = {}
        for block in res:
            key = next((k for k in block if k not in ("meta", "timestamp")), None)
            if not key:
                continue
            field = key[len(freq):]
            for item in block.get(key) or []:
                if not isinstance(item, dict):
                    continue
                day = item.get("asOfDate")
                val = (item.get("reportedValue") or {}).get("raw")
                if day and isinstance(val, (int, float)):
                    by_date.setdefault(day, {})[field] = float(val)

        out = []
        for day in sorted(by_date):
            v = by_date[day]
            rev = v.get("TotalRevenue")
            if not rev:
                continue
            def pct(x):
                return round(x / rev * 100, 2) if isinstance(x, (int, float)) else None
            out.append({
                "date": day,
                "revenue": rev,
                "gross_margin": pct(v.get("GrossProfit")),
                "operating_margin": pct(v.get("OperatingIncome")),
                "net_margin": pct(v.get("NetIncome")),
                "net_income": v.get("NetIncome"),
                "eps": v.get("DilutedEPS"),
            })
        return out

    return cache.cached(f"ts-{freq}-{symbol}", 24 * 3600, build) or []


def _quarterly_revenue(node: dict) -> list:
    """Moduł `earnings` Yahoo — przychód i zysk kwartalny, z etykietą „2Q2026"."""
    chart = ((node or {}).get("financialsChart") or {}).get("quarterly") or []
    out = []
    for r in chart:
        out.append({
            "label": r.get("date") or "",
            "revenue": _raw(r, "revenue"),
            "earnings": _raw(r, "earnings"),
        })
    return out


# ---------------- złożenie raportu ----------------

def report(symbol: str) -> dict:
    """Pełny raport spółki przed publikacją wyników."""
    from portfolio import market as pf_market

    sym = pf_market.resolve(symbol)
    if not sym:
        return {"error": "Brak symbolu"}

    def build():
        d = _quote_summary(sym)
        if not d:
            return None

        pr = d.get("price") or {}
        sd = d.get("summaryDetail") or {}
        fd = d.get("financialData") or {}
        ks = d.get("defaultKeyStatistics") or {}
        cal = ((d.get("calendarEvents") or {}).get("earnings") or {})

        dates = [x.get("fmt") for x in (cal.get("earningsDate") or []) if x.get("fmt")]
        eps_now = _raw(cal, "earningsAverage")
        rev_now = _raw(cal, "revenueAverage")

        # historia zaskoczeń: Yahoo daje kwartały, Nasdaq daty publikacji — łączymy
        history = []
        for h in ((d.get("earningsHistory") or {}).get("history") or []):
            history.append({
                "quarter": _fmt_date(h.get("quarter")),
                "eps": _raw(h, "epsActual"),
                "estimate": _raw(h, "epsEstimate"),
                "difference": _raw(h, "epsDifference"),
                "surprise_pct": (lambda v: round(v * 100, 2) if v is not None else None)(
                    _raw(h, "surprisePercent")),
                "period": h.get("period") or "",
                "date": "",
            })
        history.sort(key=lambda r: r["quarter"])

        nasdaq_rows = _surprise_rows(sym) if "." not in sym else []
        by_quarter = {}
        for r in nasdaq_rows:
            # „Mar 2026" → dopasowanie po roku i miesiącu do kwartału z Yahoo
            by_quarter[(r["quarter"] or "").lower()] = r
        closes = _daily_closes(sym)
        for h in history:
            key = ""
            if h["quarter"]:
                try:
                    day = dt.date.fromisoformat(h["quarter"])
                    key = day.strftime("%b %Y").lower()
                except ValueError:
                    key = ""
            match = by_quarter.get(key)
            if match:
                h["date"] = match["date"]
                if h["eps"] is None:
                    h["eps"] = match["eps"]
                if h["estimate"] is None:
                    h["estimate"] = match["estimate"]
            h["reaction_pct"] = _reaction(closes, h["date"])

        # gdy Yahoo nie oddał historii, a Nasdaq tak — bierzemy Nasdaq
        if not history and nasdaq_rows:
            for r in sorted(nasdaq_rows, key=lambda x: x["date"]):
                history.append({
                    "quarter": r["quarter"], "eps": r["eps"], "estimate": r["estimate"],
                    "difference": (r["eps"] - r["estimate"])
                    if r["eps"] is not None and r["estimate"] is not None else None,
                    "surprise_pct": r["surprise_pct"], "period": "", "date": r["date"],
                    "reaction_pct": _reaction(closes, r["date"]),
                })

        beats = [h for h in history if (h.get("surprise_pct") or 0) > 0]
        moves = [abs(h["reaction_pct"]) for h in history if h.get("reaction_pct") is not None]
        surprises = [h["surprise_pct"] for h in history if h.get("surprise_pct") is not None]

        trend = []
        for t in ((d.get("earningsTrend") or {}).get("trend") or []):
            eps = t.get("earningsEstimate") or {}
            rev = t.get("revenueEstimate") or {}
            revis = t.get("epsRevisions") or {}
            trend.append({
                "period": t.get("period") or "",
                "end_date": t.get("endDate") or "",
                "eps_avg": _raw(eps, "avg"), "eps_low": _raw(eps, "low"),
                "eps_high": _raw(eps, "high"),
                "eps_year_ago": _raw(eps, "yearAgoEps"),
                "eps_growth": (lambda v: round(v * 100, 2) if v is not None else None)(
                    _raw(eps, "growth")),
                "analysts": _raw(eps, "numberOfAnalysts"),
                "rev_avg": _raw(rev, "avg"), "rev_low": _raw(rev, "low"),
                "rev_high": _raw(rev, "high"),
                "rev_year_ago": _raw(rev, "yearAgoRevenue"),
                "rev_growth": (lambda v: round(v * 100, 2) if v is not None else None)(
                    _raw(rev, "growth")),
                "up_30d": _raw(revis, "upLast30days"),
                "down_30d": _raw(revis, "downLast30days"),
            })

        return {
            "symbol": sym,
            "name": pr.get("longName") or pr.get("shortName") or sym,
            "logo": logo_url(sym),
            "currency": pr.get("currency") or "",
            "exchange": pr.get("exchangeName") or "",
            "price": _raw(pr, "regularMarketPrice"),
            "change_pct": (lambda v: round(v * 100, 2) if v is not None else None)(
                _raw(pr, "regularMarketChangePercent")),
            "market_cap": _raw(pr, "marketCap"),
            "week52_low": _raw(sd, "fiftyTwoWeekLow"),
            "week52_high": _raw(sd, "fiftyTwoWeekHigh"),
            "target_price": _raw(fd, "targetMeanPrice"),
            "recommendation": fd.get("recommendationKey") or "",
            "analysts": _raw(fd, "numberOfAnalystOpinions"),
            "forward_pe": _raw(sd, "forwardPE"),
            "trailing_pe": _raw(sd, "trailingPE"),
            "shares_short_pct": (lambda v: round(v * 100, 2) if v is not None else None)(
                _raw(ks, "shortPercentOfFloat")),
            "next": {
                "date": dates[0] if dates else "",
                "date_end": dates[1] if len(dates) > 1 else "",
                "estimate": bool(cal.get("isEarningsDateEstimate")),
                "eps": eps_now,
                "eps_low": _raw(cal, "earningsLow"),
                "eps_high": _raw(cal, "earningsHigh"),
                "revenue": rev_now,
                "revenue_low": _raw(cal, "revenueLow"),
                "revenue_high": _raw(cal, "revenueHigh"),
            },
            "history": history,
            "trend": trend,
            "forecast": _forecast_rows(sym) if "." not in sym else {"quarterly": [], "yearly": []},
            "margins": {
                "quarterly": _timeseries(sym, "quarterly"),
                "annual": _timeseries(sym, "annual"),
            },
            "quarters": _quarterly_revenue(d.get("earnings")),
            "stats": {
                "quarters": len(history),
                "beats": len(beats),
                "beat_rate": round(len(beats) / len(history) * 100) if history else None,
                "avg_surprise_pct": round(sum(surprises) / len(surprises), 2) if surprises else None,
                "avg_move_pct": round(sum(moves) / len(moves), 2) if moves else None,
                "max_move_pct": round(max(moves), 2) if moves else None,
            },
        }

    data = cache.cached(f"report-{sym}", TTL, build)
    if not data:
        return {"error": "Nie udało się pobrać danych o wynikach", "symbol": sym}
    return data
