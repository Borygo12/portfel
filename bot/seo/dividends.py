"""Dywidendy spółek z katalogu — dane i strony pozycjonowane.

**Skąd dane: znikąd nowego.** `earnings/report.py` od początku prosi Yahoo
o moduły `summaryDetail` i `calendarEvents` (stała `MODULES`), w których stopa
dywidendy, kwota na akcję, dzień bez dywidendy i wskaźnik wypłaty przychodzą
razem z resztą raportu — tylko nikt ich stamtąd nie czytał. Doszło więc jedno
wyciągnięcie pól (`report._dividend`) i ten moduł, który składa z nich listy.
Zero dodatkowego ruchu do Yahoo, zero nowego źródła do pilnowania.

Czytamy **wyłącznie cache** raportów, tak samo jak `upcoming.py`: pytanie Yahoo
o dwieście symboli w trakcie obsługi żądania skończyłoby się blokadą dostawcy,
która zabrałaby dane także aplikacji. Konsekwencja, o której trzeba wiedzieć:
lista zapełnia się w miarę, jak raporty spółek trafiają do cache — po świeżym
wdrożeniu jest krótsza i to jest normalne, a nie awaria.

Dwie rzeczy, które wyglądają jak błąd, a są własnością danych:

* **„Nadchodzących dni bez dywidendy” bywa mało — czasem kilka.** Spółka ma
  jeden taki dzień w roku (w USA cztery), więc w losowym tygodniu większość
  katalogu ma tę datę już za sobą. Dlatego stroną wiodącą jest ranking stóp,
  który jest pełny zawsze, a kalendarz nadchodzących dat stoi obok niego jako
  sekcja, która ma prawo być krótka.
* **Stopa liczona jest z ostatniej wypłaty, więc bywa myląca.** Spółka, która
  raz wypłaciła zysk ze sprzedaży spółki zależnej, pokazuje stopę, jakiej nigdy
  nie powtórzy, a wskaźnik wypłaty powyżej 100% znaczy, że dywidenda była
  wyższa niż zysk. Obie rzeczy są na stronach powiedziane wprost, bo strona
  o dywidendach bez tego ostrzeżenia jest po prostu myląca.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time

from . import companies, dates, jsonld, logos, pamiec, render

log = logging.getLogger("seo.dividends")

BAZA = "/dywidendy"

#: Dzień ostatniej zmiany tekstu na tych stronach — `lastmod` w sitemapie.
ZMIENIONO = "2026-08-16"

#: Jak stary może być raport, z którego wolno wziąć dywidendę. Trzydzieści dni,
#: bo stopa zmienia się przy wypłacie — czyli raz na rok — a nie co godzinę.
#: Przy dobowym oknie lista kurczyła się do spółek odwiedzonych w ciągu doby.
TTL_RAPORTU = 30 * 24 * 3600

#: Jak długo trzymamy osobno pobraną dywidendę. Doba, bo zmienia się przy
#: wypłacie i przy zmianie kursu — a stopa policzona z wczorajszego kursu
#: różni się od dzisiejszej o tyle, co nic.
TTL_DYWIDENDY = 24 * 3600

#: Przerwa między zapytaniami przy dociąganiu w tle. Cztery sekundy razy około
#: dwustu spółek to kwadrans jednorazowo po starcie — a Yahoo nie ma powodu
#: uznać tego za nalot. Skracanie tego jest kuszące i niczego nie daje: lista
#: dywidend nie jest nikomu potrzebna dziesięć sekund wcześniej.
PRZERWA_S = 4.0

#: Poniżej tej stopy uznajemy, że spółka dywidendy realnie nie płaci. Yahoo
#: zostawia w polu ślad po wypłacie sprzed lat (CD Projekt: 0,46% z czerwca
#: 2025), a wpisanie takiej spółki na listę dywidendowych byłoby wprowadzaniem
#: w błąd — ktoś kupiłby ją dla dywidendy, której nie ma.
MIN_STOPA = 0.5

#: Powyżej tej stopy dopisujemy ostrzeżenie. To nie jest próg „oszustwa”, tylko
#: granica, powyżej której wysoka stopa najczęściej bierze się ze spadku kursu
#: albo z wypłaty jednorazowej, a nie z hojności spółki.
STOPA_PODEJRZANA = 10.0


# --------------------------------------------------------------- dane


def _z_raportu(symbol: str):
    """Dywidenda doklejona do pełnego raportu spółki, jeśli ten leży w cache.

    Najtańsze źródło, bo nic nie kosztuje: raport i tak zawiera te pola.
    Raporty zapisane przed dodaniem `report._dividend` klucza nie mają —
    wtedy zwracamy None i dywidendę dobierze `_dopobierz`.
    """
    try:
        from earnings import cache as e_cache
    except Exception:  # noqa: BLE001
        return None
    raport = e_cache.get(f"report-{symbol}", TTL_RAPORTU)
    if not raport:
        return None
    dyw = raport.get("dividend")
    return dyw if isinstance(dyw, dict) else None


def _pobierz(symbol: str):
    """Sama dywidenda jednej spółki — osobne, lekkie zapytanie do Yahoo.

    Po co osobno, skoro te pola są w raporcie: **raport odświeża się dopiero
    wtedy, gdy ktoś wejdzie na stronę spółki.** Spółka, której nikt nie
    odwiedził, zostałaby bez dywidendy na tygodnie, a lista dywidendowa
    zapełniałaby się w tempie ruchu na serwisie. Zaciąganie pełnego raportu
    dla dwustu spółek w tle nie wchodzi w grę — to kilka zapytań na spółkę,
    do Yahoo i do Nasdaqa. Tu prosimy o dwa moduły w jednym wywołaniu,
    czyli najtańsze, co da się wykonać.
    """
    try:
        from earnings import cache as e_cache
        from earnings.report import _dividend
        from portfolio import market as pf_market
        import requests
    except Exception as e:  # noqa: BLE001
        log.warning("Brak modułów do pobrania dywidendy: %s", e)
        return None

    def build():
        for proba in (0, 1):
            crumb = pf_market._get_crumb(force=bool(proba))
            if not crumb:
                return None
            try:
                r = pf_market._session.get(
                    "https://query2.finance.yahoo.com/v10/finance/quoteSummary/"
                    f"{requests.utils.quote(symbol)}"
                    "?modules=summaryDetail,calendarEvents"
                    f"&crumb={requests.utils.quote(crumb)}", timeout=20)
                if r.status_code == 401 and proba == 0:
                    continue
                r.raise_for_status()
                res = (r.json().get("quoteSummary") or {}).get("result") or []
                if not res:
                    return None
                return _dividend(res[0].get("summaryDetail") or {},
                                 res[0].get("calendarEvents") or {})
            except Exception as e:  # noqa: BLE001
                log.warning("Dywidenda %s: %s", symbol, e)
                if proba:
                    return None
        return None

    return e_cache.cached(f"dividend-{symbol}", TTL_DYWIDENDY, build)


def _z_cache() -> list[dict]:
    """Dywidendy wszystkich spółek katalogu, jakie leżą w którymkolwiek cache.

    Czyta WYŁĄCZNIE to, co już jest na dysku — żadnego ruchu po sieci w trakcie
    obsługi żądania. Braki uzupełnia w tle `dopobierz_brakujace()`.
    """
    try:
        from earnings import cache as e_cache
    except Exception as e:  # noqa: BLE001
        log.warning("Brak modułu cache: %s", e)
        return []

    dzis = dt.date.today()
    wynik = []
    for s in companies.SPOLKI:
        # Kolejność ma znaczenie: najpierw osobne, dobowe pobranie, dopiero potem
        # raport. Raport wolno mieć sprzed miesiąca, więc gdyby szedł pierwszy,
        # przesłaniałby świeższą wartość swoją starszą.
        dyw = (e_cache.get(f"dividend-{s['symbol']}", TTL_DYWIDENDY)
               or _z_raportu(s["symbol"]))
        if not isinstance(dyw, dict):
            continue
        stopa = dyw.get("stopa_pct")
        if not isinstance(stopa, (int, float)) or stopa < MIN_STOPA:
            continue

        bez = dyw.get("bez_dywidendy") or ""
        dni_do = None
        if bez:
            try:
                dni_do = (dt.date.fromisoformat(bez) - dzis).days
            except ValueError:
                dni_do = None

        # Kurs i kapitalizacja są tylko w pełnym raporcie. Gdy spółka ma na razie
        # samą dywidendę z lekkiego pobrania, po prostu ich nie ma — waluta idzie
        # wtedy z katalogu, bo bez niej „6,14" nie znaczy nic.
        raport = e_cache.get(f"report-{s['symbol']}", TTL_RAPORTU) or {}

        wynik.append({
            "spolka": s,
            "symbol": s["symbol"],
            "nazwa": s["name"],
            "adres": companies.adres(s),
            "rynek": s["market"],
            "waluta": raport.get("currency") or s.get("currency") or "",
            "kurs": raport.get("price"),
            "kapitalizacja": raport.get("market_cap"),
            "stopa": round(float(stopa), 2),
            "na_akcje": dyw.get("na_akcje"),
            "wyplata": dyw.get("wyplata_pct"),
            "srednia_5lat": dyw.get("srednia_5lat_pct"),
            "bez_dywidendy": bez,
            "wyplacana": dyw.get("wyplacana") or "",
            "przyszla": bool(dyw.get("przyszla")),
            "dni_do": dni_do,
        })
    wynik.sort(key=lambda p: -p["stopa"])
    return wynik


def wszystkie() -> list[dict]:
    """Spółki płacące dywidendę, od najwyższej stopy. Z pamięci procesu."""
    return pamiec.zapamietane("dywidendy", _z_cache)


def rynek(nazwa: str = "") -> list[dict]:
    return [p for p in wszystkie() if not nazwa or p["rynek"] == nazwa]


def nadchodzace(dni: int = 90, limit: int = 0) -> list[dict]:
    """Spółki, którym dzień bez dywidendy dopiero nadchodzi — od najbliższego.

    Ta lista ma prawo być krótka i to nie jest usterka: spółka przechodzi przez
    dzień bez dywidendy raz na rok (w USA cztery razy), więc w losowym tygodniu
    większość katalogu ma go już za sobą.
    """
    poz = [p for p in wszystkie()
           if p["przyszla"] and p["dni_do"] is not None and 0 <= p["dni_do"] <= dni]
    poz.sort(key=lambda p: (p["dni_do"], -p["stopa"]))
    return poz[:limit] if limit else poz


def dla_spolki(slug: str) -> dict | None:
    """Pozycja z listy dywidendowej — gdy potrzebne są też kurs i waluta."""
    return next((p for p in wszystkie() if p["spolka"]["slug"] == slug), None)


def surowa(symbol: str) -> dict | None:
    """Same pola dywidendy jednej spółki, z dowolnego cache. Nie rusza sieci.

    Karta spółki woła to jako drugie źródło, gdy jej własny raport pochodzi
    sprzed dodania pola `dividend` — inaczej sekcja dywidendy pojawiałaby się
    dopiero po odświeżeniu raportu, czyli u części spółek dopiero za tygodnie.
    """
    try:
        from earnings import cache as e_cache
    except Exception:  # noqa: BLE001
        return None
    dyw = (e_cache.get(f"dividend-{symbol}", TTL_DYWIDENDY)
           or _z_raportu(symbol))
    return dyw if isinstance(dyw, dict) else None


# --------------------------------------------------------------- uzupełnianie w tle


_uzupelnianie = threading.Lock()


def dopobierz_brakujace(przerwa_s: float = PRZERWA_S, limit: int = 0) -> int:
    """Dociąga dywidendy spółek, których nie ma w żadnym cache. Zwraca ile dobrał.

    Chodzi w jednym wątku i **z przerwą między zapytaniami**, bo tu nie zależy
    nam na czasie, tylko na tym, żeby nie stracić dostępu do Yahoo. Dwieście
    zapytań wypuszczonych naraz kończy się blokadą, która zabrałaby dane także
    aplikacji — a lista dywidend, która zapełni się przez kwadrans, jest warta
    dokładnie tyle samo co ta, która zapełniłaby się w dziesięć sekund.

    Zamek pilnuje, żeby dwa przebiegi nie chodziły równolegle: rozgrzewka po
    starcie i ewentualne wywołanie ręczne robiłyby tę samą robotę podwójnie.
    """
    if not _uzupelnianie.acquire(blocking=False):
        log.info("Uzupełnianie dywidend już trwa — pomijam")
        return 0
    try:
        from earnings import cache as e_cache
    except Exception as e:  # noqa: BLE001
        log.warning("Brak modułu cache: %s", e)
        _uzupelnianie.release()
        return 0

    try:
        brakujace = [s for s in companies.SPOLKI
                     if not _z_raportu(s["symbol"])
                     and not e_cache.get(f"dividend-{s['symbol']}", TTL_DYWIDENDY)]
        if limit:
            brakujace = brakujace[:limit]
        if not brakujace:
            return 0

        log.info("Dywidendy: dociągam %d spółek co %.1f s", len(brakujace), przerwa_s)
        dobrane = 0
        for i, s in enumerate(brakujace):
            if i:
                time.sleep(przerwa_s)
            try:
                if _pobierz(s["symbol"]):
                    dobrane += 1
            except Exception as e:  # noqa: BLE001
                log.warning("Dywidenda %s: %s", s["symbol"], e)
        log.info("Dywidendy: dobrano %d z %d", dobrane, len(brakujace))
        # Lista w pamięci pochodzi sprzed dociągnięcia — bez tego nowe spółki
        # pokazałyby się dopiero po wygaśnięciu wpisu, czyli za kwadrans.
        pamiec.zapisz("dywidendy", _z_cache())
        return dobrane
    finally:
        _uzupelnianie.release()


def rozgrzej_zadania():
    """Najpierw lista z tego, co już leży na dysku, potem dociąganie braków.

    Kolejność ma znaczenie: pierwsze zadanie jest natychmiastowe i sprawia, że
    strony działają od razu, choćby na niepełnej liście. Drugie chodzi kwadrans
    i dopełnia ją w tle.
    """
    return (
        ("dywidendy z cache", wszystkie),
        ("dywidendy — dociąganie braków", dopobierz_brakujace),
    )


# --------------------------------------------------------------- prezentacja


def _stopa(p: dict) -> str:
    return render.procent(p["stopa"], ze_znakiem=False)


def _kwota(p: dict) -> str:
    v = p.get("na_akcje")
    if not isinstance(v, (int, float)):
        return "—"
    return f"{render.liczba(v)} {p['waluta']}".strip()


def _wiersz_tabeli(p: dict, z_data: bool = True) -> list:
    komorki = [
        (p["nazwa"], "link", p["adres"]),
        companies.ticker(p["spolka"]),
        (_stopa(p), "num"),
        (_kwota(p), "num"),
        (render.procent(p["wyplata"], ze_znakiem=False)
         if isinstance(p.get("wyplata"), (int, float)) else "—", "num"),
    ]
    if z_data:
        komorki.append(dates.dlugo(p["bez_dywidendy"]) or "—")
    return komorki


def _tabela(pozycje, z_data: bool = True, podpis: str = "") -> str:
    naglowki = ["Spółka", "Ticker", ("Stopa dywidendy", True), ("Na akcję", True),
                ("Wskaźnik wypłaty", True)]
    if z_data:
        naglowki.append("Dzień bez dywidendy")
    return render.tabela(naglowki, [_wiersz_tabeli(p, z_data) for p in pozycje], podpis)


def _wiersze_kalendarza(pozycje) -> str:
    poz = []
    for p in pozycje:
        dni = p["dni_do"]
        kiedy = "dziś" if dni == 0 else ("jutro" if dni == 1 else f"za {dni} dni")
        poz.append({
            "logo": logos.znak(p["spolka"], 34),
            "tytul": f"{p['nazwa']} ({companies.ticker(p['spolka'])})",
            "podtytul": f"{dates.dlugo(p['bez_dywidendy'])} · {kiedy}",
            "adres": p["adres"],
            "wartosc": _stopa(p),
            "nota": _kwota(p),
        })
    return render.wiersze(poz)


def _statystyki(pozycje) -> str:
    if not pozycje:
        return ""
    stopy = [p["stopa"] for p in pozycje]
    srednia = sum(stopy) / len(stopy)
    najlepsza = pozycje[0]
    wysokie = [p for p in pozycje if p["stopa"] >= 5]
    return render.statystyki([
        ("Spółek z dywidendą", str(len(pozycje)), "w katalogu Portevo"),
        ("Najwyższa stopa", _stopa(najlepsza), najlepsza["nazwa"]),
        ("Mediana stopy", render.procent(sorted(stopy)[len(stopy) // 2],
                                         ze_znakiem=False), "połowa spółek wyżej"),
        ("Powyżej 5%", str(len(wysokie)), f"średnia {render.procent(srednia, ze_znakiem=False)}"),
    ])


_OSTRZEZENIE = (
    "Wysoka stopa dywidendy <strong>nie jest sama w sobie dobrą wiadomością</strong>. "
    "Stopa to iloraz dywidendy i kursu, więc rośnie także wtedy, gdy kurs spada — "
    "a spadający kurs zwykle ma powód. Rośnie też po wypłacie jednorazowej, na "
    "przykład z zysku ze sprzedaży spółki zależnej, której nikt nie powtórzy "
    "w przyszłym roku. Dlatego obok stopy pokazujemy <strong>wskaźnik wypłaty</strong>: "
    "mówi, jaką część zysku spółka oddała akcjonariuszom. Wartość powyżej 100% znaczy, "
    "że wypłaciła więcej, niż zarobiła — z oszczędności albo z długu."
)

_JAK_CZYTAC = (
    "<strong>Dzień bez dywidendy</strong> (ex-dividend) to pierwsza sesja, na której "
    "akcja jest notowana już bez prawa do najbliższej wypłaty. Żeby dostać dywidendę, "
    "trzeba mieć akcje na koniec sesji <em>poprzedzającej</em> ten dzień — kupno "
    "w samym dniu bez dywidendy jest już za późne. W dniu bez dywidendy kurs zwykle "
    "otwiera się niżej mniej więcej o jej wysokość i nie jest to spadek, tylko "
    "wyjęcie wypłaconych pieniędzy z wyceny."
)


def _faq_pary(zakres: str = "") -> list[tuple[str, str]]:
    gdzie = f" {zakres}" if zakres else ""
    return [
        ("Kiedy trzeba mieć akcje, żeby dostać dywidendę?",
         "Na koniec sesji poprzedzającej dzień bez dywidendy. Od dnia bez dywidendy "
         "akcja jest notowana już bez prawa do wypłaty, więc kupno tego dnia nie daje "
         "prawa do najbliższej dywidendy."),
        ("Dlaczego kurs spada w dniu bez dywidendy?",
         "Bo z wyceny spółki wychodzą pieniądze, które za chwilę trafią na rachunki "
         "akcjonariuszy. Spadek mniej więcej o wysokość dywidendy jest zjawiskiem "
         "technicznym, a nie oceną spółki przez rynek."),
        ("Czy najwyższa stopa dywidendy oznacza najlepszą spółkę?",
         "Nie. Stopa rośnie także wtedy, gdy kurs spada, oraz po wypłacie "
         "jednorazowej, która się nie powtórzy. Dlatego warto patrzeć na wskaźnik "
         "wypłaty — powyżej 100% spółka wypłaciła więcej, niż zarobiła."),
        ("Jaki podatek płaci się od dywidendy?",
         "W Polsce dywidendy są objęte 19-procentowym podatkiem od zysków "
         "kapitałowych. Przy dywidendach zagranicznych dochodzi podatek pobrany "
         "u źródła, a zasady zależą od umowy z danym krajem — Portevo nie doradza "
         "podatkowo, warto to sprawdzić u doradcy."),
        (f"Skąd pochodzą dane o dywidendach{gdzie}?",
         "Z Yahoo Finance, z tego samego zapytania, z którego bierzemy prognozy "
         "analityków i terminy publikacji wyników. Stopa liczona jest z ostatniej "
         "znanej wypłaty i bywa opóźniona wobec decyzji walnego zgromadzenia."),
    ]


# --------------------------------------------------------------- strony

STRONY = {
    "": {
        "tytul": "Dywidendy spółek — stopy, terminy i kalendarz | Portevo",
        "h1": "Dywidendy spółek z GPW i giełd amerykańskich",
        "opis": "Stopy dywidendy, kwoty na akcję, wskaźnik wypłaty i dni bez "
                "dywidendy — dla spółek z warszawskiej giełdy i z USA. Po polsku, "
                "za darmo.",
        "lead": "Ile realnie płacą spółki, kiedy wypada dzień bez dywidendy i czy "
                "wypłata mieści się w zysku — zebrane w jednym miejscu i policzone "
                "z tych samych danych, z których powstaje kalendarz wyników.",
        "rynek": "",
    },
    "gpw": {
        "tytul": "Dywidendy GPW — stopy i terminy spółek z Warszawy | Portevo",
        "h1": "Dywidendy spółek z GPW",
        "opis": "Które spółki z warszawskiej giełdy płacą dywidendę i ile. Stopa, "
                "kwota na akcję, wskaźnik wypłaty i dzień bez dywidendy.",
        "lead": "Warszawski parkiet od lat płaci wyraźnie więcej niż amerykański — "
                "poniżej spółki z GPW, które dywidendę realnie wypłacają, ułożone od "
                "najwyższej stopy.",
        "rynek": "GPW",
    },
    "usa": {
        "tytul": "Dywidendy spółek z USA — stopy i terminy | Portevo",
        "h1": "Dywidendy spółek z giełd amerykańskich",
        "opis": "Stopy dywidendy spółek z Nasdaq i NYSE, kwoty na akcję, wskaźnik "
                "wypłaty i dni bez dywidendy. Po polsku.",
        "lead": "Amerykańskie spółki płacą niżej niż polskie, ale zwykle cztery razy "
                "w roku i znacznie regularniej — poniżej te z katalogu Portevo, "
                "od najwyższej stopy.",
        "rynek": "USA",
    },
    "najwyzsze-stopy": {
        "tytul": "Najwyższe dywidendy — ranking stóp z GPW i USA | Portevo",
        "h1": "Najwyższe stopy dywidendy",
        "opis": "Ranking spółek o najwyższej stopie dywidendy z GPW i giełd "
                "amerykańskich — razem ze wskaźnikiem wypłaty, który mówi, czy "
                "wypłata mieści się w zysku.",
        "lead": "Sam ranking stóp bez drugiej kolumny bywa pułapką, więc obok każdej "
                "stopy stoi wskaźnik wypłaty. Dopiero te dwie liczby razem mówią, czy "
                "dywidenda ma z czego być wypłacona w przyszłym roku.",
        "rynek": "",
    },
    "kalendarz": {
        "tytul": "Kalendarz dywidend — najbliższe dni bez dywidendy | Portevo",
        "h1": "Kalendarz dywidend",
        "opis": "Najbliższe dni bez dywidendy dla spółek z GPW i z USA. Sprawdź, do "
                "kiedy trzeba mieć akcje, żeby dostać najbliższą wypłatę.",
        "lead": "Dzień bez dywidendy to granica: żeby dostać wypłatę, akcje trzeba mieć "
                "na koniec sesji poprzedzającej. Poniżej spółki, którym ta data dopiero "
                "nadchodzi.",
        "rynek": "",
    },
}


def adresy() -> list[str]:
    return [BAZA] + [f"{BAZA}/{s}" for s in STRONY if s]


def _okruchy(slug: str):
    if not slug:
        return [(None, "Dywidendy")]
    return [(BAZA, "Dywidendy"), (None, STRONY[slug]["h1"])]


def _linki_poboczne(slug: str) -> str:
    wszystkie_linki = [
        ("", "Wszystkie dywidendy"),
        ("gpw", "Dywidendy GPW"),
        ("usa", "Dywidendy z USA"),
        ("najwyzsze-stopy", "Najwyższe stopy"),
        ("kalendarz", "Kalendarz dywidend"),
    ]
    return render.chipsy(
        [(f"{BAZA}/{s}" if s else BAZA, t) for s, t in wszystkie_linki if s != slug]
        + [("/etf/dywidendowe", "ETF dywidendowe"),
           ("/kalendarz-wynikow-spolek", "Kalendarz wyników")])


def zbuduj(slug: str = "") -> str | None:
    cfg = STRONY.get(slug)
    if cfg is None:
        return None

    if slug == "kalendarz":
        pozycje = nadchodzace(dni=120)
    else:
        pozycje = rynek(cfg["rynek"])
        if slug == "najwyzsze-stopy":
            pozycje = pozycje[:30]

    bloki = []

    if slug == "kalendarz":
        if pozycje:
            bloki.append(render.sekcja(
                "Najbliższe dni bez dywidendy",
                f"Spółek z nadchodzącym dniem bez dywidendy jest teraz "
                f"<strong>{len(pozycje)}</strong>. Lista bywa krótka i to normalne: "
                "spółka z GPW przechodzi przez ten dzień raz w roku, amerykańska "
                "zwykle cztery razy, więc w danym tygodniu większość ma go już za sobą.",
                html_dodatkowy=_wiersze_kalendarza(pozycje)))
        else:
            bloki.append(render.sekcja(
                "Najbliższe dni bez dywidendy",
                "W tej chwili żadna spółka z katalogu nie ma dnia bez dywidendy "
                "w najbliższych czterech miesiącach. To nie jest usterka — terminy "
                "wypłat układają się sezonowo, a na GPW większość z nich wypada "
                "między majem a sierpniem.",
                html_dodatkowy=render.chipsy([
                    (f"{BAZA}/gpw", "Zobacz, ile płacą spółki z GPW"),
                    (f"{BAZA}/najwyzsze-stopy", "Ranking najwyższych stóp")])))
        bloki.append(render.sekcja("Jak czytać dzień bez dywidendy", _JAK_CZYTAC))
    else:
        bloki.append(_statystyki(pozycje))
        if pozycje:
            podpis = {"gpw": "Spółki z GPW płacące dywidendę, od najwyższej stopy",
                      "usa": "Spółki z giełd amerykańskich, od najwyższej stopy",
                      "najwyzsze-stopy": "Trzydzieści najwyższych stóp z obu rynków",
                      }.get(slug, "Wszystkie spółki z katalogu płacące dywidendę")
            bloki.append(render.sekcja(
                "Stopy dywidendy spółka po spółce",
                html_dodatkowy=_tabela(pozycje, podpis=podpis)))
        else:
            bloki.append(render.sekcja(
                "Dane się jeszcze zbierają",
                "Dywidendy czytamy z raportów spółek, a te trafiają do pamięci "
                "serwera stopniowo. Zajrzyj za chwilę albo wejdź na kartę "
                "konkretnej spółki — jej dywidenda policzy się od razu.",
                html_dodatkowy=render.chipsy([
                    ("/wyniki-finansowe/gpw", "Spółki z GPW"),
                    ("/wyniki-finansowe/usa", "Spółki z USA")])))

    if slug != "kalendarz":
        nad = nadchodzace(dni=90, limit=8)
        if nad:
            bloki.append(render.sekcja(
                "Najbliższe dni bez dywidendy",
                "Żeby dostać wypłatę, akcje trzeba mieć na koniec sesji "
                "poprzedzającej tę datę.",
                html_dodatkowy=_wiersze_kalendarza(nad)
                + render.chipsy([(f"{BAZA}/kalendarz", "Pełny kalendarz dywidend")])))

    bloki.append(render.sekcja("Zanim rzucisz się na wysoką stopę", _OSTRZEZENIE))
    bloki.append(render.sekcja("Więcej o dywidendach", html_dodatkowy=_linki_poboczne(slug)))
    bloki.append(render.faq(_faq_pary("na GPW" if slug == "gpw" else "")))
    bloki.append(render.zacheta(
        "Śledź dywidendy swoich spółek",
        "Dodaj spółkę do obserwowanych, a jej dywidendę i termin publikacji wyników "
        "zobaczysz razem z resztą portfela.",
        "/", "Otwórz Portevo",
        drugi=("/kalendarz-wynikow-spolek", "Kalendarz wyników"),
        trzeci=("/etf/dywidendowe", "ETF dywidendowe")))
    bloki.append(render.zastrzezenie())

    sciezka = f"{BAZA}/{slug}" if slug else BAZA
    dane = [
        jsonld.strona(sciezka, cfg["tytul"], cfg["opis"],
                      zmieniono=dt.date.today().isoformat()),
        jsonld.okruchy([(BAZA, "Dywidendy")]
                       + ([(sciezka, cfg["h1"])] if slug else [])),
        jsonld.pytania(_faq_pary()),
    ]
    if pozycje and slug != "kalendarz":
        # `lista_pozycji` sama robi z adresu adres bezwzględny — podajemy ścieżkę.
        dane.append(jsonld.lista_pozycji(
            cfg["h1"], [(p["adres"], p["nazwa"]) for p in pozycje[:25]]))

    return render.strona(
        sciezka=sciezka,
        tytul=cfg["tytul"],
        opis=cfg["opis"],
        h1=cfg["h1"],
        lead=cfg["lead"],
        nadtytul="Dywidendy",
        okruchy=_okruchy(slug),
        aktualizacja=dates.dzis(),
        jsonld=dane,
        bloki=bloki,
    )
