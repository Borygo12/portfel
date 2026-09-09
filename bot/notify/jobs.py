"""Zegar powiadomień o wynikach — wątek tła odpalający zadania o stałych porach.

Świadomie bez `cron` i bez zewnętrznego harmonogramu: serwer i tak chodzi cały
czas, a jeden wątek budzący się co minutę jest tańszy w utrzymaniu niż usługa,
o której trzeba pamiętać przy każdej przeprowadzce hostingu.

Godziny liczymy w czasie POLSKIM, nie serwerowym. Kontener w Railway stoi na
UTC, więc bez tej zamiany „ósma rano" wypadałaby o dziewiątej latem i o dziesiątej
zimą — czyli powiadomienie o porannych wynikach przychodziłoby po ich publikacji.

Podwójne odpalenie nie boli: kluczem przeciw duplikatom w skrzynce jest DATA
(`earnings:2026-09-09`), więc restart serwera minutę po wysyłce nie wyśle jej
drugi raz. Znacznik w pamięci jest tylko po to, żeby nie liczyć tego samego
kalendarza kilkanaście razy pod rząd.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time

log = logging.getLogger("notify.jobs")

try:
    from zoneinfo import ZoneInfo
    STREFA = ZoneInfo("Europe/Warsaw")
except Exception:  # noqa: BLE001 — brak bazy stref nie może wywrócić serwera
    STREFA = None

# Wyniki spółek z USA publikowane „przed otwarciem" wychodzą koło południa czasu
# polskiego, więc ósma rano daje realny zapas na zajrzenie do aplikacji.
GODZINA_DZIENNA = 8
# Przegląd tygodnia w poniedziałek, kwadrans wcześniej — żeby dwa powiadomienia
# nie przyszły w tej samej minucie.
GODZINA_TYGODNIOWA = 7

_watek: threading.Thread | None = None
_stop = threading.Event()
_ostatnie: dict[str, str] = {}          # nazwa zadania -> data ostatniego odpalenia


def _teraz() -> dt.datetime:
    return dt.datetime.now(STREFA) if STREFA else dt.datetime.now()


def _odpal(nazwa: str, dzien: str, funkcja) -> None:
    if _ostatnie.get(nazwa) == dzien:
        return
    _ostatnie[nazwa] = dzien
    try:
        funkcja()
    except Exception as e:  # noqa: BLE001 — zadanie nie może zabić zegara
        log.exception("Zadanie %s nie wyszło: %s", nazwa, e)


def _petla() -> None:
    from . import earnings

    log.info("Zegar powiadomień wystartował (strefa: %s)",
             STREFA or "systemowa")
    while not _stop.is_set():
        try:
            teraz = _teraz()
            dzien = teraz.date().isoformat()

            if teraz.hour == GODZINA_TYGODNIOWA and teraz.weekday() == 0:
                _odpal("tydzien", dzien, earnings.tydzien)

            if teraz.hour == GODZINA_DZIENNA and teraz.weekday() < 5:
                _odpal("dzien", dzien, earnings.dzisiejsze)

        except Exception as e:  # noqa: BLE001
            log.warning("Zegar powiadomień potknął się: %s", e)

        # Minuta zwłoki wystarczy — zadania odpalają się raz na dobę, a krótszy
        # sen tylko podbijałby zużycie procesora bez żadnego zysku.
        _stop.wait(60)
    log.info("Zegar powiadomień zatrzymany")


def start() -> bool:
    """Uruchamia zegar. Drugie wywołanie nic nie robi."""
    global _watek
    if _watek and _watek.is_alive():
        return False
    _stop.clear()
    _watek = threading.Thread(target=_petla, name="notify-clock", daemon=True)
    _watek.start()
    return True


def stop() -> None:
    _stop.set()


def stan() -> dict:
    return {
        "alive": bool(_watek and _watek.is_alive()),
        "ostatnie": dict(_ostatnie),
        "godziny": {"dzienne": GODZINA_DZIENNA, "tygodniowe": GODZINA_TYGODNIOWA},
    }
