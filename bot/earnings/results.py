"""Co się stało PO publikacji wyników — reakcja kursu rozbita na dwie części.

Kalendarz pokazuje przeszłość inaczej niż przyszłość: zamiast „ile potrzeba, żeby
pobić prognozę" chcemy widzieć „pobili czy nie i co na to rynek". Wynik i zaskoczenie
przychodzą z Nasdaqa razem z kalendarzem (`calendar._row`), tutaj liczymy kurs:

  * **luka** — ruch poza sesją: dla raportu przed otwarciem to zmiana od wczorajszego
    zamknięcia do dzisiejszego otwarcia (handel przedsesyjny), dla raportu po
    zamknięciu — od zamknięcia do otwarcia następnego dnia (handel posesyjny);
  * **sesja** — co kurs zrobił już w normalnych godzinach, od otwarcia do zamknięcia;
  * **razem** — od ostatniego zamknięcia przed raportem do końca pierwszej sesji po nim.

Rozbicie ma sens, bo te dwie części często idą w przeciwne strony: kurs wyskakuje
po wynikach o 6%, a potem przez całą sesję oddaje połowę.

Notowań NIE trzymamy w cache — tylko policzony wynik (kilkaset bajtów). Dzienne
świece każdej spółki, która kiedykolwiek raportowała, to setki megabajtów pamięci.
"""

import concurrent.futures as futures
import datetime as dt
import logging
import time

import requests

from . import cache

log = logging.getLogger("earnings.results")

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
TTL_FINAL = 30 * 24 * 3600
TTL_LIVE = 600

_session = requests.Session()
_session.headers.update(cache.UA)


def _range_for(date: str) -> str:
    """Najkrótszy zakres świec, który jeszcze obejmuje dzień raportu."""
    try:
        age = (dt.date.today() - dt.date.fromisoformat(date)).days
    except ValueError:
        return "3mo"
    for limit, rng in ((14, "1mo"), (75, "3mo"), (160, "6mo"), (340, "1y"), (700, "2y")):
        if age <= limit:
            return rng
    return "5y"


def _bars(symbol: str, rng: str) -> list:
    """[(data, otwarcie, zamknięcie)] rosnąco. Data w strefie giełdy, nie UTC."""
    r = _session.get(f"{CHART}{requests.utils.quote(symbol)}?range={rng}&interval=1d",
                     timeout=20)
    r.raise_for_status()
    res = (r.json().get("chart") or {}).get("result") or []
    if not res:
        return []
    node = res[0]
    offset = int((node.get("meta") or {}).get("gmtoffset") or 0)
    quote = ((node.get("indicators") or {}).get("quote") or [{}])[0]
    out = []
    for t, o, c in zip(node.get("timestamp") or [], quote.get("open") or [],
                       quote.get("close") or []):
        if o is None or c is None:
            continue
        day = dt.datetime.utcfromtimestamp(int(t) + offset).date().isoformat()
        out.append((day, float(o), float(c)))
    return out


def _extended(symbol: str) -> float | None:
    """Ruch poza sesją TERAZ, w procentach — ostatnia cena z handlu przed- lub
    posesyjnego względem ostatniego zamknięcia zwykłej sesji."""
    try:
        r = _session.get(f"{CHART}{requests.utils.quote(symbol)}"
                         "?range=1d&interval=5m&includePrePost=true", timeout=20)
        r.raise_for_status()
        res = (r.json().get("chart") or {}).get("result") or []
        if not res:
            return None
        node = res[0]
        base = (node.get("meta") or {}).get("regularMarketPrice")
        closes = ((node.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        last = next((c for c in reversed(closes) if c is not None), None)
        if not base or last is None:
            return None
        return round((last / base - 1) * 100, 2)
    except Exception as e:  # noqa: BLE001
        log.debug("Handel pozasesyjny %s: %s", symbol, e)
        return None


def _pct(a: float, b: float) -> float | None:
    return round((b / a - 1) * 100, 2) if a else None


def _compute(symbol: str, date: str, when: str) -> dict:
    bars = _bars(symbol, _range_for(date))
    today = dt.date.today().isoformat()
    out = {"symbol": symbol, "date": date, "session": when, "inferred": False,
           "gap_pct": None, "day_pct": None, "total_pct": None,
           "session_date": "", "final": False, "live": False}
    if not bars:
        return out

    prev = next((b for b in reversed(bars) if b[0] < date), None)
    cur = next((b for b in bars if b[0] == date), None)
    nxt = next((b for b in bars if b[0] > date), None)

    if when not in ("bmo", "amc"):
        # Pora nieznana (dla przeszłości Nasdaq jej nie podaje). Wyniki ruszają
        # kursem skokowo, więc większa z dwóch luk wskazuje, kiedy wyszły.
        gap_b = _pct(prev[2], cur[1]) if prev and cur else None
        gap_a = _pct(cur[2], nxt[1]) if cur and nxt else None
        if gap_b is not None and gap_a is not None:
            when = "bmo" if abs(gap_b) >= abs(gap_a) else "amc"
        elif gap_b is not None and abs(gap_b) >= 2.0:
            when = "bmo"
        elif cur is None and prev and nxt:
            # raport w dzień bez sesji — reakcja to po prostu następna sesja
            cur, when = prev, "amc"
        else:
            return out
        out["session"], out["inferred"] = when, True

    if when == "bmo":
        if not prev:
            return out
        if cur:
            out.update(gap_pct=_pct(prev[2], cur[1]), day_pct=_pct(cur[1], cur[2]),
                       total_pct=_pct(prev[2], cur[2]), session_date=cur[0],
                       final=cur[0] < today, live=cur[0] >= today)
        elif date >= today:
            out.update(gap_pct=_extended(symbol), live=True)
    else:
        base = cur or prev
        if not base:
            return out
        if nxt:
            out.update(gap_pct=_pct(base[2], nxt[1]), day_pct=_pct(nxt[1], nxt[2]),
                       total_pct=_pct(base[2], nxt[2]), session_date=nxt[0],
                       final=nxt[0] < today, live=nxt[0] >= today)
        elif cur:
            out.update(gap_pct=_extended(symbol), live=True)
    return out


def reaction(symbol: str, date: str, when: str = "tbd") -> dict:
    """Reakcja kursu na raport z dnia `date`. Zamknięte reakcje trzymamy miesiąc,
    trwające (sesja po raporcie jeszcze się toczy) — dziesięć minut."""
    sym = (symbol or "").strip().upper()
    when = when if when in ("bmo", "amc") else "tbd"
    key = f"react-{sym}-{date}-{when}"
    hit = cache.get(key, TTL_FINAL)
    if hit and (hit.get("final") or time.time() - hit.get("at", 0) < TTL_LIVE):
        return hit
    try:
        data = _compute(sym, date, when)
    except Exception as e:  # noqa: BLE001
        log.debug("Reakcja %s %s: %s", sym, date, e)
        return hit or {"symbol": sym, "date": date, "session": when}
    data["at"] = int(time.time())
    cache.put(key, data)
    return data


def reactions(date: str, items: list) -> dict:
    """{symbol: reakcja} dla listy (symbol, pora) — do kafli minionego dnia."""
    items = [(s, w) for s, w in items if s][:60]
    out = {}
    if not items:
        return out
    with futures.ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {pool.submit(reaction, s, date, w): s for s, w in items}
        try:
            for fut in futures.as_completed(jobs, timeout=25):
                r = fut.result()
                if r.get("total_pct") is not None or r.get("gap_pct") is not None:
                    out[jobs[fut]] = {k: r.get(k) for k in
                                      ("session", "inferred", "gap_pct", "day_pct",
                                       "total_pct", "final", "live")}
        except futures.TimeoutError:
            log.info("Reakcje %s: nie wszystkie zdążyły", date)
    return out
