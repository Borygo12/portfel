"""Silnik portfela — rekonstrukcja pozycji z operacji, dzienna wycena w PLN,
przepływy zewnętrzne (wpłaty/wypłaty), TWR i XIRR.

Model:
  - każde konto XTB ma walutę; saldo gotówki = skumulowana suma WSZYSTKICH operacji
  - liczba akcji per ticker = suma wolumenów z komentarzy OPEN/CLOSE
  - wycena dzienna = Σ gotówka(konto)*FX + Σ akcje(ticker)*cena*FX  [w PLN]
  - przepływ zewnętrzny = Deposit / Withdrawal oraz Transfer, którego druga
    strona NIE jest zaimportowanym kontem (po dograniu drugiego konta oba
    wiersze transferu stają się wewnętrzne i znoszą się same)
"""

import datetime
import logging
import re
import threading
import time as _time
from bisect import bisect_right
from collections import defaultdict

from . import fees, prices, store

log = logging.getLogger("portfolio.engine")

_VOL_RE = re.compile(r"(OPEN|CLOSE)\s+(BUY|SELL)\s+([\d.]+)(?:/[\d.]+)?\s*@\s*([\d.]+)")
# XTB pisze transfery na dwa sposoby:
#   'Currency conversion, USD to PLN from TA: 55145637 to: 51269212, ...'
#   'Transfer from 55699916 to 51269212'
_TRANSFER_RES = (
    re.compile(r"from TA:\s*(\d+)\s*to:\s*(\d+)"),
    re.compile(r"Transfer from\s*(\d+)\s*to\s*(\d+)", re.IGNORECASE),
)


def _transfer_accounts(comment: str):
    """(konto_z, konto_do) z komentarza transferu albo None."""
    for rx in _TRANSFER_RES:
        m = rx.search(comment or "")
        if m:
            return m.group(1), m.group(2)
    return None

# Memo MUSI być per użytkownik. Jedno wspólne miejsce oznaczałoby, że przez
# MEMO_TTL sekund kolejna osoba dostaje portfel poprzedniej — czyli wyciek danych,
# którego RLS by nie złapał, bo do bazy w ogóle byśmy nie poszli.
_memo: dict = {}                       # user_id -> {"at": float, "data": dict}
_memo_lock = threading.Lock()
# Tyle samo, co QUOTE_TTL w prices.py — i to nie przypadek. Bieżące notowania mają
# 15-sekundowy cache, więc przeliczanie portfela co 8 sekund dawało co drugi raz
# DOKŁADNIE te same liczby, tyle że okupione kompletem odczytów serii dziennych.
# Zrównanie obu terminów niczego nie postarza (nowe kursy i tak pojawiają się co 15 s),
# a o połowę zmniejsza liczbę przeliczeń.
MEMO_TTL = 15  # s

# Jeden przelicz na użytkownika NARAZ.
#
# Ekran przeglądu pyta o trzy rzeczy jednocześnie (podsumowanie, seria, przebieg
# śróddzienny) i każda z nich woła `compute`. Przy wygasłym memo wszystkie trzy
# zaczynały liczyć RÓWNOLEGLE — a każde liczenie to komplet zapytań do Yahoo
# o kursy i waluty. Zamiast jednego przeliczenia robiły się trzy, potrojony ruch
# w sieć i trzykrotnie większa szansa, że któreś z nich utknie. Po kliknięciu
# w zakres albo benchmark odpowiedź potrafiła przez to iść kilka sekund.
#
# Tutaj pierwszy wątek liczy, pozostałe czekają pod drzwiami i biorą gotowy wynik.
_flight_locks: dict = {}
_flight_lock = threading.Lock()


def _memo_key() -> str:
    import db
    return db.current_user() or "?"


def _flight_lock_for(key: str) -> threading.Lock:
    with _flight_lock:
        lk = _flight_locks.get(key)
        if lk is None:
            lk = _flight_locks[key] = threading.Lock()
        return lk


# Numer kolejnego przeliczenia. Zegar do tego NIE nadaje się: na Windowsie
# `time.time()` tyka co ~15 ms, więc „policzone po mojej chwili" wychodziło
# prawdziwe dla wyniku sprzed ułamka sekundy — i wymuszone odświeżenie dostawało
# odgrzewane dane. Licznik jest dokładny niezależnie od zegara.
_gen = 0


def _memo_stan(key: str) -> tuple:
    """(wynik, numer przeliczenia) z memo. (None, 0) gdy pusto."""
    with _memo_lock:
        hit = _memo.get(key)
    if not hit or not hit["data"]:
        return None, 0
    return hit, hit.get("gen", 0)


def _zapisz_memo(key: str, data: dict) -> dict:
    global _gen
    with _memo_lock:
        _gen += 1
        _memo[key] = {"data": data, "at": _time.time(), "gen": _gen}
    return data


def _from_memo(key: str, after_gen: int = -1):
    """Wynik z memo albo None.

    `after_gen >= 0` pyta o wynik policzony PÓŹNIEJ niż podany numer — tak czeka
    wymuszone odświeżenie. Bez tego argumentu obowiązuje zwykły termin ważności.
    """
    hit, gen = _memo_stan(key)
    if not hit:
        return None
    if after_gen >= 0:
        return hit["data"] if gen > after_gen else None
    return hit["data"] if _time.time() - hit["at"] < MEMO_TTL else None


def invalidate() -> None:
    """Kasuje memo zalogowanego użytkownika (cudzych nie ruszamy)."""
    with _memo_lock:
        _memo.pop(_memo_key(), None)
    intraday_invalidate(_memo_key())


# Memo przebiegu śróddziennego — ustawiane przez moduł `intraday`, żeby jego cache
# znikał razem z tym silnika (import raportu zmienia oba naraz).
intraday_invalidate = lambda _key: None      # noqa: E731


def _dstr(iso_time: str) -> str:
    return (iso_time or "")[:10]


def _daterange(d0: str, d1: str) -> list:
    a = datetime.date.fromisoformat(d0)
    b = datetime.date.fromisoformat(d1)
    return [(a + datetime.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


class _Step:
    """Seria schodkowa: wartość z ostatniej znanej daty <= d (forward-fill)."""

    def __init__(self, mapping: dict, default=0.0):
        items = sorted(mapping.items())
        self.dates = [k for k, _ in items]
        self.vals = [v for _, v in items]
        self.default = default

    def at(self, d: str):
        i = bisect_right(self.dates, d)
        return self.vals[i - 1] if i else self.default


def _parse_ops():
    """Grupuje operacje: salda gotówki per konto, wolumeny per ticker, przepływy zewn."""
    ops = store.query("SELECT * FROM cash_ops ORDER BY time")
    accounts = {a["account"]: a["currency"] for a in store.query("SELECT * FROM accounts")}
    if not ops:
        return None

    cash_delta = defaultdict(lambda: defaultdict(float))     # konto -> data -> Δgotówka
    share_delta = defaultdict(lambda: defaultdict(float))    # ticker -> data -> Δakcje
    # FIFO loty: [vol, cena_instr, koszt_w_walucie_konta, konto, data] — koszt z faktycznej
    # kwoty operacji, więc po przeliczeniu kursem z DNIA ZAKUPU P/L zawiera efekt walutowy
    # dokładnie tak, jak liczy to XTB
    lots = defaultdict(list)
    flows = []                                               # przepływy zewnętrzne (data, kwota, waluta, opis)
    instrument_name = {}

    for op in ops:
        d = _dstr(op["time"])
        acct, typ, amt = op["account"], op["type"], op["amount"]
        cash_delta[acct][d] += amt
        tick = op["ticker"]
        if tick:
            instrument_name.setdefault(tick, op["instrument"])

        if typ in ("Stock purchase", "Stock sell") and tick:
            m = _VOL_RE.search(op["comment"] or "")
            if m:
                vol, price = float(m.group(3)), float(m.group(4))
            else:
                price = 0.0
                vol = abs(amt)  # awaryjnie: nie znamy ceny — nie ruszamy akcji
                log.warning("Nie sparsowano wolumenu: %s | %s", typ, op["comment"])
                continue
            if typ == "Stock purchase":
                share_delta[tick][d] += vol
                lots[tick].append([vol, price, abs(amt), acct, d])
            else:
                share_delta[tick][d] -= vol
                left = vol
                while left > 1e-12 and lots[tick]:
                    lot = lots[tick][0]
                    take = min(lot[0], left)
                    lot[2] -= lot[2] * take / lot[0]   # koszt maleje proporcjonalnie
                    lot[0] -= take
                    left -= take
                    if lot[0] <= 1e-12:
                        lots[tick].pop(0)
        elif typ in ("Deposit", "Withdrawal"):
            flows.append({"date": d, "amount": amt, "currency": accounts.get(acct, "PLN"),
                          "type": typ, "comment": op["comment"]})
        elif typ == "Transfer":
            pair = _transfer_accounts(op["comment"])
            other = None
            if pair:
                ta_from, ta_to = pair
                other = ta_to if ta_from == acct else ta_from
            if not other or other not in accounts:
                flows.append({"date": d, "amount": amt, "currency": accounts.get(acct, "PLN"),
                              "type": "Transfer", "comment": op["comment"]})

    first_date = _dstr(ops[0]["time"])
    return {
        "accounts": accounts, "cash_delta": cash_delta, "share_delta": share_delta,
        "lots": lots, "flows": flows, "names": instrument_name, "first_date": first_date,
        "ops": ops,
    }


def _cum(delta_by_date: dict) -> dict:
    total, out = 0.0, {}
    for d in sorted(delta_by_date):
        total += delta_by_date[d]
        out[d] = round(total, 8)
    return out


def compute(force: bool = False) -> dict:
    """Pełny przelicz: dzienna seria wartości, przepływy, pozycje, TWR, XIRR.

    Równoległe wywołania nie liczą po swojemu — pierwsze liczy, reszta czeka
    i dostaje ten sam wynik (patrz `_flight_locks`).
    """
    key = _memo_key()
    if not force:
        gotowe = _from_memo(key)
        if gotowe is not None:
            return gotowe

    _, gen_przed = _memo_stan(key)
    with _flight_lock_for(key):
        # Ktoś policzył, gdy staliśmy w kolejce — bierzemy jego wynik. Liczy się
        # tylko przelicz NOWSZY niż ten, który zastaliśmy wchodząc; dzięki temu
        # `force=True` dostaje wynik policzony po jego żądaniu, a nie odgrzewany.
        gotowe = _from_memo(key, after_gen=gen_przed)
        if gotowe is not None:
            return gotowe
        if not force:
            gotowe = _from_memo(key)
            if gotowe is not None:
                return gotowe
        return _compute_now(key)


def _compute_now(key: str) -> dict:
    parsed = _parse_ops()
    if not parsed:
        return _zapisz_memo(key, {"empty": True})

    today = datetime.date.today().isoformat()
    dates = _daterange(parsed["first_date"], today)
    from_date = parsed["first_date"]

    # --- serie FX (waluta -> PLN) ---
    currencies = set(parsed["accounts"].values())
    fx_step = {"PLN": _Step({}, default=1.0)}

    # --- ceny i waluty instrumentów ---
    # najpierw historia (cache 6h), potem świeże kursy dla wciąż otwartych pozycji
    held = [t for t, dl in parsed["share_delta"].items()
            if sum(dl.values()) > 1e-9]
    quotes = prices.live_quotes(held) if held else {}

    price_step, tick_ccy, price_warn = {}, {}, []
    for tick in parsed["share_delta"]:
        series, ccy = prices.price_series(tick, from_date)
        if not series:
            price_warn.append(tick)
            continue
        q = quotes.get(tick)
        if q:   # bieżący kurs nadpisuje ostatni słupek dzienny
            series = dict(series)
            series[today] = q["price"]
            ccy = q["currency"] or ccy
        price_step[tick] = _Step(series)
        tick_ccy[tick] = ccy or "USD"
        currencies.add(tick_ccy[tick])

    # DZISIEJSZY kurs bierzemy z rynku (NBP publikuje raz dziennie ~12:15, a portfel
    # jest w większości w USD — bez tego wartość w PLN stoi mimo ruchu na walucie).
    live_fx = prices.live_fx(currencies)
    for ccy in currencies:
        if ccy != "PLN" and ccy not in fx_step:
            fx = prices.fx_series(ccy, from_date)
            lfx = live_fx.get(ccy)
            if lfx:
                fx = dict(fx)
                fx[today] = lfx["price"]
            fx_step[ccy] = _Step(fx, default=(fx[min(fx)] if fx else 1.0))

    def to_pln(amount: float, ccy: str, d: str) -> float:
        return amount * fx_step.get(ccy, fx_step["PLN"]).at(d)

    # --- schodki: gotówka per konto, akcje per ticker ---
    cash_step = {a: _Step(_cum(dl)) for a, dl in parsed["cash_delta"].items()}
    share_step = {t: _Step(_cum(dl)) for t, dl in parsed["share_delta"].items()}

    # --- przepływy zewnętrzne w PLN, zsumowane per dzień ---
    flow_by_day = defaultdict(float)
    flow_list = []
    for f in parsed["flows"]:
        pln = to_pln(f["amount"], f["currency"], f["date"])
        flow_by_day[f["date"]] += pln
        flow_list.append({**f, "amount_pln": round(pln, 2)})

    # --- profile prowizji: potrzebne już przy serii dziennej ---
    acct_rows = {a["account"]: a for a in store.query("SELECT * FROM accounts")}
    cfg = {acct: fees.profile(row.get("broker"), row.get("fees"))
           for acct, row in acct_rows.items()}
    # konto pozycji = konto ostatniego otwartego lota (stamtąd wróci gotówka ze sprzedaży)
    pos_account = {t: (lot_list[-1][3] if lot_list else "")
                   for t, lot_list in parsed["lots"].items()}

    # --- dzienna wycena (brutto i po kosztach wyjścia) ---
    # Serię „netto" liczymy TĄ SAMĄ funkcją co dzisiejszy koszt wyjścia, więc wykres
    # kończy się dokładnie kwotą z nagłówka — żadnego szacowania na skróty.
    values, values_net, invested_series = [], [], []
    invested = 0.0
    for d in dates:
        v = 0.0
        cash_d = []
        for acct, ccy in parsed["accounts"].items():
            if acct in cash_step:
                amount = cash_step[acct].at(d)
                v += to_pln(amount, ccy, d)
                cash_d.append((acct, ccy, amount))
        held = []
        for t, st in share_step.items():
            sh = st.at(d)
            if abs(sh) > 1e-9 and t in price_step:
                pv = to_pln(sh * price_step[t].at(d), tick_ccy[t], d)
                v += pv
                held.append({"ticker": t, "value_pln": pv, "currency": tick_ccy[t]})
        cost_d = fees.exit_costs(held, cash_d, pos_account, cfg,
                                lambda ccy, day=d: fx_step.get(ccy, fx_step["PLN"]).at(day))
        invested += flow_by_day.get(d, 0.0)
        values.append(round(v, 2))
        values_net.append(round(v - cost_d["total_pln"], 2))
        invested_series.append(round(invested, 2))

    # --- TWR (przepływ na początku dnia) ---
    twr = [1.0]
    for i in range(1, len(dates)):
        base = values[i - 1] + flow_by_day.get(dates[i], 0.0)
        r = (values[i] - base) / base if base > 1e-9 else 0.0
        twr.append(twr[-1] * (1.0 + r))

    # --- pozycje otwarte ---
    positions = []
    for t, st in share_step.items():
        sh = st.at(today)
        if sh <= 1e-9:
            continue
        open_lots = parsed["lots"][t]
        lot_vol = sum(l[0] for l in open_lots)
        avg_open = (sum(l[0] * l[1] for l in open_lots) / lot_vol) if lot_vol > 1e-12 else 0.0
        cur_price = price_step[t].at(today) if t in price_step else 0.0
        ccy = tick_ccy.get(t, "USD")
        val_pln = to_pln(sh * cur_price, ccy, today)
        # koszt = realnie wydane pieniądze przeliczone kursem z dnia zakupu — tak jak XTB
        cost_pln = sum(
            to_pln(l[2], parsed["accounts"].get(l[3], "PLN"), l[4]) for l in open_lots)
        q = quotes.get(t)
        positions.append({
            "ticker": t, "name": parsed["names"].get(t, t), "shares": round(sh, 6),
            "currency": ccy, "avg_open": round(avg_open, 4), "price": round(cur_price, 4),
            "value_pln": round(val_pln, 2),
            "cost_pln": round(cost_pln, 2),
            "pl_pln": round(val_pln - cost_pln, 2),
            "pl_pct": round((val_pln / cost_pln - 1) * 100, 2) if cost_pln > 1e-9 else 0.0,
            "no_price": t not in price_step,
            # znacznik czasu notowania — na jego podstawie UI pokazuje świeżość wyceny
            "quote_ts": q["ts"] if q else None,
        })
    positions.sort(key=lambda p: -p["value_pln"])

    # --- XIRR na przepływach zewnętrznych + wartość końcowa ---
    xirr = _xirr(
        [(f["date"], -f["amount_pln"]) for f in flow_list] + [(today, values[-1])]
    ) if flow_list and values[-1] > 0 else None

    deposits = sum(f["amount_pln"] for f in flow_list if f["amount_pln"] > 0)
    withdrawals = -sum(f["amount_pln"] for f in flow_list if f["amount_pln"] < 0)

    # --- koszty: zapłacone (zmierzone z historii) i wyjścia (policzone z profilu) ---
    cash_list = [(a, parsed["accounts"][a], cash_step[a].at(today))
                 for a in parsed["accounts"] if a in cash_step]
    paid = fees.measure(parsed["ops"], parsed["accounts"], to_pln)
    exit_cost = fees.exit_costs(
        positions, cash_list, pos_account, cfg,
        lambda ccy: fx_step.get(ccy, fx_step["PLN"]).at(today))
    value_net = round(values[-1] - exit_cost["total_pln"], 2)
    values_net[-1] = value_net   # ostatni punkt liczony z żywych cen, nie ze schodków

    # koszt wyjścia rozbity na pozycje — dzięki temu każdy wiersz może pokazać wynik
    # „po kosztach". Koszty WEJŚCIA są już w cost_pln (to realnie wydane pieniądze),
    # więc odejmujemy wyłącznie to, co dopiero zapłacimy przy sprzedaży.
    for p in positions:
        cost_exit = exit_cost["by_position"].get(p["ticker"], 0.0)
        net_val = p["value_pln"] - cost_exit
        p["exit_cost_pln"] = cost_exit
        # Konto, na którym pozycja stoi (to samo, którego użyliśmy do kosztów
        # wyjścia). Sam widok portfela go nie potrzebuje — potrzebuje go podział
        # majątku na portfele, który bez tego przypisywał rachunkom zero i pokazywał
        # mieszkanie jako sto procent majątku człowieka mającego też akcje.
        p["account"] = pos_account.get(p["ticker"], "")
        p["value_net_pln"] = round(net_val, 2)
        p["pl_net_pln"] = round(net_val - p["cost_pln"], 2)
        p["pl_net_pct"] = (round((net_val / p["cost_pln"] - 1) * 100, 2)
                           if p["cost_pln"] > 1e-9 else 0.0)

    data = {
        "empty": False,
        "dates": dates, "values": values, "values_net": values_net,
        "invested": invested_series,
        "twr": twr, "flows": flow_list,
        "positions": positions, "price_warnings": price_warn,
        "accounts": [
            {"account": a, "currency": c,
             "cash": (round(cash_step[a].at(today), 2) or 0.0) if a in cash_step else 0.0,
             "broker": (acct_rows.get(a) or {}).get("broker") or "",
             "broker_label": cfg[a]["label"] if a in cfg else "",
             "fees_custom": bool(cfg.get(a, {}).get("custom"))}
            for a, c in parsed["accounts"].items()
        ],
        "costs": {"paid": paid, "exit": exit_cost,
                  "profiles": {a: cfg[a] for a in cfg}},
        "summary": {
            "value": values[-1],
            "deposits": round(deposits, 2),
            "withdrawals": round(withdrawals, 2),
            "net_invested": round(deposits - withdrawals, 2),
            "profit": round(values[-1] - (deposits - withdrawals), 2),
            "twr_total_pct": round((twr[-1] - 1) * 100, 2),
            "xirr_pct": round(xirr * 100, 2) if xirr is not None else None,
            # wartość po potrąceniu kosztów wyjścia — ile realnie zostałoby w kieszeni
            "exit_cost": exit_cost["total_pln"],
            "value_net": value_net,
            "profit_net": round(value_net - (deposits - withdrawals), 2),
            "fees_paid": paid["total_pln"],
        },
        "computed_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        "quotes": _quotes_freshness(quotes, positions),
    }
    return _zapisz_memo(key, data)


def holdings(days: list) -> dict:
    """Stan portfela na koniec każdego z podanych dni: akcje per ticker i gotówka per konto.

    Wykres śróddzienny dłuższy niż jedna sesja musi wiedzieć, ILE czego mieliśmy
    danego dnia — inaczej po zakupie w środku tygodnia poniedziałkowe punkty
    liczyłyby się dzisiejszą liczbą akcji. `compute()` zwraca tylko dzisiejszy stan,
    więc schodki odtwarzamy tu jeszcze raz (odczyt z SQLite, bez sieci).
    """
    parsed = _parse_ops()
    if not parsed or not days:
        return {}
    cash_step = {a: _Step(_cum(dl)) for a, dl in parsed["cash_delta"].items()}
    share_step = {t: _Step(_cum(dl)) for t, dl in parsed["share_delta"].items()}
    out = {}
    for d in days:
        shares = {}
        for t, st in share_step.items():
            sh = st.at(d)
            if abs(sh) > 1e-9:
                shares[t] = sh
        out[d] = {
            "shares": shares,
            "cash": [(a, parsed["accounts"].get(a, "PLN"), cash_step[a].at(d))
                     for a in cash_step],
        }
    return out


def _quotes_freshness(quotes: dict, positions: list) -> dict:
    """Podsumowanie świeżości wyceny — ile pozycji ma kurs „na żywo" i jak stary jest.

    Rynek uznajemy za otwarty, gdy najświeższe notowanie jest młodsze niż 5 minut
    (Yahoo aktualizuje kursy na bieżąco w trakcie sesji, a po zamknięciu zamiera).
    """
    now = _time.time()
    ts = [q["ts"] for q in quotes.values() if q.get("ts")]
    open_positions = [p for p in positions if not p["no_price"]]
    newest = max(ts) if ts else None
    oldest = min(ts) if ts else None
    return {
        "newest_ts": newest,
        "oldest_ts": oldest,
        "age_sec": int(now - newest) if newest else None,
        "stale_sec": int(now - oldest) if oldest else None,
        "live": len(ts),
        "total": len(open_positions),
        "market_open": bool(newest and now - newest < 300),
        "server_now": int(now),
    }


def _xirr(cashflows: list):
    """XIRR (roczna stopa) metodą bisekcji; cashflows = [(YYYY-MM-DD, kwota)]."""
    if len(cashflows) < 2:
        return None
    t0 = datetime.date.fromisoformat(cashflows[0][0])

    def npv(rate: float) -> float:
        s = 0.0
        for d, amt in cashflows:
            yrs = (datetime.date.fromisoformat(d) - t0).days / 365.25
            s += amt / ((1.0 + rate) ** yrs)
        return s

    lo, hi = -0.9999, 100.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9:
            break
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2
