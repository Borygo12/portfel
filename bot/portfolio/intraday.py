"""Przebieg wartości portfela W CIĄGU DNIA (zakres „1D").

Dzienna seria z engine.py ma jeden punkt na dobę — do pytania „jak portfel radzi
sobie dzisiaj" to za mało. Tutaj składamy wartość portfela w PLN co 5 minut ze
słupków śróddziennych (Yahoo) i kursu walut (Yahoo FX), a punktem odniesienia jest
zamknięcie POPRZEDNIEJ sesji każdego instrumentu.

Model:
  - liczba akcji i saldo gotówki są w ciągu dnia stałe (operacje wchodzą z importu
    raportu, więc dzisiejsze transakcje pojawią się dopiero po wgraniu pliku)
  - cena instrumentu i kurs waluty są forward-fillowane z własnych słupków —
    dzięki temu GPW rusza się od 9:00, a USA dopiero od 15:30, tak jak naprawdę
  - walor, który DZIŚ jeszcze nie handlował, jest ZAMROŻONY: wchodzi do wykresu
    i do odniesienia tą samą kwotą, więc jego zmiana dnia wynosi dokładnie zero.
    Sam ruch kursu waluty tego nie zmienia — dopóki nie ma transakcji, nie ma
    zdarzenia. Notowania przedsesyjne pokazujemy OSOBNO, przy pozycji.
  - odniesienie (base) = wycena portfela po cenach i kursie z zamknięcia poprzedniej
    sesji; zmiana dnia = wartość teraz − base
  - ostatni punkt nadpisujemy wyceną „na żywo" z engine.compute(), żeby wykres
    kończył się dokładnie tą kwotą, którą pokazuje nagłówek

Sesja: dzień lokalny serwera (PC stoi w Polsce). Gdy dziś nic się jeszcze nie
notowało (weekend, święto, wczesny ranek), pokazujemy ostatnią sesję z notowaniami.
"""

import datetime
import logging
import time
from bisect import bisect_right

from . import engine, prices

log = logging.getLogger("portfolio.intraday")

STEP_SEC = 300          # rozdzielczość siatki — tyle samo co słupki Yahoo
MAX_POINTS = 260        # powyżej tego zagęszczenia telefon i tak nie pokaże różnicy
DAY_OPEN_H = 9          # gdy żaden instrument jeszcze nie handlował — start od otwarcia GPW


def _utc_offset() -> int:
    """Przesunięcie strefy serwera w sekundach (PC w Polsce = czas warszawski)."""
    off = datetime.datetime.now().astimezone().utcoffset()
    return int(off.total_seconds()) if off else 0


def _local_date(ts: int, off: int) -> datetime.date:
    return datetime.datetime.utcfromtimestamp(ts + off).date()


def _day_ts(day: datetime.date, hour: int, off: int) -> int:
    """Znacznik czasu lokalnej godziny danego dnia."""
    naive = datetime.datetime.combine(day, datetime.time(hour=hour))
    return int((naive - datetime.datetime(1970, 1, 1)).total_seconds()) - off


class _Track:
    """Jedna seria śróddzienna: cena przed sesją (base) + odczyt forward-fill."""

    def __init__(self, series: dict, day: datetime.date, off: int):
        ts, close = series.get("ts") or [], series.get("close") or []
        keep = [i for i, t in enumerate(ts) if _local_date(t, off) == day]
        self.ts = [ts[i] for i in keep]
        self.close = [close[i] for i in keep]
        self.traded = bool(self.ts)

        # odniesienie: ostatnie zamknięcie z sesji PRZED dniem, po który pytamy
        pts, pcl = series.get("prev_ts") or ts, series.get("prev_close") or close
        before = [c for t, c in zip(pts, pcl) if _local_date(t, off) < day]
        self.base = before[-1] if before else (self.close[0] if self.close else None)
        self.last = self.close[-1] if self.close else self.base

    def at(self, t: int):
        """Cena obowiązująca o czasie t (ostatni słupek <= t, wcześniej: base)."""
        i = bisect_right(self.ts, t)
        return self.close[i - 1] if i else self.base


def session() -> dict:
    """Śróddzienny przebieg wartości portfela + zmiana dnia per pozycja."""
    d = engine.compute()
    if d.get("empty"):
        return {"empty": True}

    off = _utc_offset()
    positions = [p for p in d["positions"] if not p.get("no_price")]
    accounts = d["accounts"]
    ccys = {p["currency"] for p in positions} | {a["currency"] for a in accounts}

    bars = prices.intraday_series([p["ticker"] for p in positions])
    fx_bars = prices.intraday_fx(ccys)

    # --- dzień sesji: dziś, jeśli cokolwiek dziś notowano; inaczej ostatnia sesja ---
    last_days = [_local_date(b["ts"][-1], off) for b in bars.values() if b.get("ts")]
    today = datetime.date.today()
    if not last_days:
        return {"empty": True, "reason": "Brak notowań śróddziennych"}
    day = min(max(last_days), today)

    tracks = {p["ticker"]: _Track(bars[p["ticker"]], day, off)
              for p in positions if p["ticker"] in bars}
    fx_tracks = {c: _Track(fx_bars[c], day, off) for c in ccys if c in fx_bars}

    _fallback_cache: dict = {}

    def _fx_fallback(ccy: str) -> float:
        """Gdy brak kursu z Yahoo — kurs NBP z ostatniego dnia (jak w wycenie dziennej)."""
        if ccy not in _fallback_cache:
            ser = prices.fx_series(ccy, (day - datetime.timedelta(days=14)).isoformat())
            _fallback_cache[ccy] = ser[max(ser)] if ser else 1.0
        return _fallback_cache[ccy]

    def fx_at(ccy: str, t: int) -> float:
        if ccy == "PLN":
            return 1.0
        tr = fx_tracks.get(ccy)
        v = tr.at(t) if tr else None
        return v if v else _fx_fallback(ccy)

    def fx_base(ccy: str) -> float:
        if ccy == "PLN":
            return 1.0
        tr = fx_tracks.get(ccy)
        return (tr.base if tr and tr.base else None) or _fx_fallback(ccy)

    # --- podział na to, co dziś realnie handluje, i resztę ---
    # Zamrożone pozycje wchodzą do każdego punktu wykresu tą samą kwotą, więc nie
    # dokładają ani grosza do zmiany dnia — także wtedy, gdy dolar drgnął.
    live, frozen = [], []
    for p in positions:
        tr = tracks.get(p["ticker"])
        (live if tr and tr.traded and tr.base else frozen).append(p)
    frozen_pln = round(sum(p["value_pln"] for p in frozen), 2)
    frozen_set = {p["ticker"] for p in frozen}

    # --- siatka czasu ---
    starts = [tracks[p["ticker"]].ts[0] for p in live]
    t0 = min(starts) if starts else _day_ts(day, DAY_OPEN_H, off)
    ends = [tracks[p["ticker"]].ts[-1] for p in live]
    ends += [tr.ts[-1] for tr in fx_tracks.values() if tr.traded and tr.ts[-1] >= t0]
    now = int(time.time())
    if day == today:
        ends.append(now)
    t1 = max(ends) if ends else t0 + STEP_SEC
    if t1 <= t0:
        t1 = t0 + STEP_SEC

    step = STEP_SEC
    while (t1 - t0) / step > MAX_POINTS:
        step *= 2
    grid = list(range(t0, t1, step)) + [t1]

    # --- wycena w każdym punkcie siatki ---
    cash = [(a["currency"], a["cash"]) for a in accounts if a.get("cash")]
    values = []
    for t in grid:
        v = frozen_pln + sum(amount * fx_at(ccy, t) for ccy, amount in cash)
        for p in live:
            price = tracks[p["ticker"]].at(t)
            if price:
                v += p["shares"] * price * fx_at(p["currency"], t)
        values.append(round(v, 2))

    # --- odniesienie: zamknięcie poprzedniej sesji ---
    base = frozen_pln + sum(amount * fx_base(ccy) for ccy, amount in cash)
    for p in live:
        base += p["shares"] * tracks[p["ticker"]].base * fx_base(p["currency"])

    # --- notowania przedsesyjne: tylko informacyjnie, przy pozycji ---
    ext = prices.extended_quotes([p["ticker"] for p in frozen]) if frozen and day == today else {}

    pos_out, missing = [], []
    for p in positions:
        tr = tracks.get(p["ticker"])
        if p["ticker"] in frozen_set:
            e = ext.get(p["ticker"])
            pre_pct = None
            if e and tr and tr.base:
                pre_pct = round((e["price"] / tr.base - 1) * 100, 2)
            if not tr or not tr.base:
                missing.append(p["ticker"])
            pos_out.append({
                "ticker": p["ticker"],
                "base_price": round(tr.base, 4) if tr and tr.base else None,
                "price": p["price"], "value_pln": p["value_pln"],
                "change_pln": 0.0, "change_pct": 0.0, "price_pct": 0.0,
                "traded": False, "no_data": not (tr and tr.base),
                "ext_pct": pre_pct,
                "ext_price": e["price"] if e else None,
                "ext_ts": e["ts"] if e else None,
                "ext_phase": e["phase"] if e else None,
            })
            continue

        fxb = fx_base(p["currency"])
        base_val = p["shares"] * tr.base * fxb
        change = p["value_pln"] - base_val
        pos_out.append({
            "ticker": p["ticker"],
            "base_price": round(tr.base, 4),
            "price": p["price"],
            "value_pln": p["value_pln"],
            "change_pln": round(change, 2),
            "change_pct": round(change / base_val * 100, 2) if base_val > 1e-9 else 0.0,
            "price_pct": round((p["price"] / tr.base - 1) * 100, 2),
            "traded": True,
            "no_data": False,
            "fx_pct": round((fx_at(p["currency"], grid[-1]) / fxb - 1) * 100, 2) if fxb else 0.0,
            "ext_pct": None, "ext_price": None, "ext_ts": None, "ext_phase": None,
        })

    # ostatni punkt = wycena „na żywo" z silnika (gotówka + wszystkie pozycje po
    # bieżących kursach), żeby wykres kończył się dokładnie kwotą z nagłówka
    if day == today:
        values[-1] = d["summary"]["value"]
    end = values[-1]

    base = round(base, 2)
    change = round(end - base, 2)

    # ile z dzisiejszej zmiany zrobił sam kurs walut (liczone tylko dla tego,
    # co dziś realnie handluje — reszta jest zamrożona, więc nic nie wnosi)
    fx_effect = sum(amount * (fx_at(ccy, grid[-1]) - fx_base(ccy)) for ccy, amount in cash)
    for p in live:
        fx_effect += (p["shares"] * tracks[p["ticker"]].base
                      * (fx_at(p["currency"], grid[-1]) - fx_base(p["currency"])))

    # Rynek „żyje", gdy ostatni słupek jest świeży. Yahoo podaje GPW z 15-minutowym
    # opóźnieniem, więc próg 5 minut (jak przy notowaniach) fałszywie mówiłby „zamknięta".
    last_bar = max([tracks[p["ticker"]].ts[-1] for p in live] or [0])
    market_open = bool(day == today and last_bar and now - last_bar < 1500)

    return {
        "empty": False,
        "session_date": day.isoformat(),
        "is_today": day == today,
        "market_open": market_open,
        "last_bar": last_bar or None,
        "tz_offset": off,
        "step_sec": step,
        "ts": grid,
        "values": values,
        "base": base,
        "positions": pos_out,
        "stats": {
            "change_pln": change,
            "change_pct": round(change / base * 100, 2) if base > 1e-9 else 0.0,
            "high": max(values),
            "low": min(values),
            "value_end": end,
            "fx_change_pln": round(fx_effect, 2),
            "frozen_pln": frozen_pln,
            "open": values[0],
        },
        "traded": len(live),
        "total": len(pos_out),
        "no_data": missing,
        "server_now": now,
        "computed_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
    }


# ---------------------------------------------------------------------------
# Zakresy dłuższe niż jedna sesja, ale wciąż w rozdzielczości śróddziennej
# ---------------------------------------------------------------------------
#
# Seria dzienna daje na tydzień 7 punktów (z czego dwa to weekend, czyli powtórka
# piątku) — wykres jest wtedy płaski i nie widać na nim ruchu. Tutaj składamy ten
# sam zakres ze słupków śróddziennych: 15-minutowych na tydzień, 30-minutowych na
# miesiąc, godzinowych na dłuższe.
#
# Metoda: KOTWICA + POPRAWKA.
#   - kotwicą jest dzienna wycena z engine.compute() dla dnia, w którym leży punkt —
#     ona jest kompletna (gotówka, kursy NBP, walory bez notowań śróddziennych,
#     zmiany liczby akcji) i to ona kończy wykres kwotą z nagłówka
#   - poprawką jest odchylenie od zamknięcia TEGO dnia, policzone tylko dla tego,
#     co ma słupki śróddzienne: Σ akcje·(cena(t)·fx(t) − cena(koniec dnia)·fx(wtedy))
#
# Dzięki temu w momencie zamknięcia sesji poprawka wynosi dokładnie zero, więc
# krzywa przechodzi przez te same punkty co wykres dzienny — dokładamy wyłącznie
# kształt w środku dnia. Walor bez słupków po prostu nie rusza się w ciągu dnia
# (bo nie wiemy, jak się ruszał), zamiast zmyślać mu przebieg.

# ile dni wstecz sięga każdy zakres — MUSI się zgadzać z `_range_start` w dashboard.py,
# bo obok tego wykresu stoją statystyki liczone z serii dziennej tego samego zakresu
HISTORY_DAYS = {"1w": 7, "1m": 31, "3m": 92, "6m": 183, "1y": 366, "3y": 1096}

# najmniejszy zakres Yahoo, który pokrywa żądaną liczbę dni (mniejszy = mniej
# niepotrzebnie ściąganych słupków)
_Y_RANGES = ((8, "5d"), (31, "1mo"), (92, "3mo"), (183, "6mo"), (366, "1y"), (730, "2y"))

# Yahoo udostępnia darmowe słupki godzinowe do 2 lat wstecz (dla 3 lat odpowiada
# „1h data not available"). Dłuższe zakresy zostają przy serii dziennej — i tak
# mają wtedy więcej punktów niż pikseli na ekranie telefonu.
HIST_MAX_DAYS = 720
HIST_MAX_POINTS = 400   # gęściej telefon nie narysuje, a payload rośnie


class _Bars:
    """Słupki jednego waloru z kilku sesji: odczyt „cena o czasie t" + zamknięcia dni."""

    def __init__(self, series: dict, off: int):
        self.ts = series.get("ts") or []
        self.close = series.get("close") or []
        self.currency = series.get("currency") or ""
        # data lokalna -> (czas ostatniego słupka tego dnia, jego cena)
        self.eod: dict = {}
        for t, c in zip(self.ts, self.close):
            self.eod[_local_date(t, off).isoformat()] = (t, c)

    def at(self, t: int):
        i = bisect_right(self.ts, t)
        return self.close[i - 1] if i else None


def _plan(rng: str, first_date: datetime.date, today: datetime.date):
    """(początek zakresu, zakres Yahoo, interwał) albo None, gdy zakres ma zostać dzienny.

    Zakres liczymy od pierwszej operacji w portfelu, nie sztywno wstecz — dla „MAX"
    i „3L" świeżego portfela oznacza to kilka miesięcy zamiast trzech lat, więc
    wciąż mieszczą się w oknie słupków godzinowych.
    """
    if rng == "ytd":
        start = today.replace(month=1, day=1)
    elif rng == "max":
        start = first_date
    elif rng in HISTORY_DAYS:
        start = today - datetime.timedelta(days=HISTORY_DAYS[rng])
    else:
        return None
    start = max(start, first_date)
    span = (today - start).days
    if span > HIST_MAX_DAYS:
        return None
    y_range = next((y for d, y in _Y_RANGES if span <= d), None)
    if not y_range:
        return None
    interval = "15m" if span <= 8 else "30m" if span <= 31 else "1h"
    return start, y_range, interval


def _thin(ts: list, values: list, values_net: list, invested: list,
          days: list, target: int) -> tuple:
    """Przerzedzenie serii z ZACHOWANIEM SKRAJNOŚCI.

    Zwykłe „co n-ty punkt" gubi dokładnie to, co na wykresie najważniejsze — szczyty
    i dołki (a w trybie świec wprost wysokość świecy). Dlatego dzielimy serię na
    kubełki i z każdego bierzemy pierwszy, najniższy, najwyższy i ostatni punkt.

    Granice kubełków idą po SESJACH, dopóki się to mieści w budżecie punktów. To nie
    kosmetyka: dzięki temu w serii zostaje zamknięcie każdego dnia, a więc krzywa
    przechodzi dokładnie przez punkty wykresu dziennego. Przy kubełkach liczonych po
    indeksie granica wypadała w środku sesji i zamknięcia znikały (rozjazd sięgał
    118 zł). Gdy sesji jest mało, a budżet duży, każdą sesję tniemy jeszcze na kilka
    części — inaczej z miesiąca zostałyby cztery punkty na dzień. Dopiero gdy samych
    sesji jest więcej niż budżet, tniemy serię równymi kawałkami.
    """
    n = len(ts)
    if n <= target:
        return ts, values, values_net, invested
    sessions = [i for i in range(n) if not i or days[i] != days[i - 1]]
    if len(sessions) * 4 <= target:
        parts = max(1, target // (4 * len(sessions)))
        bounds = sorted({a + j * (b - a) // parts
                         for a, b in zip(sessions, sessions[1:] + [n])
                         for j in range(parts)})
    else:
        buckets = max(1, target // 4)
        bounds = sorted({b * n // buckets for b in range(buckets)})
    keep = set()
    for a, b in zip(bounds, bounds[1:] + [n]):
        seg = range(a, b)
        keep.update((a, b - 1,
                     min(seg, key=values.__getitem__), max(seg, key=values.__getitem__)))
    idx = sorted(keep)
    return ([ts[i] for i in idx], [values[i] for i in idx],
            [values_net[i] for i in idx], [invested[i] for i in idx])


def history(rng: str) -> dict:
    """Przebieg wartości portfela w rozdzielczości śróddziennej dla podanego zakresu."""
    d = engine.compute()
    if d.get("empty"):
        return {"empty": True}

    off = _utc_offset()
    today = datetime.date.today()
    plan = _plan(rng, datetime.date.fromisoformat(d["dates"][0]), today)
    if not plan:
        return {"empty": True, "reason": "Zakres poza oknem notowań śróddziennych"}
    start, y_range, y_interval = plan
    start_iso = start.isoformat()

    # dni serii dziennej wewnątrz zakresu — to one są kotwicami
    idx = {day: i for i, day in enumerate(d["dates"]) if day >= start_iso}
    if not idx:
        return {"empty": True, "reason": "Brak wyceny dziennej w tym zakresie"}

    hold = engine.holdings(sorted(idx))
    tickers = sorted({t for h in hold.values() for t in h["shares"]})
    if not tickers:
        return {"empty": True, "reason": "Brak pozycji w tym zakresie"}

    raw = prices.history_series(tickers, y_range, y_interval)
    bars = {t: _Bars(s, off) for t, s in raw.items()}
    # waluty bierzemy z meta słupków (walor mógł zostać w międzyczasie sprzedany,
    # więc nie ma go już w pozycjach) plus waluty kont — dla efektu na gotówce
    ccys = ({b.currency for b in bars.values() if b.currency}
            | {a["currency"] for a in d["accounts"]})
    fx = {c: _Bars(s, off) for c, s in prices.history_fx(ccys, y_range, y_interval).items()}

    def fx_at(ccy: str, t: int):
        if ccy == "PLN":
            return 1.0
        b = fx.get(ccy)
        return b.at(t) if b else None

    def fx_eod(ccy: str, day: str):
        """Kurs w momencie zamknięcia danego dnia — punkt odniesienia poprawki."""
        if ccy == "PLN":
            return 1.0
        b = fx.get(ccy)
        e = b.eod.get(day) if b else None
        return e[1] if e else None

    # --- siatka czasu: momenty, w których cokolwiek NAPRAWDĘ się notowało ---
    # Nocy i weekendów nie wypełniamy pustymi punktami — wykres pokazuje sesje
    # jedna po drugiej, tak jak robią to platformy giełdowe.
    now = int(time.time())
    start_ts = _day_ts(start, 0, off)
    grid = sorted({t for b in bars.values() for t in b.ts if start_ts <= t <= now})
    grid = [t for t in grid if _local_date(t, off).isoformat() in idx]
    if len(grid) < 2:
        return {"empty": True, "reason": "Brak notowań śróddziennych w tym zakresie"}

    # --- wycena w każdym punkcie siatki ---
    # Liczymy WSZYSTKIE punkty, a dopiero gotową serię przerzedzamy — inaczej
    # przerzedzanie nie wiedziałoby, gdzie są szczyty i dołki, i by je wycięło.
    ts_out, values, values_net, invested, point_days = [], [], [], [], []
    for t in grid:
        day = _local_date(t, off).isoformat()
        i, h = idx.get(day), hold.get(day)
        if i is None or h is None:
            continue
        corr = 0.0
        for tick, shares in h["shares"].items():
            b = bars.get(tick)
            if not b:
                continue
            eod = b.eod.get(day)
            price = b.at(t)
            if price is None or not eod:
                continue
            t_e, price_e = eod
            f_t, f_e = fx_at(b.currency, t), fx_at(b.currency, t_e)
            if f_t is None or f_e is None:
                continue
            corr += shares * (price * f_t - price_e * f_e)
        for _acct, ccy, amount in h["cash"]:
            f_t, f_e = fx_at(ccy, t), fx_eod(ccy, day)
            if f_t is None or f_e is None:
                continue
            corr += amount * (f_t - f_e)
        ts_out.append(t)
        values.append(round(d["values"][i] + corr, 2))
        values_net.append(round(d["values_net"][i] + corr, 2))
        invested.append(d["invested"][i])
        point_days.append(day)

    if len(ts_out) < 2:
        return {"empty": True, "reason": "Brak notowań śróddziennych w tym zakresie"}

    # ostatni punkt = wycena „na żywo" z nagłówka; poprawka na ostatnim słupku jest
    # zerowa tylko wtedy, gdy słupki są świeże, więc dociągamy to wprost
    if d["dates"][-1] in idx:
        values[-1] = d["summary"]["value"]
        values_net[-1] = d["summary"]["value_net"]

    ts_out, values, values_net, invested = _thin(
        ts_out, values, values_net, invested, point_days, HIST_MAX_POINTS)

    return {
        "empty": False,
        "range": rng,
        "tz_offset": off,
        "ts": ts_out,
        "values": values,
        "values_net": values_net,
        # linia wpłat przypięta do tej samej siatki co wartość — dzięki temu wykres
        # śróddzienny nie traci nic z tego, co pokazywał dzienny
        "invested": invested,
        "base": values[0],
        "base_net": values_net[0],
        "start": start_iso,
        "interval": y_interval,
        "points": len(ts_out),
        "server_now": now,
        "computed_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
    }
