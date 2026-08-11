"""Polskie frazy w klastrach tematycznych — po jednym klastrze na podstronę.

Do czego to służy: każda podstrona bierze 4–8 fraz ze SWOJEGO klastra i wplata je
w tytuł, opis, nagłówki i pierwszy akapit. Nie ma tu jednej worki ze słowami
wrzuconej na wszystkie strony — dwie strony walczące o tę samą frazę zjadają
sobie pozycję (kanibalizacja) i Google wybiera wtedy jedną, zwykle nie tę, którą
byśmy chcieli.

Skąd te frazy: z rozpoznania rynku zrobionego przy okazji nazwy produktu —
realne zapytania do API App Store i wzorce autouzupełniania Google.pl.
Kluczowy wniosek, który wyznacza całą strategię: **„kalendarz wyników” to dziura
w polskim internecie** (w App Store zero aplikacji, „wyniki spółek” jedna), a
„portfel inwestycyjny” ma zajęte pierwsze miejsca przez myfund i Portfeo. Dlatego
frazy o kalendarzu i wynikach są w hierarchii wyżej niż frazy o portfelu, choć
sam portfel jest w aplikacji większym modułem.

Zasada języka: piszemy WYŁĄCZNIE po polsku, bo celujemy w Google.pl. Wyjątkiem
są dwa anglicyzmy, które Polacy naprawdę wpisują w wyszukiwarkę („earnings
calendar” jako termin branżowy i „ETF”, które po polsku nie ma odpowiednika).
Nazwy własne wskaźników („EPS”, „C/Z”) to nie anglicyzmy, tylko terminy.

Listę weryfikuj w Google Search Console po pierwszych 4–6 tygodniach od
zaindeksowania: raport „Zapytania” pokaże frazy, na które faktycznie nas widać,
i to one — nie ta lista — są prawdą o rynku.
"""

from __future__ import annotations

#: Frazy nośne całego serwisu — tytuł i opis strony aplikacji oraz llms.txt.
PRIMARY = (
    "kalendarz wyników spółek",
    "wyniki finansowe spółek",
    "portfel inwestycyjny",
    "wyniki kwartalne",
    "kalendarz raportów GPW",
)

#: Kalendarz wyników — nasza flagowa podstrona, tu wchodzi najmocniejszy klaster.
EARNINGS = (
    "kalendarz wyników spółek",
    "kalendarz wyników",
    "wyniki kwartalne spółek",
    "terminy publikacji raportów",
    "kalendarz raportów finansowych",
    "kiedy spółka publikuje wyniki",
    "sezon wyników",
    "raporty kwartalne GPW",
    "earnings calendar",          # 1/2 dopuszczonych anglicyzmów — termin branżowy
)

#: Podstrony pojedynczych spółek — frazy z nazwą spółki dokładamy dynamicznie.
COMPANY = (
    "wyniki finansowe",
    "wyniki kwartalne",
    "raport kwartalny",
    "prognoza EPS",
    "konsensus analityków",
    "zaskoczenie wynikami",
    "reakcja kursu na wyniki",
    "kiedy wyniki",
)

#: Portfel — walczymy tu z myfund i Portfeo, więc frazy celują w konkret
#: („import XTB”, „stopa zwrotu”), a nie w ogólne „portfel inwestycyjny”.
PORTFOLIO = (
    "portfel inwestycyjny",
    "śledzenie portfela inwestycyjnego",
    "aplikacja do portfela inwestycyjnego",
    "stopa zwrotu portfela",
    "jak liczyć zysk z akcji",
    "import raportu XTB",
    "wycena portfela w złotówkach",
    "portfel akcji i ETF",
    "koszty i prowizje maklerskie",
)

#: Skaner ETF.
ETF = (
    "skaner ETF",
    "porównanie ETF",
    "najlepsze ETF",
    "ETF na S&P 500",
    "ETF akumulujące",
    "opłata za zarządzanie TER",
    "ETF na WIG20",
    "w co inwestować ETF",
)

#: Karta spółki: notowania, wskaźniki, spółki podobne.
MARKET = (
    "notowania spółek",
    "kurs akcji",
    "wskaźnik C/Z",
    "kapitalizacja spółki",
    "dywidenda spółki",
    "wskaźniki finansowe spółki",
    "notowania GPW",
    "porównanie spółek z branży",
)

#: Alokacja i ryzyko portfela.
ALLOCATION = (
    "alokacja portfela",
    "dywersyfikacja portfela",
    "ryzyko portfela inwestycyjnego",
    "korelacja spółek w portfelu",
    "koncentracja portfela",
    "podział portfela na klasy aktywów",
    "zmienność portfela",
)

#: Kalendarz makroekonomiczny.
MACRO = (
    "kalendarz makroekonomiczny",
    "dane makro",
    "inflacja CPI odczyt",
    "decyzja RPP stopy procentowe",
    "posiedzenie Fed",
    "kalendarz ekonomiczny",
    "publikacja danych gospodarczych",
)

#: Analiza newsów przez model językowy.
NEWS_AI = (
    "analiza newsów giełdowych",
    "wpływ newsów na kurs akcji",
    "raporty ESPI",
    "komunikaty spółek giełdowych",
    "sztuczna inteligencja na giełdzie",
    "wydźwięk informacji rynkowej",
)

#: Poradniki i słownik — frazy informacyjne, najczęściej cytowane przez modele AI.
EDUCATION = (
    "co to jest EPS",
    "jak czytać raport kwartalny",
    "jak czytać raport ESPI",
    "co to jest wskaźnik C/Z",
    "czym jest stopa zwrotu XIRR",
    "kiedy GPW publikuje wyniki",
    "co to sezon wyników",
    "jak zacząć inwestować na giełdzie",
    "słownik pojęć giełdowych",
)


def wszystkie() -> list[str]:
    """Wszystkie frazy bez powtórzeń — do llms.txt i do przeglądu całości."""
    widziane: dict[str, None] = {}
    for klaster in (PRIMARY, EARNINGS, COMPANY, PORTFOLIO, ETF, MARKET,
                    ALLOCATION, MACRO, NEWS_AI, EDUCATION):
        for fraza in klaster:
            widziane.setdefault(fraza, None)
    return list(widziane)
