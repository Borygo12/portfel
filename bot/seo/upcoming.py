"""Kto raportuje w najbliższych dniach — dane na żywo dla stron pozycjonowanych.

Zadanie tego modułu jest jedno: dać stronie prawdziwe daty najbliższych publikacji
wyników, bez ryzyka, że robot Google (albo człowiek na telefonie w pociągu)
będzie czekał na pobranie danych z trzech serwisów.

Stąd dwa źródła i różne zasady dla każdego z nich:

* **Giełdy amerykańskie** — kalendarz Nasdaqa przez `earnings.calendar`. Ten sam
  cache, z którego korzysta zakładka Earnings w aplikacji, więc na czynnym
  serwerze dane zwykle już tam leżą. Sieciujemy najwyżej przez `budzet_s`
  sekund; czego nie zdążymy, dogra się w tle na następne wejście.
* **GPW** — z raportów spółek z naszego katalogu, WYŁĄCZNIE z cache
  (`report-SYMBOL`). Nasdaq nie zna warszawskich spółek, a pytanie Yahoo
  o sto symboli w trakcie obsługi żądania kończyłoby się blokadą dostawcy,
  która zabrałaby dane także aplikacji.

Gotowe listy trzyma `pamiec.zapamietane` — wspólny mechanizm dla wszystkich
stron zbiorczych, z podawaniem nieświeżego wyniku i odświeżaniem w tle. Bez tego
strona spisu spółek czytałaby po kilkaset plików cache przy każdym odświeżeniu.

Zasada, której nie wolno tu złamać: **żadna z tych funkcji nie może rzucić
wyjątkiem ani zawiesić się na dłużej niż budżet.** Sekcja „kto raportuje w tym
tygodniu” jest dodatkiem do strony — gdy danych nie ma, ma jej po prostu nie
być, a nie zabrać ze sobą całą podstronę.
"""

from __future__ import annotations

import datetime as dt
import logging

from . import companies, pamiec

log = logging.getLogger("seo.upcoming")

#: Cache raportu spółki bywa starszy niż ten, którym karmimy podstronę — data
#: publikacji zmienia się rzadko, więc wolno sięgnąć po wpis sprzed doby.
TTL_RAPORTU = 24 * 3600


# --------------------------------------------------------------- spółki z katalogu


def _z_raportow(dzis: dt.date, koniec: dt.date) -> dict[str, dict]:
    """Terminy z raportów spółek leżących w cache. {slug: pozycja}.

    Jedyne źródło, które zna spółki z GPW — Nasdaq ich nie widzi. Czyta wyłącznie
    cache: pytanie Yahoo o sto symboli w trakcie obsługi żądania skończyłoby się
    blokadą dostawcy, która zabrałaby dane także aplikacji.
    """
    try:
        from earnings import cache as e_cache
    except Exception as e:  # noqa: BLE001
        log.warning("Brak modułu cache: %s", e)
        return {}

    wynik = {}
    for s in companies.SPOLKI:
        raport = e_cache.get(f"report-{s['symbol']}", TTL_RAPORTU)
        if not raport:
            continue
        nast = raport.get("next") or {}
        data = (nast.get("date") or "")[:10]
        try:
            d = dt.date.fromisoformat(data)
        except ValueError:
            continue
        if not (dzis <= d <= koniec):
            continue
        wynik[s["slug"]] = {
            "symbol": s["symbol"],
            "nazwa": s["name"],
            "spolka": s,
            "adres": companies.adres(s),
            "rynek": s["market"],
            "data": data,
            "eps": nast.get("eps"),
            "waluta": raport.get("currency") or s.get("currency") or "",
            "kapitalizacja": raport.get("market_cap"),
            "szacowany": bool(nast.get("estimate")),
        }
    return wynik


def _z_kalendarza_usa(dzis: dt.date, dni: int, budzet_s: float) -> dict[str, dict]:
    """Terminy z kalendarza Nasdaqa, zawężone do spółek z naszego katalogu.

    Po co, skoro raporty spółek też mają daty: raport pobiera się osobno dla
    KAŻDEJ spółki, więc świeżo uruchomiony serwer zna terminy tylko tych, które
    ktoś zdążył odwiedzić. Kalendarz Nasdaqa to jedno zapytanie na dzień dla
    całego rynku — dzięki niemu lista „kto raportuje w najbliższych tygodniach”
    jest pełna od pierwszego wejścia, zamiast zapełniać się tygodniami.
    """
    try:
        from earnings import calendar as e_cal
        surowe, _ = e_cal.range_days(dzis.isoformat(),
                                     (dzis + dt.timedelta(days=dni)).isoformat(),
                                     budget_sec=budzet_s)
    except Exception as e:  # noqa: BLE001
        log.warning("Kalendarz USA dla katalogu: %s", e)
        return {}

    wynik = {}
    for data, wiersze in surowe.items():
        for w in wiersze or []:
            s = companies.po_symbolu(w.get("symbol") or "")
            if not s or s["slug"] in wynik:
                continue
            wynik[s["slug"]] = {
                "symbol": s["symbol"],
                "nazwa": s["name"],
                "spolka": s,
                "adres": companies.adres(s),
                "rynek": s["market"],
                "data": data,
                "eps": w.get("eps_forecast"),
                "waluta": w.get("currency") or s.get("currency") or "",
                "kapitalizacja": w.get("market_cap"),
                # Nasdaq nie rozróżnia terminu potwierdzonego od szacowanego,
                # a wpisanie „potwierdzony” bez pokrycia byłoby obietnicą,
                # której nie mamy jak dotrzymać.
                "szacowany": False,
                "pora": w.get("time") or "tbd",
            }
    return wynik


def _katalog(dni: int) -> list[dict]:
    """Najbliższe raporty spółek z katalogu — z obu źródeł, złożone w jedną listę."""
    def oblicz() -> list[dict]:
        dzis = dt.date.today()
        # Kolejność sklejania ma znaczenie: wpis z raportu spółki jest bogatszy
        # (widełki prognoz, informacja o tym, czy termin jest potwierdzony), więc
        # to on nadpisuje pozycję z kalendarza, a nie odwrotnie.
        scalone = _z_kalendarza_usa(dzis, dni, budzet_s=5.0)
        scalone.update(_z_raportow(dzis, dzis + dt.timedelta(days=dni)))
        return sorted(scalone.values(), key=lambda x: (x["data"], x["nazwa"].lower()))

    return pamiec.zapamietane(f"katalog-{dni}", oblicz)


def najblizsze(dni: int = 21, rynek: str = "", pomin_slug: str = "",
               sektor: str = "", limit: int = 0) -> list[dict]:
    """Nadchodzące raporty spółek z katalogu, opcjonalnie zawężone.

    `sektor` nie odsiewa, tylko przesuwa spółki z tej samej branży na początek —
    na podstronie spółki sąsiad z branży jest ciekawszym „następnym krokiem”
    niż przypadkowa firma, ale lista nie może przez to zrobić się pusta.
    """
    pozycje = [p for p in _katalog(dni)
               if (not rynek or p["rynek"] == rynek)
               and p["spolka"]["slug"] != pomin_slug]
    if sektor:
        pozycje.sort(key=lambda p: (p["spolka"].get("sector") != sektor, p["data"],
                                    p["nazwa"].lower()))
    return pozycje[:limit] if limit else pozycje


def wg_dni(dni: int = 14, rynek: str = "") -> list[tuple[str, list[dict]]]:
    """[(data ISO, [spółki]), …] — gotowe do wypisania dzień po dniu."""
    grupy: dict[str, list[dict]] = {}
    for p in najblizsze(dni, rynek=rynek):
        grupy.setdefault(p["data"], []).append(p)
    return sorted(grupy.items())


# --------------------------------------------------------------- kalendarz USA


def rynek_usa(dni: int = 10, budzet_s: float = 6.0, min_kapitalizacja: float = 5e9,
              na_dzien: int = 8) -> list[tuple[str, list[dict]]]:
    """Największe amerykańskie raporty dzień po dniu — z kalendarza Nasdaqa.

    Sięgamy po pełny rynek, a nie po nasz katalog, bo to jedyny sposób, żeby
    strona odpowiadała na pytanie „kto raportuje w tym tygodniu” także dla
    spółek, których u siebie nie opisujemy. Próg kapitalizacji odsiewa setki
    mikrospółek, dla których i tak nie ma prognoz — bez niego lista jednego dnia
    w szczycie sezonu ma 350 pozycji i nie da się jej przeczytać.
    """
    def oblicz():
        try:
            from earnings import calendar as e_cal
        except Exception as e:  # noqa: BLE001
            log.warning("Brak modułu kalendarza: %s", e)
            return []

        dzis = dt.date.today()
        try:
            surowe, _ = e_cal.range_days(dzis.isoformat(),
                                         (dzis + dt.timedelta(days=dni)).isoformat(),
                                         budget_sec=budzet_s)
        except Exception as e:  # noqa: BLE001
            log.warning("Kalendarz USA: %s", e)
            return []

        dni_wynik = []
        for data in sorted(surowe):
            wiersze = [w for w in (surowe.get(data) or [])
                       if (w.get("market_cap") or 0) >= min_kapitalizacja]
            if not wiersze:
                continue
            wiersze.sort(key=lambda w: -(w.get("market_cap") or 0))
            pozycje = []
            for w in wiersze[:na_dzien]:
                spolka = companies.po_symbolu(w["symbol"])
                pozycje.append({
                    "symbol": w["symbol"],
                    "nazwa": w.get("name") or w["symbol"],
                    "spolka": spolka,
                    # Link tylko wtedy, gdy naprawdę mamy o tej spółce podstronę.
                    # Link do adresu, który zwróci czterysta cztery, jest gorszy
                    # od braku linku — i dla człowieka, i dla robota.
                    "adres": companies.adres(spolka) if spolka else "",
                    "data": data,
                    "pora": w.get("time") or "tbd",
                    "eps": w.get("eps_forecast"),
                    "kapitalizacja": w.get("market_cap"),
                    "prognozy": w.get("estimates") or 0,
                })
            dni_wynik.append((data, pozycje))
        return dni_wynik

    return pamiec.zapamietane(f"usa-{dni}-{int(min_kapitalizacja)}-{na_dzien}", oblicz)


# --------------------------------------------------------------- pory publikacji

PORY = {
    "bmo": "przed otwarciem sesji",
    "amc": "po zamknięciu sesji",
    "tbd": "godzina niepodana",
}


# --------------------------------------------------------------- rozgrzewanie


def rozgrzej() -> None:
    """Zestawy, po które sięgają strony — złożone, zanim ktokolwiek o nie poprosi."""
    pamiec.rozgrzej((
        ("kalendarz USA (sezon)", lambda: rynek_usa(dni=12, na_dzien=7)),
        ("kalendarz USA (widget)", lambda: rynek_usa(dni=7, na_dzien=5)),
        ("katalog 21 dni (karty spółek)", lambda: _katalog(21)),
        ("katalog 30 dni (branże)", lambda: _katalog(30)),
        ("katalog 45 dni (GPW)", lambda: _katalog(45)),
    ))
