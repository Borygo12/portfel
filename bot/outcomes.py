"""Śledzenie, co stało się z kursem PO analizie newsa.

Bot nie składa zleceń i niczego nie poleca. Zapisuje jednak, jaki wydźwięk
przypisał wiadomości i jak zachował się kurs w kolejnych godzinach — dzięki temu
da się pokazać liczbę zamiast obietnicy: „na tylu a tylu analizach kurs poszedł
w stronę wskazanego wydźwięku".

Zapis w `outcomes.json` obok bota. Ceny bierzemy z tego samego darmowego źródła
co portfel (Yahoo), więc nie potrzeba żadnego brokera.

Każdy wpis:
    {"id", "ts", "ticker", "tone", "strength", "source", "price0", "currency",
     "checks": {"1h": {"price", "change_pct", "aligned"}, "1d": {...}}}

`tone` to "pozytywny" albo "negatywny" — opis wydźwięku wiadomości, nie zalecenie.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time

log = logging.getLogger("outcomes")

import paths

_FILE = paths.data_path("outcomes.json")
_lock = threading.Lock()

# po jakim czasie sprawdzamy kurs (sekundy) -> etykieta w danych
HORIZONS = {"1h": 3600, "1d": 86400}

# Ile wpisów trzymamy. Starsze wypadają — to statystyka skuteczności analiz,
# nie archiwum wieczyste.
MAX_ENTRIES = 2000


def _load() -> list:
    try:
        with open(_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    except Exception:
        log.exception("Nie udało się wczytać outcomes.json")
        return []


def _save(entries: list) -> None:
    tmp = _FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries[-MAX_ENTRIES:], f, ensure_ascii=False)
    os.replace(tmp, _FILE)


def _price(ticker: str) -> tuple[float | None, str]:
    """Bieżący kurs waloru. Zwraca (cena, waluta) albo (None, "")."""
    try:
        from portfolio import prices as pf_prices
        q = pf_prices.live_quotes([ticker]).get(ticker)
        if q and q.get("price"):
            return float(q["price"]), q.get("currency", "")
    except Exception as e:
        log.debug("Brak kursu dla %s: %s", ticker, e)
    return None, ""


def record(ticker: str, tone: str, strength: int, source: str) -> None:
    """Zapamiętaj punkt startowy tuż po analizie. Cicho odpuszcza, gdy brak kursu."""
    price, currency = _price(ticker)
    if price is None:
        return
    entry = {
        "id": f"{ticker}-{int(time.time() * 1000)}",
        "ts": time.time(),
        "ticker": ticker,
        "tone": tone,
        "strength": strength,
        "source": source,
        "price0": price,
        "currency": currency,
        "checks": {},
    }
    with _lock:
        entries = _load()
        entries.append(entry)
        _save(entries)


def tick() -> int:
    """Dopisz pomiary, którym minął czas. Zwraca liczbę uzupełnionych pomiarów.

    Wołane z pętli bota co cykl — samo pilnuje, żeby nie odpytywać za często.
    """
    now = time.time()
    with _lock:
        entries = _load()
        due: list[tuple[dict, str]] = []
        for e in entries:
            for label, delay in HORIZONS.items():
                if label not in e.get("checks", {}) and now - e["ts"] >= delay:
                    due.append((e, label))
        if not due:
            return 0

    filled = 0
    for entry, label in due:
        price, _ = _price(entry["ticker"])
        if price is None:
            continue
        change = (price - entry["price0"]) / entry["price0"] * 100 if entry["price0"] else 0.0
        # „zgodny" = kurs poszedł w stronę wskazanego wydźwięku. To opis faktu,
        # nie ocena trafności rekomendacji — bot żadnej nie wydaje.
        aligned = change > 0 if entry["tone"] == "pozytywny" else change < 0
        entry.setdefault("checks", {})[label] = {
            "price": price,
            "change_pct": round(change, 2),
            "aligned": aligned,
        }
        filled += 1

    if filled:
        with _lock:
            # wczytujemy ponownie, bo w międzyczasie mógł dojść nowy wpis
            current = {e["id"]: e for e in _load()}
            for entry, _ in due:
                if entry["id"] in current:
                    current[entry["id"]]["checks"] = entry.get("checks", {})
            _save(sorted(current.values(), key=lambda e: e["ts"]))
    return filled


def stats() -> dict:
    """Podsumowanie do panelu: ile analiz, ile z nich kurs potwierdził."""
    entries = _load()
    out = {"total": len(entries), "horizons": {}}
    for label in HORIZONS:
        measured = [e for e in entries if label in e.get("checks", {})]
        aligned = [e for e in measured if e["checks"][label]["aligned"]]
        moves = [abs(e["checks"][label]["change_pct"]) for e in measured]
        out["horizons"][label] = {
            "measured": len(measured),
            "aligned": len(aligned),
            "aligned_pct": round(len(aligned) / len(measured) * 100, 1) if measured else None,
            "avg_move_pct": round(sum(moves) / len(moves), 2) if moves else None,
        }
    return out


def recent(limit: int = 100) -> list:
    """Ostatnie wpisy, od najnowszego."""
    return sorted(_load(), key=lambda e: e["ts"], reverse=True)[:limit]
