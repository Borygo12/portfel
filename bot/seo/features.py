"""Podstrony funkcji — po jednej na każdy moduł aplikacji.

Dlaczego osobna strona na funkcję, a nie jedna długa strona główna: ludzie nie
szukają „aplikacji do inwestowania”. Szukają „kalendarz wyników spółek”, „skaner
ETF”, „jak liczyć stopę zwrotu z portfela” — czyli konkretnego zadania. Strona,
która odpowiada dokładnie na jedno takie zapytanie, wygrywa z ogólną stroną
o wszystkim, bo Google dopasowuje wynik do intencji, a nie do liczby słów.

Każda strona ma własny klaster fraz z `keywords.py` i celowo NIE powtarza fraz
sąsiadów — dwie nasze strony walczące o to samo zapytanie odbierają sobie
pozycję i Google wybiera jedną, zwykle przypadkową.

Treść opisuje wyłącznie to, co aplikacja naprawdę robi. Obietnica, której produkt
nie spełnia, zwraca się natychmiast w statystykach: człowiek wraca do wyników
wyszukiwania po kilku sekundach, a to jeden z niewielu sygnałów jakości, który
Google mierzy bezbłędnie.
"""

from __future__ import annotations

from . import jsonld, keywords, render

# Ceny bierzemy z jednego miejsca w kodzie — inaczej cennik na stronie i cennik
# pod kłódką rozjadą się przy pierwszej zmianie.
try:
    from premium import PLANS as _PLANY
    _CENA_MC = next((p["price"] for p in _PLANY if p["id"] == "monthly"), 29.0)
    _CENA_ROK = next((p["price"] for p in _PLANY if p["id"] == "yearly"), 249.0)
except Exception:  # noqa: BLE001 — strona ma się wyświetlić nawet bez modułu premium
    _CENA_MC, _CENA_ROK = 29.0, 249.0


# --------------------------------------------------------------- dane stron

STRONY = {

    # ---------------------------------------------------------- kalendarz wyników
    "/kalendarz-wynikow-spolek": {
        "nadtytul": "Funkcja darmowa",
        "h1": "Kalendarz wyników spółek — GPW i giełdy amerykańskie",
        "tytul": "Kalendarz wyników spółek 2026 — GPW i USA | Portevo",
        "opis": "Sprawdź, kiedy spółki publikują wyniki kwartalne. Kalendarz "
                "raportów z GPW i giełd amerykańskich, prognozy analityków "
                "i historia reakcji kursu. Za darmo, po polsku.",
        "lead": "Terminy publikacji raportów kwartalnych na jednym ekranie: spółki "
                "z warszawskiej giełdy obok amerykańskich, z prognozą zysku na akcję, "
                "godziną publikacji i informacją, jak kurs zachowywał się po "
                "poprzednich wynikach.",
        "akcje": [("/", "Otwórz kalendarz"), ("/wyniki-finansowe", "Wyniki spółek A–Z")],
        "sekcje": [
            {
                "h2": "Co pokazuje kalendarz wyników",
                "p": [
                    "Kalendarz układa spółki dzień po dniu i mówi wprost, "
                    "<strong>kiedy spółka publikuje wyniki</strong> — przed otwarciem "
                    "sesji, po jej zamknięciu, czy termin jest jeszcze niepotwierdzony. "
                    "To rozróżnienie ma znaczenie praktyczne: raport ogłoszony po "
                    "zamknięciu rynku amerykańskiego zobaczysz w reakcji kursu dopiero "
                    "następnego dnia.",
                ],
                "lista": [
                    "<b>Data i pora publikacji</b> — przed otwarciem, po zamknięciu "
                    "albo termin szacowany, gdy spółka jeszcze go nie potwierdziła.",
                    "<b>Prognoza zysku na akcję</b> (EPS) i liczba analityków, którzy "
                    "ją przygotowali — jedna prognoza to co innego niż zgodna opinia "
                    "trzydziestu.",
                    "<b>Kapitalizacja spółki</b>, żeby od razu było widać, czy raport "
                    "poruszy indeks, czy tylko własny kurs.",
                    "<b>Twoje spółki wyróżnione</b> — pozycje z portfela i obserwowane "
                    "wyskakują z listy, więc nie przegapisz raportu firmy, którą masz.",
                    "<b>Wydarzenia makroekonomiczne w tle</b> — odczyt inflacji tego "
                    "samego dnia potrafi przykryć dobry raport spółki.",
                ],
            },
            {
                "h2": "Sezon wyników na GPW i w USA w jednym widoku",
                "p": [
                    "Polskie spółki i amerykańskie raportują w innym rytmie i wedle "
                    "innych przepisów, a większość narzędzi pokazuje tylko jedną z tych "
                    "stron. Portevo składa oba rynki w jedną listę: "
                    "<strong>raporty kwartalne GPW</strong> pobierane osobno dla spółek "
                    "warszawskich i pełny kalendarz spółek notowanych w Stanach.",
                    "Listę można zawęzić do spółek popularnych, do progu kapitalizacji "
                    "albo posortować po godzinie publikacji, liczbie prognoz "
                    "i alfabetycznie. Przy kilkuset spółkach raportujących jednego dnia "
                    "w szczycie sezonu wyników to różnica między listą do przejrzenia "
                    "a ścianą tekstu.",
                ],
            },
            {
                "h2": "Raport spółki przed publikacją wyników",
                "p": [
                    "Kliknięcie w spółkę otwiera jej kartę: konsensus na najbliższy "
                    "kwartał wraz z widełkami, historia zaskoczeń z poprzednich "
                    "kwartałów, marże kwartał po kwartale i — co najciekawsze — "
                    "<strong>reakcja kursu na sesji po każdym poprzednim raporcie</strong>. "
                    "Z tego składa się odpowiedź na pytanie, które pada najczęściej: "
                    "„ile ta spółka zwykle skacze po wynikach”.",
                ],
            },
        ],
        "karty": (
            ("/wyniki-finansowe/gpw", "Wyniki spółek z GPW",
             "Terminy i historia raportów spółek z WIG20, mWIG40 i sWIG80.", "Polska"),
            ("/wyniki-finansowe/usa", "Wyniki spółek z USA",
             "Apple, Nvidia, Tesla i reszta największych — kwartał po kwartale.", "Świat"),
            ("/kalendarz-makroekonomiczny", "Kalendarz makroekonomiczny",
             "Inflacja, stopy procentowe i dane, które ruszają całym rynkiem.", "Makro"),
        ),
        "faq": [
            ("Czy kalendarz wyników jest darmowy?",
             "Tak. Kalendarz wyników, karta spółki z prognozami i historia reakcji "
             "kursu działają bez opłat i bez konta — wystarczy otworzyć stronę. "
             "Konto przydaje się dopiero, gdy chcesz wgrać własny portfel."),
            ("Skąd pochodzą terminy publikacji raportów?",
             "Dla spółek amerykańskich z kalendarza giełdy Nasdaq, dla spółek "
             "warszawskich z danych Yahoo Finance. Terminy niepotwierdzone przez "
             "spółkę są oznaczone jako szacowane — bywa, że firma przesuwa publikację."),
            ("Czy widzę wyniki spółek z GPW?",
             "Tak. Kalendarz obejmuje najpłynniejsze spółki z warszawskiej giełdy, "
             "a dodatkowo wszystkie, które masz w portfelu lub na liście obserwowanych. "
             "Karta spółki działa dla tickerów w formacie giełdy warszawskiej."),
            ("Co oznacza „przed otwarciem” i „po zamknięciu”?",
             "To pora, o której spółka publikuje raport względem sesji giełdowej. "
             "Publikacja przed otwarciem daje rynkowi czas na reakcję jeszcze przed "
             "startem notowań, publikacja po zamknięciu przenosi całą reakcję na "
             "następny dzień. Gdy spółka nie podała pory, kalendarz pokazuje „termin "
             "do potwierdzenia”."),
            ("Czy dostanę powiadomienie o wynikach mojej spółki?",
             "Spółki z Twojego portfela i listy obserwowanych są w kalendarzu "
             "wyróżnione, a licznik przy każdym dniu pokazuje, ile z nich raportuje. "
             "Powiadomienia push są w planach rozwoju."),
        ],
        "cta": ("Zobacz, kto raportuje w tym tygodniu",
                "Kalendarz otwiera się od razu, bez zakładania konta. Spółki z GPW "
                "i z USA, prognozy analityków i historia reakcji kursu."),
        "frazy": keywords.EARNINGS,
        "powiazane": [
            ("/wyniki-finansowe", "Wyniki finansowe spółek A–Z"),
            ("/poradniki/kiedy-spolki-publikuja-wyniki", "Kiedy spółki publikują wyniki"),
            ("/poradniki/jak-czytac-raport-kwartalny", "Jak czytać raport kwartalny"),
            ("/slownik/eps", "Co to jest EPS"),
            ("/slownik/konsensus-analitykow", "Konsensus analityków"),
        ],
    },

    # ---------------------------------------------------------- portfel
    "/portfel-inwestycyjny": {
        "nadtytul": "Funkcja darmowa",
        "h1": "Portfel inwestycyjny — śledzenie inwestycji z raportu maklerskiego",
        "tytul": "Portfel inwestycyjny — aplikacja do śledzenia inwestycji | Portevo",
        "opis": "Wgraj raport z rachunku maklerskiego i zobacz wartość portfela "
                "w złotówkach, prawdziwą stopę zwrotu, koszty i porównanie "
                "z indeksami. Bez ręcznego wpisywania transakcji.",
        "lead": "Wgrywasz raport operacji z rachunku maklerskiego, a Portevo odtwarza "
                "z niego cały portfel: pozycje, wpłaty, prowizje i wycenę dzień po "
                "dniu w złotówkach. Bez przepisywania transakcji do arkusza i bez "
                "podawania komukolwiek danych logowania do brokera.",
        "akcje": [("/", "Otwórz portfel"), ("/analiza-portfela", "Analiza i ryzyko")],
        "sekcje": [
            {
                "h2": "Skąd biorą się dane o portfelu",
                "p": [
                    "Z pliku, który sam pobierasz od brokera — raport historii operacji "
                    "w formacie XLSX, CSV lub ZIP. Portevo <strong>nie łączy się z Twoim "
                    "rachunkiem maklerskim</strong>, nie prosi o hasło do konta brokera "
                    "i nie ma dostępu do Twoich pieniędzy. To świadomy wybór: import "
                    "pliku daje te same dane, a nie wymaga powierzania nikomu kluczy do "
                    "rachunku.",
                    "Import jest powtarzalny. Operacje mają własny identyfikator, więc "
                    "wgranie tego samego raportu drugi raz niczego nie dubluje — "
                    "dokładają się tylko nowe wiersze. Nowy raport wgrywasz raz na "
                    "jakiś czas i portfel po prostu nadgania.",
                ],
            },
            {
                "h2": "Co Portevo liczy za Ciebie",
                "lista": [
                    "<b>Wartość portfela w złotówkach</b> — pozycje w dolarach i euro "
                    "przeliczane po kursie z dnia, więc widzisz jedną liczbę, a nie "
                    "cztery waluty do dodania w głowie.",
                    "<b>Stopę zwrotu odporną na wpłaty</b> — wpłata nowych pieniędzy "
                    "podnosi wartość portfela, ale nie jest zyskiem. Portevo liczy "
                    "osobno wynik z inwestycji i osobno linię wpłat.",
                    "<b>Koszty</b> — prowizje faktycznie zapłacone, wyliczone z historii "
                    "operacji, oraz koszt wyjścia z bieżących pozycji według profilu "
                    "prowizji Twojego brokera.",
                    "<b>Porównanie z rynkiem</b> — ta sama krzywa nałożona na S&P 500, "
                    "WIG, WIG20 i polską inflację. Zysk niższy od inflacji to realna "
                    "strata i wykres pokazuje to bez owijania.",
                    "<b>Pozycje zamknięte</b> — skuteczność, średni zysk i strata, "
                    "średni czas trzymania pozycji, najlepsza i najgorsza transakcja.",
                ],
            },
            {
                "h2": "Wykres, który nie kłamie na krótkich zakresach",
                "p": [
                    "Tydzień złożony z notowań na koniec dnia to pięć punktów, z czego "
                    "dwa to powtórzony piątek — wykres wychodzi wtedy płaską kreską "
                    "i wygląda, jakby nic się nie działo. Zakresy dzienne i tygodniowe "
                    "Portevo składa ze słupków śróddziennych, więc krótki zakres "
                    "pokazuje realny przebieg sesji, a nie schodki.",
                ],
            },
        ],
        "karty": (
            ("/analiza-portfela", "Alokacja i ryzyko",
             "Z czego naprawdę składa się portfel i co z tego wynika.", "Analiza"),
            ("/notowania-spolek", "Notowania i wskaźniki",
             "Karta spółki z wykresem, na którym widać Twoje zakupy.", "Rynek"),
            ("/poradniki/jak-liczyc-stope-zwrotu", "Jak liczyć stopę zwrotu",
             "Dlaczego „ile mam minus ile wpłaciłem” to zła miara.", "Poradnik"),
        ),
        "faq": [
            ("Z jakich brokerów mogę wgrać raport?",
             "Import jest przygotowany pod raporty XTB w formacie XLSX — to najczęściej "
             "używany rachunek w Polsce. Pliki CSV i ZIP też są rozpoznawane. Obsługę "
             "kolejnych brokerów dokładamy na podstawie zgłoszeń użytkowników."),
            ("Czy Portevo ma dostęp do moich pieniędzy?",
             "Nie. Aplikacja czyta wyłącznie plik z historią operacji, który sam "
             "wgrywasz. Nie łączy się z rachunkiem maklerskim, nie zna hasła do niego "
             "i nie wykonuje żadnych transakcji."),
            ("Czy śledzenie portfela jest płatne?",
             f"Nie. Import raportu, wycena portfela, stopa zwrotu, koszty i porównanie "
             f"z indeksami są darmowe. Płatne są dodatkowe narzędzia analityczne — "
             f"{render.liczba(_CENA_MC, 0)} zł miesięcznie albo "
             f"{render.liczba(_CENA_ROK, 0)} zł za rok."),
            ("Czy mogę mieć kilka rachunków w jednym portfelu?",
             "Tak. Raporty z różnych rachunków wgrywasz jeden po drugim, a Portevo "
             "trzyma je osobno i jednocześnie sumuje do jednego widoku. Każdemu kontu "
             "można też ustawić własny profil prowizji."),
            ("Co się stanie z moimi danymi, gdy usunę konto?",
             "Usunięcie konta w zakładce „Więcej” kasuje wszystkie dane portfela "
             "natychmiast i bezpowrotnie. Nie trzeba do nas pisać ani czekać."),
        ],
        "cta": ("Zobacz swój portfel w złotówkach",
                "Wgraj raport z rachunku maklerskiego i w kilkanaście sekund masz "
                "wycenę, stopę zwrotu i koszty. Bez podawania danych do brokera."),
        "frazy": keywords.PORTFOLIO,
        "powiazane": [
            ("/analiza-portfela", "Analiza i ryzyko portfela"),
            ("/poradniki/jak-liczyc-stope-zwrotu", "Jak liczyć stopę zwrotu"),
            ("/poradniki/koszty-inwestowania", "Koszty inwestowania na giełdzie"),
            ("/slownik/xirr", "Co to jest XIRR"),
            ("/slownik/twr", "Stopa zwrotu ważona czasem (TWR)"),
        ],
    },

    # ---------------------------------------------------------- ETF
    "/skaner-etf": {
        "nadtytul": "Narzędzie",
        "h1": "Skaner ETF — wyszukiwarka i porównywarka funduszy",
        "tytul": "Skaner ETF — porównanie funduszy ETF po polsku | Portevo",
        "opis": "Przefiltruj fundusze ETF po regionie, sektorze, klasie aktywów "
                "i walucie. Stopy zwrotu, opłata za zarządzanie i porównanie "
                "funduszy obok siebie — po polsku.",
        "lead": "Fundusze ETF opisane po polsku, z filtrami, które mają znaczenie przy "
                "wyborze: region, sektor, klasa aktywów, waluta notowania i opłata za "
                "zarządzanie. Bez przekopywania się przez angielskie karty funduszy.",
        "akcje": [("/", "Otwórz skaner")],
        "sekcje": [
            {
                "h2": "Po czym filtrujesz",
                "lista": [
                    "<b>Region</b> — świat, rynki rozwinięte, USA, Europa, rynki "
                    "wschodzące, Polska.",
                    "<b>Klasa aktywów</b> — akcje, obligacje, surowce, złoto.",
                    "<b>Sektor</b> — technologia, zdrowie, energia, finanse i reszta.",
                    "<b>Waluta notowania</b> — bo fundusz w dolarach kupowany za "
                    "złotówki dokłada do wyniku ryzyko kursowe.",
                    "<b>Stopa zwrotu</b> za rok, trzy lata i pięć lat — do sortowania "
                    "listy.",
                ],
            },
            {
                "h2": "Opłata za zarządzanie widoczna od razu",
                "p": [
                    "Wskaźnik kosztów całkowitych (TER) to jedyna liczba w tym zestawieniu, "
                    "którą znasz z góry na pewno — przyszłej stopy zwrotu nie zna nikt, "
                    "a opłata jest pewna i pobierana co roku. Przy horyzoncie "
                    "dwudziestoletnim różnica między funduszem za 0,07% a 0,45% rocznie "
                    "to kilkanaście procent końcowego kapitału.",
                ],
            },
            {
                "h2": "Prześwietlenie funduszu i porównywarka",
                "p": [
                    "Lista funduszy i filtry są darmowe — masz zobaczyć, co jest do "
                    "wyboru, zanim za cokolwiek zapłacisz. Szczegółowe prześwietlenie "
                    "pojedynczego funduszu, jego skład i zestawienie kilku funduszy obok "
                    "siebie należą do wersji płatnej.",
                ],
            },
        ],
        "faq": [
            ("Czym jest ETF?",
             "Fundusz notowany na giełdzie, który odwzorowuje zachowanie całego "
             "indeksu, sektora albo surowca. Kupujesz jeden papier i masz w nim "
             "kilkaset spółek naraz — stąd popularność ETF-ów jako podstawy portfela "
             "długoterminowego."),
            ("Co oznacza skrót TER?",
             "Total Expense Ratio, czyli wskaźnik kosztów całkowitych funduszu. Mówi, "
             "ile procent wartości Twojej inwestycji fundusz pobiera rocznie za "
             "zarządzanie. Nie płacisz go osobno — jest odejmowany z wyniku funduszu."),
            ("Czym różni się ETF akumulujący od dystrybuującego?",
             "Akumulujący reinwestuje dywidendy wewnątrz funduszu, dystrybuujący "
             "wypłaca je na rachunek. Dla polskiego inwestora akumulujący bywa "
             "wygodniejszy podatkowo, bo odsuwa moment rozliczenia — ale rozstrzyga "
             "to Twoja sytuacja, nie ogólna zasada."),
            ("Czy skaner ETF jest darmowy?",
             "Katalog funduszy, filtry i lista wyników są darmowe. Prześwietlenie "
             "pojedynczego funduszu i porównywarka są w wersji płatnej."),
        ],
        "cta": ("Znajdź fundusz pod swój portfel",
                "Filtruj po regionie, klasie aktywów i opłacie, a potem sprawdź, jak "
                "ETF-y wyglądają obok siebie."),
        "frazy": keywords.ETF,
        "powiazane": [
            ("/portfel-inwestycyjny", "Portfel inwestycyjny"),
            ("/slownik/etf", "Co to jest ETF"),
            ("/slownik/ter", "Opłata za zarządzanie (TER)"),
            ("/poradniki/jak-zaczac-inwestowac", "Jak zacząć inwestować"),
        ],
    },

    # ---------------------------------------------------------- alokacja i ryzyko
    "/analiza-portfela": {
        "nadtytul": "Analiza",
        "h1": "Analiza portfela — alokacja, dywersyfikacja i ryzyko",
        "tytul": "Analiza portfela — alokacja, ryzyko i korelacja | Portevo",
        "opis": "Sprawdź, z czego naprawdę składa się Twój portfel: podział na klasy "
                "aktywów, rynki, sektory i waluty, koncentracja, zmienność "
                "i korelacja największych pozycji.",
        "lead": "Portfel z dwudziestu spółek bywa mniej zdywersyfikowany niż z pięciu — "
                "jeśli wszystkie stoją w tej samej branży i tej samej walucie. Analiza "
                "pokazuje ten obraz wprost, zamiast zostawiać go domysłom.",
        "akcje": [("/", "Otwórz analizę"), ("/portfel-inwestycyjny", "Zacznij od portfela")],
        "sekcje": [
            {
                "h2": "Sześć sposobów spojrzenia na ten sam portfel",
                "p": [
                    "Ten sam zestaw pozycji, pokazany w sześciu podziałach: klasa "
                    "aktywów, rynek, sektor, waluta, pojedyncza pozycja i rachunek "
                    "maklerski. Gotówka jest liczona razem z resztą, bo pieniądze "
                    "leżące na rachunku to też decyzja o alokacji — po prostu rzadko "
                    "świadoma.",
                ],
            },
            {
                "h2": "Rentgen ryzyka",
                "lista": [
                    "<b>Koncentracja</b> — ile portfela stoi w największej pozycji "
                    "i w pierwszej piątce.",
                    "<b>Zmienność</b> — jak mocno portfel waha się w porównaniu "
                    "z szerokim rynkiem.",
                    "<b>Wkład pozycji w wahania</b> — która spółka faktycznie generuje "
                    "ruch całości. To rzadko ta, którą się podejrzewa.",
                    "<b>Macierz korelacji</b> — czy Twoje największe pozycje poruszają "
                    "się razem. Trzy spółki technologiczne to w praktyce jedna pozycja "
                    "pomnożona przez trzy.",
                ],
            },
            {
                "h2": "Do czego to służy",
                "p": [
                    "Nie do przewidywania rynku — tego nie umie nikt. Do zauważenia "
                    "ryzyka, które już wziąłeś, nie podejmując o nim decyzji: "
                    "<strong>koncentracji w jednej branży</strong>, całego portfela "
                    "w jednej walucie albo pozycji, która urosła tak, że sama decyduje "
                    "o wyniku całości.",
                ],
            },
        ],
        "faq": [
            ("Co to jest dywersyfikacja portfela?",
             "Rozłożenie kapitału tak, żeby wynik nie zależał od jednego zdarzenia. "
             "Liczy się nie liczba pozycji, tylko to, czy reagują na różne rzeczy — "
             "dziesięć spółek z jednej branży spada zwykle razem."),
            ("Czym jest korelacja i po co ją sprawdzać?",
             "To miara tego, czy dwa instrumenty poruszają się w tę samą stronę. "
             "Wysoka korelacja między pozycjami oznacza, że portfel jest mniej "
             "rozłożony, niż wynika z liczby spółek."),
            ("Czy analiza ryzyka jest płatna?",
             f"Podstawowy podział portfela na klasy aktywów, sektory i waluty jest "
             f"darmowy. Rentgen ryzyka i macierz korelacji należą do wersji płatnej "
             f"({render.liczba(_CENA_MC, 0)} zł miesięcznie)."),
        ],
        "cta": ("Sprawdź, gdzie naprawdę siedzi Twoje ryzyko",
                "Wgraj raport z rachunku maklerskiego, a podział portfela i "
                "koncentracja pozycji policzą się same."),
        "frazy": keywords.ALLOCATION,
        "powiazane": [
            ("/portfel-inwestycyjny", "Portfel inwestycyjny"),
            ("/slownik/dywersyfikacja", "Dywersyfikacja"),
            ("/slownik/korelacja", "Korelacja"),
            ("/slownik/zmiennosc", "Zmienność"),
        ],
    },

    # ---------------------------------------------------------- notowania i spółki
    "/notowania-spolek": {
        "nadtytul": "Rynek",
        "h1": "Notowania spółek i wskaźniki finansowe",
        "tytul": "Notowania spółek i wskaźniki — GPW i świat | Portevo",
        "opis": "Kurs, kapitalizacja, wskaźnik C/Z, dywidenda i porównanie z podobnymi "
                "spółkami z branży. Wyszukiwarka obejmuje GPW, giełdy amerykańskie, "
                "ETF-y i kryptowaluty.",
        "lead": "Wpisujesz nazwę spółki i dostajesz jej kartę: notowanie, opis "
                "działalności, wskaźniki finansowe i medianę tych samych wskaźników "
                "dla spółek z branży — bo sam wskaźnik C/Z nic nie mówi, dopóki nie ma "
                "do czego go przyłożyć.",
        "akcje": [("/", "Otwórz wyszukiwarkę"), ("/wyniki-finansowe", "Wyniki spółek A–Z")],
        "sekcje": [
            {
                "h2": "Wyszukiwarka obejmuje cały świat",
                "p": [
                    "Spółki z warszawskiej giełdy, amerykańskie, europejskie, fundusze "
                    "ETF i kryptowaluty — w jednym polu wyszukiwania. Ticker z raportu "
                    "maklerskiego (na przykład zapis „NVDA.US”) jest rozpoznawany "
                    "automatycznie, więc nie trzeba go tłumaczyć na format giełdy.",
                ],
            },
            {
                "h2": "Wskaźniki z odniesieniem, nie w próżni",
                "lista": [
                    "<b>Wskaźnik C/Z</b> bieżący i prognozowany, obok mediany dla "
                    "spółek z tej samej branży.",
                    "<b>Kapitalizacja</b>, zakres z ostatnich 52 tygodni i cena "
                    "docelowa analityków.",
                    "<b>Dywidenda</b> i stopa dywidendy, gdy spółka ją wypłaca.",
                    "<b>Udział akcji sprzedanych krótko</b> — sygnał, ilu graczy "
                    "obstawia spadek.",
                ],
            },
            {
                "h2": "Twoje transakcje na wykresie spółki",
                "p": [
                    "Gdy masz walor w portfelu, na wykresie pojawiają się znaczniki "
                    "Twoich zakupów i sprzedaży. To najprostszy sposób, żeby zobaczyć "
                    "własne decyzje na tle przebiegu kursu — bez przepisywania dat do "
                    "arkusza.",
                ],
            },
        ],
        "faq": [
            ("Co oznacza wskaźnik C/Z?",
             "Cena akcji podzielona przez zysk przypadający na jedną akcję. Mówi, ile "
             "lat zysków w obecnej wysokości „mieści się” w cenie. Wysoki C/Z oznacza "
             "wysokie oczekiwania rynku, niski — albo okazję, albo kłopot spółki."),
            ("Czy notowania są w czasie rzeczywistym?",
             "Nie. Dane pochodzą od zewnętrznych dostawców i bywają opóźnione, zwykle "
             "o kilkanaście minut. Portevo służy do analizy i śledzenia, nie do "
             "handlu na krótkim terminie."),
            ("Czy znajdę tu spółki z GPW?",
             "Tak, wraz z ich wskaźnikami i wykresem. Wyszukiwarka rozpoznaje zarówno "
             "nazwę spółki, jak i jej ticker."),
        ],
        "cta": ("Sprawdź spółkę, zanim ją kupisz",
                "Kurs, wskaźniki i porównanie z branżą — dla GPW i giełd zagranicznych."),
        "frazy": keywords.MARKET,
        "powiazane": [
            ("/wyniki-finansowe", "Wyniki finansowe spółek"),
            ("/slownik/cz", "Wskaźnik C/Z"),
            ("/slownik/kapitalizacja", "Kapitalizacja"),
            ("/slownik/dywidenda", "Dywidenda"),
        ],
    },

    # ---------------------------------------------------------- makro
    "/kalendarz-makroekonomiczny": {
        "nadtytul": "Funkcja darmowa",
        "h1": "Kalendarz makroekonomiczny — dane, które ruszają rynkiem",
        "tytul": "Kalendarz makroekonomiczny — inflacja, stopy, dane | Portevo",
        "opis": "Terminy publikacji danych gospodarczych: inflacja, decyzje o stopach "
                "procentowych, rynek pracy i PKB. Z prognozą, poprzednim odczytem "
                "i historią, po polsku.",
        "lead": "Odczyt inflacji albo decyzja o stopach potrafi w kilka minut przykryć "
                "wszystkie dobre raporty spółek z danego dnia. Kalendarz makro pokazuje "
                "te terminy obok kalendarza wyników, żeby jedno nie zaskakiwało drugiego.",
        "akcje": [("/", "Otwórz kalendarz"),
                  ("/kalendarz-wynikow-spolek", "Kalendarz wyników spółek")],
        "sekcje": [
            {
                "h2": "Co znajdziesz w kalendarzu",
                "lista": [
                    "<b>Inflacja</b> — odczyty wskaźnika cen konsumpcyjnych dla Polski, "
                    "strefy euro i Stanów.",
                    "<b>Decyzje o stopach procentowych</b> — posiedzenia Rady Polityki "
                    "Pieniężnej, Europejskiego Banku Centralnego i amerykańskiej "
                    "Rezerwy Federalnej.",
                    "<b>Rynek pracy</b> — bezrobocie i dane o zatrudnieniu.",
                    "<b>Produkt krajowy brutto</b> i wskaźniki koniunktury.",
                    "<b>Waga wydarzenia</b> — filtr, który odsiewa szum i zostawia "
                    "odczyty faktycznie poruszające rynkiem.",
                ],
            },
            {
                "h2": "Prognoza, poprzedni odczyt i historia",
                "p": [
                    "Sama liczba nic nie znaczy — rynek reaguje na <strong>różnicę "
                    "między odczytem a prognozą</strong>. Dlatego przy każdym wydarzeniu "
                    "widać oczekiwania analityków, poprzedni odczyt i przebieg "
                    "poprzednich publikacji tego samego wskaźnika.",
                ],
            },
        ],
        "faq": [
            ("Dlaczego inflacja rusza kursami akcji?",
             "Bo od niej zależą stopy procentowe. Wyższa inflacja to zwykle wyższe "
             "stopy, a te podnoszą koszt pieniądza i obniżają wycenę przyszłych zysków "
             "spółek — najmocniej tych, których zyski są dopiero przed nimi."),
            ("Czy kalendarz obejmuje polskie dane?",
             "Tak. Odczyty dla Polski, w tym decyzje Rady Polityki Pieniężnej, są "
             "w kalendarzu obok danych ze strefy euro i Stanów Zjednoczonych."),
            ("Co oznacza waga wydarzenia?",
             "Szacunek tego, jak mocno dana publikacja zwykle porusza rynkiem. Filtr "
             "pozwala zostawić na ekranie tylko odczyty o wysokiej wadze."),
        ],
        "cta": ("Miej terminy pod ręką",
                "Kalendarz makro i kalendarz wyników spółek w jednym miejscu, za darmo."),
        "frazy": keywords.MACRO,
        "powiazane": [
            ("/kalendarz-wynikow-spolek", "Kalendarz wyników spółek"),
            ("/slownik/cpi", "Inflacja CPI"),
            ("/slownik/stopa-procentowa", "Stopa procentowa"),
        ],
    },

    # ---------------------------------------------------------- bot newsów
    "/analiza-newsow-ai": {
        "nadtytul": "Narzędzie",
        "h1": "Analiza newsów giełdowych przez sztuczną inteligencję",
        "tytul": "Analiza newsów giełdowych AI — ESPI i rynek | Portevo",
        "opis": "Model językowy czyta komunikaty spółek i newsy rynkowe, ocenia ich "
                "wydźwięk i wskazuje, kogo dotyczą. Z pomiarem, jak kurs zachował się "
                "godzinę i dobę później.",
        "lead": "Rynek reaguje na informację w sekundy, a człowiek czyta ją w minuty. "
                "Portevo nasłuchuje źródeł, oddaje komunikat modelowi językowemu "
                "i pokazuje ocenę wydźwięku wraz z uzasadnieniem — a potem sprawdza, "
                "co kurs zrobił naprawdę.",
        "akcje": [("/", "Otwórz analizy")],
        "sekcje": [
            {
                "h2": "Czego to narzędzie NIE robi",
                "p": [
                    "Nie doradza, nie składa zleceń i nie mówi, co kupić. "
                    "<strong>Portevo nie jest doradcą inwestycyjnym</strong> i nie ma "
                    "w nim słów „kup” ani „sprzedaj”. Analiza kończy się na ocenie "
                    "wydźwięku informacji — pozytywny, negatywny, neutralny — wraz "
                    "z wyjaśnieniem, skąd taka ocena. Decyzja należy wyłącznie do Ciebie.",
                ],
            },
            {
                "h2": "Jak działa nasłuch",
                "lista": [
                    "<b>Źródła</b> — komunikaty bieżące spółek z warszawskiej giełdy "
                    "(raporty ESPI) i wybrane źródła rynkowe.",
                    "<b>Rozpoznanie spółki</b> — komunikat jest wiązany z konkretnym "
                    "tickerem, więc od razu wiadomo, kogo dotyczy.",
                    "<b>Kategoria zdarzenia</b> i waga źródła — komunikat spółki waży "
                    "inaczej niż wpis w mediach społecznościowych.",
                    "<b>Pomiar po fakcie</b> — kurs godzinę i dobę po analizie, "
                    "zapisany obok niej. To jedyny uczciwy sposób sprawdzenia, czy "
                    "ocena cokolwiek znaczyła.",
                ],
            },
            {
                "h2": "Sprawdzalność zamiast obietnic",
                "p": [
                    "Każda analiza zostaje w historii razem z tym, co kurs zrobił "
                    "później. Statystyki trafień są widoczne w aplikacji i nie da się "
                    "ich wyczyścić — bo narzędzie, które chwali się skutecznością bez "
                    "pokazania pomyłek, jest reklamą, a nie narzędziem.",
                ],
            },
        ],
        "faq": [
            ("Czy to jest bot, który handluje za mnie?",
             "Nie. Bot wyłącznie nasłuchuje i analizuje. Część handlowa została "
             "z aplikacji świadomie usunięta — Portevo nie składa zleceń i nie łączy "
             "się z rachunkiem maklerskim."),
            ("Co to są raporty ESPI?",
             "Komunikaty bieżące i okresowe, które spółki giełdowe muszą publikować "
             "w Elektronicznym Systemie Przekazywania Informacji. To oficjalne źródło "
             "informacji cenotwórczych o spółkach z GPW."),
            ("Czy analiza AI może się mylić?",
             "Tak i regularnie się myli. Model językowy ocenia tekst, nie zna "
             "przyszłości i nie widzi kontekstu, którego nie ma w komunikacie. Dlatego "
             "obok każdej analizy stoi pomiar tego, co kurs zrobił faktycznie."),
        ],
        "cta": ("Zobacz analizy z ostatnich dni",
                "Komunikaty, ocena wydźwięku i to, co kurs zrobił godzinę później."),
        "frazy": keywords.NEWS_AI,
        "powiazane": [
            ("/poradniki/jak-czytac-raport-espi", "Jak czytać raport ESPI"),
            ("/kalendarz-wynikow-spolek", "Kalendarz wyników spółek"),
            ("/slownik/espi", "ESPI"),
        ],
    },
}


# --------------------------------------------------------------- strona zbiorcza

FUNKCJE_META = {
    "h1": "Wszystkie funkcje Portevo",
    "tytul": "Funkcje Portevo — kalendarz wyników, portfel, ETF, analiza",
    "opis": "Kalendarz wyników spółek, śledzenie portfela inwestycyjnego, skaner ETF, "
            "analiza ryzyka, kalendarz makro i analiza newsów. Wszystko po polsku, "
            "w przeglądarce i na telefonie.",
    "lead": "Portevo jest jedną aplikacją złożoną z kilku narzędzi. Każde z nich "
            "odpowiada na inne pytanie — poniżej opis, do czego które służy i co "
            "jest darmowe.",
}


def _kolejnosc():
    """Kolejność stron w spisie i w sitemapie — od najważniejszej biznesowo."""
    return [
        "/kalendarz-wynikow-spolek",
        "/portfel-inwestycyjny",
        "/skaner-etf",
        "/analiza-portfela",
        "/notowania-spolek",
        "/kalendarz-makroekonomiczny",
        "/analiza-newsow-ai",
    ]


def adresy() -> list[str]:
    """Adresy wszystkich podstron funkcji — dla sitemapy i llms.txt."""
    return ["/funkcje"] + _kolejnosc()


def zbuduj(sciezka: str) -> str | None:
    """Gotowy HTML jednej podstrony funkcji."""
    d = STRONY.get(sciezka)
    if not d:
        return None

    bloki = []
    for s in d["sekcje"]:
        bloki.append(render.sekcja(
            s["h2"], *s.get("p", []), lista=s.get("lista"),
            kotwica=s.get("kotwica", "")))

    if d.get("karty"):
        bloki.append(render.sekcja("Zobacz też", html_dodatkowy=render.karty(d["karty"])))

    bloki.append(render.sekcja(
        "Najczęstsze pytania", kotwica="pytania", html_dodatkowy=render.faq(d["faq"])))

    if d.get("powiazane"):
        bloki.append(render.sekcja(
            "Powiązane tematy", html_dodatkowy=render.chipsy(d["powiazane"])))

    tytul_cta, tekst_cta = d["cta"]
    bloki.append(render.zacheta(tytul_cta, tekst_cta))
    bloki.append(render.zastrzezenie())

    okruchy = [("/funkcje", "Funkcje"), ("", d["h1"])]
    return render.strona(
        sciezka=sciezka,
        tytul=d["tytul"],
        opis=d["opis"],
        h1=d["h1"],
        lead=d["lead"],
        nadtytul=d.get("nadtytul", ""),
        akcje=d.get("akcje"),
        okruchy=okruchy,
        szeroki_naglowek=True,
        bloki=bloki,
        jsonld=[
            jsonld.strona(sciezka, d["tytul"], d["opis"]),
            jsonld.okruchy(okruchy),
            jsonld.pytania(d["faq"]),
        ],
    )


def zbuduj_spis() -> str:
    """Strona `/funkcje` — spis wszystkich narzędzi, węzeł linkowania wewnętrznego."""
    pozycje = []
    for sciezka in _kolejnosc():
        d = STRONY[sciezka]
        pozycje.append((sciezka, d["h1"].split(" — ")[0], d["opis"],
                        d.get("nadtytul", "")))

    bloki = [
        render.sekcja("Narzędzia w aplikacji", html_dodatkowy=render.karty(pozycje)),
        render.sekcja(
            "Co jest darmowe, a co płatne",
            "Kalendarz wyników spółek, kalendarz makroekonomiczny, karta spółki "
            "z prognozami, import portfela, wycena, stopa zwrotu i koszty są "
            "<strong>darmowe</strong> — to trzon aplikacji i nie chowamy go pod kłódką.",
            f"Płatne są narzędzia analityczne, które dokładają warstwę interpretacji: "
            f"rentgen ryzyka, macierz korelacji, prześwietlenie funduszu ETF, "
            f"porównywarka i analizy bota. Kosztuje to {render.liczba(_CENA_MC, 0)} zł "
            f"miesięcznie albo {render.liczba(_CENA_ROK, 0)} zł za rok.",
        ),
        render.sekcja(
            "Ta sama aplikacja w przeglądarce i na telefonie",
            "Portevo jest jednym programem uruchamianym w dwóch miejscach — nie ma "
            "wersji okrojonej. W przeglądarce układ rozkłada się na szerszy ekran, "
            "na telefonie zakładki wracają na dół. Konto, dane i wykupiony dostęp są "
            "wspólne, więc portfel wgrany na komputerze widzisz od razu w telefonie.",
        ),
        render.zacheta("Otwórz Portevo",
                       "Bez instalowania czegokolwiek — aplikacja otwiera się "
                       "w przeglądarce, a konto zakładasz dopiero, gdy chcesz wgrać "
                       "własny portfel."),
        render.zastrzezenie(),
    ]

    okruchy = [("", "Funkcje")]
    return render.strona(
        sciezka="/funkcje",
        tytul=FUNKCJE_META["tytul"],
        opis=FUNKCJE_META["opis"],
        h1=FUNKCJE_META["h1"],
        lead=FUNKCJE_META["lead"],
        nadtytul="Przegląd",
        okruchy=okruchy,
        szeroki_naglowek=True,
        bloki=bloki,
        jsonld=[
            jsonld.strona("/funkcje", FUNKCJE_META["tytul"], FUNKCJE_META["opis"],
                          typ="CollectionPage"),
            jsonld.okruchy(okruchy),
            jsonld.aplikacja(),
            jsonld.lista_pozycji("Funkcje Portevo",
                                 [(p[0], p[1]) for p in pozycje]),
        ],
    )
