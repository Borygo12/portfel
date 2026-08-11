"""Poradniki — teksty pod frazy informacyjne („jak…”, „kiedy…”, „co to znaczy…”).

Rola tego klastra w całości: podstrony funkcji łapią osoby, które już wiedzą,
czego szukają, a podstrony spółek — osoby szukające konkretnej firmy. Poradniki
łapią wszystkich pozostałych, czyli największą grupę: ludzi, którzy dopiero
formułują problem. Są też jedynym rodzajem treści, który modele językowe cytują
w odpowiedziach — pytanie „jak liczyć stopę zwrotu z portfela” ma odpowiedź
tekstową, a nie produktową.

Każdy poradnik kończy się linkiem do funkcji, która dany problem rozwiązuje —
ale dopiero PO odpowiedzeniu na pytanie. Tekst, który zamiast odpowiedzi
podsuwa produkt, jest odrzucany zarówno przez czytelnika, jak i przez algorytm
oceniający przydatność treści.

`data` to dzień publikacji tekstu i wchodzi do danych strukturalnych. Gdy
poprawiasz treść merytorycznie, podnieś `zmieniono` — data udawanej świeżości
przy niezmienionym tekście jest łatwa do wykrycia i nic nie daje.
"""

from __future__ import annotations

from . import jsonld, render

DATA = "2026-08-11"

#: slug -> treść poradnika
PORADNIKI = {

    "kiedy-spolki-publikuja-wyniki": {
        "h1": "Kiedy spółki publikują wyniki? Terminy na GPW i w USA",
        "tytul": "Kiedy spółki publikują wyniki — terminy GPW i USA | Portevo",
        "opis": "Jak działa sezon wyników, w jakich terminach raportują spółki "
                "z warszawskiej giełdy i z USA, i dlaczego pora publikacji "
                "(przed sesją czy po niej) ma znaczenie.",
        "lead": "Sezon wyników wraca cztery razy w roku i za każdym razem zaskakuje "
                "tych, którzy nie sprawdzili kalendarza. Oto jak wygląda ten rytm "
                "w Polsce i w Stanach.",
        "sekcje": [
            {"h2": "Rytm czterech kwartałów",
             "p": ["Spółki giełdowe rozliczają się z rynkiem co trzy miesiące. Po "
                   "zakończeniu kwartału mają określony czas na przygotowanie raportu — "
                   "i właśnie dlatego publikacje kumulują się w kilkutygodniowym oknie, "
                   "które nazywa się sezonem wyników.",
                   "Na rynku amerykańskim sezon zaczyna się zwykle w drugim tygodniu "
                   "po zamknięciu kwartału, czyli w połowie stycznia, kwietnia, lipca "
                   "i października. Otwierają go tradycyjnie największe banki, a "
                   "w kolejnych dwóch–trzech tygodniach raportuje główna część rynku, "
                   "w tym spółki technologiczne."]},
            {"h2": "Terminy na warszawskiej giełdzie",
             "p": ["Polskie przepisy dają spółkom szersze okno niż amerykańskie, więc "
                   "publikacje są bardziej rozciągnięte w czasie. Raport za pierwsze "
                   "półrocze i raport roczny mają dłuższe terminy niż raporty kwartalne.",
                   "Każda spółka z GPW ma obowiązek podać z wyprzedzeniem harmonogram "
                   "publikacji na cały rok — i opublikować go jako raport bieżący. "
                   "Zmiana terminu też wymaga osobnego komunikatu, więc daty są "
                   "publicznie znane wcześniej."],
             "lista": ["<b>Raport kwartalny</b> — najkrótszy, zwykle sam rachunek "
                       "wyników i podstawowe dane.",
                       "<b>Raport półroczny</b> — szerszy, przeglądany przez biegłego "
                       "rewidenta.",
                       "<b>Raport roczny</b> — pełne, zbadane sprawozdanie wraz ze "
                       "sprawozdaniem zarządu.",
                       "<b>Szacunkowe wyniki</b> — część spółek publikuje wstępne "
                       "liczby wcześniej, gdy odbiegają one od oczekiwań rynku."]},
            {"h2": "Przed otwarciem czy po zamknięciu — dlaczego to ważne",
             "p": ["Amerykańskie spółki publikują raporty albo przed otwarciem sesji, "
                   "albo po jej zamknięciu. To rozróżnienie zmienia praktycznie "
                   "wszystko: raport ogłoszony po zamknięciu rynku zobaczysz w kursie "
                   "dopiero następnego dnia, a w międzyczasie handel odbywa się poza "
                   "sesją, przy niskiej płynności i szerokich spreadach.",
                   "Polskie spółki publikują najczęściej rano, przed sesją albo "
                   "w jej trakcie — ale nie ma tu takiej regularności jak w Stanach, "
                   "a dane o porze publikacji bywają niedostępne. Wtedy kalendarz "
                   "pokazuje termin jako niepotwierdzony."]},
            {"h2": "Jak nie przegapić raportu swojej spółki",
             "p": ["Najprostszy sposób to jedno miejsce, w którym widać terminy "
                   "wszystkich spółek, które Cię interesują. W Portevo spółki "
                   "z portfela i z listy obserwowanych są w kalendarzu wyróżnione, "
                   "a licznik przy każdym dniu pokazuje, ile z nich raportuje.",
                   "Warto też sprawdzać kalendarz wydarzeń makroekonomicznych. Odczyt "
                   "inflacji albo decyzja o stopach potrafi przykryć nawet bardzo dobry "
                   "raport pojedynczej spółki."]},
        ],
        "faq": [
            ("Ile razy w roku spółka publikuje wyniki?",
             "Zwykle cztery razy — po każdym kwartale. Raport za czwarty kwartał bywa "
             "zastępowany raportem rocznym, który zawiera pełne, zbadane sprawozdanie."),
            ("Czy terminy publikacji można poznać wcześniej?",
             "Tak. Spółki z GPW mają obowiązek opublikować harmonogram raportów na cały "
             "rok, a zmianę terminu zgłosić osobnym komunikatem. Amerykańskie spółki "
             "podają datę zwykle na kilka tygodni przed publikacją."),
            ("Dlaczego kurs spada mimo dobrych wyników?",
             "Bo rynek reaguje na różnicę między wynikiem a oczekiwaniami, a nie na "
             "bezwzględną wysokość zysku. Rekordowy kwartał poniżej prognozy analityków "
             "jest odbierany jako rozczarowanie."),
        ],
        "powiazane": [("/kalendarz-wynikow-spolek", "Kalendarz wyników spółek"),
                      ("/poradniki/jak-czytac-raport-kwartalny", "Jak czytać raport kwartalny"),
                      ("/slownik/sezon-wynikow", "Sezon wyników"),
                      ("/slownik/espi", "ESPI")],
        "cta": ("Sprawdź, kto raportuje w tym tygodniu",
                "Kalendarz wyników z GPW i USA otwiera się bez zakładania konta."),
        "cta_link": "/kalendarz-wynikow-spolek",
    },

    "jak-czytac-raport-kwartalny": {
        "h1": "Jak czytać raport kwartalny spółki — przewodnik dla początkujących",
        "tytul": "Jak czytać raport kwartalny spółki — poradnik | Portevo",
        "opis": "Od czego zacząć lekturę raportu kwartalnego, na które liczby patrzeć "
                "w pierwszej kolejności i jakie sygnały ostrzegawcze łatwo przeoczyć.",
        "lead": "Raport kwartalny ma kilkadziesiąt stron, a naprawdę liczy się w nim "
                "kilkanaście liczb. Oto które i w jakiej kolejności je czytać.",
        "sekcje": [
            {"h2": "Zacznij od trzech liczb, nie od pierwszej strony",
             "p": ["Lektura od początku do końca to najgorszy możliwy sposób. Zacznij od "
                   "porównania trzech pozycji z poprzednim rokiem: przychodów, zysku "
                   "operacyjnego i zysku netto. To dwie minuty, a odpowiada na pytanie, "
                   "czy spółka rośnie i czy ten wzrost jest opłacalny."],
             "lista": ["<b>Przychody</b> — czy sprzedaż rośnie i w jakim tempie.",
                       "<b>Zysk operacyjny</b> — czy rośnie szybciej niż przychody "
                       "(dobrze) czy wolniej (koszty wyprzedzają wzrost).",
                       "<b>Zysk netto</b> — na końcu, bo najłatwiej nim manipulować "
                       "zdarzeniami jednorazowymi."]},
            {"h2": "Marża mówi więcej niż dynamika",
             "p": ["Rosnące przychody przy kurczącej się marży to najczęstszy sygnał, że "
                   "wzrost jest kupowany — rabatami, wyższymi kosztami sprzedaży albo "
                   "droższymi surowcami. Odwrotność, czyli stabilne przychody przy "
                   "rosnącej marży, bywa lepszą informacją niż efektowny wzrost sprzedaży.",
                   "Porównuj marże z tą samą spółką rok wcześniej i z konkurencją "
                   "z branży. Poziom marży zależy od modelu biznesu: producent "
                   "oprogramowania i sieć handlowa mają je nieporównywalne."]},
            {"h2": "Sprawdź, skąd wziął się zysk",
             "p": ["Zysk netto potrafi wynikać ze sprzedaży nieruchomości, przeszacowania "
                   "aktywów albo rozwiązania rezerwy — czyli zdarzeń, które nie powtórzą "
                   "się w kolejnym kwartale. Dlatego w raporcie szuka się pozycji "
                   "„zdarzenia jednorazowe” i wyników oczyszczonych.",
                   "Pomocny jest też rachunek przepływów pieniężnych. Spółka wykazująca "
                   "zysk przy ujemnych przepływach z działalności operacyjnej zarabia "
                   "na papierze, ale nie w kasie — i taka rozbieżność powtarzana przez "
                   "kilka kwartałów jest poważnym ostrzeżeniem."]},
            {"h2": "Zadłużenie i to, co mówi zarząd",
             "p": ["Sprawdź dług netto w relacji do zysku operacyjnego powiększonego "
                   "o amortyzację. Wskaźnik powyżej trzech–czterech oznacza spółkę "
                   "wrażliwą na wyższe stopy procentowe albo jeden słabszy kwartał.",
                   "Na koniec przeczytaj komentarz zarządu i ewentualną prognozę na "
                   "kolejne okresy. Liczby opisują przeszłość, a kurs wycenia przyszłość — "
                   "dlatego obniżona prognoza potrafi zepchnąć notowania mocniej niż "
                   "słaby miniony kwartał."]},
        ],
        "faq": [
            ("Od czego zacząć czytanie raportu kwartalnego?",
             "Od porównania przychodów, zysku operacyjnego i zysku netto z tym samym "
             "kwartałem rok wcześniej. Dopiero potem sięgaj po marże, przepływy "
             "pieniężne i zadłużenie."),
            ("Co to znaczy, że wyniki są „oczyszczone”?",
             "Że wyłączono z nich zdarzenia jednorazowe — sprzedaż majątku, odpisy, "
             "rozwiązanie rezerw. Taki wynik lepiej opisuje powtarzalną działalność, ale "
             "warto sprawdzić, co dokładnie wyłączono."),
            ("Dlaczego zysk nie równa się gotówce?",
             "Bo księgowo zysk powstaje w momencie wystawienia faktury, a gotówka wpływa "
             "przy zapłacie. Trwała rozbieżność między zyskiem a przepływami operacyjnymi "
             "wymaga wyjaśnienia."),
        ],
        "powiazane": [("/slownik/raport-kwartalny", "Raport kwartalny"),
                      ("/slownik/marza-netto", "Marża netto"),
                      ("/slownik/ebitda", "EBITDA"),
                      ("/wyniki-finansowe", "Wyniki finansowe spółek")],
        "cta": ("Zobacz wyniki konkretnej spółki",
                "Marże kwartał po kwartale, historia zaskoczeń i reakcje kursu — "
                "dla 266 spółek z GPW i USA."),
        "cta_link": "/wyniki-finansowe",
    },

    "jak-czytac-raport-espi": {
        "h1": "Jak czytać raporty ESPI spółek z GPW",
        "tytul": "Jak czytać raporty ESPI — komunikaty spółek GPW | Portevo",
        "opis": "Czym są raporty bieżące ESPI, które komunikaty faktycznie ruszają "
                "kursem, a które są formalnością — i gdzie ich szukać.",
        "lead": "ESPI to pierwotne źródło informacji o spółkach z warszawskiej giełdy. "
                "Wszystko, co czytasz później w serwisach, jest zwykle streszczeniem "
                "komunikatu stamtąd.",
        "sekcje": [
            {"h2": "Co trafia do ESPI",
             "p": ["Spółka giełdowa ma obowiązek niezwłocznie opublikować każdą "
                   "informację poufną — czyli taką, która mogłaby wpłynąć na decyzje "
                   "inwestorów. Robi to przez Elektroniczny System Przekazywania "
                   "Informacji, prowadzony przez Komisję Nadzoru Finansowego."],
             "lista": ["<b>Raporty okresowe</b> — kwartalne, półroczne i roczne.",
                       "<b>Umowy znaczące</b> — kontrakty istotne w stosunku do skali "
                       "działalności.",
                       "<b>Zmiany w organach spółki</b> — zarząd i rada nadzorcza.",
                       "<b>Wezwania i transakcje na akcjach</b> — także te zawierane "
                       "przez osoby zarządzające.",
                       "<b>Prognozy i ich korekty</b>, decyzje o dywidendzie, emisje akcji."]},
            {"h2": "Które komunikaty ruszają kursem",
             "p": ["Większość raportów bieżących to formalności, których rynek nie "
                   "zauważa. Reakcja pojawia się wtedy, gdy komunikat zmienia obraz "
                   "przyszłych zysków spółki albo jej ryzyka.",
                   "Praktyczna miara istotności: odnieś liczbę z komunikatu do skali "
                   "spółki. Kontrakt na 400 mln zł przy rocznych przychodach 1,2 mld zł "
                   "to informacja duża. Ten sam kontrakt przy przychodach 40 mld zł jest "
                   "szumem."]},
            {"h2": "Na co uważać przy lekturze",
             "p": ["Komunikaty pisze się językiem prawniczym, w którym łatwo przeoczyć "
                   "zastrzeżenia. Szukaj warunków zawieszających („umowa wejdzie w życie "
                   "po uzyskaniu zgody…”), terminów realizacji rozłożonych na lata "
                   "i informacji o karach umownych.",
                   "Uważaj też na komunikaty publikowane po zamknięciu sesji i w piątki "
                   "po południu — to klasyczny moment na informacje, którym spółka nie "
                   "chce robić rozgłosu."]},
        ],
        "faq": [
            ("Gdzie znaleźć raporty ESPI?",
             "Na stronie internetowej samej spółki w sekcji relacji inwestorskich oraz "
             "w serwisach agregujących komunikaty. Portevo dodatkowo analizuje ich "
             "wydźwięk i wiąże komunikat z konkretnym tickerem."),
            ("Czym różni się ESPI od EBI?",
             "ESPI służy do publikacji informacji poufnych i raportów okresowych, EBI — "
             "do komunikatów wynikających z regulaminu giełdy, głównie o charakterze "
             "korporacyjnym. Informacje cenotwórcze idą przez ESPI."),
            ("Czy każda informacja w ESPI wpływa na kurs?",
             "Nie. Większość to formalności. Reakcja pojawia się, gdy komunikat zmienia "
             "oczekiwania co do przyszłych zysków spółki lub jej ryzyka."),
        ],
        "powiazane": [("/analiza-newsow-ai", "Analiza newsów AI"),
                      ("/slownik/espi", "ESPI"),
                      ("/slownik/gpw", "GPW"),
                      ("/wyniki-finansowe/gpw", "Wyniki spółek z GPW")],
        "cta": ("Komunikaty czytane przez AI",
                "Portevo nasłuchuje komunikatów spółek, ocenia ich wydźwięk i mierzy, "
                "co kurs zrobił godzinę później."),
        "cta_link": "/analiza-newsow-ai",
    },

    "jak-liczyc-stope-zwrotu": {
        "h1": "Jak liczyć stopę zwrotu z portfela, żeby wyszła prawda",
        "tytul": "Jak liczyć stopę zwrotu z portfela — XIRR i TWR | Portevo",
        "opis": "Dlaczego „ile mam minus ile wpłaciłem” to zła miara, czym różni się "
                "XIRR od TWR i którą liczbę porównywać z indeksem.",
        "lead": "Najpopularniejszy sposób liczenia wyniku portfela jest jednocześnie "
                "najbardziej mylący. Oto dlaczego i co zrobić zamiast tego.",
        "sekcje": [
            {"h2": "Dlaczego proste odejmowanie zawodzi",
             "p": ["„Mam 57 000 zł, wpłaciłem 50 000 zł, więc zarobiłem 14%” działa "
                   "tylko wtedy, gdy wszystkie pieniądze wpłaciłeś jednego dnia "
                   "i nigdy nic nie wypłaciłeś. W praktyce dopłaca się co miesiąc, "
                   "czasem coś wyjmuje, a każda z tych kwot pracowała inny czas.",
                   "Efekt jest przewidywalny: przy regularnych dopłatach ta metoda "
                   "systematycznie zaniża wynik, bo świeże pieniądze nie zdążyły "
                   "jeszcze zarobić, a już powiększają mianownik."]},
            {"h2": "XIRR — ile zarobiłeś Ty",
             "p": ["Wewnętrzna stopa zwrotu uwzględnia daty i wielkości wszystkich wpłat "
                   "oraz wypłat. Szuka takiej rocznej stopy, przy której wszystkie "
                   "przepływy sprowadzone do dziś dają obecną wartość portfela.",
                   "Wynik jest jedną liczbą porównywalną z oprocentowaniem lokaty. "
                   "To najuczciwsza odpowiedź na pytanie „ile realnie zarobiłem na "
                   "swoich pieniądzach”."]},
            {"h2": "TWR — jak dobra była Twoja strategia",
             "p": ["Stopa zwrotu ważona czasem dzieli historię portfela na odcinki "
                   "między przepływami i mnoży ich wyniki. Moment wpłaty przestaje mieć "
                   "znaczenie, więc mierzone są same inwestycje, a nie szczęście "
                   "w wyborze terminu dopłaty.",
                   "To ta miara nadaje się do porównania z indeksem — indeks też nie "
                   "dostaje wpłat. Jeśli Twój TWR jest niższy od WIG-u albo od S&P 500, "
                   "to informacja, którą warto potraktować poważnie."]},
            {"h2": "Czego nie zapomnieć",
             "lista": ["<b>Prowizji i spreadu</b> — przy częstym handlu potrafią zjeść "
                       "większość wyniku.",
                       "<b>Podatku</b> — dziewiętnaście procent od zysku to realna "
                       "część rachunku.",
                       "<b>Waluty</b> — pozycja w dolarach może zyskać, a w złotówkach "
                       "stracić.",
                       "<b>Inflacji</b> — wynik niższy od inflacji jest realną stratą, "
                       "mimo dodatniej liczby."]},
        ],
        "faq": [
            ("Czym różni się XIRR od TWR?",
             "XIRR mówi, ile zarobiłeś Ty przy swoich terminach wpłat. TWR mówi, ile "
             "zarobiła sama strategia, niezależnie od tego, kiedy dopłacałeś. Do "
             "porównania z indeksem służy TWR."),
            ("Jak policzyć stopę zwrotu w arkuszu?",
             "Funkcja XIRR przyjmuje listę przepływów z datami: wpłaty ze znakiem "
             "ujemnym, obecna wartość portfela ze znakiem dodatnim na dzisiejszą datę. "
             "Pracochłonne jest utrzymywanie tej listy w aktualności, nie sam wzór."),
            ("Czy dobry wynik to wynik dodatni?",
             "Nie wystarczy. Wynik trzeba odnieść do inflacji i do szerokiego rynku. "
             "Plus 4% przy inflacji 6% i indeksie na plus 18% jest wynikiem słabym."),
        ],
        "powiazane": [("/portfel-inwestycyjny", "Portfel inwestycyjny"),
                      ("/slownik/xirr", "XIRR"), ("/slownik/twr", "TWR"),
                      ("/slownik/benchmark", "Benchmark")],
        "cta": ("Policz to bez arkusza",
                "Wgraj raport z rachunku maklerskiego, a stopa zwrotu, koszty "
                "i porównanie z indeksami policzą się same."),
        "cta_link": "/portfel-inwestycyjny",
    },

    "koszty-inwestowania": {
        "h1": "Koszty inwestowania na giełdzie — czego nie widać w tabeli opłat",
        "tytul": "Koszty inwestowania na giełdzie — prowizje i podatki | Portevo",
        "opis": "Prowizje, spread, przewalutowanie, opłata za zarządzanie i podatek — "
                "pełna lista kosztów, które zjadają stopę zwrotu, z przykładami.",
        "lead": "Prowizja maklerska jest tylko jedną z pięciu pozycji rachunku. "
                "Pozostałe są mniej widoczne i zwykle większe.",
        "sekcje": [
            {"h2": "Pięć kosztów, które płacisz naprawdę",
             "lista": ["<b>Prowizja maklerska</b> — procent od transakcji z kwotą "
                       "minimalną. To minimum decyduje o opłacalności małych zleceń.",
                       "<b>Spread</b> — różnica między ceną kupna a sprzedaży. "
                       "Natychmiastowy koszt wejścia w pozycję, niewidoczny w żadnym "
                       "zestawieniu opłat.",
                       "<b>Przewalutowanie</b> — przy instrumentach zagranicznych, "
                       "zwykle 0,2–0,5% w każdą stronę.",
                       "<b>Opłata za zarządzanie</b> — przy funduszach i ETF-ach, "
                       "pobierana co roku z wyniku funduszu.",
                       "<b>Podatek</b> — dziewiętnaście procent od zysku, płacone przy "
                       "rozliczeniu rocznym."]},
            {"h2": "Dlaczego minimalna prowizja boli najbardziej",
             "p": ["Stawka 0,29% wygląda niegroźnie, ale przy minimum 5 zł zlecenie na "
                   "500 zł kosztuje realnie 1% — i drugie tyle przy sprzedaży. Dwa "
                   "procent na wejściu i wyjściu to dużo, zanim cokolwiek się wydarzy.",
                   "Wniosek praktyczny: przy małych kwotach lepiej kupować rzadziej "
                   "i większymi pakietami niż co tydzień po trochu."]},
            {"h2": "Koszt, który rośnie z czasem",
             "p": ["Opłata za zarządzanie działa co roku i od coraz większego kapitału, "
                   "więc jej wpływ narasta. Przy dwudziestu latach i siedmiu procentach "
                   "rocznie różnica między funduszem za 0,07% a 0,45% to kilkanaście "
                   "procent końcowego kapitału.",
                   "To jedyna liczba w całej analizie, którą znasz z góry na pewno. "
                   "Przyszłej stopy zwrotu nie zna nikt — dlatego przy wyborze funduszu "
                   "opłata jest kryterium mocniejszym niż wynik z ostatnich lat."]},
            {"h2": "Jak sprawdzić, ile faktycznie zapłaciłeś",
             "p": ["Raport z rachunku maklerskiego zawiera wszystkie pobrane prowizje "
                   "i opłaty. Portevo wylicza z niego sumę kosztów faktycznie "
                   "poniesionych oraz szacunek kosztu wyjścia z obecnych pozycji — bo "
                   "portfel wyceniony bez uwzględnienia sprzedaży pokazuje wynik, "
                   "którego nie da się zrealizować."]},
        ],
        "faq": [
            ("Ile wynosi podatek od zysków z giełdy w Polsce?",
             "Dziewiętnaście procent od dochodu, czyli od zysku pomniejszonego o straty "
             "z instrumentów rozliczanych w ten sam sposób. Broker wystawia PIT-8C, "
             "rozliczenia dokonujesz w zeznaniu rocznym."),
            ("Czy spread to koszt?",
             "Tak, i to natychmiastowy. Kupujesz po cenie wyższej, a sprzedajesz po "
             "niższej, więc różnica jest stratą w momencie zawarcia transakcji."),
            ("Co jest droższe: prowizja czy opłata za zarządzanie?",
             "Przy inwestowaniu długoterminowym zwykle opłata za zarządzanie, bo działa "
             "co roku. Przy częstym handlu — prowizje i spread."),
        ],
        "powiazane": [("/portfel-inwestycyjny", "Portfel inwestycyjny"),
                      ("/skaner-etf", "Skaner ETF"),
                      ("/slownik/prowizja-maklerska", "Prowizja maklerska"),
                      ("/slownik/podatek-belki", "Podatek Belki")],
        "cta": ("Sprawdź swoje realne koszty",
                "Portevo wylicza z raportu maklerskiego prowizje faktycznie zapłacone "
                "i koszt wyjścia z bieżących pozycji."),
        "cta_link": "/portfel-inwestycyjny",
    },

    "jak-zaczac-inwestowac": {
        "h1": "Jak zacząć inwestować na giełdzie — pierwsze kroki",
        "tytul": "Jak zacząć inwestować na giełdzie — poradnik 2026 | Portevo",
        "opis": "Od czego zacząć inwestowanie: rachunek maklerski, pierwszy portfel, "
                "ETF czy pojedyncze akcje, i najczęstsze błędy początkujących.",
        "lead": "Bez obietnic i bez „pewnych okazji”. Uczciwa kolejność kroków "
                "i lista rzeczy, na których najłatwiej się potknąć.",
        "sekcje": [
            {"h2": "Zanim kupisz cokolwiek",
             "lista": ["<b>Poduszka finansowa</b> — pieniądze na kilka miesięcy życia "
                       "poza rynkiem. Bez niej pierwszy spadek zmusi Cię do sprzedaży "
                       "w najgorszym momencie.",
                       "<b>Horyzont</b> — pieniądze potrzebne za rok nie powinny być "
                       "na giełdzie.",
                       "<b>Tolerancja na spadki</b> — sprawdź szczerze, jak zareagujesz "
                       "na trzydziestoprocentowe obsunięcie. Takie zdarzają się "
                       "regularnie.",
                       "<b>Rachunek maklerski</b> — porównaj prowizje, minimalną "
                       "prowizję i koszt przewalutowania."]},
            {"h2": "ETF czy pojedyncze akcje",
             "p": ["Fundusz ETF na szeroki indeks daje ekspozycję na kilkaset spółek "
                   "za jedną transakcję i jedną, znaną z góry opłatę. Dla większości "
                   "osób zaczynających jest to punkt wyjścia trudniejszy do zepsucia "
                   "niż samodzielny dobór spółek.",
                   "Pojedyncze akcje wymagają czasu na analizę i akceptacji, że część "
                   "wyborów będzie błędna. Nie ma w tym nic złego — trzeba tylko wiedzieć, "
                   "że to inna aktywność niż kupienie indeksu i czekanie."]},
            {"h2": "Najczęstsze błędy pierwszego roku",
             "lista": ["<b>Zbyt duże pozycje</b> — jedna spółka za połowę portfela "
                       "sprawia, że wynik zależy od jednej firmy.",
                       "<b>Zbyt częsty handel</b> — prowizje i spread zjadają wynik "
                       "szybciej, niż rynek zdąży cokolwiek dać.",
                       "<b>Brak punktu odniesienia</b> — bez porównania z indeksem "
                       "i inflacją nie wiadomo, czy wynik jest dobry.",
                       "<b>Mylenie wpłat z zyskiem</b> — rosnąca wartość portfela przy "
                       "regularnych dopłatach nie oznacza, że inwestycje zarabiają.",
                       "<b>Kupowanie po nagłówkach</b> — zanim informacja trafi do "
                       "mediów, kurs zwykle już ją uwzględnił."]},
            {"h2": "Co warto robić od pierwszego dnia",
             "p": ["Notuj każdą transakcję razem z powodem decyzji. Po roku ten zapis "
                   "jest wart więcej niż jakikolwiek kurs — pokazuje, które Twoje "
                   "przekonania sprawdzały się, a które nie.",
                   "Mierz wynik uczciwie: stopą zwrotu uwzględniającą wpłaty, "
                   "porównaną z szerokim rynkiem i inflacją. Narzędzie, które robi to "
                   "automatycznie, oszczędza godziny w arkuszu i eliminuje błędy."]},
        ],
        "faq": [
            ("Od jakiej kwoty można zacząć inwestować?",
             "Technicznie od kilkuset złotych, ale przy minimalnej prowizji małe zlecenia "
             "są nieopłacalne. Rozsądniej kupować rzadziej i większymi pakietami."),
            ("Czy lepiej zacząć od ETF-ów?",
             "Dla większości osób tak — jedna transakcja daje szeroką dywersyfikację, "
             "a jedyny pewny koszt jest znany z góry. To nie jest porada inwestycyjna, "
             "tylko opis najczęstszej ścieżki."),
            ("Ile czasu wymaga inwestowanie?",
             "Portfel oparty na szerokich funduszach można przeglądać kilka razy w roku. "
             "Samodzielny dobór spółek to praca ciągła — czytanie raportów, śledzenie "
             "terminów publikacji wyników i pilnowanie proporcji w portfelu."),
        ],
        "powiazane": [("/skaner-etf", "Skaner ETF"),
                      ("/portfel-inwestycyjny", "Portfel inwestycyjny"),
                      ("/slownik/etf", "Co to jest ETF"),
                      ("/slownik/dywersyfikacja", "Dywersyfikacja")],
        "cta": ("Zacznij od zmierzenia tego, co masz",
                "Portevo pokazuje wartość portfela w złotówkach, realną stopę zwrotu "
                "i porównanie z indeksami — za darmo."),
        "cta_link": "/portfel-inwestycyjny",
    },

    "jak-sledzic-portfel-inwestycyjny": {
        "h1": "Jak śledzić portfel inwestycyjny — arkusz czy aplikacja",
        "tytul": "Jak śledzić portfel inwestycyjny — arkusz czy aplikacja | Portevo",
        "opis": "Co musi umieć narzędzie do śledzenia portfela, gdzie zawodzi arkusz "
                "kalkulacyjny i jakie liczby naprawdę warto mieć pod ręką.",
        "lead": "Arkusz kalkulacyjny wystarcza dłużej, niż się wydaje — ale ma trzy "
                "granice, o które prędzej czy później uderza każdy.",
        "sekcje": [
            {"h2": "Gdzie kończy się arkusz",
             "lista": ["<b>Notowania</b> — ręczne wpisywanie kursów przestaje działać "
                       "przy kilkunastu pozycjach, a formuły pobierające dane potrafią "
                       "przestać działać bez ostrzeżenia.",
                       "<b>Waluty</b> — pozycja w dolarach wymaga kursu z dnia "
                       "transakcji i z dnia wyceny, osobno dla każdej operacji.",
                       "<b>Stopa zwrotu</b> — przy regularnych dopłatach prosta różnica "
                       "przestaje cokolwiek znaczyć, a utrzymanie listy przepływów do "
                       "funkcji XIRR jest pracochłonne."]},
            {"h2": "Co narzędzie powinno liczyć samo",
             "lista": ["Wartość portfela w jednej walucie, po kursie z właściwego dnia.",
                       "Stopę zwrotu odporną na wpłaty i wypłaty.",
                       "Koszty faktycznie poniesione oraz koszt wyjścia z pozycji.",
                       "Porównanie z indeksem i z inflacją.",
                       "Podział na klasy aktywów, sektory i waluty.",
                       "Wynik pozycji już zamkniętych, osobno od otwartych."]},
            {"h2": "Import zamiast przepisywania",
             "p": ["Najważniejsza różnica praktyczna nie dotyczy liczb, tylko sposobu "
                   "wprowadzania danych. Ręczne przepisywanie transakcji odpada po "
                   "kilku miesiącach — nie z powodu trudności, tylko nudy.",
                   "Import raportu z rachunku maklerskiego rozwiązuje to raz na zawsze. "
                   "W Portevo wgrywa się plik pobrany od brokera, a aplikacja odtwarza "
                   "z niego pozycje, wpłaty i prowizje. Powtórne wgranie tego samego "
                   "raportu niczego nie dubluje, więc aktualizacja to jedna czynność."]},
            {"h2": "O bezpieczeństwie",
             "p": ["Narzędzie do śledzenia portfela nie potrzebuje dostępu do Twojego "
                   "rachunku maklerskiego i nie powinno go mieć. Import pliku daje te "
                   "same dane bez powierzania komukolwiek kluczy do konta, na którym "
                   "leżą pieniądze.",
                   "Sprawdź też, czy da się usunąć konto razem z danymi — i czy da się "
                   "to zrobić samodzielnie, bez pisania próśb."]},
        ],
        "faq": [
            ("Czy Google Sheets wystarczy do śledzenia portfela?",
             "Na początku tak. Granicą jest zwykle liczba pozycji, obsługa walut "
             "i policzenie stopy zwrotu uwzględniającej dopłaty."),
            ("Czy aplikacja do portfela potrzebuje dostępu do rachunku maklerskiego?",
             "Nie. Import pliku z historią operacji daje te same dane bez udostępniania "
             "danych logowania. Portevo działa właśnie w ten sposób."),
            ("Jak często aktualizować portfel?",
             "Wystarczy wgrywać nowy raport po serii transakcji — notowania i wycena "
             "aktualizują się same."),
        ],
        "powiazane": [("/portfel-inwestycyjny", "Portfel inwestycyjny"),
                      ("/analiza-portfela", "Analiza i ryzyko"),
                      ("/poradniki/jak-liczyc-stope-zwrotu", "Jak liczyć stopę zwrotu"),
                      ("/slownik/xirr", "XIRR")],
        "cta": ("Wgraj raport i zobacz różnicę",
                "Pozycje, wycena w złotówkach, koszty i porównanie z indeksami — "
                "bez jednej formuły."),
        "cta_link": "/portfel-inwestycyjny",
    },

    "wskazniki-finansowe-spolki": {
        "h1": "Wskaźniki finansowe spółki — które naprawdę coś mówią",
        "tytul": "Wskaźniki finansowe spółki — C/Z, ROE, EBITDA | Portevo",
        "opis": "Przegląd najważniejszych wskaźników finansowych: co mierzą, jak je "
                "czytać w kontekście branży i gdzie każdy z nich kłamie.",
        "lead": "Żaden wskaźnik nie działa w oderwaniu od innych. Oto sześć "
                "najważniejszych i pułapka, którą każdy z nich ma wbudowaną.",
        "sekcje": [
            {"h2": "Wycena: C/Z i C/WK",
             "p": ["Wskaźnik cena/zysk mówi, ile płacisz za złotówkę rocznego zysku. "
                   "Wysoki oznacza wysokie oczekiwania rynku, niski — albo okazję, albo "
                   "kłopot. Bez porównania z branżą i z historią spółki jest bezużyteczny.",
                   "Pułapka: spółka cykliczna ma najniższy C/Z na szczycie cyklu, gdy "
                   "zyski są rekordowe i za chwilę spadną. Najniższy wskaźnik bywa więc "
                   "najgorszym momentem."]},
            {"h2": "Rentowność: marże i ROE",
             "p": ["Marża operacyjna najlepiej opisuje sam biznes, bo nie zależy od "
                   "struktury finansowania. ROE pokazuje, ile zysku spółka wyciska "
                   "z kapitału właścicieli.",
                   "Pułapka ROE: wysokie zadłużenie zmniejsza kapitał własny i sztucznie "
                   "podbija wskaźnik. Dlatego ROE zawsze czyta się razem z poziomem "
                   "zadłużenia."]},
            {"h2": "Zadłużenie: dług netto do EBITDA",
             "p": ["Relacja długu pomniejszonego o gotówkę do zysku operacyjnego "
                   "powiększonego o amortyzację. Powyżej trzech–czterech spółka robi się "
                   "wrażliwa na wzrost stóp procentowych.",
                   "Pułapka EBITDA: pomijana amortyzacja to realne zużycie majątku, "
                   "który trzeba kiedyś odtworzyć. Wysoka EBITDA przy stale ujemnych "
                   "przepływach gotówkowych nie oznacza zdrowej firmy."]},
            {"h2": "Jak używać wskaźników sensownie",
             "lista": ["Porównuj w obrębie jednej branży — bank i producent gier mają "
                       "nieporównywalne wskaźniki.",
                       "Patrz na trend, nie na pojedynczy odczyt.",
                       "Sprawdzaj, czy zysk ma pokrycie w przepływach pieniężnych.",
                       "Nie buduj decyzji na jednej liczbie — każda ma sytuację, "
                       "w której wprowadza w błąd."]},
        ],
        "faq": [
            ("Który wskaźnik jest najważniejszy?",
             "Żaden pojedynczy. Wycena bez rentowności nic nie mówi, a rentowność bez "
             "zadłużenia bywa złudna. Zestaw minimalny to wycena, marża operacyjna "
             "i dług netto do EBITDA."),
            ("Czy niski wskaźnik C/Z oznacza okazję?",
             "Nie musi. Często oznacza, że rynek spodziewa się spadku zysków — na "
             "przykład na szczycie cyklu w spółce cyklicznej."),
            ("Gdzie sprawdzić wskaźniki polskich spółek?",
             "W Portevo, w karcie spółki, razem z medianą tych samych wskaźników dla "
             "firm z tej samej branży — bo bez odniesienia liczba nic nie znaczy."),
        ],
        "powiazane": [("/notowania-spolek", "Notowania i wskaźniki"),
                      ("/slownik/cz", "Wskaźnik C/Z"), ("/slownik/roe", "ROE"),
                      ("/slownik/ebitda", "EBITDA"),
                      ("/slownik/dlug-netto", "Dług netto")],
        "cta": ("Zobacz wskaźniki z porównaniem do branży",
                "Karta spółki w Portevo pokazuje wskaźniki obok mediany dla firm "
                "z tego samego sektora."),
        "cta_link": "/notowania-spolek",
    },

    "sezon-wynikow-jak-sie-przygotowac": {
        "h1": "Sezon wyników — jak się do niego przygotować",
        "tytul": "Sezon wyników — jak się przygotować krok po kroku | Portevo",
        "opis": "Co zrobić przed sezonem wyników: przegląd terminów, sprawdzenie "
                "oczekiwań rynku i ocena, ile Twoje spółki zwykle skaczą po raportach.",
        "lead": "Sezon wyników to kilka tygodni, w których portfel potrafi zmienić się "
                "bardziej niż przez poprzedni kwartał. Przygotowanie zajmuje godzinę.",
        "sekcje": [
            {"h2": "Krok pierwszy: zbierz terminy",
             "p": ["Zacznij od listy dat publikacji dla wszystkich spółek, które masz "
                   "albo obserwujesz. Zaznacz, które raportują przed otwarciem sesji, "
                   "a które po zamknięciu — to decyduje, kiedy zobaczysz reakcję kursu.",
                   "Dopisz do tego terminy najważniejszych danych makroekonomicznych. "
                   "Odczyt inflacji albo decyzja o stopach w dniu publikacji raportu "
                   "potrafi całkowicie przykryć wyniki spółki."]},
            {"h2": "Krok drugi: sprawdź, czego oczekuje rynek",
             "p": ["Dla każdej spółki zanotuj konsensus zysku na akcję i przychodów oraz "
                   "widełki prognoz. Wąskie widełki oznaczają zgodność analityków — wynik "
                   "poza nimi będzie zaskoczeniem. Szerokie oznaczają, że nikt nie wie, "
                   "czego się spodziewać.",
                   "Zwróć uwagę na rewizje z ostatnich tygodni. Fala obniżek prognoz "
                   "tuż przed raportem mówi o zmianie nastawienia rynku więcej niż sam "
                   "poziom konsensusu."]},
            {"h2": "Krok trzeci: oceń, ile ta spółka zwykle skacze",
             "p": ["Najbardziej praktyczna liczba w całym przygotowaniu: średnia zmiana "
                   "kursu na sesji po poprzednich publikacjach. Spółka, która zwykle "
                   "rusza się o 2%, i taka, która rusza się o 12%, wymagają zupełnie "
                   "innego podejścia do wielkości pozycji.",
                   "Sprawdź też historię zaskoczeń. Firma, która od ośmiu kwartałów bije "
                   "prognozy, zwykle prowadzi ostrożną komunikację — analitycy się tego "
                   "uczą i z czasem samo pobicie przestaje wystarczać."]},
            {"h2": "Czego nie robić",
             "lista": ["Nie zwiększaj pozycji tylko dlatego, że „wyniki powinny być "
                       "dobre” — rynek zna te same prognozy.",
                       "Nie traktuj jednego kwartału jako dowodu na cokolwiek.",
                       "Nie czytaj wyłącznie nagłówka. Prognoza zarządu na kolejne "
                       "okresy bywa ważniejsza niż liczby za miniony kwartał."]},
        ],
        "faq": [
            ("Ile trwa sezon wyników?",
             "Na rynku amerykańskim około sześciu tygodni od drugiego tygodnia po "
             "zakończeniu kwartału. W Polsce publikacje są bardziej rozciągnięte."),
            ("Czy warto trzymać akcje przez publikację wyników?",
             "To decyzja indywidualna, zależna od wielkości pozycji i tolerancji na "
             "wahania. Portevo nie doradza — pokazuje tylko, o ile kurs danej spółki "
             "zwykle się zmieniał po poprzednich raportach."),
            ("Gdzie sprawdzić średni ruch kursu po wynikach?",
             "W karcie spółki w Portevo, w sekcji z historią publikacji — obok każdego "
             "kwartału stoi reakcja kursu na kolejnej sesji."),
        ],
        "powiazane": [("/kalendarz-wynikow-spolek", "Kalendarz wyników spółek"),
                      ("/kalendarz-makroekonomiczny", "Kalendarz makro"),
                      ("/slownik/zaskoczenie-wynikami", "Zaskoczenie wynikami"),
                      ("/slownik/konsensus-analitykow", "Konsensus analityków")],
        "cta": ("Przygotuj się w pięć minut",
                "Kalendarz wyników pokazuje terminy, prognozy i średni ruch kursu "
                "po poprzednich raportach — dla każdej spółki osobno."),
        "cta_link": "/kalendarz-wynikow-spolek",
    },
}

#: Kolejność w spisie — od tekstu o największym potencjale ruchu.
KOLEJNOSC = [
    "kiedy-spolki-publikuja-wyniki",
    "jak-czytac-raport-kwartalny",
    "jak-liczyc-stope-zwrotu",
    "jak-zaczac-inwestowac",
    "koszty-inwestowania",
    "wskazniki-finansowe-spolki",
    "jak-sledzic-portfel-inwestycyjny",
    "jak-czytac-raport-espi",
    "sezon-wynikow-jak-sie-przygotowac",
]


def adresy() -> list[str]:
    return ["/poradniki"] + [f"/poradniki/{s}" for s in KOLEJNOSC]


def zbuduj(slug: str) -> str | None:
    d = PORADNIKI.get(slug)
    if not d:
        return None
    sciezka = f"/poradniki/{slug}"

    bloki = []
    for s in d["sekcje"]:
        bloki.append(render.sekcja(s["h2"], *s.get("p", []), lista=s.get("lista")))
    bloki.append(render.sekcja("Najczęstsze pytania", kotwica="pytania",
                               html_dodatkowy=render.faq(d["faq"])))
    bloki.append(render.sekcja("Powiązane", html_dodatkowy=render.chipsy(d["powiazane"])))
    tytul_cta, tekst_cta = d["cta"]
    bloki.append(render.zacheta(tytul_cta, tekst_cta,
                                adres=d.get("cta_link", "/"),
                                etykieta="Zobacz w Portevo",
                                drugi=("/poradniki", "Więcej poradników")))
    bloki.append(render.zastrzezenie())

    okruchy = [("/poradniki", "Poradniki"), ("", d["h1"].split(" — ")[0])]
    return render.strona(
        sciezka=sciezka, tytul=d["tytul"], opis=d["opis"], h1=d["h1"],
        lead=d["lead"], nadtytul="Poradnik", okruchy=okruchy,
        aktualizacja="11 sierpnia 2026", bloki=bloki,
        jsonld=[
            jsonld.artykul(sciezka, d["h1"], d["opis"], DATA),
            jsonld.okruchy(okruchy),
            jsonld.pytania(d["faq"]),
        ],
    )


def zbuduj_spis() -> str:
    pozycje = [(f"/poradniki/{s}", PORADNIKI[s]["h1"].split(" — ")[0],
                PORADNIKI[s]["opis"], "Poradnik") for s in KOLEJNOSC]

    bloki = [
        render.sekcja("Wszystkie poradniki", html_dodatkowy=render.karty(pozycje)),
        render.sekcja(
            "Skąd te teksty",
            "Piszemy o tym, co sami robimy w aplikacji: terminach publikacji wyników, "
            "liczeniu stopy zwrotu, kosztach i wskaźnikach. Bez prognoz rynkowych, "
            "bez „pewnych okazji” i bez rekomendacji — Portevo nie jest doradcą "
            "inwestycyjnym i nie udaje nim być.",
            "Każdy tekst kończy się linkiem do funkcji, która opisany problem "
            "rozwiązuje — ale dopiero po odpowiedzeniu na pytanie."),
        render.zacheta(
            "Od teorii do własnych liczb",
            "Kalendarz wyników i portfel w jednej aplikacji, po polsku, za darmo.",
            drugi=("/slownik", "Słownik giełdowy")),
        render.zastrzezenie(),
    ]

    tytul = "Poradniki giełdowe — wyniki spółek, portfel, wskaźniki | Portevo"
    opis = ("Poradniki o inwestowaniu po polsku: kiedy spółki publikują wyniki, jak "
            "czytać raport kwartalny, jak liczyć stopę zwrotu i ile naprawdę kosztuje "
            "inwestowanie.")
    okruchy = [("", "Poradniki")]

    return render.strona(
        sciezka="/poradniki", tytul=tytul, opis=opis, h1="Poradniki giełdowe",
        lead="Konkretne odpowiedzi na pytania, które zadaje sobie każdy inwestor "
             "w pierwszych latach. Bez żargonu i bez obietnic.",
        nadtytul="Wiedza", okruchy=okruchy, szeroki_naglowek=True, bloki=bloki,
        jsonld=[
            jsonld.strona("/poradniki", tytul, opis, typ="CollectionPage"),
            jsonld.okruchy(okruchy),
            jsonld.lista_pozycji("Poradniki Portevo",
                                 [(p[0], p[1]) for p in pozycje]),
        ],
    )
