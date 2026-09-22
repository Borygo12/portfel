"""IndexNow — mówimy wyszukiwarkom o nowych stronach, zamiast czekać, aż wpadną.

Google wycofał pingowanie sitemapy, ale Bing, Yandex, Seznam i Naver (a przez
Binga także Copilot i część odpowiedzi AI) przyjmują IndexNow: jeden POST
z listą adresów i strona trafia do kolejki indeksowania w kilkanaście minut
zamiast w kilka tygodni. Dla serwisu z żywymi danymi — nowy profil insidera,
nowe transakcje — to różnica między „jest w wyszukiwarce" a „nikt tego nie widzi".

Zasada działania: serwis udostępnia plik `<klucz>.txt` z tym samym kluczem
w treści (dowód, że adres należy do nas), a potem wysyła listy adresów.
Klucz trzymamy na dysku danych, żeby przeżył wdrożenie — zmiana klucza
unieważnia wcześniejsze zgłoszenia.

Ograniczamy się do tego, co naprawdę się zmieniło: przy starcie serwera
(raz na dobę) idą adresy sekcji z żywymi danymi i profile osób z nowym
zgłoszeniem. Wysyłanie wszystkiego codziennie to najszybsza droga do tego,
żeby dostawca przestał traktować zgłoszenia poważnie.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time

import requests

import paths

from . import site

log = logging.getLogger("seo.indexnow")

ENDPOINT = "https://api.indexnow.org/indexnow"
PLIK_STANU = paths.data_path("indexnow.json")
LIMIT = 150                      # ile adresów najwyżej na jedno zgłoszenie
CO_S = 24 * 3600


def _stan() -> dict:
    try:
        with open(PLIK_STANU, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _zapisz(stan: dict) -> None:
    try:
        os.makedirs(os.path.dirname(PLIK_STANU), exist_ok=True)
        with open(PLIK_STANU, "w", encoding="utf-8") as f:
            json.dump(stan, f)
    except OSError as e:
        log.info("Zapis stanu IndexNow: %s", e)


def klucz() -> str:
    """Klucz serwisu — ze zmiennej środowiskowej albo wylosowany raz i zapisany."""
    z_env = (os.environ.get("INDEXNOW_KEY") or "").strip()
    if z_env:
        return z_env
    stan = _stan()
    if not stan.get("key"):
        stan["key"] = secrets.token_hex(16)
        _zapisz(stan)
    return stan["key"]


def zglos(adresy: list[str]) -> dict:
    """Wysyła listę adresów. Zwraca statystykę (bez wyjątków na zewnątrz)."""
    adresy = [a for a in dict.fromkeys(adresy) if a.startswith("http")][:LIMIT]
    if not adresy or not site.kanoniczny_host(site.HOST):
        return {"wyslane": 0}
    k = klucz()
    dane = {"host": site.HOST, "key": k,
            "keyLocation": site.absolute(f"/{k}.txt"), "urlList": adresy}
    try:
        r = requests.post(ENDPOINT, json=dane, timeout=20,
                          headers={"Content-Type": "application/json; charset=utf-8"})
        # 200 i 202 znaczą „przyjęte"; 422 to zwykle adres spoza hosta klucza
        ok = r.status_code in (200, 202)
        log.info("IndexNow: %s adresów, odpowiedź %s", len(adresy), r.status_code)
        return {"wyslane": len(adresy) if ok else 0, "status": r.status_code}
    except Exception as e:  # noqa: BLE001 — zgłoszenie to dodatek, nie funkcja serwisu
        log.info("IndexNow: %s", e)
        return {"wyslane": 0, "blad": str(e)[:200]}


def _adresy_do_zgloszenia() -> list[str]:
    from . import insiders, tools
    a = site.absolute
    poz = [a("/"), a(insiders.BAZA), a(tools.SCIEZKA), a("/sezon-wynikow"),
           a("/kalendarz-wynikow-spolek"), a("/dywidendy"), a("/wyniki-finansowe")]
    poz += [a(f"{insiders.BAZA}/{k}") for k in insiders.KLASY_STRON]
    # profile osób, które zgłosiły coś w ostatnich dwóch dniach — reszta się nie zmieniła
    try:
        import datetime as dt
        prog = (dt.date.today() - dt.timedelta(days=2)).isoformat()
        for slug, pid in insiders._mapa().items():
            if insiders.ostatnie_zgloszenie(pid)[:10] >= prog:
                poz.append(a(f"{insiders.BAZA}/{slug}"))
    except Exception:  # noqa: BLE001
        pass
    return poz


def zegar() -> None:
    """Raz na dobę zgłasza to, co się zmieniło. Wołane ze startu serwera."""
    def bieg():
        while True:
            stan = _stan()
            if time.time() - float(stan.get("ostatnie") or 0) >= CO_S:
                wynik = zglos(_adresy_do_zgloszenia())
                if wynik.get("wyslane"):
                    stan["ostatnie"] = time.time()
                    stan["ile"] = wynik["wyslane"]
                    _zapisz(stan)
            time.sleep(3600)

    threading.Thread(target=bieg, name="indexnow", daemon=True).start()
