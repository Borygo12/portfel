"""Jedno miejsce, w którym decyduje się, gdzie serwer zapisuje pliki.

Na komputerze pliki leżały obok kodu i to działało. W chmurze kontener jest
budowany od nowa przy każdym wdrożeniu — wszystko, co leży obok kodu, znika.
Bez tego modułu każdy deploy kasowałby ustawienia suwaków i historię analiz.

`PORTEVO_DATA_DIR` wskazuje katalog, który przeżywa wdrożenie (w Railway: dysk
podpięty pod /data). Gdy zmiennej nie ma — czyli u Ciebie na komputerze —
zostaje katalog `bot/`, dokładnie jak dotąd.

Dane portfela NIE są tutaj: siedzą w Supabase (patrz db.py). Tu zostają pliki
robocze samego serwera i bota.
"""

import os

BOT_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.abspath(os.environ.get("PORTEVO_DATA_DIR") or BOT_DIR)


def data_path(*parts: str) -> str:
    """Ścieżka do pliku roboczego. Tworzy katalog, gdy trzeba."""
    full = os.path.join(DATA_DIR, *parts)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    return full


def ensure() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
