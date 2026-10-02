"""Jak rynek reaguje na odczyty makro — teraz i w przeszłości.

Trzy pytania, na które odpowiada ten moduł:

  1. **Co rynek zrobił po TYM odczycie** — zmiana indeksu na sesji, w którą odczyt
     trafił, a dla świeżych wydarzeń (do ~8 tygodni) także przebieg kontraktów
     terminowych co pięć minut wokół samej publikacji. Kontraktów, nie indeksu, bo
     inflacja i payrollsy wychodzą o 8:30 czasu nowojorskiego — godzinę przed
     otwarciem giełdy, kiedy indeks stoi, a kontrakty już skaczą.
  2. **Jak bywało wcześniej** — te same publikacje z trzech lat podzielone na
     „powyżej prognozy / poniżej / zgodnie" ze średnią zmianą indeksu w każdej grupie.
  3. **Czy to w ogóle idzie w parze** — korelacja wielkości zaskoczenia ze zmianą indeksu.

To są średnie z kilkunastu–kilkudziesięciu obserwacji i tego samego dnia potrafi
wyjść kilka odczytów naraz, więc interfejs pokazuje liczebność grup obok wyniku.

Dla polskich odczytów punktem odniesienia jest WIG20, dla reszty świata — S&P 500
i Nasdaq 100.
"""

import datetime as dt
import logging
import math
import time

import requests

from . import cache, econ

log = logging.getLogger("earnings.impact")

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
YEARS = 3

_session = requests.Session()
_session.headers.update(cache.UA)

# (identyfikator, symbol Yahoo, nazwa, strefa, godzina zamknięcia sesji)
_US = [("spx", "^GSPC", "S&P 500", "us", 16), ("ndx", "^NDX", "Nasdaq 100", "us", 16)]
# Yahoo nie ma historii samego indeksu WIG20 (oddaje jeden dzień), więc bierzemy
# fundusz, który go odwzorowuje — dzienne zmiany są praktycznie te same.
_PL = [("wig20", "ETFBW20TR.WA", "WIG20", "pl", 17)]
_FUTURES = [("spx", "ES=F", "S&P 500"), ("ndx", "NQ=F", "Nasdaq 100")]


def _indexes(country: str) -> list:
    return _PL if (country or "").upper() == "PL" else _US


# ---------------- czas lokalny giełdy ----------------
#
# Liczone ręcznie, bez `zoneinfo`: kontener na hostingu nie musi mieć bazy stref,
# a reguły dla USA i Unii są dwie i nie zmieniły się od lat.

def _nth_sunday(year: int, month: int, n: int) -> dt.date:
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def _last_sunday(year: int, month: int) -> dt.date:
    last = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    return last - dt.timedelta(days=(last.weekday() + 1) % 7)


def _local(ts: float, zone: str) -> dt.datetime:
    utc = dt.datetime.utcfromtimestamp(ts)
    if zone == "us":      # czas letni: druga niedziela marca – pierwsza niedziela listopada
        summer = _nth_sunday(utc.year, 3, 2) <= utc.date() < _nth_sunday(utc.year, 11, 1)
        return utc - dt.timedelta(hours=4 if summer else 5)
    summer = _last_sunday(utc.year, 3) <= utc.date() < _last_sunday(utc.year, 10)
    return utc + dt.timedelta(hours=2 if summer else 1)


# ---------------- notowania indeksów ----------------

def _closes(symbol: str) -> dict:
    """{data: zamknięcie} indeksu z pięciu lat. Dwa–trzy symbole, więc można trzymać."""
    def build():
        r = _session.get(f"{CHART}{requests.utils.quote(symbol)}?range=5y&interval=1d",
                         timeout=25)
        r.raise_for_status()
        res = (r.json().get("chart") or {}).get("result") or []
        if not res:
            return None
        node = res[0]
        offset = int((node.get("meta") or {}).get("gmtoffset") or 0)
        closes = ((node.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        out = {}
        for t, c in zip(node.get("timestamp") or [], closes):
            if c is not None:
                out[dt.datetime.utcfromtimestamp(int(t) + offset).date().isoformat()] = float(c)
        return out or None

    return cache.cached(f"idx-daily-{symbol}", 1800, build) or {}


def _session_move(closes: dict, days: list, ts, date: str, zone: str, close_hour: int):
    """(zmiana %, data sesji) — sesja, w którą trafił odczyt.

    Odczyt po zamknięciu giełdy (albo w dzień bez sesji) rusza kursem dopiero
    następnego dnia, więc liczymy go do następnej sesji.
    """
    if ts:
        loc = _local(ts, zone)
        day = loc.date()
        if loc.hour >= close_hour:
            day += dt.timedelta(days=1)
        target = day.isoformat()
    else:
        target = date
    if not target:
        return None, ""
    sess = next((d for d in days if d >= target), None)
    if not sess:
        return None, ""
    i = days.index(sess)
    if i == 0 or (dt.date.fromisoformat(sess) - dt.date.fromisoformat(target)).days > 4:
        return None, ""
    a, b = closes[days[i - 1]], closes[sess]
    return (round((b / a - 1) * 100, 2) if a else None), sess


# ---------------- reakcja na to wydarzenie ----------------

def _path(symbol: str, ts: int) -> list:
    """[(minuty od publikacji, zmiana % od ceny w chwili publikacji)] co 5 minut."""
    r = _session.get(
        f"{CHART}{requests.utils.quote(symbol)}?period1={ts - 45 * 60}"
        f"&period2={ts + 185 * 60}&interval=5m&includePrePost=true", timeout=20)
    r.raise_for_status()
    res = (r.json().get("chart") or {}).get("result") or []
    if not res:
        return []
    node = res[0]
    closes = ((node.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    opens = ((node.get("indicators") or {}).get("quote") or [{}])[0].get("open") or []
    bars = [(int(t), o, c) for t, o, c in zip(node.get("timestamp") or [], opens, closes)
            if c is not None and o is not None]
    if len(bars) < 6:
        return []
    # cena odniesienia: otwarcie świecy, która zaczyna się w chwili publikacji,
    # a gdy takiej nie ma — zamknięcie ostatniej sprzed publikacji
    at = next((o for t, o, _ in bars if t >= ts), None)
    before = [c for t, _, c in bars if t < ts]
    base = before[-1] if before else at
    if not base:
        return []
    out = []
    for t, _, c in bars:
        # świeca [t, t+5 min) kończy się w t+5 — to jest chwila, której dotyczy zamknięcie
        out.append([round((t + 300 - ts) / 60), round((c / base - 1) * 100, 3)])
    return out


def _at(path: list, minute: int):
    hit = [p for m, p in path if m <= minute and m > 0]
    return hit[-1] if hit else None


def reaction(ts, date: str, country: str) -> dict:
    """Co rynek zrobił po tym konkretnym wydarzeniu."""
    now = time.time()
    if ts and ts > now:
        return {}
    out = {"indexes": [], "path": None}
    today = dt.date.today().isoformat()
    for ident, symbol, name, zone, close_hour in _indexes(country):
        closes = _closes(symbol)
        days = sorted(closes)
        pct, sess = _session_move(closes, days, ts, date, zone, close_hour)
        if pct is None:
            continue
        out["indexes"].append({"id": ident, "name": name, "pct": pct,
                               "session_date": sess, "live": sess >= today})

    # przebieg kontraktów — tylko dla świeżych wydarzeń z godziną i nie dla Polski
    # (kontraktów na WIG20 Yahoo nie ma)
    if ts and (country or "").upper() != "PL" and now - ts < 55 * 86400 and now - ts > 600:
        key = f"evpath-{int(ts)}"
        done = now > ts + 190 * 60
        hit = cache.get(key, 30 * 86400 if done else 300)
        if hit is None:
            hit = {"series": []}
            for ident, symbol, name in _FUTURES:
                try:
                    pts = _path(symbol, int(ts))
                except Exception as e:  # noqa: BLE001
                    log.debug("Przebieg %s: %s", symbol, e)
                    pts = []
                if pts:
                    hit["series"].append({
                        "id": ident, "name": name, "points": pts,
                        "m30": _at(pts, 30), "m60": _at(pts, 60), "m120": _at(pts, 120),
                    })
            cache.put(key, hit)
        if hit.get("series"):
            out["path"] = hit
    return out


# ---------------- historia: odczyt względem prognozy a indeks ----------------

def _year_index(country: str, year: int) -> dict:
    """{event_id: [[ts, odczyt, prognoza, poprzednio, jednostka, mnożnik], …]} za rok.

    Surowy rok kalendarza jednego kraju to prawie 2 MB — za dużo, żeby go trzymać
    dla każdego klikniętego wskaźnika. Zostawiamy sam szkielet liczb.
    """
    today = dt.date.today()
    if year > today.year:
        return {}
    closed = year < today.year

    def build():
        end = f"{year}-12-31" if closed else today.isoformat()
        out: dict = {}
        for raw in econ._fetch(f"{year}-01-01", end, [country]):
            ev = raw.get("eventId")
            stamp = raw.get("dateUtc") or ""
            if not ev or not stamp:
                continue
            try:
                ts = int(dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())
            except ValueError:
                continue
            out.setdefault(ev, []).append([
                ts, econ._num(raw.get("actual")), econ._num(raw.get("consensus")),
                econ._num(raw.get("previous")), raw.get("unit") or "", raw.get("potency") or "",
            ])
        return out

    return cache.cached(f"fxs-idx-{country}-{year}", 30 * 86400 if closed else 6 * 3600,
                        build) or {}


def _series(event_id: str, country: str) -> list:
    year = dt.date.today().year
    rows = []
    for y in range(year - YEARS, year + 1):
        rows.extend(_year_index(country, y).get(event_id) or [])
    rows.sort(key=lambda r: r[0])
    # stary wpis bez odczytu: „poprzednio" następnej publikacji to ta sama liczba
    for i in range(len(rows) - 1):
        if rows[i][1] is None and rows[i + 1][3] is not None:
            rows[i][1] = rows[i + 1][3]
    return rows


def _avg(vals: list):
    return round(sum(vals) / len(vals), 2) if vals else None


def _corr(xs: list, ys: list):
    n = len(xs)
    if n < 8:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return None
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), 2)


def history(event_id: str, country: str) -> dict:
    """Poprzednie publikacje wskaźnika zestawione ze zmianą indeksu tego dnia."""
    cc = (country or "US").upper()
    today = dt.date.today().isoformat()
    key = f"impact-{cc}-{event_id}-{today}"
    hit = cache.get(key, 6 * 3600)
    if hit is not None:
        return hit

    idx = _indexes(cc)
    books = []
    for ident, symbol, name, zone, close_hour in idx:
        closes = _closes(symbol)
        books.append((ident, name, zone, close_hour, closes, sorted(closes)))

    now = time.time()
    rows = []
    for ts, actual, consensus, _prev, unit, potency in _series(event_id, cc):
        if ts > now:
            continue
        moves = {}
        for ident, _name, zone, close_hour, closes, days in books:
            pct, sess = _session_move(closes, days, ts, "", zone, close_hour)
            if pct is not None and sess < today:
                moves[ident] = pct
        if not moves:
            continue
        side = "none"
        diff = None
        if actual is not None and consensus is not None:
            diff = actual - consensus
            side = "above" if diff > 1e-9 else "below" if diff < -1e-9 else "inline"
        rows.append({
            "date": dt.datetime.utcfromtimestamp(ts).date().isoformat(),
            "actual_fmt": econ._fmt_value(actual, unit, potency),
            "consensus_fmt": econ._fmt_value(consensus, unit, potency),
            "side": side, "diff": diff, "moves": moves,
        })

    def bucket(side):
        pick = rows if side == "all" else [r for r in rows if r["side"] == side]
        out = {"n": len(pick)}
        for ident, *_ in idx:
            vals = [r["moves"][ident] for r in pick if ident in r["moves"]]
            out[ident] = {
                "avg": _avg(vals),
                "avg_abs": _avg([abs(v) for v in vals]),
                "up_pct": round(sum(1 for v in vals if v > 0) / len(vals) * 100) if vals else None,
                "best": max(vals) if vals else None,
                "worst": min(vals) if vals else None,
            }
        return out

    main = idx[0][0]
    paired = [(r["diff"], r["moves"][main]) for r in rows
              if r["diff"] is not None and main in r["moves"]]
    out = {
        "years": YEARS,
        "since": dt.date.today().year - YEARS,
        "indexes": [{"id": i[0], "name": i[2]} for i in idx],
        "n": len(rows),
        "above": bucket("above"), "below": bucket("below"),
        "inline": bucket("inline"), "all": bucket("all"),
        "corr": _corr([p[0] for p in paired], [p[1] for p in paired]),
        "corr_n": len(paired),
        "recent": [{k: r[k] for k in ("date", "actual_fmt", "consensus_fmt", "side", "moves")}
                   for r in rows[-10:]][::-1],
    }
    if rows:        # pusty wynik to zwykle chwilowa awaria źródła — nie utrwalamy go
        cache.put(key, out)
    return out
