"""Jedno miejsce, w którym decyduje się, gdzie serwer zapisuje pliki.

Na komputerze pliki leżały obok kodu i to działało. W chmurze kontener jest
budowany od nowa przy każdym wdrożeniu — wszystko, co leży obok kodu, znika.
Bez tego modułu każdy deploy kasowałby ustawienia suwaków i historię analiz.

`PORTEVO_DATA_DIR` wskazuje katalog, który przeżywa wdrożenie (w Railway: dysk
podpięty pod /data). Gdy zmiennej nie ma — czyli u Ciebie na komputerze —
zostaje katalog `bot/`, dokładnie jak dotąd.

Dane portfela NIE są tutaj: siedzą w Supabase (patrz db.py). Tu zostają pliki
robocze samego serwera i bota.

DLACZEGO KATALOG JEST SPRAWDZANY, A NIE PRZYJMOWANY NA WIARĘ
------------------------------------------------------------
Dysk w Railway podpina się pod `/data` już PO zbudowaniu obrazu i należy do
roota, a serwer chodzi jako `portevo` (uid 10001). Katalog wtedy istnieje i da
się z niego czytać, więc wszystko wygląda normalnie — dopóki coś nie spróbuje
ZAPISAĆ. Wtedy leci `PermissionError` i, zanim to naprawiliśmy, pierwszym
objawem było okno logowania przy przycisku „Uruchom nasłuch": jedyny zapis na
tej ścieżce (`params.json`) wywracał żądanie, a serwer mylił ten wyjątek
z brakiem tożsamości.

Dlatego przy starcie próbujemy naprawdę zapisać plik próbny. Gdy się nie uda,
schodzimy na katalog tymczasowy i mówimy o tym głośno (`PROBLEM` widać w panelu
dewelopera) — serwer działa dalej, tylko ustawienia nie przeżyją wdrożenia.
"""

import logging
import os
import tempfile

log = logging.getLogger("paths")

BOT_DIR = os.path.dirname(os.path.abspath(__file__))

# Opis kłopotu z katalogiem danych albo pusty string. Panel dewelopera pokazuje
# to właścicielowi, żeby „ustawienia znikają po deployu" nie było zagadką.
PROBLEM = ""


def _zapisywalny(katalog: str) -> str:
    """Czy da się w tym katalogu utworzyć plik. Zwraca powód odmowy albo ''."""
    try:
        os.makedirs(katalog, exist_ok=True)
    except OSError as e:
        return f"nie da się utworzyć katalogu: {e}"
    try:
        probny = os.path.join(katalog, ".portevo-zapis")
        with open(probny, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probny)
    except OSError as e:
        return f"katalog istnieje, ale nie mam prawa zapisu: {e}"
    return ""


def _wybierz() -> str:
    """Katalog danych: żądany, a gdy nie da się w nim pisać — zapasowy."""
    global PROBLEM
    zadany = os.path.abspath(os.environ.get("PORTEVO_DATA_DIR") or BOT_DIR)
    powod = _zapisywalny(zadany)
    if not powod:
        return zadany

    zapasowy = os.path.join(tempfile.gettempdir(), "portevo-data")
    PROBLEM = (f"Katalog danych {zadany} jest tylko do odczytu ({powod}). "
               f"Pliki robocze idą do {zapasowy} i ZNIKNĄ przy następnym wdrożeniu. "
               f"W Railway: dysk podpięty pod {zadany} należy do roota — "
               f"naprawia to zmienna RAILWAY_RUN_UID=0 albo chown w entrypoincie.")
    log.error("%s", PROBLEM)
    if _zapisywalny(zapasowy):
        # nawet katalog tymczasowy odmówił — zostajemy przy żądanym i niech
        # błędy zapisu lecą tam, gdzie widać je w logu razem z tym ostrzeżeniem
        return zadany
    return zapasowy


DATA_DIR = _wybierz()


def data_path(*parts: str) -> str:
    """Ścieżka do pliku roboczego. Tworzy katalog, gdy trzeba."""
    full = os.path.join(DATA_DIR, *parts)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    return full


def ensure() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
