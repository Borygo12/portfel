"""Benchmarki do porównań z portfelem (perspektywa inwestora w PLN).

Serie denominowane w USD przeliczamy na PLN kursem NBP — porównanie jest wtedy
uczciwe: "co by było, gdybym za te złotówki kupił S&P500/złoto/BTC".
Inflacja PL: indeks HICP (Eurostat, 2015=100), miesięczny -> schodkowo dziennie.
"""

import datetime
import logging

import requests

from . import prices, store

log = logging.getLogger("portfolio.benchmarks")

# name -> (etykieta, ticker XTB-owy dla prices.price_series, czy przeliczać na PLN)
BENCHMARKS = {
    "sp500":     ("S&P 500", "US500", True),
    "nasdaq100": ("Nasdaq 100", "US100", True),
    # Yahoo ma dla indeksu WIG20 tylko bieżący dzień — ETF Beta WIG20TR (PLN,
    # total return) ma pełną historię i jest uczciwszym benchmarkiem
    "wig20":     ("WIG20 TR (ETF)", "ETFBW20TR.PL", False),
    "gold":      ("Złoto", "GOLD", True),
    "btc":       ("Bitcoin", "BITCOIN", True),
    "usd":       ("Dolar (USDPLN)", None, None),          # sam kurs
    "inflation": ("Inflacja PL (HICP)", None, None),      # Eurostat
}


def available() -> list:
    return [{"id": k, "label": v[0]} for k, v in BENCHMARKS.items()]


def series(name: str, from_date: str) -> dict:
    """{data: poziom_indeksu} — surowa seria; normalizację do początku zakresu robi UI."""
    if name == "inflation":
        return _hicp_pl(from_date)
    if name == "usd":
        return prices.fx_series("USD", from_date)
    if name not in BENCHMARKS:
        return {}
    _, ticker, to_pln = BENCHMARKS[name]
    ser, ccy = prices.price_series(ticker, from_date)
    if not ser:
        return {}
    if to_pln and ccy and ccy != "PLN":
        fx = prices.fx_series(ccy, from_date)
        if fx:
            from .engine import _Step
            fxs = _Step(fx, default=fx[min(fx)])
            ser = {d: v * fxs.at(d) for d, v in ser.items()}
    return ser


def _hicp_pl(from_date: str) -> dict:
    """Miesięczny indeks HICP dla Polski z Eurostatu, cache 7 dni."""
    key = "eu:HICP_PL"
    meta = store.get_price_meta(key)
    cached = store.get_prices(key)
    if cached and meta and meta.get("last_fetch"):
        try:
            last = datetime.datetime.strptime(meta["last_fetch"], "%Y-%m-%dT%H:%M:%S")
            if (datetime.datetime.utcnow() - last).days < 7:
                return cached
        except ValueError:
            pass
    url = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_midx"
           "?format=JSON&geo=PL&coicop=CP00&unit=I15&sinceTimePeriod=2005-01")
    try:
        r = requests.get(url, timeout=20, headers=prices.UA)
        r.raise_for_status()
        js = r.json()
        time_idx = js["dimension"]["time"]["category"]["index"]   # '2006-01' -> pozycja
        values = js["value"]                                       # pozycja(str) -> wartość
        ser = {}
        for period, pos in time_idx.items():
            v = values.get(str(pos))
            if v is None:
                continue
            ser[period + "-01"] = float(v)   # pierwszy dzień miesiąca
        if ser:
            store.put_prices(key, ser, "eurostat", "ok|PLN",
                             datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"))
            return ser
    except Exception as e:  # noqa: BLE001
        log.warning("Eurostat HICP: %s", e)
    return cached
