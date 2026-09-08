"""Drugie źródło danych o funduszach: publiczne API giełdy we Frankfurcie.

Po co, skoro mamy Yahoo: Yahoo regularnie czegoś nie oddaje. Dla części linii
notowań nie ma składu funduszu, dla całego Vanguarda i papierów surowcowych
podaje opłatę roczną jako `0.00%` zamiast „nie wiem", a `quoteSummary` bywa
zamknięte błędem 401, gdy wygaśnie crumb. Dopóki mamy jedno źródło, każda taka
dziura jest dziurą w aplikacji.

Deutsche Börse wystawia dane swojego serwisu boerse-frankfurt.de zwykłym,
publicznym JSON-em — bez klucza, bez logowania, bez omijania zabezpieczeń.
Notowana jest tam praktycznie każda europejska ETF-ka, a rekord zawiera to,
czego Yahoo nie daje: opłatę roczną (TER), aktywa funduszu, emitenta,
odwzorowywany indeks i to, czy fundusz wypłaca dywidendy.

Trzy wejścia:
  * `fund(isin)`       — opłata, aktywa, emitent, indeks (z dziennej migawki)
  * `quote(isin)`      — bieżąca cena i zmiana dnia
  * `performance(isin)`— wyniki 1M/3M/6M/1R

Migawkę całego uniwersum (~3,5 tys. papierów) pobieramy raz na dobę czterema
zapytaniami i zostawiamy w pamięci TYLKO wiersze funduszy z naszego katalogu —
reszta to kilka megabajtów, których nikt nigdy nie odczyta.

Klucz łączący oba światy to ISIN, wpisany przy funduszu w `catalog.py`. Każdy
z nich został potwierdzony dwoma niezależnymi źródłami: nazwą z Frankfurtu i
nazwą, którą Yahoo zwraca przy wyszukaniu tego ISIN-u. Tam, gdzie potwierdzenia
zabrakło (fundusze Beta ETF z GPW nie są notowane we Frankfurcie), pola `isin`
po prostu nie ma i cały ten moduł się nie odzywa.
"""

from __future__ import annotations

import logging
import threading
import time

import requests

log = logging.getLogger("etf.xetra")

BASE = "https://api.boerse-frankfurt.de/v1"
SNAPSHOT_TTL = 24 * 3600     # opłata i aktywa zmieniają się rzadziej niż raz na dobę
LIVE_TTL = 5 * 60            # cena i wyniki — jak reszta listy

#: Przedstawiamy się z nazwą serwisu i kontaktem — tak, jak wypada odpytywać
#: cudze API i jak wymagają tego regulaminy takich usług.
UA = {"User-Agent": "Portevo/1.0 (https://portevo.pl)",
      "Accept": "application/json", "Content-Type": "application/json"}

_session = requests.Session()
_session.headers.update(UA)

_lock = threading.Lock()
_snapshot: dict[str, dict] = {}
_snapshot_at = 0.0
_live: dict[str, tuple[float, dict]] = {}


# ----------------------------------------------------------- migawka uniwersum

def _pct(v):
    """Opłata przychodzi jako ułamek (0.0033) — oddajemy procenty (0.33)."""
    return round(v * 100, 3) if isinstance(v, (int, float)) else None


def _row(x: dict) -> dict:
    ov = x.get("overview") or {}
    kd = x.get("keyData") or {}
    perf = x.get("performance") or {}
    uop = kd.get("useOfProfits") or {}
    uop = uop.get("originalValue") if isinstance(uop, dict) else uop
    bench = kd.get("benchmark") or {}
    return {
        "isin": x.get("isin") or "",
        "name": (x.get("name") or {}).get("originalValue") or "",
        "ter_pct": _pct(ov.get("totalExpenseRatio")),
        "aum": ov.get("assetsUnderManagement"),
        "currency": (ov.get("currency") or {}).get("originalValue") or "",
        "issuer": kd.get("issuer") or "",
        "benchmark": (bench.get("originalValue") if isinstance(bench, dict) else bench) or "",
        "replication": kd.get("replicationMethod") or "",
        "acc": (uop == "Accumulating") if uop else None,
        "y1_pct": perf.get("performance1Year"),
        "m3_pct": perf.get("performance3Month"),
        "m6_pct": perf.get("performance6Month"),
        "w52_high": perf.get("weeks52High"),
        "w52_low": perf.get("weeks52Low"),
    }


def _fetch_snapshot(wanted: set[str]) -> dict[str, dict]:
    """Całe uniwersum ETP z Frankfurtu, przefiltrowane do naszych ISIN-ów."""
    out: dict[str, dict] = {}
    offset = 0
    while offset < 8000:
        r = _session.post(f"{BASE}/search/etp_search",
                          json={"limit": 1000, "offset": offset}, timeout=40)
        r.raise_for_status()
        data = r.json().get("data") or []
        for x in data:
            if x.get("isin") in wanted:
                out[x["isin"]] = _row(x)
        offset += len(data)
        if len(data) < 1000:
            break
    return out


def _ensure_snapshot() -> dict[str, dict]:
    global _snapshot, _snapshot_at
    with _lock:
        fresh = _snapshot and time.time() - _snapshot_at < SNAPSHOT_TTL
        if fresh:
            return _snapshot
    from . import catalog as cat
    wanted = {e["isin"] for e in cat.CATALOG if e.get("isin")}
    if not wanted:
        return {}
    try:
        snap = _fetch_snapshot(wanted)
    except Exception as e:                                       # noqa: BLE001
        log.warning("migawka Frankfurt: %s", e)
        with _lock:
            return _snapshot                    # lepiej stara migawka niż żadna
    with _lock:
        _snapshot, _snapshot_at = snap, time.time()
    log.info("Frankfurt: migawka %d funduszy", len(snap))
    return snap


def fund(isin: str) -> dict:
    """Opłata, aktywa, emitent i indeks dla funduszu o danym ISIN-ie."""
    if not isin:
        return {}
    return _ensure_snapshot().get(isin) or {}


def warm() -> None:
    """Pobiera migawkę w tle — wołane przy starcie listy funduszy."""
    try:
        _ensure_snapshot()
    except Exception:                                            # noqa: BLE001
        pass


# ------------------------------------------------------------- dane na żywo

def _live_get(kind: str, isin: str, path: str) -> dict:
    key = f"{kind}:{isin}"
    now = time.time()
    with _lock:
        hit = _live.get(key)
        if hit and hit[0] > now:
            return hit[1]
    try:
        r = _session.get(f"{BASE}/data/{path}",
                         params={"isin": isin, "mic": "XETR"}, timeout=15)
        out = r.json() if r.status_code == 200 else {}
        if not isinstance(out, dict):
            out = {}
    except Exception as e:                                       # noqa: BLE001
        log.warning("Frankfurt %s %s: %s", kind, isin, e)
        out = {}
    with _lock:
        _live[key] = (now + LIVE_TTL, out)
    return out


def quote(isin: str) -> dict:
    """Bieżąca cena i zmiana dnia z Xetry. Pusto, gdy papier tam nie jest notowany."""
    if not isin:
        return {}
    js = _live_get("q", isin, "quote_box/single")
    price = js.get("lastPrice")
    if not isinstance(price, (int, float)):
        return {}
    return {
        "price": float(price),
        "change_pct": js.get("changeToPrevDayInPercent"),
        "open": js.get("open"),
        # Xetra rozlicza w euro — to nie zawsze waluta naszej linii notowań,
        # więc cena stąd nadaje się na zapchajdziurę, nie do liczenia wyniku
        "currency": js.get("tradingCurrency") or "EUR",
        "at": js.get("timestamp") or "",
    }


def performance(isin: str) -> dict:
    """Wyniki 1M/3M/6M/1R liczone przez giełdę, w walucie notowania na Xetrze."""
    if not isin:
        return {}
    js = _live_get("p", isin, "performance")

    def ch(node):
        v = (js.get(node) or {}).get("changeInPercent")
        return round(v, 2) if isinstance(v, (int, float)) else None

    out = {"m1": ch("months1"), "m3": ch("months3"),
           "m6": ch("months6"), "y1": ch("years1")}
    return out if any(v is not None for v in out.values()) else {}
