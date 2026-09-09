"""Powiadomienia systemowe na telefon przez usługę Expo.

Świadomie bez SDK — to jeden POST na `https://exp.host/--/api/v2/push/send`
z listą wiadomości. Dokładanie paczki do obrazu za jedno wywołanie HTTP nie ma
sensu, a `requests` i tak już jest w zależnościach.

Czego ten moduł pilnuje, bo inaczej powiadomienia cicho przestają działać:

* **martwe tokeny.** Gdy ktoś odinstaluje aplikację, Expo odpowiada
  `DeviceNotRegistered`. Taki token trzeba skasować, inaczej każda wysyłka
  puka w nieistniejące urządzenie w nieskończoność;
* **paczkowanie.** Expo przyjmuje maksymalnie 100 wiadomości w jednym żądaniu;
* **cisza przy awarii.** Wyjątek nie może wywrócić pętli bota — powiadomienie
  i tak czeka w skrzynce w aplikacji, więc nic nie ginie.
"""

from __future__ import annotations

import logging

import requests

from . import store

log = logging.getLogger("notify.push")

ADRES = "https://exp.host/--/api/v2/push/send"
PACZKA = 100


def wyslij(tokeny: list[str], tytul: str, tresc: str,
           dane: dict | None = None) -> int:
    """Wysyła jedno powiadomienie na wiele urządzeń. Zwraca liczbę przyjętych."""
    tokeny = [t for t in tokeny if t and t.startswith("Expo")]
    if not tokeny:
        return 0

    przyjete = 0
    for start in range(0, len(tokeny), PACZKA):
        paczka = tokeny[start:start + PACZKA]
        wiadomosci = [{
            "to": t,
            "title": tytul[:100],
            "body": tresc[:240],
            "data": dane or {},
            "sound": "default",
            # Kanał musi istnieć po stronie Androida (tworzy go aplikacja przy
            # starcie). Bez zgodnej nazwy powiadomienie przychodzi bez dźwięku.
            "channelId": "portevo",
            "priority": "high",
        } for t in paczka]

        try:
            r = requests.post(ADRES, json=wiadomosci, timeout=15,
                              headers={"Content-Type": "application/json"})
            if r.status_code != 200:
                log.warning("Expo odrzuciło wysyłkę (%s): %.200s",
                            r.status_code, r.text)
                continue
            wyniki = (r.json() or {}).get("data") or []
        except (requests.RequestException, ValueError) as e:
            log.warning("Nie udało się wysłać powiadomień: %s", e)
            continue

        # Odpowiedzi wracają w tej samej kolejności, co wysłane wiadomości.
        for token, wynik in zip(paczka, wyniki):
            if (wynik or {}).get("status") == "ok":
                przyjete += 1
                continue
            blad = ((wynik or {}).get("details") or {}).get("error") or ""
            if blad == "DeviceNotRegistered":
                log.info("Urządzenie zniknęło — kasuję token")
                try:
                    store.wyrzuc_token(token)
                except Exception as e:  # noqa: BLE001
                    log.debug("Nie skasowano martwego tokenu: %s", e)
            else:
                log.warning("Expo odmówiło wysyłki: %s", wynik)

    return przyjete


def wyslij_do(user_id: str, tytul: str, tresc: str, dane: dict | None = None) -> int:
    """Wysyła na wszystkie urządzenia jednego konta."""
    try:
        return wyslij(store.tokeny(user_id), tytul, tresc, dane)
    except Exception as e:  # noqa: BLE001 — kanał nie może wywrócić powiadomienia
        log.warning("Push do %s nie wyszedł: %s", user_id, e)
        return 0
