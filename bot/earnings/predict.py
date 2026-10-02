"""Rynki predykcyjne — co obstawiają ludzie, którzy kładą na to pieniądze.

Prognoza analityków mówi „spodziewamy się 0,3%". Rynek predykcyjny mówi więcej:
jak rozkłada się prawdopodobieństwo wokół tej liczby i czy ktoś na serio liczy się
z niespodzianką. Dwa źródła, oba publiczne i bez klucza:

  * **Kalshi** — amerykańska regulowana giełda kontraktów na wydarzenia. Ma osobne
    serie na decyzje Fed, inflację, rynek pracy i PKB.
  * **Polymarket** — największy rynek na decyzje Fed (obroty rzędu dziesiątek mln USD).

Pokrywamy wyłącznie dane z USA, bo tylko na nie istnieją płynne rynki. Dla reszty
kalendarza funkcja zwraca pustą listę i sekcja w aplikacji po prostu się nie pojawia.

Kontrakty progowe („inflacja powyżej 0,3%") przeliczamy na rozkład: szansa, że
odczyt wyląduje w danym przedziale, to różnica cen dwóch sąsiednich progów.
"""

import datetime as dt
import json
import logging
import re

import requests

from . import cache

log = logging.getLogger("earnings.predict")

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
POLY = "https://gamma-api.polymarket.com"
TTL = 600

_session = requests.Session()
_session.headers.update(cache.UA)

# (wzorzec nazwy z kalendarza, seria Kalshi, rodzaj skali). Kolejność ma znaczenie:
# warianty bazowe („ex Food & Energy") muszą wygrać z ogólnym CPI.
_SERIES = [
    (re.compile(r"consumer price index ex food & energy \(mom\)", re.I), "KXCPICORE", "pct"),
    (re.compile(r"consumer price index ex food & energy \(yoy\)", re.I), "KXCPICOREYOY", "pct"),
    (re.compile(r"^consumer price index \(mom\)", re.I), "KXCPI", "pct"),
    (re.compile(r"^consumer price index \(yoy\)", re.I), "KXCPIYOY", "pct"),
    (re.compile(r"^nonfarm payrolls", re.I), "KXPAYROLLS", "k"),
    (re.compile(r"^unemployment rate", re.I), "KXU3", "pct"),
    (re.compile(r"^gross domestic product annualized", re.I), "KXGDP", "pct"),
    (re.compile(r"core personal consumption expenditures.*\(mom\)", re.I), "KXPCECORE", "pct"),
    (re.compile(r"^initial jobless claims$", re.I), "KXJOBLESSCLAIMS", "k"),
]

# decyzja, komunikat i konferencja tego samego dnia to jedno posiedzenie
_FED = re.compile(r"fed interest rate decision|fomc (statement|press conference|"
                  r"economic projections)|fed('s)? monetary policy statement|"
                  r"interest rate projections", re.I)

_FED_PL = [
    (re.compile(r"cut\s*>\s*25|50\+?\s*bps decrease", re.I), "Cięcie o 50 pb lub więcej", -2),
    (re.compile(r"cut\s*25|25\s*bps decrease", re.I), "Cięcie o 25 pb", -1),
    (re.compile(r"maintain|no change", re.I), "Bez zmian", 0),
    (re.compile(r"hike\s*>\s*25|50\+?\s*bps increase", re.I), "Podwyżka o 50 pb lub więcej", 2),
    (re.compile(r"hike\s*25|25\+?\s*bps increase", re.I), "Podwyżka o 25 pb", 1),
]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _price(m: dict):
    """Szansa „tak" z arkusza zleceń. Środek widełek, gdy są wąskie; inaczej
    ostatnia transakcja — przy szerokich widełkach środek nic nie znaczy."""
    bid, ask, last = _f(m.get("yes_bid_dollars")), _f(m.get("yes_ask_dollars")), \
        _f(m.get("last_price_dollars"))
    if bid is not None and ask is not None and ask - bid <= 0.12:
        return (bid + ask) / 2
    if last:
        return last
    if bid is not None and ask is not None:
        return (bid + ask) / 2
    return None


def _kalshi_events(series: str) -> list:
    def build():
        r = _session.get(f"{KALSHI}/events", params={
            "series_ticker": series, "status": "open",
            "with_nested_markets": "true", "limit": 6}, timeout=20)
        r.raise_for_status()
        out = []
        for e in r.json().get("events") or []:
            markets = [{
                "label": m.get("yes_sub_title") or m.get("subtitle") or "",
                "strike": m.get("floor_strike"),
                "type": m.get("strike_type") or "",
                "prob": _price(m),
                "close": m.get("close_time") or "",
                "volume": _f(m.get("volume_fp")) or 0,
            } for m in e.get("markets") or []]
            if markets:
                out.append({"ticker": e.get("event_ticker") or "",
                            "title": e.get("title") or "", "markets": markets})
        return out

    return cache.cached(f"kalshi-{series}", TTL, build) or []


def _ts(iso: str):
    try:
        return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def _pick(events: list, ts: float, tolerance_h: float = 40):
    """Wydarzenie Kalshi, którego rynki zamykają się tuż przed tą publikacją."""
    best, gap = None, tolerance_h * 3600
    for e in events:
        close = _ts(e["markets"][0]["close"])
        if close is None:
            continue
        d = abs(close - ts)
        if d < gap:
            best, gap = e, d
    return best


def _num(v: float, digits: int = 1) -> str:
    return f"{v:.{digits}f}".replace(".", ",").replace("-", "−")


def _label(lo, hi, scale: str, step: float, inclusive_low: bool) -> str:
    """Podpis przedziału między dwoma progami."""
    if scale == "k":
        f = lambda v: _num(v / 1000, 0)   # noqa: E731
        if lo is None:
            return f"poniżej {f(hi)} tys." if inclusive_low else f"{f(hi)} tys. lub mniej"
        if hi is None:
            return f"{f(lo)} tys. lub więcej" if inclusive_low else f"powyżej {f(lo)} tys."
        return f"{f(lo)}–{f(hi)} tys."
    digits = 2 if step < 0.1 - 1e-9 else 1
    f = lambda v: _num(v, digits)   # noqa: E731
    if lo is None:
        return f"{f(hi)}% lub mniej"
    if hi is None:
        return f"powyżej {f(lo)}%"
    # odczyty publikuje się z jednym miejscem po przecinku, więc przy progach co 0,1
    # przedział (0,2; 0,3] to po prostu „dokładnie 0,3"
    if abs(step - 0.1) < 1e-9:
        return f"{f(hi)}%"
    return f"{f(lo)}–{f(hi)}%"


def _distribution(markets: list, scale: str) -> dict | None:
    """Progi „powyżej X" → rozkład po przedziałach + mediana."""
    rows = sorted((m for m in markets if m["strike"] is not None and m["prob"] is not None),
                  key=lambda m: m["strike"])
    if len(rows) < 3:
        return None
    inclusive = rows[0]["type"] == "greater_or_equal"
    strikes = [float(m["strike"]) for m in rows]
    probs = []
    low = 1.0
    for m in rows:                       # szansa „powyżej" nie może rosnąć z progiem
        low = min(low, max(0.0, min(1.0, m["prob"])))
        probs.append(low)
    step = min(b - a for a, b in zip(strikes, strikes[1:])) or 1.0

    buckets = [{"lo": None, "hi": strikes[0], "p": 1 - probs[0]}]
    for i in range(len(rows) - 1):
        buckets.append({"lo": strikes[i], "hi": strikes[i + 1], "p": probs[i] - probs[i + 1]})
    buckets.append({"lo": strikes[-1], "hi": None, "p": probs[-1]})

    median = None
    for i in range(len(rows) - 1):
        if probs[i] >= 0.5 > probs[i + 1]:
            if scale == "pct" and abs(step - 0.1) < 1e-9:
                # odczyt ma jedno miejsce po przecinku: „powyżej 0,5" to 0,6 i więcej
                median = strikes[i + 1]
            else:
                span = probs[i] - probs[i + 1]
                median = strikes[i] + (strikes[i + 1] - strikes[i]) * (
                    (probs[i] - 0.5) / span if span else 0)
            break

    # Pokazujemy okno pięciu sąsiednich przedziałów, w którym siedzi najwięcej
    # prawdopodobieństwa, a oba ogony zwijamy w „…lub mniej" i „powyżej…". Wyrzucanie
    # mało prawdopodobnych przedziałów ze środka zostawiało dziury w skali.
    width = min(5, len(buckets))
    start = max(range(len(buckets) - width + 1),
                key=lambda i: sum(b["p"] for b in buckets[i:i + width]))
    window = buckets[start:start + width]
    below = sum(b["p"] for b in buckets[:start])
    above = sum(b["p"] for b in buckets[start + width:])
    if below >= 0.015 and window[0]["lo"] is not None:
        window.insert(0, {"lo": None, "hi": window[0]["lo"], "p": below})
    if above >= 0.015 and window[-1]["hi"] is not None:
        window.append({"lo": window[-1]["hi"], "hi": None, "p": above})
    outcomes = [{
        "label": _label(b["lo"], b["hi"], scale, step, inclusive),
        "prob": round(b["p"] * 100, 1),
        "value": b["hi"] if b["hi"] is not None else b["lo"],
    } for b in window if b["p"] >= 0.005]
    if not outcomes:
        return None
    top = max(outcomes, key=lambda o: o["prob"])
    for o in outcomes:
        o["top"] = o is top
    median_fmt = ""
    if median is not None:
        median_fmt = (f"{_num(median / 1000, 0)} tys." if scale == "k"
                      else f"{_num(median, 1 if abs(step - 0.1) < 1e-9 else 2)}%")
    return {"outcomes": outcomes, "median_fmt": median_fmt}


def _fed_outcomes(pairs: list) -> list:
    """[(etykieta źródła, szansa 0–1)] → wiersze po polsku, od cięcia do podwyżki."""
    out = {}
    for label, prob in pairs:
        if prob is None:
            continue
        for rx, pl, order in _FED_PL:
            if rx.search(label or ""):
                cur = out.setdefault(order, {"label": pl, "prob": 0.0, "value": order})
                cur["prob"] += prob * 100
                break
    rows = [out[k] for k in sorted(out)]
    total = sum(r["prob"] for r in rows)
    if not rows or total <= 0:
        return []
    for r in rows:
        # ceny kilku kontraktów nie sumują się dokładnie do 100 — wyrównujemy
        r["prob"] = round(r["prob"] / total * 100, 1)
    top = max(rows, key=lambda r: r["prob"])
    for r in rows:
        r["top"] = r is top
    return [r for r in rows if r["prob"] >= 0.5 or r["top"]]


def _money(v: float) -> str:
    if v >= 1e6:
        return f"{_num(v / 1e6, 1)} mln USD"
    if v >= 1e3:
        return f"{_num(v / 1e3, 0)} tys. USD"
    return ""


def _fed(ts: float) -> list:
    out = []
    try:
        ev = _pick(_kalshi_events("KXFEDDECISION"), ts)
        if ev:
            rows = _fed_outcomes([(m["label"], m["prob"]) for m in ev["markets"]])
            if rows:
                out.append({"source": "Kalshi", "title": "Decyzja Fed na tym posiedzeniu",
                            "url": "https://kalshi.com/markets/kxfeddecision",
                            "outcomes": rows, "median_fmt": "", "volume_fmt": ""})
    except Exception as e:  # noqa: BLE001
        log.debug("Kalshi Fed: %s", e)

    try:
        def build():
            r = _session.get(f"{POLY}/public-search",
                             params={"q": "fed decision", "limit_per_type": 8}, timeout=20)
            r.raise_for_status()
            rows = []
            for e in r.json().get("events") or []:
                if e.get("closed") or not re.match(r"fed decision in", e.get("title") or "", re.I):
                    continue
                pairs = []
                for m in e.get("markets") or []:
                    try:
                        prices = json.loads(m.get("outcomePrices") or "[]")
                        pairs.append([m.get("groupItemTitle") or "", float(prices[0])])
                    except (ValueError, IndexError, TypeError):
                        continue
                rows.append({"end": e.get("endDate") or "", "slug": e.get("slug") or "",
                             "volume": _f(e.get("volume")) or 0, "pairs": pairs})
            return rows

        for e in cache.cached("poly-fed", TTL, build) or []:
            end = _ts(e["end"])
            # rynek rozlicza się kilka–kilkanaście godzin po komunikacie
            if end is None or not (-6 * 3600 <= end - ts <= 40 * 3600):
                continue
            rows = _fed_outcomes(e["pairs"])
            if rows:
                out.append({"source": "Polymarket", "title": "Decyzja Fed na tym posiedzeniu",
                            "url": f"https://polymarket.com/event/{e['slug']}",
                            "outcomes": rows, "median_fmt": "",
                            "volume_fmt": _money(e["volume"])})
            break
    except Exception as e:  # noqa: BLE001
        log.debug("Polymarket Fed: %s", e)
    return out


def markets(name: str, country: str, ts) -> list:
    """Rynki predykcyjne dla wydarzenia z kalendarza. Pusta lista = nie ma takiego rynku."""
    if (country or "").upper() != "US" or not ts:
        return []
    if _FED.search(name or ""):
        return _fed(float(ts))
    for rx, series, scale in _SERIES:
        if not rx.search(name or ""):
            continue
        try:
            ev = _pick(_kalshi_events(series), float(ts))
            dist = _distribution(ev["markets"], scale) if ev else None
        except Exception as e:  # noqa: BLE001
            log.debug("Kalshi %s: %s", series, e)
            return []
        if not dist:
            return []
        return [{"source": "Kalshi", "title": ev["title"],
                 "url": f"https://kalshi.com/markets/{series.lower()}",
                 "outcomes": dist["outcomes"], "median_fmt": dist["median_fmt"],
                 # Kalshi podaje obrót w kontraktach, nie w dolarach — nie udajemy kwoty
                 "volume_fmt": ""}]
    return []
