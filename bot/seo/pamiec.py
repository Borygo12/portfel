"""Pamięć procesu dla list składanych z cache — jeden mechanizm dla całej warstwy.

Strony zbiorcze (kalendarz, dywidendy, reakcje kursu) powstają tak samo: trzeba
przejść po kilkuset plikach cache raportów, coś z nich policzyć i posortować.
To nie jest ruch po sieci, ale przy robocie wchodzącym na kilkadziesiąt podstron
naraz robi się z tego wąskie gardło na dysku — i każda z tych stron potrzebuje
dokładnie tej samej ochrony.

Zasada jest jedna i wynika z pomiaru: **nikt, kto wchodzi na stronę, nie ma
płacić za odświeżenie danych.** Zwykły cache z czasem życia tego nie daje —
w chwili wygaśnięcia pełny koszt spada na pierwszego, kto akurat wszedł, a na
czynnym serwisie tym pierwszym jest zazwyczaj robot wyszukiwarki, bo chodzi
regularnie, a ludzie nie. Zmierzone przed poprawką: 9,2 s wobec 0,1 s na ciepło.

Stąd trzy stany zamiast dwóch:

* wpis świeży (do `TTL_SWIEZY`) — idzie wprost;
* wpis nieświeży, ale w oknie `TTL_AWARYJNY` — idzie wprost **i** zleca
  odświeżenie w tle, więc następne wejście dostanie już nowe dane;
* brak wpisu albo wpis starszy niż okno — liczymy na miejscu, bo lepsze dane
  z opóźnieniem niż pusta strona.

Pierwszego wejścia po restarcie żaden cache nie uratuje — od tego jest
`rozgrzej()`, wołane ze zdarzenia `startup` serwera.
"""

from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("seo.pamiec")

#: Jak długo wynik jest uznawany za świeży.
TTL_SWIEZY = 900
#: Jak długo wolno jeszcze PODAĆ nieświeży wynik, odświeżając go w tle.
#: Dwanaście godzin, bo te listy opisują terminy i stopy dywidend, a nie
#: notowania — półdniowe opóźnienie nikogo nie wprowadzi w błąd, a pusta
#: strona owszem.
TTL_AWARYJNY = 12 * 3600

_pamiec: dict[str, tuple[float, object]] = {}
_zamek = threading.Lock()
#: Klucze, dla których odświeżenie już biegnie — żeby dziesięć żądań naraz
#: nie wystartowało dziesięciu wątków liczących to samo.
_w_locie: set[str] = set()


def zapisz(klucz: str, dane):
    with _zamek:
        _pamiec[klucz] = (time.time(), dane)
    return dane


def _odswiez_w_tle(klucz: str, oblicz) -> None:
    def zadanie():
        try:
            zapisz(klucz, oblicz())
        except Exception as e:  # noqa: BLE001
            # Odświeżanie w tle nie ma prawa niczego wywrócić: stary wynik już
            # poszedł na stronę, a następne wejście spróbuje jeszcze raz.
            log.warning("Odświeżanie %s w tle nie powiodło się: %s", klucz, e)
        finally:
            with _zamek:
                _w_locie.discard(klucz)

    with _zamek:
        if klucz in _w_locie:
            return
        _w_locie.add(klucz)
    threading.Thread(target=zadanie, name=f"seo-odswiez-{klucz}", daemon=True).start()


def zapamietane(klucz: str, oblicz):
    """Wynik z pamięci; gdy się zestarzał — stary teraz, świeży w tle."""
    with _zamek:
        wpis = _pamiec.get(klucz)
    if wpis:
        wiek = time.time() - wpis[0]
        if wiek < TTL_SWIEZY:
            return wpis[1]
        if wiek < TTL_AWARYJNY:
            _odswiez_w_tle(klucz, oblicz)
            return wpis[1]
    return zapisz(klucz, oblicz())


def poczekaj_na_yahoo(prob: int = 5, przerwa_s: float = 20.0) -> bool:
    """Czeka, aż da się zdobyć klucz dostępowy Yahoo (crumb). Zwraca, czy się udało.

    **Po co to istnieje — na tym się przejechaliśmy.** Yahoo wymaga ciasteczka
    i krótkiego klucza (`crumb`), który zdobywa się osobnym żądaniem. Przy
    obsłudze zwykłego wejścia jest już dawno w ręku, bo zdobył go pierwszy lepszy
    odczyt notowań. Ale **rozgrzewka startuje razem z serwerem**, czyli zanim
    ktokolwiek o cokolwiek poprosił — i wtedy klucza nie ma jeszcze wcale.

    Kod pobierający wyglądał tak, że brak klucza w pierwszym podejściu kończył
    całą próbę. Efekt na produkcji: przebieg sumiennie przechodził przez dwieście
    sześćdziesiąt spółek z czterosekundową przerwą, za każdym razem odbijał się
    od braku klucza i po kwadransie kończył z zerem. Strony pokazywały „dane się
    jeszcze zbierają” bez końca, choć samo pobieranie działało bez zarzutu —
    karta pojedynczej spółki dowoziła dywidendę w ułamku sekundy, bo tam klucz
    już był.

    Dlatego rozgrzewka najpierw upewnia się, że klucz jest, i dopiero potem
    rusza z listą. Kilka podejść z przerwą, bo tuż po starcie kontenera sieć
    bywa jeszcze niegotowa.
    """
    try:
        from portfolio import market as pf_market
    except Exception as e:  # noqa: BLE001
        log.warning("Brak modułu notowań: %s", e)
        return False

    for i in range(prob):
        try:
            if pf_market._get_crumb(force=bool(i)):
                return True
        except Exception as e:  # noqa: BLE001
            log.warning("Klucz Yahoo, podejście %d: %s", i + 1, e)
        if i + 1 < prob:
            log.info("Klucz Yahoo jeszcze niedostępny — czekam %.0f s", przerwa_s)
            time.sleep(przerwa_s)
    log.warning("Nie udało się zdobyć klucza Yahoo — rozgrzewka bez pobierania")
    return False


def rozgrzej(zadania) -> None:
    """Liczy podane zestawy w tle, zaraz po starcie serwera.

    `zadania` to pary (opis, funkcja bez argumentów). Wątek jest `daemon`,
    a każde zadanie opakowane osobno: rozgrzewka nie może ani opóźnić startu
    (healthcheck Railway nie zaczeka), ani przewrócić serwera, gdy jedno
    ze źródeł akurat nie odpowiada.
    """
    def bieg():
        for opis, wolanie in zadania:
            try:
                start = time.time()
                wynik = wolanie()
                ile = len(wynik) if hasattr(wynik, "__len__") else "?"
                log.info("Rozgrzano %s: %s pozycji w %.1f s", opis, ile,
                         time.time() - start)
            except Exception as e:  # noqa: BLE001
                log.warning("Rozgrzewanie %s nie powiodło się: %s", opis, e)

    threading.Thread(target=bieg, name="seo-rozgrzewanie", daemon=True).start()
