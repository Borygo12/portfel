"""Wspólny cache sekcji Earnings — pamięć + dysk.

Dysk jest tu istotny: kalendarz miesięczny to 30 zapytań do Nasdaqa, a panel
bywa restartowany kilka razy dziennie. Bez zapisu na dysk każdy restart oznaczałby
minutę czekania na pierwszy widok.

Klucze są nazwami plików, więc muszą być bezpieczne — `_safe` zamienia wszystko
poza [a-z0-9._-] na podkreślenie.
"""

import json
import logging
import os
import re
import threading
import time

log = logging.getLogger("earnings.cache")

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "portfolio_data", "earnings_cache")
_mem: dict = {}
_lock = threading.Lock()

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,pl;q=0.8",
}


def _safe(key: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "_", key.lower())[:120]


def _path(key: str) -> str:
    return os.path.join(_DIR, _safe(key) + ".json")


def get(key: str, ttl: int):
    """Świeży wpis albo None. Najpierw pamięć, potem dysk."""
    now = time.time()
    with _lock:
        hit = _mem.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        with open(_path(key), encoding="utf-8") as f:
            saved = json.load(f)
        if now - saved.get("at", 0) < ttl:
            with _lock:
                _mem[key] = (saved["at"], saved["data"])
            return saved["data"]
    except (OSError, ValueError):
        pass
    return None


def put(key: str, data) -> None:
    now = time.time()
    with _lock:
        _mem[key] = (now, data)
    try:
        os.makedirs(_DIR, exist_ok=True)
        tmp = _path(key) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"at": now, "data": data}, f, ensure_ascii=False)
        os.replace(tmp, _path(key))
    except OSError as e:
        log.debug("Cache zapis %s: %s", key, e)


def cached(key: str, ttl: int, build):
    """Wynik `build()` z cache. Gdy budowanie padnie, oddajemy STARY wpis.

    Świadomie: kalendarz sprzed godziny jest dużo lepszy niż pusty ekran,
    gdy Nasdaq akurat nie odpowiada.
    """
    hit = get(key, ttl)
    if hit is not None:
        return hit
    try:
        data = build()
    except Exception as e:  # noqa: BLE001
        log.warning("Cache build %s: %s", key, e)
        data = None
    if data is None:
        stale = get(key, 10 ** 9)
        return stale
    put(key, data)
    return data
