"""Pamięć procesu — pomiar i oddawanie jej systemowi.

Na Railway płaci się za zajętą pamięć co do minuty, a nie za ruch: 1 GB trzymany
przez miesiąc to około 10 $, czy ktoś z aplikacji korzysta, czy nie. Dlatego
warto wiedzieć, KTÓRE zadanie tła ją nabiera — i oddać ją zaraz po nim.

Dwie rzeczy, których Python sam nie robi:

* **pomiar** — `/proc/self/status` (Linux), bez dodatkowych paczek. Na Windowsie
  zwracamy None i nic się nie loguje;
* **zwrot** — po `del` pamięć wraca do puli glibc, ale nie do systemu, więc
  rachunek dalej ją liczy. `malloc_trim(0)` oddaje wolne strony naprawdę.
"""

from __future__ import annotations

import ctypes
import gc
import logging

log = logging.getLogger("memstat")

_libc = None


def rss_mb() -> float | None:
    """Pamięć zajęta przez proces w MB albo None, gdy systemu nie da się zapytać."""
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for linia in f:
                if linia.startswith("VmRSS:"):
                    return round(int(linia.split()[1]) / 1024, 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


def zwolnij() -> None:
    """Sprząta nieużywane obiekty i oddaje wolną pamięć systemowi (tylko glibc)."""
    global _libc
    gc.collect()
    if _libc is False:
        return
    try:
        if _libc is None:
            _libc = ctypes.CDLL("libc.so.6")
        _libc.malloc_trim(0)
    except (OSError, AttributeError):
        _libc = False                     # Windows, musl — nie próbujemy w kółko


def po_zadaniu(nazwa: str, przed: float | None, prog_mb: float = 80) -> float | None:
    """Wołane po zadaniu tła: oddaje pamięć i zapisuje w logu zadania, które
    nabrały jej dużo — po tym widać w Railway, kto winien skokom na wykresie."""
    szczyt = rss_mb()
    zwolnij()
    po = rss_mb()
    if przed is not None and szczyt is not None and szczyt - przed >= prog_mb:
        log.warning("Pamięć: zadanie %s nabrało %.0f MB (%.0f → %.0f MB), po sprzątaniu %.0f MB",
                    nazwa, szczyt - przed, przed, szczyt, po or 0)
    return po
