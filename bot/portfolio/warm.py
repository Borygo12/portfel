"""Podgrzewanie danych, dopóki apka jest otwarta.

Problem: każde wejście na ekran czekało na Yahoo (kursy + słupki śróddzienne).
Rozwiązanie: gdy z apki przychodzi ruch, w tle startuje wątek, który co kilkanaście
sekund odświeża te same cache. Odczyty z apki trafiają wtedy w gotowe dane —
odpowiedź jest natychmiastowa, a notowania są świeższe, niż gdyby czekać na kliknięcie.

Wątek żyje tylko przez ACTIVE_SEC od ostatniego zapytania, więc po zamknięciu apki
sam gaśnie i nic nie pobiera. Świadomie nie jest to demon odpalany razem z panelem —
przy zamkniętej apce nikt tych danych nie potrzebuje.

Przy wielu użytkownikach dochodzi rzecz, której w wersji jednoosobowej nie było:
wątek działa POZA żądaniem, więc nie zna zalogowanego. Tożsamość trzeba mu podać
jawnie — inaczej albo nie odczyta niczego, albo (gorzej) odczytałby cudze dane.
Dlatego `touch()` przyjmuje identyfikator, a pętla podgrzewa po kolei dla każdego,
kto miał ruch w ostatnich ACTIVE_SEC. Notowania i tak lądują we wspólnym cache,
więc dwie osoby z tą samą spółką nie pobierają jej dwa razy.
"""

import logging
import threading
import time

import db

log = logging.getLogger("portfolio.warm")

REFRESH_SEC = 10        # co ile odświeżamy w tle
ACTIVE_SEC = 120        # jak długo po ostatnim zapytaniu uznajemy apkę za otwartą

_thread: threading.Thread | None = None
_lock = threading.Lock()
# user_id -> znacznik ostatniego ruchu
_active: dict[str, float] = {}
_stats = {"cycles": 0, "last_ok": 0.0, "last_ms": 0, "last_error": ""}


def touch(user_id: str = "") -> None:
    """Sygnał „apka właśnie coś czytała" — utrzymuje wątek odświeżania przy życiu."""
    global _thread
    uid = user_id or db.current_user()
    if not uid:
        return
    with _lock:
        _active[uid] = time.time()
        if _thread and _thread.is_alive():
            return
        _thread = threading.Thread(target=_loop, name="portfolio-warm", daemon=True)
        _thread.start()


def _live_users() -> list:
    now = time.time()
    with _lock:
        for uid, ts in list(_active.items()):
            if now - ts >= ACTIVE_SEC:
                _active.pop(uid, None)
        return list(_active)


def status() -> dict:
    """Informacja dla UI: czy dane są podgrzewane i jak świeże są."""
    uid = db.current_user()
    with _lock:
        active = bool(uid) and time.time() - _active.get(uid, 0.0) < ACTIVE_SEC
    return {
        "active": active,
        "refresh_sec": REFRESH_SEC,
        "cycles": _stats["cycles"],
        "age_sec": int(time.time() - _stats["last_ok"]) if _stats["last_ok"] else None,
        "last_ms": _stats["last_ms"],
        "last_error": _stats["last_error"],
    }


def _loop() -> None:
    from . import intraday

    while True:
        users = _live_users()
        if not users:
            return
        started = time.time()
        for uid in users:
            try:
                db.set_current_user(uid)
                # jedno wywołanie odświeża wszystko naraz: engine.compute() ciągnie
                # notowania i kursy walut, a session() dokłada słupki śróddzienne
                intraday.session()
                _stats["last_ok"] = time.time()
                _stats["last_error"] = ""
            except Exception as e:  # noqa: BLE001 — w tle nie mamy komu tego zgłosić
                _stats["last_error"] = str(e)[:200]
                log.warning("Podgrzewanie (%s): %s", uid[:8], e)
            finally:
                db.set_current_user("")
        _stats["cycles"] += 1
        _stats["last_ms"] = int((time.time() - started) * 1000)
        time.sleep(max(1.0, REFRESH_SEC - (time.time() - started)))
