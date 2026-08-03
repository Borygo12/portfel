"""Prześwietlenie ETF-ów: skład, sektory, koszty, ryzyko i wyniki.

Skąd co pochodzi:
  * etykiety (region, sektor, opis po ludzku)  — nasz katalog, `catalog.py`
  * skład, sektory, opłata roczna, aktywa       — Yahoo `quoteSummary`
  * notowania, zmienność, obsunięcia            — `portfolio.prices`, ten sam cache
                                                  co reszta portfela

Zasada wydajnościowa: lista funduszy NIE czeka na sieć. Zwracamy to, co już jest
w pamięci, resztę dociągamy w tle i oznaczamy `pending`. Aplikacja rysuje szkielet
i wraca po dane za chwilę — dokładnie tak, jak działa kalendarz wyników.
"""

from __future__ import annotations

import datetime as _dt
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from . import catalog as cat

log = logging.getLogger("etf")

SUMMARY_TTL = 12 * 3600      # skład funduszu zmienia się raz na jakiś czas
ROW_TTL = 30 * 60            # cena i wynik na liście
LOOKBACK_DAYS = 400

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}
_inflight: set[str] = set()
_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="etf")

MODULES = ("topHoldings,fundProfile,fundPerformance,defaultKeyStatistics,"
           "price,summaryDetail,assetProfile")


# ------------------------------------------------------------------ Yahoo

def _quote_summary(symbol: str) -> dict:
    """Surowy quoteSummary dla funduszu. Korzysta z sesji i crumba z market.py,
    żeby nie utrzymywać drugiego kompletu ciasteczek.

    Symbol przepuszczamy przez mapowanie z `prices` — do skanera wchodzą tickery
    Yahoo, ale z portfela i listy obserwowanych przychodzą tickery XTB („BTEC.DE"),
    których quoteSummary nie zna.
    """
    from portfolio import market as m
    from portfolio import prices as pf
    symbol = pf.resolved_symbol(symbol) or symbol
    for attempt in (0, 1):
        crumb = m._get_crumb(force=bool(attempt))
        if not crumb:
            return {}
        try:
            r = m._session.get(
                f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/"
                f"{requests.utils.quote(symbol)}?modules={MODULES}"
                f"&crumb={requests.utils.quote(crumb)}", timeout=15)
            if r.status_code == 401 and attempt == 0:
                continue
            if r.status_code != 200:
                return {}
            res = (r.json().get("quoteSummary") or {}).get("result") or []
            return res[0] if res else {}
        except Exception as e:                                   # noqa: BLE001
            log.warning("quoteSummary %s: %s", symbol, e)
            if attempt:
                return {}
    return {}


def _raw(node, key, default=None):
    v = (node or {}).get(key)
    if isinstance(v, dict):
        v = v.get("raw")
    return v if isinstance(v, (int, float)) else default


# ------------------------------------------------------------- notowania

def _quotes(symbol: str) -> tuple[dict[str, float], str]:
    """Dzienne zamknięcia z cache portfela ({data: cena}) i waluta.

    UWAGA: `prices.price_series` sam przelicza pensy na funty (GBp -> GBP), więc
    ceny stąd są już znormalizowane — nie wolno dzielić ich drugi raz. Surowe pensy
    przychodzą tylko z `quoteSummary` i tylko tam robimy korektę.
    """
    from portfolio import prices as pf
    since = (_dt.date.today() - _dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
    try:
        ser, cur = pf.price_series(symbol, since)
        return ser or {}, cur or ""
    except Exception as e:                                       # noqa: BLE001
        log.warning("price_series %s: %s", symbol, e)
        return {}, ""


def _series(symbol: str) -> dict[str, float]:
    return _quotes(symbol)[0]


def _returns(series: dict) -> list[float]:
    days = sorted(series)
    out, prev = [], series[days[0]] if days else 0
    for d in days[1:]:
        cur = series[d]
        if prev and cur and prev > 0:
            out.append(cur / prev - 1.0)
        prev = cur or prev
    return out


def _stdev(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def _max_drawdown(series: dict) -> float:
    """Największy spadek od szczytu do dołka, w procentach. Liczba dodatnia."""
    days = sorted(series)
    peak, worst = 0.0, 0.0
    for d in days:
        v = series[d]
        if v > peak:
            peak = v
        if peak > 0:
            worst = min(worst, v / peak - 1.0)
    return abs(worst) * 100


def _change_over(series: dict, days_back: int) -> float | None:
    days = sorted(series)
    if len(days) < 2:
        return None
    last = series[days[-1]]
    target = (_dt.date.fromisoformat(days[-1]) - _dt.timedelta(days=days_back)).isoformat()
    older = [d for d in days if d <= target]
    if not older or not last:
        return None
    base = series[older[-1]]
    return (last / base - 1.0) * 100 if base else None


# ------------------------------------------------------------------ ryzyko

RISK_LEVELS = [
    (8, 1, "Bardzo spokojny", "Wahania rzędu obligacji. Nie zbuduje majątku, ale i nie zabierze snu."),
    (14, 2, "Spokojny", "Typowo szeroki rynek z domieszką obligacji albo fundusz mocno zdywersyfikowany."),
    (20, 3, "Umiarkowany", "Poziom typowy dla szerokiego rynku akcji. Spadek o kilkanaście procent w roku jest normalny."),
    (30, 4, "Wysoki", "Wąska branża albo mocna koncentracja. Trzeba umieć wytrzymać obsunięcie rzędu jednej trzeciej."),
    (999, 5, "Bardzo wysoki", "Zmienność na poziomie pojedynczych spółek albo krypto. Tylko jako mała część portfela."),
]


def _risk(vol_pct: float | None, dd_pct: float | None, top10: float | None) -> dict:
    if vol_pct is None:
        return {"score": None, "label": "Brak danych", "desc": "Za mało historii notowań, żeby ocenić ryzyko.",
                "vol_pct": None, "max_dd_pct": dd_pct, "notes": []}
    score, label, desc = 3, "Umiarkowany", ""
    for limit, sc, lab, dsc in RISK_LEVELS:
        if vol_pct < limit:
            score, label, desc = sc, lab, dsc
            break

    notes = []
    if dd_pct and dd_pct > 25:
        notes.append(f"W ciągu ostatniego roku fundusz tracił w szczytowym momencie "
                     f"{dd_pct:.0f}% od górki. Tyle trzeba było przetrzymać, żeby doczekać odbicia.")
    if top10 and top10 > 55:
        notes.append(f"Dziesięć największych pozycji to {top10:.0f}% funduszu — mimo setek spółek "
                     "w składzie o wyniku decyduje garstka.")
    elif top10 and top10 < 20:
        notes.append(f"Dziesięć największych pozycji to tylko {top10:.0f}% funduszu — "
                     "ryzyko jest realnie rozłożone.")
    return {"score": score, "label": label, "desc": desc,
            "vol_pct": round(vol_pct, 1), "max_dd_pct": round(dd_pct, 1) if dd_pct else None,
            "notes": notes}


# ---------------------------------------------------------------- sektory

SECTOR_PL = {
    "technology": ("Technologia", "Oprogramowanie, sprzęt i półprzewodniki. Najszybciej rosnąca i najbardziej zmienna część rynku."),
    "financial_services": ("Finanse", "Banki, ubezpieczyciele, giełdy. Zarabiają więcej przy wysokich stopach procentowych."),
    "healthcare": ("Ochrona zdrowia", "Farmacja, sprzęt medyczny, ubezpieczenia zdrowotne. Ludzie chorują niezależnie od koniunktury."),
    "consumer_cyclical": ("Dobra cykliczne", "Motoryzacja, moda, turystyka — rzeczy kupowane wtedy, gdy ludziom się dobrze powodzi."),
    "consumer_defensive": ("Dobra podstawowe", "Żywność, chemia domowa, handel spożywczy. Kupujemy je nawet w kryzysie."),
    "communication_services": ("Komunikacja i media", "Telekomy, platformy społecznościowe, rozrywka."),
    "industrials": ("Przemysł", "Maszyny, lotnictwo, transport, budownictwo. Chodzi razem z gospodarką."),
    "energy": ("Energia", "Wydobycie i przerób ropy oraz gazu. Kurs idzie za ceną surowca, nie za giełdą."),
    "basic_materials": ("Surowce i materiały", "Górnictwo, chemia, metale, papier — początek każdego łańcucha produkcji."),
    "utilities": ("Usługi komunalne", "Prąd, gaz, woda. Regulowane ceny, stabilne dywidendy, wrażliwość na stopy."),
    "realestate": ("Nieruchomości", "Właściciele biur, magazynów i galerii. Zarabiają na czynszach."),
}


def _countries(holdings: list[dict]) -> list[dict]:
    """Rozbicie geograficzne wyliczone z giełd, na których notowane są pozycje.

    Yahoo nie podaje dla ETF-ów kraju — ale sufiks tickera mówi, gdzie spółka jest
    notowana, a to dokładnie ta ekspozycja, którą bierze na siebie inwestor.
    Procenty normalizujemy do sumy rozpoznanych pozycji, żeby dodawały się do 100.
    """
    agg: dict[str, float] = {}
    known = 0.0
    for h in holdings:
        code = cat.country_of(h.get("symbol", ""))
        if not code:
            continue
        agg[code] = agg.get(code, 0.0) + float(h.get("pct") or 0)
        known += float(h.get("pct") or 0)
    if known <= 0:
        return []
    rows = []
    for code, pct in sorted(agg.items(), key=lambda kv: -kv[1]):
        name, flag = cat.country_label(code)
        rows.append({"code": code, "name": name, "flag": flag,
                     "pct": round(pct / known * 100, 1)})
    return rows[:6]


#: regiony z katalogu, które są jednym krajem — dla nich znamy odpowiedź bez składu
_SINGLE_COUNTRY_REGION = {"poland": "PL", "usa": "US"}


def _region_country(meta: dict) -> list[dict]:
    """Awaryjne rozbicie krajowe dla funduszy, dla których Yahoo nie oddaje składu.

    Dotyczy głównie ETF-ów z GPW. Region mamy we własnym katalogu, więc przy
    funduszu jednego kraju odpowiedź jest znana i nie ma powodu zostawiać pustki.
    """
    code = _SINGLE_COUNTRY_REGION.get(meta.get("region") or "")
    if not code:
        return []
    name, flag = cat.country_label(code)
    return [{"code": code, "name": name, "flag": flag, "pct": 100.0}]


def _sector_rows(weights: dict[str, float]) -> list[dict]:
    """Lista sektorów z gotowych udziałów (klucz w konwencji Yahoo -> procent)."""
    rows = []
    for key, pct in weights.items():
        if not pct:
            continue
        label, desc = SECTOR_PL.get(key, (key.replace("_", " ").capitalize(), ""))
        rows.append({"id": key, "label": label, "desc": desc, "pct": round(pct, 2)})
    rows.sort(key=lambda r: -r["pct"])
    return rows


def _sectors(top: dict) -> list[dict]:
    rows = []
    for entry in (top.get("sectorWeightings") or []):
        for key, val in entry.items():
            pct = val.get("raw") if isinstance(val, dict) else None
            if not isinstance(pct, (int, float)) or pct <= 0:
                continue
            label, desc = SECTOR_PL.get(key, (key.replace("_", " ").capitalize(), ""))
            rows.append({"id": key, "label": label, "desc": desc, "pct": round(pct * 100, 2)})
    rows.sort(key=lambda r: -r["pct"])
    return rows


# ------------------------------------------------- polskie ETF-y (skład)
#
# Yahoo dla funduszy z GPW oddaje samą cenę — ani składu, ani sektorów, ani opłaty.
# Skład indeksu mamy więc we własnym katalogu, a wagi liczymy z bieżącej kapitalizacji
# spółek, z limitem udziału jednej firmy (tak działają metodyki WIG). To szacunek
# i tak jest podpisany w aplikacji — ale odpowiada na pytanie „co ja właściwie kupuję",
# na które karta polskiego ETF-a wcześniej milczała.

def _market_caps(tickers: list[str]) -> dict[str, float]:
    """Kapitalizacje spółek z Yahoo, hurtem. Nieznane symbole po prostu wypadają."""
    from portfolio import market as m
    out: dict[str, float] = {}
    for i in range(0, len(tickers), 25):
        chunk = tickers[i:i + 25]
        for attempt in (0, 1):
            crumb = m._get_crumb(force=bool(attempt))
            if not crumb:
                return out
            try:
                r = m._session.get(
                    "https://query2.finance.yahoo.com/v7/finance/quote"
                    f"?symbols={requests.utils.quote(','.join(chunk))}"
                    f"&crumb={requests.utils.quote(crumb)}", timeout=15)
                if r.status_code == 401 and attempt == 0:
                    continue
                if r.status_code != 200:
                    break
                for q in ((r.json().get("quoteResponse") or {}).get("result") or []):
                    cap = q.get("marketCap")
                    if isinstance(cap, (int, float)) and cap > 0:
                        out[q.get("symbol") or ""] = float(cap)
                break
            except Exception as e:                               # noqa: BLE001
                log.warning("quote batch: %s", e)
                if attempt:
                    return out
    return out


def _capped_weights(caps: list[float], cap: float, covers: float = 1.0) -> list[float]:
    """Udziały z kapitalizacji, z limitem na jedną spółkę (tak liczą indeksy WIG).

    `covers` to szacowana część indeksu, którą pokrywa nasza lista spółek — przy
    mWIG40 i sWIG80 znamy największe firmy, nie cały ogon. Dzięki temu wagi liczą się
    względem CAŁEGO indeksu, a nie tylko znanego wycinka; reszta ląduje w wierszu
    „pozostałe spółki". Nadwyżki ponad limit celowo NIE rozdzielamy dalej — wolimy
    udział lekko zaniżony niż zmyślony.
    """
    total = sum(caps) / max(covers, 0.05)
    if total <= 0:
        return [0.0] * len(caps)
    return [min(c / total, cap) for c in caps]


def _pl_index_composition(index_id: str) -> dict | None:
    """Skład indeksu GPW: dziesięć największych pozycji + sektory całego koszyka."""
    idx = cat.PL_INDEX.get(index_id)
    if not idx:
        return None

    key = f"plidx:{index_id}"
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]

    members = idx["members"]
    caps = _market_caps([t for t, _n, _s in members])
    rows = [(t, n, s, caps[t]) for t, n, s in members if caps.get(t)]
    if len(rows) < 5:                       # za mało, żeby cokolwiek sensownie ważyć
        return None

    weights = _capped_weights([r[3] for r in rows], idx["cap"], idx.get("covers", 1.0))
    rows = sorted(zip(rows, weights), key=lambda rw: -rw[1])

    holdings = []
    for (ticker, name, _sec, _cap), w in rows[:10]:
        pct = round(w * 100, 2)
        holdings.append({"symbol": ticker, "name": name, "pct": pct,
                         "per_1000": round(w * 1000, 2)})

    sec_w: dict[str, float] = {}
    for (_t, _n, sec, _c), w in rows:
        sec_w[sec] = sec_w.get(sec, 0.0) + w * 100

    out = {
        "holdings": holdings,
        "sectors": _sector_rows(sec_w),
        "count": len(rows),
        "label": idx["label"],
    }
    with _lock:
        _cache[key] = (now + SUMMARY_TTL, out)
    return out


def _holdings_from(top: dict) -> list[dict]:
    """Dziesięć największych pozycji z modułu `topHoldings` Yahoo."""
    out = []
    for h in (top.get("holdings") or []):
        pct = _raw(h, "holdingPercent")
        if pct is None:
            continue
        out.append({
            "symbol": h.get("symbol") or "",
            "name": h.get("holdingName") or h.get("symbol") or "",
            "pct": round(pct * 100, 2),
            # najprostsze możliwe tłumaczenie procentu na pieniądze
            "per_1000": round(pct * 1000, 2),
        })
    return out


def _with_rest(holdings: list[dict]) -> tuple[list[dict], float | None]:
    """Dokłada jedenasty wiersz „Pozostałe": bez niego dziesięć spółek wygląda jak
    cały fundusz, a zwykle jest to jedna trzecia jego zawartości."""
    if not holdings:
        return holdings, None
    top10 = round(sum(h["pct"] for h in holdings), 2)
    if top10 < 99.0:
        rest = round(100.0 - top10, 2)
        holdings = holdings + [{
            "symbol": "", "name": "Pozostałe spółki w funduszu",
            "pct": rest, "per_1000": round(rest * 10, 2), "is_rest": True,
        }]
    return holdings, top10


# ------------------------------------------------------------------ karta

def detail(symbol: str) -> dict:
    """Pełne prześwietlenie jednego funduszu."""
    symbol = (symbol or "").strip()
    if not symbol:
        return {"error": "Brak symbolu"}

    key = f"detail:{symbol}"
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]

    meta = cat.BY_SYMBOL.get(symbol, {})
    qs = _quote_summary(symbol)
    price_node = qs.get("price") or {}
    profile = qs.get("fundProfile") or {}
    top = qs.get("topHoldings") or {}
    stats = qs.get("defaultKeyStatistics") or {}
    detail_node = qs.get("summaryDetail") or {}
    perf = qs.get("fundPerformance") or {}

    series, series_cur = _quotes(symbol)
    raw_cur = price_node.get("currency") or meta.get("cur") or ""
    # dzielimy TYLKO ceny z quoteSummary — te z price_series są już przeliczone
    div = 100.0 if raw_cur in ("GBp", "ZAc", "ILA") else 1.0
    currency = series_cur or {"GBp": "GBP", "ZAc": "ZAR", "ILA": "ILS"}.get(raw_cur, raw_cur)
    price = _raw(price_node, "regularMarketPrice")
    prev = _raw(price_node, "regularMarketPreviousClose")
    rets = _returns(series)
    vol = _stdev(rets) * math.sqrt(252) * 100 if len(rets) > 30 else None
    dd = _max_drawdown(series) if len(series) > 30 else None

    # ---- skład
    holdings, top10 = _with_rest(_holdings_from(top))
    sectors = _sectors(top)

    comp = {
        "stock_pct": round((_raw(top, "stockPosition") or 0) * 100, 2),
        "bond_pct": round((_raw(top, "bondPosition") or 0) * 100, 2),
        "cash_pct": round((_raw(top, "cashPosition") or 0) * 100, 2),
        "other_pct": round(((_raw(top, "otherPosition") or 0)
                            + (_raw(top, "preferredPosition") or 0)
                            + (_raw(top, "convertiblePosition") or 0)) * 100, 2),
    }

    fees = profile.get("feesExpensesInvestment") or {}
    ter = _raw(fees, "annualReportExpenseRatio")

    # ---- fundusze z GPW: Yahoo nie zna ich zawartości, składamy ją sami
    pl = cat.PL_FUND.get(symbol) or {}
    holdings_note, about = "", pl.get("about") or ""
    if pl and not holdings:
        if pl.get("index"):
            built = _pl_index_composition(pl["index"])
            if built:
                holdings, top10 = _with_rest(built["holdings"])
                sectors = sectors or built["sectors"]
                holdings_note = (
                    f"Fundusz odwzorowuje indeks {built['label']} — pokazujemy jego skład "
                    f"({built['count']} spółek) z udziałami policzonymi z bieżącej "
                    "kapitalizacji giełdowej i limitem na jedną spółkę. To bliski szacunek, "
                    "a nie oficjalna karta funduszu: dokładne wagi publikuje GPW Benchmark."
                )
            comp = {"stock_pct": 100.0, "bond_pct": 0.0, "cash_pct": 0.0, "other_pct": 0.0}
        elif pl.get("proxy"):
            pqs = _quote_summary(pl["proxy"])
            ptop = pqs.get("topHoldings") or {}
            holdings, top10 = _with_rest(_holdings_from(ptop))
            sectors = sectors or _sectors(ptop)
            if holdings:
                holdings_note = (
                    f"W środku jest indeks {pl.get('proxy_label') or pl['proxy']} — skład "
                    f"bierzemy z dużego funduszu na ten sam indeks ({pl['proxy']}), bo polski "
                    "fundusz kupuje dokładnie te same spółki, tyle że rozlicza je w złotówkach."
                )
            comp = {"stock_pct": 100.0, "bond_pct": 0.0, "cash_pct": 0.0, "other_pct": 0.0}
        elif pl.get("bonds"):
            comp = {"stock_pct": 0.0, "bond_pct": 100.0, "cash_pct": 0.0, "other_pct": 0.0}

    out = {
        "symbol": symbol,
        "name": meta.get("name") or price_node.get("shortName") or symbol,
        "long_name": price_node.get("longName") or "",
        "currency": currency,
        "currency_note": ("Na giełdzie w Londynie fundusz kwotowany jest w pensach — "
                          "tu pokazujemy ceny przeliczone na funty.") if raw_cur == "GBp" else "",
        "exchange": price_node.get("exchangeName") or "",
        "price": round(price / div, 4) if price else None,
        "prev_close": round(prev / div, 4) if prev else None,
        "change_pct": round((price / prev - 1) * 100, 2) if price and prev else None,

        "catalog": {
            "region": meta.get("region"), "region_label": cat.REGION_LABEL.get(meta.get("region"), ""),
            "sector": meta.get("sector"), "sector_label": cat.SECTOR_LABEL.get(meta.get("sector"), ""),
            "asset": meta.get("asset"), "asset_label": cat.ASSET_LABEL.get(meta.get("asset"), ""),
            "acc": meta.get("acc"), "note": meta.get("note") or "",
        },

        "profile": {
            "family": profile.get("family") or pl.get("family") or "",
            "category": profile.get("categoryName") or pl.get("category") or "",
            "legal_type": profile.get("legalType") or "",
            "ter_pct": round(ter * 100, 3) if ter else None,
            # `totalNetAssets` z Yahoo bywa raz w milionach, raz w tysiącach i nie da się
            # tego wiarygodnie rozstrzygnąć — lepiej nie pokazywać niż pokazać bzdurę

            "turnover_pct": round((_raw(fees, "annualHoldingsTurnover") or 0) * 100, 1) or None,
            "yield_pct": round((_raw(detail_node, "yield") or 0) * 100, 2) or None,
            "beta_3y": _raw(stats, "beta3Year"),
        },

        "composition": comp,
        "holdings": holdings,
        "holdings_note": holdings_note,
        "about": about,
        "top10_pct": top10,
        "sectors": sectors,
        "countries": _countries([h for h in holdings if not h.get("is_rest")]) or _region_country(meta),

        "performance": {
            "d1": round((price / prev - 1) * 100, 2) if price and prev else None,
            "m1": _round(_change_over(series, 30)),
            "m3": _round(_change_over(series, 91)),
            "m6": _round(_change_over(series, 182)),
            "y1": _round(_change_over(series, 365)),
            "ytd": _round(_ytd(series)),
        },

        "risk": _risk(vol, dd, top10),
        "chart": _chart_payload(series),
        "explain": _explain(meta, {
            "family": profile.get("family") or pl.get("family") or "",
            "categoryName": profile.get("categoryName") or pl.get("category") or "",
        }, comp, ter, top10, holdings, currency),
        "fetched_at": int(now),
    }

    if pl and not ter:
        # Yahoo nie oddaje opłat dla funduszy z GPW, a zmyślona liczba byłaby gorsza
        # od jej braku — mówimy wprost, gdzie ją znaleźć.
        out["explain"].append({
            "title": "Ile to kosztuje",
            "text": "Opłaty za zarządzanie tego funduszu nie mamy w danych — dla funduszy "
                    "notowanych na GPW Yahoo jej nie udostępnia. Aktualną stawkę podaje "
                    "dokument KID na stronie funduszu; u Beta ETF mieści się ona zwykle "
                    "w okolicach pół procenta rocznie, czyli więcej niż w dużych funduszach "
                    "zagranicznych, ale bez kosztu przewalutowania.",
        })

    if not qs and not series:
        out["error"] = "Yahoo nie zna tego symbolu albo chwilowo nie odpowiada."

    with _lock:
        _cache[key] = (now + SUMMARY_TTL, out)
    return out


def _round(v, n=2):
    return round(v, n) if isinstance(v, (int, float)) else None


def _ytd(series: dict) -> float | None:
    days = sorted(series)
    if not days:
        return None
    year = days[-1][:4]
    inside = [d for d in days if d.startswith(year)]
    if len(inside) < 2:
        return None
    base, last = series[inside[0]], series[inside[-1]]
    return (last / base - 1.0) * 100 if base else None


def _chart_payload(series: dict) -> dict:
    days = sorted(series)
    if not days:
        return {"dates": [], "values": []}
    return {
        "dates": days,
        "values": [round(series[d], 4) for d in days],
        "base": round(series[days[0]], 4),
    }


def _explain(meta, profile, comp, ter, top10, holdings, currency) -> list[dict]:
    """Sekcje „co to właściwie znaczy" — pisane dla kogoś, kto pierwszy raz widzi ETF."""
    out = []

    if meta.get("acc") is not None:
        out.append({
            "title": "Akumulujący czy wypłacający?",
            "text": ("Ten fundusz jest **akumulujący** — dywidendy ze spółek zostają w środku i "
                     "zwiększają jego wartość. Nic nie wpływa na rachunek, więc nie ma corocznego "
                     "podatku od dywidend i nie trzeba samodzielnie reinwestować.")
            if meta["acc"] else
            ("Ten fundusz jest **wypłacający** — dywidendy trafiają na Twój rachunek gotówką. "
             "Wygodne, jeśli chcesz z portfela żyć, ale każda wypłata jest opodatkowana i "
             "reinwestować trzeba ręcznie."),
        })

    if ter:
        yearly = ter * 100
        out.append({
            "title": "Ile to kosztuje naprawdę",
            "text": f"Opłata roczna wynosi **{yearly:.2f}%** wartości inwestycji. Przy 10 000 zł to "
                    f"około {yearly * 100:.0f} zł rocznie, pobierane po cichu z wyceny — nie zobaczysz "
                    "tego jako osobnej transakcji. To najpewniejszy koszt w całej inwestycji, "
                    "bo płacisz go niezależnie od wyniku.",
        })

    if top10 is not None:
        out.append({
            "title": "Jak bardzo skupiony jest ten koszyk",
            "text": (f"Dziesięć największych pozycji to **{top10:.0f}%** funduszu. "
                     + ("Przy takim poziomie o wyniku decyduje kilka spółek — dywersyfikacja "
                        "jest bardziej deklaracją niż faktem."
                        if top10 > 50 else
                        "To rozsądne rozłożenie — żadna pojedyncza spółka nie przesądza o wyniku.")),
        })

    if holdings:
        first = holdings[0]
        out.append({
            "title": "Co to znaczy w złotówkach",
            "text": f"Z każdego **1000 zł** wpłaconego do tego funduszu około "
                    f"**{first['per_1000']:.0f} zł** pracuje w spółce {first['name']}. "
                    "Kupując fundusz, kupujesz kawałek każdej firmy z listy poniżej — "
                    "w takiej proporcji, w jakiej siedzą w indeksie.",
        })

    if comp.get("bond_pct", 0) > 5:
        out.append({
            "title": "Nie tylko akcje",
            "text": f"**{comp['bond_pct']:.0f}%** funduszu to obligacje. Ta część rzadko rośnie "
                    "szybko, za to hamuje spadki, gdy giełda się osuwa.",
        })

    if currency and currency not in ("PLN",):
        out.append({
            "title": "Ryzyko walutowe",
            "text": f"Fundusz jest notowany w **{'GBP (w pensach)' if currency == 'GBp' else currency}**. "
                    "Nawet jeśli jego wartość nie drgnie, Twój wynik w złotówkach zmieni się razem "
                    "z kursem waluty. Przy wieloletnim inwestowaniu to zwykle się uśrednia, "
                    "ale w pojedynczym roku potrafi zrobić kilkanaście punktów procentowych różnicy.",
        })

    if profile.get("family"):
        out.append({
            "title": "Kto tym zarządza",
            "text": f"Fundusz prowadzi **{profile['family']}**"
                    + (f", kategoria: {profile['categoryName']}." if profile.get("categoryName") else ".")
                    + " Dostawca odpowiada za wierne odwzorowanie indeksu — im większy i dłużej "
                      "obecny na rynku, tym mniejsze ryzyko, że fundusz zostanie zamknięty "
                      "i będziesz musiał przenosić pieniądze.",
        })

    return out


# ------------------------------------------------------------------ lista

def _row(symbol: str) -> dict:
    """Skrócony wiersz listy: cena, wynik, zmienność, koszt."""
    meta = cat.BY_SYMBOL.get(symbol, {})
    series, series_cur = _quotes(symbol)
    rets = _returns(series)
    days = sorted(series)
    vol = _stdev(rets) * math.sqrt(252) * 100 if len(rets) > 30 else None
    dd = _max_drawdown(series) if len(series) > 30 else None

    last = series[days[-1]] if days else None
    prev = series[days[-2]] if len(days) > 1 else None

    # TER dociągamy z pełnej karty, ale tylko jeśli już siedzi w cache — lista
    # nie ma prawa czekać na sześćdziesiąt zapytań do Yahoo
    ter = None
    with _lock:
        cached = _cache.get(f"detail:{symbol}")
    if cached:
        ter = (cached[1].get("profile") or {}).get("ter_pct")

    return {
        "symbol": symbol,
        "name": meta.get("name") or symbol,
        "region": meta.get("region"), "region_label": cat.REGION_LABEL.get(meta.get("region"), ""),
        "sector": meta.get("sector"), "sector_label": cat.SECTOR_LABEL.get(meta.get("sector"), ""),
        "asset": meta.get("asset"), "asset_label": cat.ASSET_LABEL.get(meta.get("asset"), ""),
        "currency": series_cur or meta.get("cur", ""), "acc": meta.get("acc"),
        "note": meta.get("note", ""),
        "price": round(last, 4) if last else None,
        "change_pct": round((last / prev - 1) * 100, 2) if last and prev else None,
        "y1_pct": _round(_change_over(series, 365)),
        "ytd_pct": _round(_ytd(series)),
        "m1_pct": _round(_change_over(series, 30)),
        "m3_pct": _round(_change_over(series, 91)),
        "vol_pct": round(vol, 1) if vol else None,
        "max_dd_pct": round(dd, 1) if dd else None,
        "risk_score": _risk(vol, dd, None)["score"],
        "ter_pct": ter,
        "sparkline": [round(series[d], 4) for d in days[-60:]],
        "pending": not days,
    }


def _warm(symbol: str) -> None:
    try:
        row = _row(symbol)
        with _lock:
            _cache[f"row:{symbol}"] = (time.time() + ROW_TTL, row)
    except Exception as e:                                       # noqa: BLE001
        log.warning("warm %s: %s", symbol, e)
    finally:
        with _lock:
            _inflight.discard(symbol)


def _trend_score(row: dict):
    """Siła bieżącego trendu: ostatni miesiąc waży więcej niż kwartał.

    Chodzi o fundusze, które rozpędzają się TERAZ — sam roczny wynik tego nie
    pokazuje, bo równie dobrze mógł powstać rok temu i od pół roku stać w miejscu.
    """
    m1, m3 = row.get("m1_pct"), row.get("m3_pct")
    if m1 is None and m3 is None:
        return None
    return (m1 or 0) * 0.6 + (m3 or 0) * 0.4


def screen(region: str = "", sector: str = "", asset: str = "", currency: str = "",
           query: str = "", sort: str = "y1", limit: int = 24, offset: int = 0) -> dict:
    """Filtrowanie katalogu. Wiersze bez danych wracają jako `pending` i dociągają się w tle."""
    q = (query or "").strip().lower()
    picked = []
    for e in cat.CATALOG:
        if region and e["region"] != region:
            continue
        if sector and e["sector"] != sector:
            continue
        if asset and e["asset"] != asset:
            continue
        if currency and e["cur"] != currency:
            continue
        if q and q not in e["sym"].lower() and q not in e["name"].lower() and q not in e["note"].lower():
            continue
        picked.append(e["sym"])

    now = time.time()
    rows, cold = [], []
    for sym in picked:
        with _lock:
            hit = _cache.get(f"row:{sym}")
        if hit and hit[0] > now and not hit[1].get("pending"):
            rows.append(hit[1])
            continue
        cold.append(sym)
        meta = cat.BY_SYMBOL[sym]
        rows.append({
            "symbol": sym, "name": meta["name"], "note": meta["note"],
            "region": meta["region"], "region_label": cat.REGION_LABEL.get(meta["region"], ""),
            "sector": meta["sector"], "sector_label": cat.SECTOR_LABEL.get(meta["sector"], ""),
            "asset": meta["asset"], "asset_label": cat.ASSET_LABEL.get(meta["asset"], ""),
            "currency": meta["cur"], "acc": meta["acc"], "pending": True,
            "price": None, "change_pct": None, "y1_pct": None, "ytd_pct": None,
            "m1_pct": None, "m3_pct": None,
            "vol_pct": None, "max_dd_pct": None, "risk_score": None, "ter_pct": None,
            "sparkline": [],
        })

    # ---- sortowanie po wszystkim, co mamy; nieznane wartości lądują na końcu
    if sort == "name":
        rows.sort(key=lambda r: r["name"])
    elif sort == "drop":                               # największe spadki najpierw
        rows.sort(key=lambda r: (r.get("y1_pct") is None, r.get("y1_pct") or 0))
    elif sort == "trend":
        rows.sort(key=lambda r: (_trend_score(r) is None, -(_trend_score(r) or 0)))
    elif sort in ("risk", "cost"):                     # tu mniej znaczy lepiej
        key = "vol_pct" if sort == "risk" else "ter_pct"
        rows.sort(key=lambda r: (r.get(key) is None, r.get(key) or 0))
    else:
        key = "ytd_pct" if sort == "ytd" else "y1_pct"
        rows.sort(key=lambda r: (r.get(key) is None, -(r.get(key) or 0)))

    page = rows[offset:offset + limit]

    # Dociągamy to, co użytkownik widzi, plus zapas na przewinięcie — katalog ma
    # ponad sto funduszy i grzanie wszystkich przy każdym wejściu byłoby marnowaniem
    # limitów Yahoo. Wyjątek: sortowania, które BEZ danych nie mają sensu („największe
    # spadki" po ośmiu wierszach pokaże wzrosty). Dla nich rozgrzewamy szerszy zestaw,
    # żeby ranking mówił prawdę o całej liście, a nie o przypadkowej próbce.
    reach = limit + 8
    if offset == 0 and sort in ("drop", "trend", "risk", "cost"):
        reach = max(reach, 48)
    horizon = {r["symbol"] for r in rows[offset:offset + reach]}
    started = 0
    for sym in cold:
        if sym not in horizon:
            continue
        with _lock:
            if sym in _inflight:
                continue
            _inflight.add(sym)
        _pool.submit(_warm, sym)
        started += 1

    waiting = sum(1 for r in page if r.get("pending"))
    return {
        "rows": page,
        "total": len(picked),
        "shown": offset + len(page),
        "has_more": offset + len(page) < len(picked),
        "pending": waiting,
        "warming": started,
        "complete": waiting == 0,
    }


def meta() -> dict:
    """Opcje filtrów dla aplikacji — waluty liczone z faktycznej zawartości katalogu."""
    currencies = sorted({e["cur"] for e in cat.CATALOG})
    return {
        "regions": cat.REGIONS,
        "sectors": cat.SECTORS,
        "assets": cat.ASSETS,
        "currencies": [{"id": c, "label": "GBP (pensy)" if c == "GBp" else c} for c in currencies],
        "sorts": [
            {"id": "y1", "label": "Wynik 12 mies.", "desc": "Największy zwrot za ostatni rok."},
            {"id": "trend", "label": "Na fali", "desc": "Fundusze rozpędzające się teraz — ostatni miesiąc waży więcej niż kwartał."},
            {"id": "ytd", "label": "Od początku roku", "desc": "Wynik liczony od stycznia."},
            {"id": "drop", "label": "Największe spadki", "desc": "Co przecenione — czasem okazja, czasem ostrzeżenie."},
            {"id": "risk", "label": "Najspokojniejsze", "desc": "Najmniejsze wahania w skali roku."},
            {"id": "cost", "label": "Najtańsze", "desc": "Najniższa opłata roczna."},
            {"id": "name", "label": "Alfabetycznie", "desc": ""},
        ],
        "count": len(cat.CATALOG),
    }


# ------------------------------------------------------------ porównanie

def compare(symbols: list[str]) -> dict:
    """Zestawienie kilku funduszy obok siebie + korelacje między nimi.

    Korelacja liczona na dziennych stopach zwrotu w walucie notowania — chodzi
    o to, czy fundusze *ruszają się razem*, a nie o wynik w złotówkach.
    """
    syms = [s.strip() for s in (symbols or []) if s and s.strip()][:6]
    if len(syms) < 1:
        return {"empty": True, "reason": "Wybierz co najmniej jeden fundusz."}

    series = {s: _series(s) for s in syms}
    series = {s: v for s, v in series.items() if len(v) > 30}
    if not series:
        return {"empty": True, "reason": "Brak historii notowań dla wybranych funduszy."}

    rows = []
    for s in series:
        meta_e = cat.BY_SYMBOL.get(s, {})
        ser = series[s]
        rets = _returns(ser)
        vol = _stdev(rets) * math.sqrt(252) * 100
        dd = _max_drawdown(ser)
        # Ekspozycja krajowa wymaga składu funduszu. `detail` jest cache'owany na
        # dwanaście godzin, a porównujemy najwyżej sześć pozycji — koszt do przyjęcia,
        # a flagi to najczytelniejsza informacja w całym zestawieniu.
        try:
            countries = detail(s).get("countries") or []
        except Exception:                                        # noqa: BLE001
            countries = []
        rows.append({
            "symbol": s, "name": meta_e.get("name") or s,
            "countries": countries,
            "currency": meta_e.get("cur", ""),
            "region_label": cat.REGION_LABEL.get(meta_e.get("region"), ""),
            "sector_label": cat.SECTOR_LABEL.get(meta_e.get("sector"), ""),
            "y1_pct": _round(_change_over(ser, 365)),
            "ytd_pct": _round(_ytd(ser)),
            "vol_pct": round(vol, 1),
            "max_dd_pct": round(dd, 1),
            "risk_score": _risk(vol, dd, None)["score"],
            # wynik podzielony przez ryzyko — ile zwrotu na jednostkę wahań
            "reward_risk": _round((_change_over(ser, 365) or 0) / vol, 2) if vol > 0 else None,
        })

    keys = list(series)
    matrix = []
    for a in keys:
        row = []
        for b in keys:
            if a == b:
                row.append(1.0)
                continue
            shared = sorted(set(series[a]) & set(series[b]))
            if len(shared) < 40:
                row.append(None)
                continue
            ra = _pair_returns(series[a], shared)
            rb = _pair_returns(series[b], shared)
            sa, sb = _stdev(ra), _stdev(rb)
            if sa <= 0 or sb <= 0:
                row.append(None)
                continue
            n = len(ra)
            ma, mb = sum(ra) / n, sum(rb) / n
            cov = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n)) / (n - 1)
            row.append(round(max(-1.0, min(1.0, cov / (sa * sb))), 3))
        matrix.append(row)

    pairs = []
    for i, a in enumerate(keys):
        for j, b in enumerate(keys):
            if i < j and matrix[i][j] is not None:
                pairs.append({"a": a, "b": b, "corr": matrix[i][j]})
    pairs.sort(key=lambda p: -p["corr"])

    verdict = None
    if pairs:
        hi = pairs[0]
        if hi["corr"] > 0.9:
            verdict = (f"{hi['a']} i {hi['b']} poruszają się praktycznie identycznie "
                       f"(korelacja {hi['corr']:.2f}). Trzymanie obu naraz nie daje "
                       "dywersyfikacji — to dwa opakowania tej samej ekspozycji.")
        elif hi["corr"] > 0.75:
            verdict = (f"Najmocniej powiązana para to {hi['a']} i {hi['b']} ({hi['corr']:.2f}). "
                       "Częściowo się dublują, ale nie całkowicie.")
        else:
            verdict = ("Wybrane fundusze są od siebie wyraźnie niezależne — łączenie ich "
                       "realnie obniża wahania całości.")

    # wspólna oś czasu, żeby wykres porównawczy startował z tego samego punktu
    common = sorted(set.intersection(*[set(v) for v in series.values()])) if len(series) > 1 \
        else sorted(next(iter(series.values())))
    common = common[-260:]
    normalized = {
        s: [round(series[s][d] / series[s][common[0]] * 100, 2) for d in common]
        for s in series if common and series[s].get(common[0])
    }

    return {
        "empty": False,
        "rows": sorted(rows, key=lambda r: (r["y1_pct"] is None, -(r["y1_pct"] or 0))),
        "tickers": keys,
        "matrix": matrix,
        "pairs": pairs,
        "verdict": verdict,
        "chart": {"dates": common, "series": normalized},
    }


def _pair_returns(series: dict, days: list) -> list[float]:
    out, prev = [], series[days[0]]
    for d in days[1:]:
        cur = series[d]
        if prev and cur and prev > 0:
            out.append(cur / prev - 1.0)
        prev = cur or prev
    return out


# ------------------------------------------------- rozpoznanie „czy to ETF"

def is_etf(symbol: str, name: str = "", quote_type: str = "") -> bool:
    """Czy dla tego symbolu ma sens prześwietlenie funduszu."""
    s = (symbol or "").strip()
    if s in cat.BY_SYMBOL:
        return True
    if (quote_type or "").upper() == "ETF":
        return True
    n = (name or "").lower()
    return any(w in n for w in ("etf", "ucits", "index fund", "beta etf"))
