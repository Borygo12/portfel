"""Alokacja premium: ryzyko, korelacje i symulator „co jeśli”.

Zwykła alokacja odpowiada na pytanie *z czego składa się portfel*. Tu liczymy, *co
z tego wynika* — a to wymaga historii notowań, nie tylko dzisiejszej wyceny.

Wszystko liczone na dziennych stopach zwrotu w PLN, bo w tej walucie właściciel
realnie mierzy wynik: spadek kursu dolara jest wtedy taką samą stratą jak spadek
notowania spółki, i tak samo widać go w wynikach.
"""

from __future__ import annotations

import datetime as _dt
import math

# Ile sesji bierzemy do liczenia zmienności i korelacji. Rok to kompromis: krócej
# łapie szum jednego kwartału, dłużej — spółkę, której już nie ma.
LOOKBACK_DAYS = 380
MIN_OVERLAP = 30          # mniej wspólnych sesji niż tyle = korelacja bez sensu
TRADING_DAYS = 252


# ------------------------------------------------------------ dane wejściowe


def _returns(ticker: str, since: str) -> dict[str, float]:
    """Dzienne stopy zwrotu w walucie notowania: {data: zmiana}."""
    from portfolio import prices as pf_prices
    series, _cur = pf_prices.price_series(ticker, since)
    if not series or len(series) < 5:
        return {}
    days = sorted(series)
    out = {}
    prev = series[days[0]]
    for d in days[1:]:
        cur = series[d]
        if prev and cur and prev > 0:
            out[d] = cur / prev - 1.0
        prev = cur or prev
    return out


def _fx_returns(currency: str, since: str) -> dict[str, float]:
    """Dzienne zmiany kursu waluty do złotego."""
    if not currency or currency == "PLN":
        return {}
    from portfolio import prices as pf_prices
    series = pf_prices.fx_series(currency, since)
    if not series or len(series) < 5:
        return {}
    days = sorted(series)
    out, prev = {}, series[days[0]]
    for d in days[1:]:
        cur = series[d]
        if prev and cur and prev > 0:
            out[d] = cur / prev - 1.0
        prev = cur or prev
    return out


def _pln_returns(positions: list, since: str) -> dict[str, dict[str, float]]:
    """Stopy zwrotu każdej pozycji przeliczone na złotówki.

    (1+r_waloru)·(1+r_kursu)−1 — kurs waluty jest częścią wyniku, nie dodatkiem obok.
    """
    fx_cache: dict[str, dict] = {}
    out = {}
    for p in positions:
        tkr = p["ticker"]
        base = _returns(tkr, since)
        if not base:
            continue
        cur = (p.get("currency") or "PLN").upper()
        if cur != "PLN":
            if cur not in fx_cache:
                fx_cache[cur] = _fx_returns(cur, since)
            fx = fx_cache[cur]
            if fx:
                base = {d: (1 + r) * (1 + fx.get(d, 0.0)) - 1 for d, r in base.items()}
        out[tkr] = base
    return out


def _since() -> str:
    return (_dt.date.today() - _dt.timedelta(days=LOOKBACK_DAYS)).isoformat()


# ------------------------------------------------------------------- miary


def _hhi(weights: list[float]) -> float:
    """Wskaźnik Herfindahla–Hirschmana na udziałach 0–1. 1 = wszystko w jednym."""
    return sum(w * w for w in weights)


def _stdev(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def _cov(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    ma, mb = sum(a[:n]) / n, sum(b[:n]) / n
    return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / (n - 1)


def _max_drawdown(returns: list[float]) -> float | None:
    """Największe obsunięcie odtworzone ze stóp zwrotu (liczba dodatnia, w procentach)."""
    if len(returns) < 5:
        return None
    value, peak, worst = 1.0, 1.0, 0.0
    for r in returns:
        value *= (1 + r)
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return round(abs(worst) * 100, 2)


def _corr(a: list[float], b: list[float]) -> float | None:
    sa, sb = _stdev(a), _stdev(b)
    if sa <= 0 or sb <= 0:
        return None
    return max(-1.0, min(1.0, _cov(a, b) / (sa * sb)))


# ---------------------------------------------------------------- rentgen


def risk(data: dict, cash_pln: float = 0.0) -> dict:
    """Pełny rentgen ryzyka portfela.

    `data` to wynik `portfolio.engine.compute()`. Gotówka wchodzi do wag (obniża
    ryzyko całości), ale nie ma własnej zmienności.
    """
    positions = [p for p in data.get("positions", []) if not p.get("no_price")]
    if not positions:
        return {"empty": True}

    total = sum(p["value_pln"] for p in positions) + max(0.0, cash_pln)
    if total <= 0:
        return {"empty": True}

    weights = {p["ticker"]: p["value_pln"] / total for p in positions}
    cash_w = max(0.0, cash_pln) / total

    # ---- koncentracja
    ws = sorted(weights.values(), reverse=True)
    hhi = _hhi(ws + ([cash_w] if cash_w > 0 else []))
    effective_n = (1.0 / hhi) if hhi > 0 else 0.0

    # ---- zmienność i wkład w ryzyko
    rets = _pln_returns(positions, _since())
    common = None
    for r in rets.values():
        common = set(r) if common is None else (common & set(r))
    dates = sorted(common or [])
    contrib, port_vol, port_series = [], 0.0, []

    if len(dates) >= MIN_OVERLAP and rets:
        cols = {t: [rets[t][d] for d in dates] for t in rets}
        port_series = [
            sum(weights.get(t, 0.0) * cols[t][i] for t in cols) for i in range(len(dates))
        ]
        port_vol = _stdev(port_series) * math.sqrt(TRADING_DAYS)

        var = _stdev(port_series) ** 2
        for p in positions:
            t = p["ticker"]
            if t not in cols:
                continue
            w = weights.get(t, 0.0)
            own_vol = _stdev(cols[t]) * math.sqrt(TRADING_DAYS)
            # wkład krańcowy: ile z wariancji portfela pochodzi z tej pozycji
            share = (w * _cov(cols[t], port_series) / var) if var > 0 else 0.0
            col = cols[t]
            downs = [x for x in col if x < 0]
            contrib.append({
                "ticker": t, "name": p.get("name", ""),
                "weight_pct": round(w * 100, 2),
                "vol_pct": round(own_vol * 100, 2),
                "risk_pct": round(share * 100, 2),
                # >1 = ta pozycja waży w ryzyku więcej, niż w pieniądzach
                "ratio": round(share / w, 2) if w > 0.0001 else None,
                # ile złotych wahań dziennie bierze na siebie ta pozycja
                "daily_pln": round(_stdev(col) * p["value_pln"], 2),
                "best_day_pct": round(max(col) * 100, 2) if col else None,
                "worst_day_pct": round(min(col) * 100, 2) if col else None,
                "up_days_pct": round(sum(1 for x in col if x > 0) / len(col) * 100, 1) if col else None,
                # zmienność liczona tylko z sesji spadkowych — to ona boli
                "downside_pct": round(_stdev(downs) * math.sqrt(TRADING_DAYS) * 100, 1)
                                if len(downs) > 2 else None,
                "value_pln": round(p["value_pln"], 2),
                "currency": (p.get("currency") or "PLN").upper(),
            })
        contrib.sort(key=lambda c: -c["risk_pct"])

    # ---- ekspozycja walutowa
    fx: dict[str, float] = {}
    for p in positions:
        cur = (p.get("currency") or "PLN").upper()
        fx[cur] = fx.get(cur, 0.0) + p["value_pln"]
    fx_rows = [{"currency": c, "value": round(v, 2), "pct": round(v / total * 100, 2)}
               for c, v in sorted(fx.items(), key=lambda kv: -kv[1])]
    foreign_pct = round(sum(r["pct"] for r in fx_rows if r["currency"] != "PLN"), 2)

    # ---- ostrzeżenia progowe
    warnings = []
    biggest = max(positions, key=lambda p: p["value_pln"])
    big_pct = biggest["value_pln"] / total * 100
    if big_pct > 20:
        warnings.append({
            "level": "warn" if big_pct < 35 else "alert",
            "text": f"{biggest['ticker']} to {big_pct:.1f}% portfela. "
                    "Powyżej 20% pojedyncza spółka zaczyna decydować o całym wyniku.",
        })
    if effective_n and effective_n < 5:
        warnings.append({
            "level": "warn",
            "text": f"Efektywnie stoisz na {effective_n:.1f} pozycji — mimo "
                    f"{len(positions)} w zestawieniu. Reszta jest zbyt mała, żeby cokolwiek zmienić.",
        })
    if foreign_pct > 70:
        warnings.append({
            "level": "warn",
            "text": f"{foreign_pct:.0f}% portfela pracuje w obcych walutach. "
                    "Umocnienie złotego obniży wynik nawet przy rosnących kursach spółek.",
        })
    if contrib and contrib[0]["risk_pct"] > 45:
        warnings.append({
            "level": "alert",
            "text": f"{contrib[0]['ticker']} odpowiada za {contrib[0]['risk_pct']:.0f}% "
                    "wahań portfela. To już nie jest portfel, to jedna pozycja z dodatkami.",
        })

    return {
        "empty": False,
        "total": round(total, 2),
        "cash_pct": round(cash_w * 100, 2),
        "positions": len(positions),
        "concentration": {
            "hhi": round(hhi, 4),
            "effective_n": round(effective_n, 2),
            "top1_pct": round(ws[0] * 100, 2) if ws else 0.0,
            "top3_pct": round(sum(ws[:3]) * 100, 2),
            "top5_pct": round(sum(ws[:5]) * 100, 2),
        },
        "volatility": {
            "annual_pct": round(port_vol * 100, 2) if port_vol else None,
            "daily_pct": round(_stdev(port_series) * 100, 3) if port_series else None,
            "sessions": len(dates),
            # przybliżenie: jednodniowa strata przekraczana raz na 20 sesji
            "var95_pln": round(1.645 * _stdev(port_series) * total, 2) if port_series else None,
            "best_day_pct": round(max(port_series) * 100, 2) if port_series else None,
            "worst_day_pct": round(min(port_series) * 100, 2) if port_series else None,
            "up_days_pct": round(sum(1 for x in port_series if x > 0) / len(port_series) * 100, 1)
                           if port_series else None,
            # zmienność samych spadków — dwa portfele o tej samej zmienności potrafią
            # się różnić tym, po której stronie ona siedzi
            "downside_pct": round(
                _stdev([x for x in port_series if x < 0]) * math.sqrt(TRADING_DAYS) * 100, 2)
                if len([x for x in port_series if x < 0]) > 2 else None,
            "max_dd_pct": _max_drawdown(port_series),
        },
        "risk_contribution": contrib,
        "currency": {"rows": fx_rows, "foreign_pct": foreign_pct},
        "warnings": warnings,
    }


# -------------------------------------------------------------- korelacje


def correlation(data: dict, limit: int = 14) -> dict:
    """Macierz korelacji największych pozycji — mniejsze i tak nic nie zmienią."""
    positions = [p for p in data.get("positions", []) if not p.get("no_price")]
    positions.sort(key=lambda p: -p["value_pln"])
    positions = positions[:max(2, limit)]
    if len(positions) < 2:
        return {"empty": True, "reason": "Do korelacji potrzeba co najmniej dwóch pozycji."}

    rets = _pln_returns(positions, _since())
    tickers = [p["ticker"] for p in positions if p["ticker"] in rets]
    if len(tickers) < 2:
        return {"empty": True, "reason": "Brak wystarczającej historii notowań."}

    matrix, pairs = [], []
    for a in tickers:
        row = []
        for b in tickers:
            if a == b:
                row.append(1.0)
                continue
            shared = sorted(set(rets[a]) & set(rets[b]))
            if len(shared) < MIN_OVERLAP:
                row.append(None)
                continue
            c = _corr([rets[a][d] for d in shared], [rets[b][d] for d in shared])
            row.append(round(c, 3) if c is not None else None)
        matrix.append(row)

    seen = set()
    for i, a in enumerate(tickers):
        for j, b in enumerate(tickers):
            if i >= j or matrix[i][j] is None:
                continue
            key = (a, b)
            if key in seen:
                continue
            seen.add(key)
            pairs.append({"a": a, "b": b, "corr": matrix[i][j]})

    vals = [p["corr"] for p in pairs]
    avg = sum(vals) / len(vals) if vals else None
    pairs.sort(key=lambda p: -p["corr"])

    verdict = None
    if avg is not None:
        if avg > 0.7:
            verdict = ("Twoje pozycje chodzą niemal jak jedna. Liczba spółek nie chroni "
                       "portfela, jeśli wszystkie reagują na to samo.")
        elif avg > 0.45:
            verdict = ("Umiarkowane powiązanie — typowe dla portfela skupionego na jednym "
                       "rynku. Dołożenie innej klasy aktywów wyraźnie obniżyłoby wahania.")
        else:
            verdict = "Pozycje są od siebie dość niezależne — dywersyfikacja realnie działa."

    # Średnia korelacja KAŻDEJ pozycji z resztą portfela. Najniższa wartość wskazuje
    # walor, który najbardziej chodzi własnym rytmem — czyli realnie dywersyfikuje.
    per_ticker = []
    for i, t in enumerate(tickers):
        vals_i = [matrix[i][j] for j in range(len(tickers)) if j != i and matrix[i][j] is not None]
        if not vals_i:
            continue
        mean_i = sum(vals_i) / len(vals_i)
        per_ticker.append({
            "ticker": t,
            "name": next((p.get("name", "") for p in positions if p["ticker"] == t), ""),
            "avg": round(mean_i, 3),
            "max": round(max(vals_i), 3),
            "min": round(min(vals_i), 3),
            "value_pln": next((round(p["value_pln"], 2) for p in positions if p["ticker"] == t), 0),
        })
    per_ticker.sort(key=lambda r: r["avg"])

    return {
        "empty": False,
        "tickers": tickers,
        "names": {p["ticker"]: p.get("name", "") for p in positions},
        "matrix": matrix,
        "avg": round(avg, 3) if avg is not None else None,
        "highest": pairs[:5],
        "lowest": pairs[-5:][::-1],
        "per_ticker": per_ticker,
        "diversifier": per_ticker[0] if per_ticker else None,
        "crowd": per_ticker[-1] if per_ticker else None,
        "sessions": len(sorted(set.intersection(*[set(rets[t]) for t in tickers]))) if tickers else 0,
        "verdict": verdict,
    }


# ----------------------------------------------------------- symulator


def what_if(data: dict, changes: list, cash_pln: float = 0.0) -> dict:
    """Portfel po hipotetycznych transakcjach — przed i po, obok siebie.

    `changes`: [{"ticker": "AAPL.US", "amount_pln": 5000}] — kwota dodatnia to dokupienie,
    ujemna to sprzedaż. Nieznany ticker traktujemy jako nową pozycję.
    """
    positions = [p for p in data.get("positions", []) if not p.get("no_price")]
    before = {p["ticker"]: p["value_pln"] for p in positions}
    names = {p["ticker"]: p.get("name", "") for p in positions}
    after = dict(before)
    cash_after = max(0.0, cash_pln)
    applied, rejected = [], []

    for ch in changes or []:
        tkr = str(ch.get("ticker") or "").strip().upper()
        try:
            amount = float(ch.get("amount_pln") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        if not tkr or abs(amount) < 0.01:
            continue
        have = after.get(tkr, 0.0)
        if amount < 0 and abs(amount) > have + 0.01:
            rejected.append({"ticker": tkr,
                             "why": f"Masz tam {have:,.0f} zł — nie da się sprzedać za więcej."})
            amount = -have
        after[tkr] = max(0.0, have + amount)
        cash_after -= amount
        applied.append({"ticker": tkr, "amount_pln": round(amount, 2)})

    after = {t: v for t, v in after.items() if v > 0.01}
    if cash_after < -0.01:
        rejected.append({"ticker": "", "why": "Symulacja schodzi poniżej zera gotówki — "
                                              "w praktyce trzeba by najpierw coś sprzedać."})

    def snapshot(vals: dict, cash: float) -> dict:
        total = sum(vals.values()) + max(0.0, cash)
        if total <= 0:
            return {"total": 0.0, "rows": [], "hhi": 0.0, "effective_n": 0.0, "top1_pct": 0.0}
        ws = [v / total for v in vals.values()] + ([max(0.0, cash) / total] if cash > 0 else [])
        hhi = _hhi(ws)
        rows = sorted(
            ({"ticker": t, "name": names.get(t, ""), "value": round(v, 2),
              "pct": round(v / total * 100, 2)} for t, v in vals.items()),
            key=lambda r: -r["value"])
        return {
            "total": round(total, 2),
            "cash": round(max(0.0, cash), 2),
            "rows": rows,
            "hhi": round(hhi, 4),
            "effective_n": round(1.0 / hhi, 2) if hhi > 0 else 0.0,
            "top1_pct": rows[0]["pct"] if rows else 0.0,
        }

    a, b = snapshot(before, cash_pln), snapshot(after, cash_after)
    return {
        "empty": not before and not after,
        "before": a,
        "after": b,
        "applied": applied,
        "rejected": rejected,
        "delta": {
            "effective_n": round(b["effective_n"] - a["effective_n"], 2),
            "top1_pct": round(b["top1_pct"] - a["top1_pct"], 2),
            "hhi": round(b["hhi"] - a["hhi"], 4),
        },
    }
