"""Silnik danych dywidendowych — historia wypłat i wszystko, co z niej wynika.

Zasila narzędzie „Inwestowanie dywidendowe" w aplikacji oraz podstrony w `seo/`.
Nie myl tego modułu z `seo/dividends.py`: tamten składa strony pozycjonowane
z bieżącej stopy dywidendy, ten liczy z **dziesięcioletniej historii wypłat**
rzeczy, których z jednej liczby wyciągnąć się nie da — serię lat ze wzrostem,
tempo wzrostu, regularność i ocenę bezpieczeństwa.

**Skąd historia.** Yahoo oddaje ją w tym samym punkcie, z którego bierzemy
notowania: `chart?range=10y&interval=1mo&events=div`. Sprawdzone na spółkach
z GPW, z USA i na funduszach ETF — wszędzie działa, co jest istotne, bo bez
ETF-ów nie dałoby się porównać „spółka kontra fundusz", a to jest realne
pytanie kogoś, kto zaczyna inwestować dywidendowo.

**Pułapka, przez którą liczby wyszłyby fałszywie: rok bieżący jest niepełny.**
W sierpniu Coca-Cola ma zsumowane 1,06 USD wobec 2,04 za cały poprzedni rok.
Wrzucenie tego do porównania rok do roku pokazałoby „spadek dywidendy o połowę"
dla spółki, która nie obniżyła jej ani razu od dekad. Dlatego **wszystkie miary
wzrostu liczą się wyłącznie na latach zamkniętych**, a rok bieżący jest zwracany
osobno i opisany jako niepełny. To samo dotyczy pierwszego roku w oknie danych:
dziesięcioletni zakres zaczyna się w środku roku, więc najstarszy rok też bywa
ucięty i też go odcinamy.

**Ocena bezpieczeństwa nie jest wróżeniem.** Liczy się z czterech rzeczy, które
są sprawdzalne: jaką część zysku spółka oddaje, czy podnosiła wypłatę rok po
roku, czy kiedykolwiek ją obcięła i czy stopa nie jest podejrzanie wysoka.
Świadomie NIE ma tu prognozy — punktacja opisuje przeszłość i to jest napisane
wszędzie, gdzie się pokazuje.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time

log = logging.getLogger("dividend_lab")

#: Historia wypłat zmienia się kilka razy w roku — tygodniowy cache w zupełności
#: wystarczy, a oszczędza kilkaset zapytań przy każdym przeliczeniu skanera.
TTL_HISTORII = 7 * 24 * 3600

#: Ile lat wstecz pobieramy. Dziesięć, bo tyle wystarcza na ocenę serii wzrostów
#: i przetrwania jednego kryzysu, a jednocześnie mieści się w jednym zapytaniu.
LAT_HISTORII = 10

#: Minimalna liczba zamkniętych lat, żeby w ogóle liczyć tempo wzrostu. Poniżej
#: trzech „średnioroczny wzrost" jest pojedynczą różnicą przebraną za trend.
MIN_LAT_DO_WZROSTU = 3

_zamek = threading.Lock()
_w_locie: dict[str, threading.Event] = {}


# --------------------------------------------------------------- historia


def _pobierz_historie(symbol: str) -> list[dict] | None:
    """Wszystkie wypłaty spółki z ostatnich lat: [{data, kwota}, …]. None przy błędzie.

    Zwracamy None, a nie pustą listę, przy problemie z pobraniem — pusta lista
    znaczy „ta spółka nie płaci dywidendy" i to jest zupełnie inna informacja,
    której nie wolno zapisać do cache po nieudanym zapytaniu.
    """
    try:
        from portfolio import market as pf_market
    except Exception as e:  # noqa: BLE001
        log.warning("Brak modułu notowań: %s", e)
        return None

    try:
        r = pf_market._session.get(
            f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
            f"?range={LAT_HISTORII}y&interval=1mo&events=div", timeout=25)
        r.raise_for_status()
        wynik = (r.json().get("chart") or {}).get("result") or []
        if not wynik:
            return None
        zdarzenia = ((wynik[0].get("events") or {}).get("dividends") or {})
    except Exception as e:  # noqa: BLE001
        log.warning("Historia dywidend %s: %s", symbol, e)
        return None

    wyplaty = []
    for w in zdarzenia.values():
        try:
            data = dt.date.fromtimestamp(int(w["date"])).isoformat()
            kwota = float(w["amount"])
        except (KeyError, TypeError, ValueError, OSError):
            continue
        if kwota > 0:
            wyplaty.append({"data": data, "kwota": round(kwota, 6)})
    wyplaty.sort(key=lambda x: x["data"])
    return wyplaty


def historia(symbol: str) -> list[dict] | None:
    """Historia wypłat z cache. Pusta lista = spółka nie płaci, None = nie wiemy."""
    try:
        from earnings import cache as e_cache
    except Exception:  # noqa: BLE001
        return None

    klucz = f"divhist-{symbol}"
    gotowe = e_cache.get(klucz, TTL_HISTORII)
    if gotowe is not None:
        return gotowe

    # Bez tego dwadzieścia równoległych żądań na tę samą spółkę wysłałoby
    # dwadzieścia zapytań do Yahoo. Pierwszy pobiera, reszta czeka na wynik.
    with _zamek:
        czekaj = _w_locie.get(symbol)
        pierwszy = czekaj is None
        if pierwszy:
            czekaj = threading.Event()
            _w_locie[symbol] = czekaj
    if not pierwszy:
        czekaj.wait(timeout=30)
        return e_cache.get(klucz, TTL_HISTORII)

    try:
        dane = _pobierz_historie(symbol)
        if dane is not None:
            e_cache.put(klucz, dane)
        return dane
    finally:
        with _zamek:
            _w_locie.pop(symbol, None)
        czekaj.set()


# --------------------------------------------------------------- miary


def _lata(wyplaty: list[dict]) -> dict[int, float]:
    """Suma wypłat w każdym roku kalendarzowym."""
    lata: dict[int, float] = {}
    for w in wyplaty:
        rok = int(w["data"][:4])
        lata[rok] = round(lata.get(rok, 0.0) + w["kwota"], 6)
    return lata


def _lata_zamkniete(wyplaty: list[dict]) -> dict[int, float]:
    """Tylko lata, które da się uczciwie porównywać — z zerami w lukach.

    Odcinamy dwa końce. **Rok bieżący** jest z definicji niepełny — w sierpniu
    ma połowę wypłat, więc pokazany obok pełnych lat udawałby załamanie
    dywidendy. **Najstarszy rok w oknie** też bywa ucięty, bo dziesięcioletni
    zakres zaczyna się w środku roku, a nie 1 stycznia.

    **Lata bez wypłaty muszą tu być, jako zero.** Inaczej rok pominięty po
    prostu znika z zestawienia i spółka, która dywidendy nie wypłaciła wcale,
    wygląda jak taka, która nieprzerwanie podnosi. Zdarzyło się to na PKO:
    wypłaty 2019 i 2022, przerwa w 2020 i 2021 przez zakaz KNF dla banków —
    a wynik pokazywał czteroletnią serię podwyżek bez ani jednego obcięcia.
    Z zerami przerwa poprawnie zrywa serię i liczy się jako obcięcie.
    """
    lata = _lata(wyplaty)
    if not lata:
        return {}
    biezacy = dt.date.today().year
    lata.pop(biezacy, None)
    if lata:
        najstarszy = min(lata)
        # Najstarszy rok odcinamy tylko wtedy, gdy okno faktycznie się w nim
        # zaczyna — przy krótszej historii spółki byłby to niepotrzebny ubytek.
        if najstarszy <= biezacy - LAT_HISTORII:
            lata.pop(najstarszy, None)
    if not lata:
        return {}
    return {rok: lata.get(rok, 0.0) for rok in range(min(lata), max(lata) + 1)}


def _seria_wzrostow(lata: dict[int, float]) -> int:
    """Ile lat z rzędu, licząc wstecz od ostatniego zamkniętego, wypłata rosła.

    Rok bez zmiany przerywa serię tak samo jak spadek. To celowe: „utrzymał"
    i „podniósł" to dla inwestora dywidendowego dwie różne informacje, a seria
    ma mówić o tej drugiej.
    """
    if len(lata) < 2:
        return 0
    kolejne = sorted(lata)
    seria = 0
    for i in range(len(kolejne) - 1, 0, -1):
        if lata[kolejne[i]] > lata[kolejne[i - 1]]:
            seria += 1
        else:
            break
    return seria


def _czy_obcinala(lata: dict[int, float]) -> bool:
    kolejne = sorted(lata)
    return any(lata[kolejne[i]] < lata[kolejne[i - 1]] for i in range(1, len(kolejne)))


def _cagr(lata: dict[int, float], ile_lat: int) -> float | None:
    """Średnioroczne tempo wzrostu wypłaty w procentach, albo None."""
    kolejne = sorted(lata)
    if len(kolejne) < MIN_LAT_DO_WZROSTU:
        return None
    okno = kolejne[-(ile_lat + 1):] if len(kolejne) > ile_lat else kolejne
    start, koniec = lata[okno[0]], lata[okno[-1]]
    n = len(okno) - 1
    if n <= 0 or start <= 0 or koniec <= 0:
        return None
    return round(((koniec / start) ** (1 / n) - 1) * 100, 2)


def _czestotliwosc(wyplaty: list[dict], lata: dict[int, float]) -> int:
    """Ile razy w roku spółka wypłaca — liczone na ostatnim zamkniętym roku."""
    if not lata:
        return 0
    ostatni = max(lata)
    return sum(1 for w in wyplaty if int(w["data"][:4]) == ostatni)


CZESTOTLIWOSC_PL = {
    0: "nieregularnie", 1: "raz w roku", 2: "co pół roku",
    4: "co kwartał", 12: "co miesiąc",
}


def czestotliwosc_pl(n: int) -> str:
    if n in CZESTOTLIWOSC_PL:
        return CZESTOTLIWOSC_PL[n]
    return f"{n} razy w roku" if n else "nieregularnie"


def metryki(symbol: str) -> dict:
    """Komplet miar policzonych z historii wypłat jednej spółki albo funduszu."""
    wyplaty = historia(symbol)
    if wyplaty is None:
        return {"znane": False}
    if not wyplaty:
        return {"znane": True, "placi": False, "lata": {}, "wyplaty": []}

    zamkniete = _lata_zamkniete(wyplaty)
    wszystkie = _lata(wyplaty)
    biezacy = dt.date.today().year

    return {
        "znane": True,
        "placi": True,
        "wyplaty": wyplaty[-40:],
        "lata": {str(k): v for k, v in sorted(zamkniete.items())},
        "rok_biezacy": {
            "rok": biezacy,
            "suma": wszystkie.get(biezacy),
            "niepelny": True,
        },
        "ostatni_pelny_rok": max(zamkniete) if zamkniete else None,
        "suma_ostatni_pelny": zamkniete.get(max(zamkniete)) if zamkniete else None,
        "seria_wzrostow": _seria_wzrostow(zamkniete),
        "obcinala": _czy_obcinala(zamkniete),
        "wzrost_3l": _cagr(zamkniete, 3),
        "wzrost_5l": _cagr(zamkniete, 5),
        "lat_danych": len(zamkniete),
        "czestotliwosc": _czestotliwosc(wyplaty, zamkniete),
        "pierwsza_wyplata": wyplaty[0]["data"],
        "ostatnia_wyplata": wyplaty[-1]["data"],
    }


# --------------------------------------------------------------- bezpieczeństwo


#: Waga każdego składnika oceny. Suma to 100.
WAGI = {"wyplata": 35, "seria": 25, "ciaglosc": 25, "stopa": 15}


def bezpieczenstwo(m: dict, stopa_pct=None, wyplata_pct=None) -> dict:
    """Ocena 0–100 tego, jak pewna wygląda dywidenda. Opisuje PRZESZŁOŚĆ.

    Nie jest prognozą i nigdzie nie wolno jej tak przedstawić — to skrót
    z czterech sprawdzalnych faktów, po to, żeby nie trzeba było czytać
    czterech tabel naraz:

    * **Wskaźnik wypłaty (35 pkt)** — jaką część zysku spółka oddaje. Poniżej
      60% wypłata ma zapas; powyżej 100% spółka dopłaca z oszczędności albo
      z długu i to jest najczęstszy zwiastun obcięcia.
    * **Seria wzrostów (25 pkt)** — ile lat z rzędu podnosiła. Spółka, która
      podnosi dziesiąty rok, ma to wpisane w politykę i zwykle broni tej serii.
    * **Ciągłość (25 pkt)** — czy w całej znanej historii choć raz obcięła.
      Jedno obcięcie waży więcej niż kilka dobrych lat, bo pokazuje, że przy
      gorszej koniunkturze dywidenda jest pierwsza do cięcia.
    * **Zdrowy poziom stopy (15 pkt)** — bardzo wysoka stopa najczęściej nie
      bierze się z hojności, tylko ze spadku kursu.

    Punktów NIE przyznajemy za składniki, których nie znamy — zamiast tego
    zmniejszamy maksimum i przeliczamy na procent. Dzięki temu spółka z niepełnymi
    danymi nie dostaje sztucznie niskiej oceny za cudzy brak.
    """
    zdobyte, mozliwe, powody = 0.0, 0.0, []

    # **Bez historii nie ma oceny — i to jest twarda zasada.** Bez tego warunku
    # spółka z jedną wypłatą w bieżącym roku dostawała komplet punktów za sam
    # niski wskaźnik wypłaty i rozsądną stopę, po czym stawała na szczycie
    # rankingu „najbezpieczniejszych" (tak wyszedł Tauron: zero zamkniętych lat
    # i ocena 100). Ocena ma mówić „ta wypłata się broni od lat"; przy braku
    # historii uczciwą odpowiedzią jest „nie wiem", a nie sto punktów.
    if (m.get("lat_danych") or 0) < MIN_LAT_DO_WZROSTU:
        return {
            "ocena": None, "poziom": "brak", "powody": powody,
            "opis": "Za krótka historia wypłat, żeby cokolwiek uczciwie ocenić",
        }

    if isinstance(wyplata_pct, (int, float)):
        mozliwe += WAGI["wyplata"]
        if wyplata_pct <= 40:
            zdobyte += WAGI["wyplata"]
            powody.append(("dobry", f"Oddaje {wyplata_pct:.0f}% zysku — duży zapas"))
        elif wyplata_pct <= 60:
            zdobyte += WAGI["wyplata"] * 0.85
            powody.append(("dobry", f"Oddaje {wyplata_pct:.0f}% zysku — zdrowy poziom"))
        elif wyplata_pct <= 80:
            zdobyte += WAGI["wyplata"] * 0.6
            powody.append(("uwaga", f"Oddaje {wyplata_pct:.0f}% zysku — mało zapasu"))
        elif wyplata_pct <= 100:
            zdobyte += WAGI["wyplata"] * 0.3
            powody.append(("uwaga", f"Oddaje {wyplata_pct:.0f}% zysku — prawie cały"))
        else:
            powody.append(("zle", f"Wypłaciła {wyplata_pct:.0f}% zysku — więcej, niż zarobiła"))

    seria = m.get("seria_wzrostow")
    if isinstance(seria, int) and m.get("lat_danych"):
        mozliwe += WAGI["seria"]
        if seria >= 10:
            zdobyte += WAGI["seria"]
            powody.append(("dobry", f"Podnosi dywidendę {seria} lat z rzędu"))
        elif seria >= 5:
            zdobyte += WAGI["seria"] * 0.8
            powody.append(("dobry", f"Podnosi dywidendę {seria} lat z rzędu"))
        elif seria >= 2:
            zdobyte += WAGI["seria"] * 0.5
            powody.append(("neutralny", f"Podnosi od {seria} lat"))
        else:
            zdobyte += WAGI["seria"] * 0.2
            powody.append(("neutralny", "Brak serii podwyżek w ostatnich latach"))

    if m.get("lat_danych"):
        mozliwe += WAGI["ciaglosc"]
        if m.get("obcinala"):
            powody.append(("zle", "W znanej historii obcinała już dywidendę"))
        else:
            zdobyte += WAGI["ciaglosc"]
            powody.append(("dobry", f"Ani razu nie obcięła przez {m['lat_danych']} lat"))

    if isinstance(stopa_pct, (int, float)):
        mozliwe += WAGI["stopa"]
        if stopa_pct <= 8:
            zdobyte += WAGI["stopa"]
        elif stopa_pct <= 12:
            zdobyte += WAGI["stopa"] * 0.5
            powody.append(("uwaga", f"Stopa {stopa_pct:.1f}% jest wysoka — sprawdź, czy nie jednorazowa"))
        else:
            powody.append(("zle", f"Stopa {stopa_pct:.1f}% bywa sygnałem kłopotów, nie hojności"))

    if mozliwe < 50:
        return {"ocena": None, "poziom": "brak", "powody": powody,
                "opis": "Za mało danych, żeby uczciwie ocenić"}

    ocena = round(zdobyte / mozliwe * 100)
    if ocena >= 80:
        poziom, opis = "wysokie", "Dywidenda wygląda na dobrze ugruntowaną"
    elif ocena >= 60:
        poziom, opis = "srednie", "Dywidenda wygląda solidnie, ale bez dużego zapasu"
    elif ocena >= 40:
        poziom, opis = "niskie", "Sporo znaków zapytania — sprawdź, zanim kupisz dla dywidendy"
    else:
        poziom, opis = "ryzykowne", "Historia i wskaźniki nie dają pewności co do wypłaty"
    return {"ocena": ocena, "poziom": poziom, "powody": powody, "opis": opis}


# --------------------------------------------------------------- podatek


#: Podatek od zysków kapitałowych w Polsce.
PODATEK_PL = 19.0

#: Podatek pobierany u źródła przy dywidendach z USA dla polskiego rezydenta,
#: gdy złożył formularz W-8BEN u brokera. Bez niego bywa 30%.
PODATEK_ZRODLO_USA = 15.0


def po_podatku(kwota: float, rynek: str, w8ben: bool = True) -> dict:
    """Kwota dywidendy przed i po podatku. Rozbite, bo różnica bywa zaskoczeniem.

    Dla spółki z GPW to po prostu 19% podatku Belki. Dla amerykańskiej najpierw
    broker oddaje fiskusowi w USA 15% (przy złożonym W-8BEN), a w Polsce dopłaca
    się różnicę do 19% — łącznie te same 19%, ale rozbite na dwa kraje i to jest
    powód, dla którego ludzie widzą na rachunku inną kwotę, niż się spodziewali.
    Bez W-8BEN u źródła schodzi 30% i tej nadwyżki nie da się już odzyskać
    zwykłym rozliczeniem.

    To jest wyliczenie orientacyjne, a nie porada podatkowa — i tak jest opisane
    wszędzie, gdzie się pokazuje.
    """
    if rynek == "USA":
        stopa_zrodla = PODATEK_ZRODLO_USA if w8ben else 30.0
        u_zrodla = kwota * stopa_zrodla / 100
        # W Polsce dopłacamy różnicę do 19%, ale nigdy poniżej zera.
        w_polsce = max(kwota * PODATEK_PL / 100 - u_zrodla, 0.0)
    else:
        u_zrodla = 0.0
        w_polsce = kwota * PODATEK_PL / 100

    laczny = u_zrodla + w_polsce
    return {
        "brutto": round(kwota, 2),
        "podatek_zrodlo": round(u_zrodla, 2),
        "podatek_pl": round(w_polsce, 2),
        "podatek_razem": round(laczny, 2),
        "netto": round(kwota - laczny, 2),
        "efektywny_pct": round(laczny / kwota * 100, 1) if kwota else 0.0,
    }


# --------------------------------------------------------------- projekcja


def projekcja(kwota: float, stopa_pct: float, wzrost_pct: float = 0.0,
              lat: int = 10, reinwestycja: bool = True, rynek: str = "GPW",
              doplata_roczna: float = 0.0, w8ben: bool = True) -> dict:
    """Ile dywidend da kwota zainwestowana na danych warunkach przez `lat` lat.

    Model jest celowo prosty i **jawnie zakłada stały kurs akcji**. Kuszące jest
    dorzucenie wzrostu kursu, bo liczby robią się ładniejsze, ale wtedy wynik
    zależałby głównie od zmyślonego założenia o rynku, a nie od dywidendy —
    a to jest kalkulator dywidendy, nie prognoza portfela.

    Co model uwzględnia: wzrost samej dywidendy (spółki ją podnoszą),
    reinwestycję wypłat po tym samym kursie, coroczne dopłaty i podatek.
    """
    kwota = max(float(kwota or 0), 0.0)
    lat = max(1, min(int(lat or 1), 40))
    stopa = max(float(stopa_pct or 0), 0.0) / 100
    wzrost = float(wzrost_pct or 0) / 100

    kapital = kwota
    wiersze = []
    suma_brutto = suma_netto = suma_podatku = 0.0
    biezaca_stopa = stopa

    for rok in range(1, lat + 1):
        brutto = kapital * biezaca_stopa
        p = po_podatku(brutto, rynek, w8ben)
        suma_brutto += brutto
        suma_netto += p["netto"]
        suma_podatku += p["podatek_razem"]

        # Yield on cost: ile procent WŁASNYCH PIENIĘDZY daje dywidenda w tym roku.
        # To jest liczba, dla której ludzie w ogóle inwestują dywidendowo — po
        # latach podwyżek potrafi być wielokrotnością stopy z dnia zakupu.
        #
        # Mianownikiem jest suma wpłat DO TEGO ROKU, a nie sama pierwsza wpłata.
        # Przy włączonych dopłatach rocznych dzielenie przez pierwszą wpłatę
        # dawało 56% tam, gdzie uczciwa liczba to 20% — bo licznik rósł też
        # dzięki dopłatom, a mianownik stał w miejscu. Reinwestowane dywidendy
        # do mianownika NIE wchodzą: to pieniądze z inwestycji, nie z kieszeni.
        wlozone = kwota + max(float(doplata_roczna or 0), 0.0) * (rok - 1)
        yoc = (brutto / wlozone * 100) if wlozone else 0.0

        wiersze.append({
            "rok": rok,
            "kapital": round(kapital, 2),
            "brutto": round(brutto, 2),
            "netto": p["netto"],
            "podatek": p["podatek_razem"],
            "yield_on_cost": round(yoc, 2),
            "narastajaco_netto": round(suma_netto, 2),
        })

        if reinwestycja:
            kapital += p["netto"]
        kapital += max(float(doplata_roczna or 0), 0.0)
        biezaca_stopa *= (1 + wzrost)

    ostatni = wiersze[-1]
    return {
        "wiersze": wiersze,
        "wplacone": round(kwota + max(float(doplata_roczna or 0), 0.0) * lat, 2),
        "kapital_koncowy": round(kapital, 2),
        "suma_brutto": round(suma_brutto, 2),
        "suma_netto": round(suma_netto, 2),
        "suma_podatku": round(suma_podatku, 2),
        "miesiecznie_ostatni_rok": round(ostatni["netto"] / 12, 2),
        "yield_on_cost_koncowy": ostatni["yield_on_cost"],
        "zalozenia": {
            "kurs_bez_zmian": True,
            "stopa_startowa_pct": round(stopa * 100, 2),
            "wzrost_dywidendy_pct": round(wzrost * 100, 2),
            "reinwestycja": bool(reinwestycja),
            "lat": lat,
            "rynek": rynek,
            "w8ben": bool(w8ben),
        },
    }
