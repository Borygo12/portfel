"""Ceny dzienne do wyceny portfela.

Źródła (wszystkie darmowe, bez kluczy):
  - Yahoo Finance chart API — akcje/ETF/indeksy/krypto (główne źródło;
    Stooq odpadł — wprowadził weryfikację anty-botową, której nie obchodzimy)
  - NBP API — kursy średnie walut (tabela A), do przeliczeń na PLN
  - Eurostat (benchmarks.py) — indeks HICP dla inflacji PL

Cache w SQLite (price_cache); dociągamy tylko gdy ostatni fetch starszy niż TTL.
"""

import datetime
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from . import store

log = logging.getLogger("portfolio.prices")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
TTL_H = 6           # godzin — historia dzienna nie zmienia się w ciągu dnia
QUOTE_TTL = 15      # sekund — osobna, szybka ścieżka dla BIEŻĄCEJ ceny — wycena „na bieżąco"
_session = requests.Session()
_session.headers.update(UA)

# mapowanie sufiksów XTB -> giełda Yahoo (US bez sufiksu)
_SUFFIX = {
    "US": "", "PL": ".WA", "DE": ".DE", "UK": ".L", "FR": ".PA", "ES": ".MC",
    "IT": ".MI", "NL": ".AS", "BE": ".BR", "PT": ".LS", "CH": ".SW", "SE": ".ST",
    "DK": ".CO", "NO": ".OL", "FI": ".HE", "AT": ".VI", "CZ": ".PR", "HU": ".BD",
}
# instrumenty XTB bez sufiksu (CFD/krypto) -> symbol Yahoo
_SPECIAL = {
    "BITCOIN": "BTC-USD", "ETHEREUM": "ETH-USD", "SOLANA": "SOL-USD",
    "RIPPLE": "XRP-USD", "DOGECOIN": "DOGE-USD", "LITECOIN": "LTC-USD",
    "GOLD": "GC=F", "SILVER": "SI=F", "OIL.WTI": "CL=F", "NATGAS": "NG=F",
    "US500": "^GSPC", "US100": "^NDX", "US30": "^DJI", "W20": "WIG20.WA",
    "DE40": "^GDAXI", "EU50": "^STOXX50E", "VIX": "^VIX",
}


def yahoo_symbol(xtb_ticker: str) -> str:
    t = (xtb_ticker or "").strip().upper()
    if t in _SPECIAL:
        return _SPECIAL[t]
    m = re.match(r"^(.+)\.([A-Z]{2})$", t)
    if m and m.group(2) in _SUFFIX:
        return m.group(1) + _SUFFIX[m.group(2)]
    return t


def _now_iso() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def _fresh(meta) -> bool:
    if not meta or not meta.get("last_fetch"):
        return False
    try:
        last = datetime.datetime.strptime(meta["last_fetch"], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    return (datetime.datetime.utcnow() - last).total_seconds() < TTL_H * 3600


# ---------------- Yahoo ----------------

def _yahoo_fetch(symbol: str, from_date: str) -> tuple:
    """Zwraca ({data: close}, waluta). Waluta wg meta Yahoo; GBp/ZAc -> /100."""
    p1 = int(datetime.datetime.strptime(from_date, "%Y-%m-%d").timestamp()) - 86400 * 7
    p2 = int(time.time()) + 86400
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(symbol)}"
           f"?period1={max(p1, 0)}&period2={p2}&interval=1d&events=div%2Csplit")
    r = _session.get(url, timeout=15)
    r.raise_for_status()
    js = r.json()
    result = (js.get("chart") or {}).get("result") or []
    if not result:
        return {}, ""
    res = result[0]
    currency = (res.get("meta") or {}).get("currency") or ""
    ts = res.get("timestamp") or []
    quotes = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quotes.get("close") or []
    divisor = 100.0 if currency in ("GBp", "ZAc", "ILA") else 1.0
    if currency == "GBp":
        currency = "GBP"
    elif currency == "ZAc":
        currency = "ZAR"
    elif currency == "ILA":
        currency = "ILS"
    series = {}
    for t, c in zip(ts, closes):
        if c is None:
            continue
        d = datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
        series[d] = round(float(c) / divisor, 6)
    # Yahoo często zostawia ostatni słupek z close=None, a aktualną/zamknięciową cenę
    # trzyma w meta.regularMarketPrice — bez tego wycena wisiała na D-1
    meta = res.get("meta") or {}
    rmp, rmt = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
    if rmp and rmt:
        d = datetime.datetime.utcfromtimestamp(rmt).strftime("%Y-%m-%d")
        series[d] = round(float(rmp) / divisor, 6)
    return series, currency


def _yahoo_search(base: str) -> list:
    """Kandydaci z wyszukiwarki Yahoo (np. BTEC -> BTEC.L), gdy bezpośredni symbol nie istnieje."""
    try:
        r = _session.get(
            f"https://query1.finance.yahoo.com/v1/finance/search?q={requests.utils.quote(base)}"
            "&quotesCount=8&newsCount=0", timeout=10)
        r.raise_for_status()
        out = []
        for q in r.json().get("quotes", []):
            sym = q.get("symbol") or ""
            if q.get("quoteType") in ("EQUITY", "ETF") and sym.split(".")[0].upper() == base.upper():
                out.append(sym)
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("Yahoo search %s: %s", base, e)
        return []



# ---------------- pamięć podręczna serii dziennych (w procesie) ----------------
#
# `price_series` i `fx_series` czytają z Postgresa: metadane + CAŁĄ serię dzienną
# waloru, po trzy zapytania na ticker. Silnik woła je przy każdym przeliczeniu
# portfela, czyli dla portfela z trzydziestoma pozycjami to ~90 zapytań i
# trzydzieści dużych wyników — za każdym razem, gdy wygaśnie memo silnika.
#
# To są dane WSPÓLNE (price_cache jest jedno dla całego serwera, poza RLS), więc
# pamięć podręczna też może być wspólna — w przeciwieństwie do memo portfela,
# które musi być per użytkownik. Notowanie dzienne zmienia się raz na sesję,
# a bieżący kurs i tak dokłada się osobno (QUOTE_TTL), więc pięć minut nie
# postarza niczego, co widać na ekranie.
SERIES_MEMO_TTL = 300       # s
_series_memo: dict = {}
_series_memo_lock = threading.Lock()


def _memoizuj(klucz, ttl, licz):
    with _series_memo_lock:
        hit = _series_memo.get(klucz)
    if hit and time.time() - hit["at"] < ttl:
        return hit["val"]
    val = licz()
    with _series_memo_lock:
        _series_memo[klucz] = {"val": val, "at": time.time()}
    return val


def price_series(xtb_ticker: str, from_date: str) -> tuple:
    """({data: close}, waluta) dla tickera XTB — z pamięcią podręczną procesu."""
    return _memoizuj(("px", (xtb_ticker or "").strip().upper(), from_date),
                     SERIES_MEMO_TTL, lambda: _price_series_now(xtb_ticker, from_date))


def fx_series(currency: str, from_date: str) -> dict:
    """{data: kurs} dla waluty — z pamięcią podręczną procesu."""
    return _memoizuj(("fx", (currency or "PLN").upper(), from_date),
                     SERIES_MEMO_TTL, lambda: _fx_series_now(currency, from_date))


def _price_series_now(xtb_ticker: str, from_date: str) -> tuple:
    """({data: close}, waluta) dla tickera XTB. Puste dict, gdy nic nie znaleziono.

    Gdy zmapowany symbol nie ma notowań na Yahoo (np. BTEC.DE), szukamy tego samego
    instrumentu na innych giełdach przez wyszukiwarkę Yahoo i zapamiętujemy wynik.
    """
    tkey = f"res:{(xtb_ticker or '').strip().upper()}"
    resolved = store.get_price_meta(tkey)
    ysym = (resolved or {}).get("status") or yahoo_symbol(xtb_ticker)
    key = f"y:{ysym}"
    meta = store.get_price_meta(key)
    cached = store.get_prices(key)
    have_from = min(cached) if cached else None
    # cache świeży i pokrywa żądany zakres -> zwróć z cache
    if cached and _fresh(meta) and (have_from is None or have_from <= from_date or meta.get("status", "").startswith("full")):
        return cached, _meta_currency(meta)
    try:
        series, currency = _yahoo_fetch(ysym, from_date)
    except Exception as e:  # noqa: BLE001 — 404 = symbol nie istnieje; idziemy do wyszukiwarki
        log.warning("Yahoo %s: %s", ysym, e)
        series, currency = {}, ""
    if not series and not resolved:
        # symbol nie istnieje na Yahoo — poszukaj tego instrumentu na innych giełdach
        base = ysym.split(".")[0]
        for cand in _yahoo_search(base):
            if cand == ysym:
                continue
            try:
                series, currency = _yahoo_fetch(cand, from_date)
            except Exception:  # noqa: BLE001
                continue
            if series:
                ysym = cand
                key = f"y:{ysym}"
                cached = store.get_prices(key)
                store.set_meta(tkey, "resolve", ysym, _now_iso())
                log.info("Rozwiązano %s -> %s", xtb_ticker, ysym)
                break
    if not series:
        if cached:   # sieć padła albo nic nie znaleziono — zostań przy cache
            return cached, _meta_currency(meta)
        store.put_prices(key, {}, "yahoo", "empty|", _now_iso())
        return {}, ""
    status = f"ok|{currency}"
    store.put_prices(key, series, "yahoo", status, _now_iso())
    merged = dict(cached)
    merged.update(series)
    return merged, currency


def _meta_currency(meta) -> str:
    if meta and "|" in (meta.get("status") or ""):
        return meta["status"].split("|", 1)[1]
    return ""


# ---------------- bieżące notowania (szybka ścieżka) ----------------
#
# Historia dzienna zmienia się raz na dobę, ale KURS zmienia się co sekundę.
# Dlatego notowania „na teraz" pobieramy osobno, równolegle i z krótkim TTL —
# dzięki temu portfel pokazuje realną wartość, nawet gdy rynek leci w dół.

_quotes: dict = {}          # ysym -> {"price", "ts", "currency", "fetched"}
_quotes_lock = threading.Lock()


def resolved_symbol(xtb_ticker: str) -> str:
    """Symbol Yahoo dla tickera XTB — z uwzględnieniem wcześniejszego dopasowania."""
    t = (xtb_ticker or "").strip().upper()
    res = store.get_price_meta(f"res:{t}")
    if res and res.get("status"):
        return res["status"]
    return yahoo_symbol(t)


def _norm(meta: dict) -> tuple:
    """(waluta, dzielnik) — Yahoo podaje część rynków w groszach (GBp, ZAc, ILA)."""
    currency = meta.get("currency") or ""
    divisor = 100.0 if currency in ("GBp", "ZAc", "ILA") else 1.0
    return {"GBp": "GBP", "ZAc": "ZAR", "ILA": "ILS"}.get(currency, currency), divisor


# --- spark: JEDNO żądanie na 20 symboli --------------------------------------
#
# Osobne żądanie na każdy walor to przy 26 pozycjach 26 rund sieciowych (~1,8 s).
# Endpoint `spark` zwraca to samo (meta + słupki) dla maks. 20 symboli naraz,
# więc cały portfel schodzi do dwóch żądań (~0,3 s). To jest główny powód,
# dla którego dane potrafią być świeże co kilkanaście sekund.

SPARK_MAX = 20


def _spark_batch(symbols: list, rng: str, interval: str) -> dict:
    try:
        q = ",".join(requests.utils.quote(s) for s in symbols)
        r = _session.get(
            f"https://query1.finance.yahoo.com/v7/finance/spark?symbols={q}"
            f"&range={rng}&interval={interval}", timeout=20)
        r.raise_for_status()
        out = {}
        for item in (r.json().get("spark") or {}).get("result") or []:
            resp = (item.get("response") or [{}])[0]
            out[item.get("symbol")] = {
                "meta": resp.get("meta") or {},
                "ts": resp.get("timestamp") or [],
                "close": ((resp.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [],
            }
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("Spark %s (%s): %s", symbols[:3], rng, e)
        return {}


def _spark(symbols: list, rng: str, interval: str) -> dict:
    """{ysym: {"meta", "ts", "close"}} — partie po 20 symboli, równolegle."""
    uniq = list(dict.fromkeys(symbols))
    if not uniq:
        return {}
    parts = [uniq[i:i + SPARK_MAX] for i in range(0, len(uniq), SPARK_MAX)]
    out = {}
    if len(parts) == 1:
        return _spark_batch(parts[0], rng, interval)
    with ThreadPoolExecutor(max_workers=4) as ex:
        for part in ex.map(lambda b: _spark_batch(b, rng, interval), parts):
            out.update(part)
    return out


def _quote_fetch(ysym: str) -> dict | None:
    """Jedno bieżące notowanie z Yahoo — zapas, gdy spark nie zna symbolu."""
    try:
        r = _session.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(ysym)}"
            "?range=1d&interval=1d", timeout=10)
        r.raise_for_status()
        result = (r.json().get("chart") or {}).get("result") or []
        return _quote_from_meta((result[0].get("meta") or {})) if result else None
    except Exception as e:  # noqa: BLE001
        log.warning("Quote %s: %s", ysym, e)
        return None


def _quote_from_meta(meta: dict) -> dict | None:
    price, ts = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
    if not price or not ts:
        return None
    currency, divisor = _norm(meta)
    return {"price": float(price) / divisor, "ts": int(ts),
            "currency": currency, "fetched": time.time()}


def _quotes_for(symbols: list) -> dict:
    """{ysym: notowanie} — z cache QUOTE_TTL, brakujące dociągane sparkiem."""
    now = time.time()
    out, need = {}, []
    for sym in dict.fromkeys(symbols):
        with _quotes_lock:
            q = _quotes.get(sym)
        if q and now - q["fetched"] < QUOTE_TTL:
            out[sym] = q
        else:
            need.append(sym)
    if not need:
        return out

    data = _spark(need, "1d", "1d")
    missing = []
    for sym in need:
        entry = data.get(sym)
        q = _quote_from_meta(entry["meta"]) if entry else None
        if q:
            with _quotes_lock:
                _quotes[sym] = q
            out[sym] = q
        else:
            missing.append(sym)
    if missing:   # symbole, których spark nie zna — po staremu, pojedynczo
        with ThreadPoolExecutor(max_workers=8) as ex:
            for sym, q in zip(missing, ex.map(_quote_fetch, missing)):
                if q:
                    with _quotes_lock:
                        _quotes[sym] = q
                    out[sym] = q
    return out


def live_fx(currencies) -> dict:
    """{waluta: {price, ts}} — rynkowy kurs waluty do PLN (Yahoo `USDPLN=X`).

    NBP publikuje kurs raz dziennie (~12:15), a portfel jest w większości w USD —
    bez bieżącego kursu wartość w złotówkach potrafi się mylić o kilkadziesiąt
    złotych i „stoi" mimo ruchu na rynku. Historię nadal liczymy z NBP (oficjalna,
    kompletna), a DZISIEJSZY punkt nadpisujemy kursem rynkowym.
    """
    pairs = [(c.upper(), f"{c.upper()}PLN=X") for c in currencies
             if c and c.upper() not in ("PLN", "")]
    data = _quotes_for([sym for _, sym in pairs])
    return {cur: data[sym] for cur, sym in pairs if sym in data}


def live_quotes(tickers: list) -> dict:
    """{ticker XTB: {price, ts, currency}} — świeże kursy, jednym żądaniem na 20 walorów."""
    pairs = [(t, resolved_symbol(t)) for t in tickers]
    known = {sym for sym in _quotes if time.time() - _quotes[sym]["fetched"] < QUOTE_TTL}
    data = _quotes_for([sym for _, sym in pairs])

    today = datetime.date.today().isoformat()
    out = {}
    for t, ysym in pairs:
        q = data.get(ysym)
        if not q:
            continue
        out[t] = q
        if ysym in known:
            continue   # z cache — historia już dopisana przy poprzednim pobraniu
        # dopisz do historii, żeby wykres dzienny kończył się bieżącą ceną
        day = datetime.datetime.utcfromtimestamp(q["ts"]).strftime("%Y-%m-%d")
        store.put_prices(f"y:{ysym}", {day: round(q["price"], 6)}, "yahoo",
                         f"ok|{q['currency']}", _now_iso())
        if day != today:   # np. rynek zamknięty — trzymaj też pod dzisiejszą datą
            store.put_prices(f"y:{ysym}", {today: round(q["price"], 6)}, "yahoo",
                             f"ok|{q['currency']}", _now_iso())
    return out


# ---------------- notowania śróddzienne (słupki 5-minutowe) ----------------
#
# Do zakresu „1D" nie wystarczy jedna cena na dzień — potrzebny jest przebieg
# sesji. Yahoo daje darmowe słupki 5-minutowe do 60 dni wstecz; bierzemy 5 dni,
# bo w poniedziałek „2 dni wstecz" to weekend bez notowań, a potrzebujemy jeszcze
# zamknięcia POPRZEDNIEJ sesji jako punktu odniesienia.

INTRADAY_TTL = 20       # s — bieżąca sesja; tak często realnie zmieniają się słupki
PREV_TTL = 1800         # s — zamknięcie poprzedniej sesji w ciągu dnia się nie zmienia
EXT_TTL = 60            # s — notowania przed sesją / po sesji

_intraday: dict = {}    # ysym -> {"ts", "close", "currency", "fetched"}   (dziś)
_prev: dict = {}        # ysym -> {"ts", "close", "fetched"}               (5 sesji wstecz)
_ext: dict = {}         # ysym -> {"price", "ts", "phase", "fetched"}
_intraday_lock = threading.Lock()


def _clean_bars(entry: dict) -> tuple:
    """(ts, close, waluta) ze słupków spark — dziury wypełnione ostatnią ceną."""
    currency, divisor = _norm(entry.get("meta") or {})
    ts, cl, last = [], [], None
    for t, c in zip(entry.get("ts") or [], entry.get("close") or []):
        # Yahoo zostawia dziury (brak transakcji w slocie) — bez wypełnienia
        # wykres portfela miałby przerwy
        if c is None:
            c = last
        if c is None:
            continue
        last = c
        ts.append(int(t))
        cl.append(round(float(c) / divisor, 6))
    return ts, cl, currency


def _cached(store_dict: dict, symbols: list, ttl: int, fetch) -> dict:
    """Wspólny wzorzec: weź z cache, resztę dociągnij i zapamiętaj."""
    now = time.time()
    out, need = {}, []
    for sym in dict.fromkeys(symbols):
        with _intraday_lock:
            s = store_dict.get(sym)
        if s and now - s["fetched"] < ttl:
            out[sym] = s
        else:
            need.append(sym)
    if need:
        for sym, s in fetch(need).items():
            with _intraday_lock:
                store_dict[sym] = s
            out[sym] = s
    return out


def _fetch_today(symbols: list) -> dict:
    out = {}
    for sym, entry in _spark(symbols, "1d", "5m").items():
        ts, cl, currency = _clean_bars(entry)
        if ts:
            out[sym] = {"ts": ts, "close": cl, "currency": currency, "fetched": time.time()}
    return out


def _fetch_prev(symbols: list) -> dict:
    out = {}
    for sym, entry in _spark(symbols, "5d", "5m").items():
        ts, cl, _ = _clean_bars(entry)
        if ts:
            out[sym] = {"ts": ts, "close": cl, "fetched": time.time()}
    return out


def _intraday_for(symbols: list) -> dict:
    """{ysym: {"ts","close","currency","prev_ts","prev_close"}}.

    Dwa różne tempa: bieżąca sesja co INTRADAY_TTL (bo to jest „na żywo"), a starsze
    sesje — potrzebne wyłącznie do punktu odniesienia — raz na pół godziny. Dzięki temu
    częste odświeżanie ściąga kilkadziesiąt kB zamiast kilkuset.
    """
    today = _cached(_intraday, symbols, INTRADAY_TTL, _fetch_today)
    prev = _cached(_prev, symbols, PREV_TTL, _fetch_prev)
    out = {}
    for sym in dict.fromkeys(symbols):
        t, p = today.get(sym), prev.get(sym)
        if not t and not p:
            continue
        base = t or {"ts": [], "close": [], "currency": ""}
        out[sym] = {
            "ts": base["ts"], "close": base["close"], "currency": base.get("currency") or "",
            "prev_ts": (p or {}).get("ts") or base["ts"],
            "prev_close": (p or {}).get("close") or base["close"],
        }
    return out


def intraday_series(tickers: list) -> dict:
    """{ticker XTB: seria śróddzienna} — bieżąca sesja + materiał na odniesienie."""
    pairs = [(t, resolved_symbol(t)) for t in tickers]
    data = _intraday_for([sym for _, sym in pairs])
    return {t: data[sym] for t, sym in pairs if sym in data}


def intraday_fx(currencies) -> dict:
    """{waluta: seria śróddzienna kursu do PLN}."""
    pairs = [(c.upper(), f"{c.upper()}PLN=X") for c in currencies if c and c.upper() != "PLN"]
    data = _intraday_for([sym for _, sym in pairs])
    return {c: data[sym] for c, sym in pairs if sym in data}


# --- słupki śróddzienne z WIELU sesji (zakresy „1T" i „1M") -------------------
#
# Zakres tygodniowy z serii dziennej to 5–7 punktów — wykres wychodzi płaski i nic
# nie mówi o tym, co się w tym tygodniu działo. Yahoo daje darmowe słupki 15/30-minutowe
# do 60 dni wstecz, więc ten sam tydzień da się pokazać w kilkuset punktach.
#
# Cache osobny dla każdej pary (zakres, interwał): kluczem jest sam symbol, a wiadro
# wybieramy po zakresie — dzięki temu „1T" i „1M" nie nadpisują sobie nawzajem danych.

HIST_TTL = 300          # s — kształt starszych sesji się nie zmienia, a ostatni punkt
                        # wykresu i tak kotwiczymy w wycenie „na żywo"

_hist: dict = {}        # "zakres|interwał" -> {ysym: {"ts", "close", "currency", "fetched"}}


def _history_for(symbols: list, rng: str, interval: str) -> dict:
    bucket = _hist.setdefault(f"{rng}|{interval}", {})

    def fetch(need: list) -> dict:
        out = {}
        for sym, entry in _spark(need, rng, interval).items():
            ts, cl, currency = _clean_bars(entry)
            if ts:
                out[sym] = {"ts": ts, "close": cl, "currency": currency,
                            "fetched": time.time()}
        return out

    return _cached(bucket, symbols, HIST_TTL, fetch)


def history_series(tickers: list, rng: str, interval: str) -> dict:
    """{ticker XTB: {"ts", "close", "currency"}} — słupki śróddzienne z kilku sesji."""
    pairs = [(t, resolved_symbol(t)) for t in tickers]
    data = _history_for([sym for _, sym in pairs], rng, interval)
    return {t: data[sym] for t, sym in pairs if sym in data}


def history_fx(currencies, rng: str, interval: str) -> dict:
    """{waluta: słupki śróddzienne kursu do PLN} z kilku sesji."""
    pairs = [(c.upper(), f"{c.upper()}PLN=X") for c in currencies if c and c.upper() != "PLN"]
    data = _history_for([sym for _, sym in pairs], rng, interval)
    return {c: data[sym] for c, sym in pairs if sym in data}


# --- notowania poza sesją (przed otwarciem / po zamknięciu) -------------------
#
# Spark ich nie zwraca, więc lecimy po jednym symbolu — ale TYLKO dla walorów,
# które dziś jeszcze nie handlowały, i tylko po to, żeby POKAZAĆ ruch przy pozycji.
# Do wykresu i podsumowania tego nie wliczamy: to jeszcze nie jest zdarzenie.

def _ext_fetch(ysym: str) -> dict | None:
    try:
        r = _session.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(ysym)}"
            "?range=1d&interval=5m&includePrePost=true", timeout=12)
        r.raise_for_status()
        result = (r.json().get("chart") or {}).get("result") or []
        if not result:
            return None
        res = result[0]
        meta = res.get("meta") or {}
        periods = (meta.get("tradingPeriods") or {}).get("regular") or []
        spans = [(p["start"], p["end"]) for grp in periods for p in grp] if periods else []
        ts, cl, _ = _clean_bars({"meta": meta, "ts": res.get("timestamp"),
                                 "close": ((res.get("indicators") or {}).get("quote")
                                           or [{}])[0].get("close")})
        outside = [(t, c) for t, c in zip(ts, cl)
                   if not any(a <= t < b for a, b in spans)]
        if not outside:
            return None
        t, c = outside[-1]
        first_start = min((a for a, _ in spans), default=None)
        phase = "pre" if first_start and t < first_start else "post"
        return {"price": c, "ts": t, "phase": phase, "fetched": time.time()}
    except Exception as e:  # noqa: BLE001
        log.warning("Extended %s: %s", ysym, e)
        return None


def extended_quotes(tickers: list) -> dict:
    """{ticker XTB: {price, ts, phase}} — ostatnie notowanie poza sesją."""
    pairs = [(t, resolved_symbol(t)) for t in tickers]

    def fetch(symbols):
        with ThreadPoolExecutor(max_workers=12) as ex:
            return {sym: q for sym, q in zip(symbols, ex.map(_ext_fetch, symbols)) if q}

    data = _cached(_ext, [sym for _, sym in pairs], EXT_TTL, fetch)
    return {t: data[sym] for t, sym in pairs if sym in data}


# ---------------- NBP (FX -> PLN) ----------------

def _fx_series_now(currency: str, from_date: str) -> dict:
    """{data: kurs_PLN_za_1_jednostkę}. Dla PLN zwraca pusty dict (kurs=1 obsługuje engine)."""
    cur = (currency or "PLN").upper()
    if cur == "PLN":
        return {}
    key = f"nbp:{cur}"
    meta = store.get_price_meta(key)
    cached = store.get_prices(key)
    if cached and _fresh(meta) and min(cached) <= from_date:
        return cached
    start = datetime.date.fromisoformat(from_date) - datetime.timedelta(days=10)
    if cached and min(cached) <= from_date:
        start = datetime.date.fromisoformat(max(cached))  # tylko dociągnij ogon
    end = datetime.date.today()
    series = dict(cached)
    d = start
    try:
        while d <= end:
            d2 = min(d + datetime.timedelta(days=360), end)
            url = (f"https://api.nbp.pl/api/exchangerates/rates/a/{cur.lower()}"
                   f"/{d.isoformat()}/{d2.isoformat()}/?format=json")
            r = _session.get(url, timeout=15)
            if r.status_code == 404:   # brak notowań w zakresie (weekend/stara waluta)
                d = d2 + datetime.timedelta(days=1)
                continue
            r.raise_for_status()
            for row in r.json().get("rates", []):
                series[row["effectiveDate"]] = float(row["mid"])
            d = d2 + datetime.timedelta(days=1)
        store.put_prices(key, series, "nbp", "ok|PLN", _now_iso())
    except Exception as e:  # noqa: BLE001
        log.warning("NBP %s: %s", cur, e)
    return series
