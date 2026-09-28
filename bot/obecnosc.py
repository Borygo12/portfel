"""Obecność: kto jest w Portevo teraz i ilu ludzi było danego dnia.

Aplikacja (telefon, przeglądarka) i podstrony pozycjonowane pukają co minutę na
`POST /api/ping` z losowym identyfikatorem urządzenia. Tu sygnały lądują w pamięci,
a zegar co `FLUSH_S` sekund odsyła paczkę do Supabase (`activity_bump`, migracja
0009) — jeden zapis na pół minuty zamiast jednego na każdy sygnał każdej osoby.

Paczka niesie PRZYROSTY (minuty, odsłony ekranów), a baza je dodaje. Dzięki temu
restart serwera w środku dnia gubi najwyżej ostatnie pół minuty, a nie cały dzień.

Czyta to Kokpit (`activity_summary`), nie aplikacja.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timezone

import requests

import supabase_auth as sa

log = logging.getLogger("obecnosc")

FLUSH_S = 30
# Sygnał przychodzi co minutę; minuta obecności liczy się, gdy od poprzedniej
# policzonej minęło co najmniej tyle. Zmiana ekranu wysyła sygnał od razu,
# więc bez tego progu szybkie klikanie po zakładkach nabijałoby czas.
_MINUTA_S = 45

PLATFORMY = {"ios", "android", "web", "seo"}
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_EKRAN_RE = re.compile(r"[^a-z0-9_./-]")
# Robot wyszukiwarki uruchamia JavaScript podstron, więc wysłałby sygnał jak człowiek.
_ROBOT_RE = re.compile(r"bot|crawl|spider|slurp|lighthouse|headless|preview|facebookexternalhit",
                       re.I)

_lock = threading.Lock()
# visitor -> {user_id, platform, first_seen, last_seen, minutes, screens, _minuta}
_bufor: dict[str, dict] = {}
# visitor -> czas ostatnio policzonej minuty; przeżywa wysyłkę paczki
_ostatnia_minuta: dict[str, float] = {}
_zegar: threading.Thread | None = None


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def robot(user_agent: str) -> bool:
    return not user_agent or bool(_ROBOT_RE.search(user_agent))


def ping(visitor: str, platform: str, screen: str = "", user_id: str = "") -> bool:
    """Zapisuje sygnał w pamięci. Zwraca False, gdy dane są niepoprawne."""
    if not _ID_RE.match(visitor or "") or platform not in PLATFORMY:
        return False
    uid = user_id if _UUID_RE.match(user_id or "") else ""
    ekran = _EKRAN_RE.sub("", (screen or "").lower())[:48]
    teraz = time.time()

    with _lock:
        w = _bufor.get(visitor)
        if w is None:
            w = _bufor[visitor] = {"user_id": "", "platform": platform, "first_seen": teraz,
                                   "last_seen": teraz, "minutes": 0, "screens": {}}
        w["last_seen"] = teraz
        w["platform"] = platform
        if uid:
            w["user_id"] = uid
        if teraz - _ostatnia_minuta.get(visitor, 0) >= _MINUTA_S:
            w["minutes"] += 1
            _ostatnia_minuta[visitor] = teraz
        if ekran:
            w["screens"][ekran] = w["screens"].get(ekran, 0) + 1
    _uruchom_zegar()
    return True


def _wyslij() -> None:
    with _lock:
        if not _bufor:
            return
        paczka = dict(_bufor)
        _bufor.clear()
        # sprzątanie: urządzenia nieaktywne od godziny nie potrzebują progu minuty
        granica = time.time() - 3600
        for v in [v for v, t in _ostatnia_minuta.items() if t < granica]:
            _ostatnia_minuta.pop(v, None)

    wiersze = [{"visitor": v, "user_id": w["user_id"], "platform": w["platform"],
                "first_seen": _iso(w["first_seen"]), "last_seen": _iso(w["last_seen"]),
                "minutes": w["minutes"], "screens": w["screens"]}
               for v, w in paczka.items()]
    if not (sa.URL and sa.SERVICE):
        return
    try:
        r = requests.post(
            f"{sa.URL}/rest/v1/rpc/activity_bump",
            json={"p_rows": wiersze},
            headers={"apikey": sa.SERVICE, "Authorization": f"Bearer {sa.SERVICE}",
                     "Content-Type": "application/json"},
            timeout=10,
        )
        if r.status_code >= 300:
            log.warning("Obecność: baza odrzuciła paczkę (%s): %s", r.status_code, r.text[:200])
            _odloz(paczka)
    except requests.RequestException as e:
        log.warning("Obecność: brak połączenia z bazą: %s", e)
        _odloz(paczka)


def _odloz(paczka: dict) -> None:
    """Nieudana wysyłka wraca do bufora i pójdzie z następną paczką."""
    with _lock:
        if len(_bufor) > 20000:     # baza leży od dawna — nie puchniemy w nieskończoność
            return
        for v, stare in paczka.items():
            w = _bufor.get(v)
            if w is None:
                _bufor[v] = stare
                continue
            w["first_seen"] = min(w["first_seen"], stare["first_seen"])
            w["minutes"] += stare["minutes"]
            w["user_id"] = w["user_id"] or stare["user_id"]
            for k, n in stare["screens"].items():
                w["screens"][k] = w["screens"].get(k, 0) + n


def _petla() -> None:
    while True:
        time.sleep(FLUSH_S)
        try:
            _wyslij()
        except Exception:  # noqa: BLE001 — zegar statystyk nie może umrzeć po cichu
            log.exception("Obecność: wysyłka paczki się nie udała")


def _uruchom_zegar() -> None:
    global _zegar
    if _zegar and _zegar.is_alive():
        return
    with _lock:
        if _zegar and _zegar.is_alive():
            return
        _zegar = threading.Thread(target=_petla, name="obecnosc", daemon=True)
        _zegar.start()
