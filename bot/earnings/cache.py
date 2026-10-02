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

def _katalog_cache() -> str:
    """Gdzie trzymamy cache na dysku — z uwzględnieniem woluminu na hostingu.

    **Domyślnie `bot/portfolio_data/earnings_cache`, ale kontener bez trwałego
    dysku kasuje ten katalog przy każdym wdrożeniu.** Skutek widać było gołym
    okiem: strony zbiorcze (dywidendy, reakcje kursu) po każdym pushu wracały do
    stanu „dane się zbierają" i musiały odbudować kilkaset plików, co zajmowało
    pół godziny.

    Railway po podpięciu woluminu ustawia `RAILWAY_VOLUME_MOUNT_PATH` na ścieżkę
    montowania. Czytamy ją zamiast zakładać, że wolumin wisi akurat tam, gdzie
    leży kod — bo nie musi i u nas nie wisiał. Dzięki temu wolumin działa bez
    względu na to, jaką ścieżkę ktoś wpisał w panelu, a lokalnie (gdzie tej
    zmiennej nie ma) nic się nie zmienia.

    `DATA_DIR` daje to samo ręcznie — przydaje się na innym hostingu i w testach.
    """
    reczny = (os.environ.get("DATA_DIR") or "").strip()
    wolumin = (os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or "").strip()
    baza = reczny or wolumin
    if baza:
        return os.path.join(baza, "earnings_cache")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "portfolio_data", "earnings_cache")


_DIR = _katalog_cache()
_lock = threading.Lock()

# Pamięć ma LIMIT — dysk nie. Bez limitu każdy klucz, o który ktokolwiek zapytał,
# zostawał w procesie do restartu: notowania z dwóch lat dla każdej spółki, którą
# tknął jakiś insider, to kilka tysięcy wpisów po ~50 KB, czyli setki MB RAM-u,
# za które hosting liczy co do minuty. Trzymamy więc tylko ostatnio używane
# (słownik zachowuje kolejność — trafiony wpis idzie na koniec, wypadają
# z początku); reszta wraca z pliku w milisekundę.
#
# Rozmiar wpisu liczymy długością jego JSON-a. W pamięci Pythona to samo zajmuje
# 3–5 razy więcej, więc 24 MB tekstu to około 100 MB procesu.
_MEM_LIMIT = int(float(os.environ.get("EARNINGS_CACHE_MEM_MB", "24")) * 1024 * 1024)
_mem: dict = {}                 # klucz -> (czas, dane, rozmiar)
_mem_rozmiar = 0


def _zapamietaj(key: str, at: float, data, rozmiar: int) -> None:
    """Wstawia wpis na koniec kolejki i wyrzuca najdawniej używane ponad limit.
    Wołać z `_lock`."""
    global _mem_rozmiar
    stary = _mem.pop(key, None)
    if stary:
        _mem_rozmiar -= stary[2]
    if rozmiar > _MEM_LIMIT // 4:
        return                          # olbrzym wypchnąłby wszystko inne — zostaje na dysku
    _mem[key] = (at, data, rozmiar)
    _mem_rozmiar += rozmiar
    while _mem_rozmiar > _MEM_LIMIT and _mem:
        _mem_rozmiar -= _mem.pop(next(iter(_mem)))[2]

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
    global _mem_rozmiar
    now = time.time()
    with _lock:
        hit = _mem.get(key)
        if hit:
            if now - hit[0] < ttl:
                _mem[key] = _mem.pop(key)       # trafiony = ostatnio używany
                return hit[1]
            # przeterminowany wpis nie ma po co leżeć w pamięci
            _mem_rozmiar -= _mem.pop(key)[2]
    try:
        with open(_path(key), encoding="utf-8") as f:
            tekst = f.read()
        saved = json.loads(tekst)
        if now - saved.get("at", 0) < ttl:
            with _lock:
                _zapamietaj(key, saved["at"], saved["data"], len(tekst))
            return saved["data"]
    except (OSError, ValueError):
        pass
    return None


def saved_at(key: str):
    """Kiedy wpis został zapisany (czas uniksowy) albo None, gdy go nie ma.

    Potrzebne tam, gdzie sam wiek wpisu nie wystarcza: dzień z kalendarza wyników
    zapisany W TRAKCIE tego dnia nie ma jeszcze wyników spółek raportujących
    wieczorem, więc nie wolno go traktować jak zamkniętej przeszłości.
    """
    with _lock:
        hit = _mem.get(key)
        if hit:
            return hit[0]
    try:
        with open(_path(key), encoding="utf-8") as f:
            return json.load(f).get("at")
    except (OSError, ValueError):
        return None


def put(key: str, data) -> None:
    now = time.time()
    try:
        tekst = json.dumps({"at": now, "data": data}, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        # danych nie da się zapisać — zostają tylko w pamięci, jak dotąd
        log.debug("Cache zapis %s: %s", key, e)
        with _lock:
            _zapamietaj(key, now, data, 4096)
        return
    with _lock:
        _zapamietaj(key, now, data, len(tekst))
    try:
        os.makedirs(_DIR, exist_ok=True)
        tmp = _path(key) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(tekst)
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
