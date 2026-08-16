"""Słownik pojęć giełdowych — hasło po haśle, po polsku.

Po co słownik w aplikacji do portfela: to najtańszy sposób na frazy informacyjne
(„co to jest EPS”, „co oznacza C/Z”), których nikt nie wpisuje z zamiarem
zakupu — ale które przyprowadzają dokładnie te osoby, które za pół roku będą
szukały narzędzia. Dodatkowo `DefinedTerm` ze schema.org jest najchętniej
cytowanym przez modele językowe typem danych: pytany „co to jest wskaźnik C/Z”,
model dostaje gotową parę termin–definicja z podanym źródłem.

Struktura hasła jest stała i celowo skromna:
  krotka  — jedno zdanie, to trafia do danych strukturalnych i do spisu,
  dluga   — dwa–trzy akapity wyjaśnienia,
  przyklad— policzony przykład z liczbami, bo definicja bez liczby nic nie uczy,
  linki   — powiązane hasła i podstrona funkcji, która danego pojęcia używa.

Zasada: definicja ma być prawdziwa i sprawdzalna. Hasło, którego nie umiemy
napisać uczciwie, po prostu tu nie trafia.
"""

from __future__ import annotations

from . import jsonld, render, site

#: Dzień ostatniej zmiany w definicjach — `lastmod` w sitemapie. Podnieś przy
#: poprawce treści, nie przy każdym wdrożeniu (patrz `guides.ZMIENIONO`).
ZMIENIONO = "2026-08-11"

#: (slug, nazwa, krótka definicja, akapity, przykład, powiązane slugi)
HASLA = [
    # ---------------------------------------------------------- wyniki spółek
    ("eps", "EPS — zysk na akcję",
     "Zysk netto spółki przypadający na jedną akcję.",
     ["Skrót pochodzi od angielskiego <em>earnings per share</em>. Powstaje z podzielenia "
      "zysku netto przez liczbę akcji. Dzięki temu wynik dwóch spółek o zupełnie różnej "
      "wielkości da się porównać: milion złotych zysku znaczy co innego przy tysiącu "
      "akcji, a co innego przy milionie.",
      "EPS jest liczbą, wokół której kręci się cały sezon wyników. Analitycy publikują "
      "prognozę EPS na najbliższy kwartał, a rynek reaguje nie na sam wynik, tylko na "
      "<strong>różnicę między wynikiem a prognozą</strong>. Spółka może zarobić rekordowo "
      "dużo i mimo to jej kurs spadnie — jeśli oczekiwano jeszcze więcej."],
     "Spółka zarobiła 120 mln zł przy 60 mln akcji. EPS wynosi 2,00 zł. Jeśli analitycy "
     "spodziewali się 2,20 zł, to mimo wysokiego zysku mamy zaskoczenie negatywne "
     "o około 9%.",
     ["konsensus-analitykow", "zaskoczenie-wynikami", "cz", "raport-kwartalny"]),

    ("konsensus-analitykow", "Konsensus analityków",
     "Uśredniona prognoza wyniku spółki, przygotowana przez śledzących ją analityków.",
     ["Konsensus to średnia z prognoz wielu instytucji finansowych — najczęściej dotyczy "
      "zysku na akcję i przychodów na najbliższy kwartał. Obok średniej podaje się zwykle "
      "widełki, czyli prognozę najniższą i najwyższą.",
      "Widełki mówią więcej niż sama średnia. Wąskie oznaczają, że analitycy są zgodni "
      "i wynik poza nimi będzie zaskoczeniem. Szerokie oznaczają, że nikt tak naprawdę "
      "nie wie, czego się spodziewać — i wtedy reakcja kursu bywa gwałtowna niezależnie "
      "od tego, co spółka pokaże.",
      "Liczba analityków też ma znaczenie. Prognoza oparta na dwóch opiniach jest "
      "znacznie mniej wiarygodna niż zgodna ocena trzydziestu."],
     "Dla dużej spółki technologicznej konsensus EPS wynosi 1,85 USD przy widełkach "
     "1,78–1,94 i 34 analitykach. Wynik 1,60 USD byłby wyraźnie poniżej najniższej "
     "prognozy — takie odczyty rynek zwykle karze mocno.",
     ["eps", "zaskoczenie-wynikami", "cena-docelowa", "sezon-wynikow"]),

    ("zaskoczenie-wynikami", "Zaskoczenie wynikami",
     "Różnica między faktycznym wynikiem spółki a prognozą analityków, podawana w procentach.",
     ["Angielski termin <em>earnings surprise</em>. Dodatnie zaskoczenie oznacza wynik "
      "lepszy od oczekiwań, ujemne — gorszy. To właśnie ta różnica, a nie bezwzględna "
      "wysokość zysku, tłumaczy większość gwałtownych ruchów kursu po publikacji raportu.",
      "Warto patrzeć na serię, nie na pojedynczy kwartał. Spółka, która regularnie bije "
      "prognozy, zwykle prowadzi ostrożną komunikację z rynkiem — analitycy uczą się tego "
      "i podnoszą poprzeczkę, więc z czasem samo pobicie przestaje wystarczać."],
     "Prognoza mówiła 1,00 zł na akcję, spółka pokazała 1,12 zł. Zaskoczenie wynosi +12%.",
     ["eps", "konsensus-analitykow", "raport-kwartalny", "sezon-wynikow"]),

    ("raport-kwartalny", "Raport kwartalny",
     "Sprawozdanie finansowe spółki giełdowej za trzy miesiące działalności.",
     ["Spółki notowane na giełdzie mają obowiązek regularnie pokazywać, ile zarobiły "
      "i jak wygląda ich sytuacja finansowa. Raport kwartalny zawiera rachunek zysków "
      "i strat, bilans, rachunek przepływów pieniężnych oraz komentarz zarządu.",
      "Dla inwestora najważniejsze są zwykle trzy rzeczy: przychody, marża i to, co zarząd "
      "mówi o kolejnych kwartałach. Same liczby opisują przeszłość — kurs wycenia "
      "przyszłość, dlatego prognoza podana przez spółkę potrafi ruszyć notowaniami "
      "mocniej niż wynik za miniony kwartał."],
     "Spółka pokazuje przychody 800 mln zł (rok wcześniej 700 mln) i zysk netto 60 mln zł. "
     "Przychody rosną o 14%, ale jeśli zysk spadł ze 70 mln, to znaczy, że wzrost "
     "kosztował więcej, niż przyniósł.",
     ["marza-netto", "sezon-wynikow", "espi", "guidance"]),

    ("sezon-wynikow", "Sezon wyników",
     "Okres kilku tygodni po zakończeniu kwartału, gdy większość spółek publikuje raporty.",
     ["Spółki raportują w podobnym rytmie, więc ich publikacje kumulują się w krótkim "
      "oknie — na rynku amerykańskim zwykle od drugiego tygodnia po zakończeniu kwartału "
      "przez mniej więcej sześć tygodni. W Polsce terminy są bardziej rozciągnięte, bo "
      "przepisy dają spółkom szersze okno.",
      "W szczycie sezonu jednego dnia raportuje kilkaset spółek. Dlatego kalendarz "
      "wyników z filtrami jest w tym okresie różnicą między listą do przejrzenia "
      "a ścianą tekstu."],
     "Największe amerykańskie banki otwierają sezon w połowie stycznia, kwietnia, lipca "
     "i października. Spółki technologiczne raportują zwykle dwa–trzy tygodnie później.",
     ["raport-kwartalny", "eps", "espi"]),

    ("espi", "ESPI — raport bieżący",
     "System, przez który spółki z GPW publikują informacje mogące wpłynąć na kurs.",
     ["Elektroniczny System Przekazywania Informacji prowadzi Komisja Nadzoru Finansowego. "
      "Spółka ma obowiązek opublikować w nim każdą informację poufną — czyli taką, która "
      "mogłaby wpłynąć na decyzje inwestorów — niezwłocznie po jej powstaniu.",
      "Przez ESPI idą raporty okresowe, ale też pojedyncze zdarzenia: podpisanie dużego "
      "kontraktu, zmiana w zarządzie, wezwanie, prognoza wyników. To oficjalne, pierwotne "
      "źródło informacji o spółkach z warszawskiej giełdy — wszystko, co czytasz później "
      "w serwisach, jest zwykle streszczeniem komunikatu z ESPI."],
     "Spółka budowlana publikuje raport bieżący o umowie na 400 mln zł przy rocznych "
     "przychodach 1,2 mld zł. To informacja istotna — stąd obowiązek natychmiastowej "
     "publikacji.",
     ["raport-kwartalny", "gpw", "guidance"]),

    ("guidance", "Prognoza spółki (guidance)",
     "Własne oczekiwania zarządu co do przyszłych wyników, podawane przy raporcie.",
     ["Część spółek publikuje razem z raportem widełki przychodów lub zysku na kolejny "
      "okres. To jedyna prognoza pochodząca od ludzi, którzy naprawdę wiedzą, jak idzie "
      "biznes — stąd jej waga.",
      "Obniżenie prognozy potrafi zepchnąć kurs mocniej niż słaby miniony kwartał, bo "
      "rynek wycenia przyszłość. Działa to też w drugą stronę: rozczarowujące wyniki "
      "z podniesioną prognozą bywają przyjmowane wzrostem."],
     "Spółka pokazuje wynik zgodny z oczekiwaniami, ale obniża prognozę rocznych "
     "przychodów z 5,0 do 4,6 mld zł. Kurs reaguje na tę drugą informację.",
     ["raport-kwartalny", "konsensus-analitykow", "espi"]),

    # ---------------------------------------------------------- wskaźniki
    ("cz", "C/Z — wskaźnik cena/zysk",
     "Cena akcji podzielona przez zysk przypadający na jedną akcję.",
     ["Po angielsku P/E. Mówi, ile lat zysków w obecnej wysokości „mieści się” w cenie "
      "akcji — albo inaczej: ile złotych płacisz za złotówkę rocznego zysku spółki.",
      "Wysoki C/Z nie oznacza automatycznie, że spółka jest droga. Oznacza, że rynek "
      "oczekuje wzrostu zysków. Niski nie oznacza okazji — bywa, że rynek spodziewa się "
      "spadku. Sam wskaźnik jest bezużyteczny bez odniesienia: porównuj go z innymi "
      "spółkami z tej samej branży i z historią tej samej spółki.",
      "Spotkasz dwie wersje: bieżącą (na podstawie zysków z ostatnich dwunastu miesięcy) "
      "i prognozowaną (na podstawie oczekiwanych zysków). Ta druga bywa mocno różna, "
      "zwłaszcza w spółkach szybko rosnących."],
     "Akcja kosztuje 100 zł, EPS wynosi 5 zł. C/Z równa się 20. Przy medianie 12 dla "
     "branży spółka jest wyceniana z wyraźną premią — pytanie brzmi, czy zasłużenie.",
     ["eps", "kapitalizacja", "cena-docelowa"]),

    ("kapitalizacja", "Kapitalizacja rynkowa",
     "Wartość rynkowa całej spółki: cena akcji pomnożona przez liczbę wszystkich akcji.",
     ["To najprostsza miara wielkości spółki i najczęściej używany sposób dzielenia rynku "
      "na spółki duże, średnie i małe. Na warszawskiej giełdzie odpowiadają temu indeksy "
      "WIG20, mWIG40 i sWIG80.",
      "Kapitalizacja mówi, ile rynek wycenia spółkę — nie ile jest ona warta „naprawdę” "
      "ani ile kosztowałby jej majątek. Duża kapitalizacja zwykle idzie w parze z większą "
      "płynnością, czyli łatwością kupna i sprzedaży bez ruszania kursem."],
     "60 mln akcji po 150 zł daje kapitalizację 9 mld zł.",
     ["cz", "plynnosc", "wig20", "blue-chip"]),

    ("dywidenda", "Dywidenda",
     "Część zysku spółki wypłacana akcjonariuszom.",
     ["O wypłacie decyduje walne zgromadzenie akcjonariuszy. Spółka może wypłacić całość "
      "zysku, część albo nic — brak dywidendy nie jest sam w sobie zły, jeśli pieniądze "
      "zostają w firmie i finansują rozwój.",
      "Stopa dywidendy to wysokość wypłaty podzielona przez cenę akcji. Bardzo wysoka "
      "stopa bywa ostrzeżeniem, a nie zaletą: często oznacza, że kurs mocno spadł, "
      "a rynek nie wierzy w utrzymanie wypłaty w kolejnym roku.",
      "W dniu ustalenia prawa do dywidendy kurs spada zwykle mniej więcej o jej wysokość — "
      "to mechanika, nie strata."],
     "Spółka wypłaca 4 zł na akcję przy kursie 80 zł. Stopa dywidendy wynosi 5%.",
     ["podatek-belki", "raport-kwartalny", "etf"]),

    ("marza-netto", "Marża netto",
     "Jaka część przychodów zostaje w spółce jako zysk netto.",
     ["Zysk netto podzielony przez przychody. Pokazuje, ile z każdej złotówki sprzedaży "
      "faktycznie zostaje po opłaceniu wszystkiego — kosztów, podatków i odsetek.",
      "Marże czyta się w czasie i w porównaniu z branżą. Rosnące przychody przy "
      "kurczącej się marży oznaczają, że wzrost jest kupowany rabatami albo rosnącymi "
      "kosztami — i to zwykle ciekawsza informacja niż sama dynamika sprzedaży.",
      "Obok marży netto podaje się marżę brutto (po kosztach wytworzenia) i operacyjną "
      "(po kosztach działalności, przed odsetkami i podatkiem). Ta ostatnia najlepiej "
      "opisuje sam biznes, bo nie zależy od struktury finansowania."],
     "Przychody 1 000 mln zł, zysk netto 80 mln zł. Marża netto wynosi 8%.",
     ["raport-kwartalny", "ebitda", "roe"]),

    ("ebitda", "EBITDA",
     "Zysk operacyjny powiększony o amortyzację — przybliżenie gotówki generowanej przez biznes.",
     ["Skrót od zysku przed odsetkami, podatkami i amortyzacją. Pozwala porównać spółki "
      "o różnym poziomie zadłużenia i różnym wieku majątku, bo pomija koszty, które nie "
      "wynikają wprost z bieżącej działalności.",
      "Ma poważne ograniczenie: pomijana amortyzacja to realne zużycie majątku, który "
      "kiedyś trzeba odtworzyć. Spółka o wysokiej EBITDA i stale ujemnych przepływach "
      "pieniężnych nie jest zdrowa — jest tylko ładnie opisana."],
     "Zysk operacyjny 120 mln zł plus amortyzacja 40 mln zł daje EBITDA 160 mln zł.",
     ["marza-netto", "dlug-netto", "raport-kwartalny"]),

    ("roe", "ROE — rentowność kapitału własnego",
     "Ile zysku spółka wypracowuje z każdej złotówki kapitału należącego do akcjonariuszy.",
     ["Zysk netto podzielony przez kapitał własny. Odpowiada na pytanie, jak skutecznie "
      "zarząd pracuje pieniędzmi właścicieli.",
      "Wysokie ROE bywa efektem wysokiego zadłużenia, a nie sprawności — dług zmniejsza "
      "kapitał własny w mianowniku i podbija wskaźnik. Dlatego ROE czyta się razem "
      "z poziomem zadłużenia."],
     "Zysk netto 90 mln zł przy kapitale własnym 600 mln zł daje ROE 15%.",
     ["marza-netto", "dlug-netto", "ebitda"]),

    ("dlug-netto", "Dług netto",
     "Zadłużenie spółki pomniejszone o posiadaną gotówkę.",
     ["Spółka z długiem 500 mln zł i gotówką 450 mln zł jest w zupełnie innej sytuacji niż "
      "taka z tym samym długiem i pustą kasą. Dług netto pokazuje faktyczne obciążenie.",
      "Najczęściej podaje się go w relacji do EBITDA. Wskaźnik powyżej 3–4 oznacza, że "
      "spółka jest mocno zadłużona i wrażliwa na wzrost stóp procentowych albo słabszy "
      "kwartał."],
     "Dług 800 mln zł, gotówka 200 mln zł, EBITDA 200 mln zł. Dług netto to 600 mln zł, "
     "czyli trzykrotność EBITDA.",
     ["ebitda", "stopa-procentowa", "roe"]),

    ("cena-docelowa", "Cena docelowa",
     "Poziom kursu, na jaki analityk wycenia akcję w horyzoncie zwykle roku.",
     ["Publikowana razem z rekomendacją. To wynik modelu wyceny, a nie prognoza — model "
      "opiera się na założeniach, które mogą się nie sprawdzić.",
      "Ceny docelowe warto traktować jako opinie, nie fakty, i patrzeć raczej na ich "
      "zmianę niż na bezwzględny poziom. Fala podwyżek cen docelowych po raporcie mówi "
      "o zmianie nastawienia rynku więcej niż pojedyncza liczba."],
     "Mediana cen docelowych 24 analityków wynosi 180 zł przy kursie 150 zł — rynek "
     "analityczny widzi 20% przestrzeni w górę.",
     ["konsensus-analitykow", "cz", "eps"]),

    # ---------------------------------------------------------- portfel
    ("xirr", "XIRR — wewnętrzna stopa zwrotu",
     "Roczna stopa zwrotu portfela uwzględniająca daty i wielkości wszystkich wpłat i wypłat.",
     ["Zwykłe „ile mam minus ile wpłaciłem” nie działa, gdy pieniądze dokładasz w różnych "
      "momentach. Sto tysięcy wpłacone rok temu i sto tysięcy wpłacone wczoraj nie "
      "zarabiały tyle samo czasu, więc nie można ich po prostu zsumować.",
      "XIRR rozwiązuje to, szukając takiej rocznej stopy, przy której wszystkie przepływy "
      "sprowadzone do dnia dzisiejszego dają obecną wartość portfela. Efekt: jedna liczba "
      "porównywalna z oprocentowaniem lokaty albo ze stopą zwrotu indeksu."],
     "Wpłacasz 10 000 zł w styczniu i 10 000 zł w lipcu, a w grudniu masz 21 500 zł. Zysk "
     "to 1 500 zł, ale XIRR wynosi około 10% rocznie, bo druga wpłata pracowała pół roku.",
     ["twr", "benchmark", "stopa-zwrotu"]),

    ("twr", "TWR — stopa zwrotu ważona czasem",
     "Miara wyniku samych inwestycji, odporna na wpłaty i wypłaty.",
     ["TWR odpowiada na pytanie „jak dobrze radziły sobie moje inwestycje”, a nie „ile "
      "zarobiłem”. Dzieli historię portfela na odcinki między przepływami pieniężnymi "
      "i mnoży ich wyniki, przez co moment wpłaty przestaje mieć znaczenie.",
      "Dzięki temu TWR da się uczciwie porównać z indeksem — indeks też nie dostaje wpłat. "
      "XIRR mówi, ile zarobiłeś Ty; TWR mówi, ile zarobiła Twoja strategia."],
     "Portfel rośnie o 10%, potem dopłacasz duże środki i rynek spada o 5%. XIRR będzie "
     "słaby, bo większość kapitału złapała spadek. TWR pokaże wynik samych inwestycji: "
     "1,10 × 0,95 − 1, czyli około +4,5%.",
     ["xirr", "benchmark", "stopa-zwrotu"]),

    ("stopa-zwrotu", "Stopa zwrotu",
     "Procentowa zmiana wartości inwestycji w danym okresie.",
     ["Najprostsza miara wyniku, ale łatwo ją policzyć źle. Trzy typowe pułapki: "
      "nieuwzględnienie wpłat, pominięcie prowizji i podatku oraz porównywanie okresów "
      "o różnej długości.",
      "Stopę zwrotu podaje się zwykle w skali roku, żeby dało się ją porównać z lokatą, "
      "inflacją albo indeksem. Wynik +30% w trzy lata to niecałe 9% rocznie."],
     "Portfel wart 50 000 zł urósł do 57 500 zł bez dopłat. Stopa zwrotu wynosi 15%.",
     ["xirr", "twr", "inflacja", "benchmark"]),

    ("benchmark", "Benchmark",
     "Punkt odniesienia, z którym porównujesz wynik swojego portfela.",
     ["Najczęściej indeks giełdowy — WIG, WIG20 albo S&P 500 — a dla polskiego inwestora "
      "także inflacja. Bez punktu odniesienia „zarobiłem 8%” nie znaczy nic: przy "
      "indeksie na +20% to słaby wynik, przy indeksie na −10% bardzo dobry.",
      "Benchmark powinien odpowiadać temu, co masz w portfelu. Porównywanie portfela "
      "polskich małych spółek z amerykańskim indeksem technologicznym niczego nie mierzy."],
     "Portfel zarobił 12%, WIG w tym czasie 18%. Wynik jest dodatni, ale gorszy od "
     "biernego kupienia szerokiego rynku.",
     ["twr", "inflacja", "etf", "wig20"]),

    ("dywersyfikacja", "Dywersyfikacja",
     "Rozłożenie kapitału tak, żeby wynik nie zależał od jednego zdarzenia.",
     ["Liczy się nie liczba pozycji, tylko to, czy reagują na różne rzeczy. Dziesięć "
      "spółek z jednej branży spada zwykle razem — to w praktyce jedna pozycja pomnożona "
      "przez dziesięć.",
      "Dywersyfikować można po branżach, krajach, walutach i klasach aktywów. Każdy z tych "
      "wymiarów działa niezależnie: portfel z akcji z całego świata wciąż jest w całości "
      "portfelem akcyjnym."],
     "Portfel z pięciu spółek technologicznych i portfel z pięciu spółek z pięciu różnych "
     "branż mają tę samą liczbę pozycji i zupełnie inne ryzyko.",
     ["korelacja", "koncentracja", "zmiennosc", "etf"]),

    ("korelacja", "Korelacja",
     "Miara tego, czy dwa instrumenty poruszają się w tę samą stronę.",
     ["Przyjmuje wartości od −1 do +1. Wartość bliska +1 oznacza, że instrumenty rosną "
      "i spadają razem, bliska 0 — że ich ruchy są niezależne, a ujemna — że idą "
      "w przeciwne strony.",
      "Wysoka korelacja między pozycjami oznacza, że portfel jest mniej rozłożony, niż "
      "wynikałoby z liczby spółek. Warto pamiętać, że korelacje rosną w czasie paniki "
      "rynkowej — dokładnie wtedy, kiedy dywersyfikacja byłaby najbardziej potrzebna."],
     "Dwie spółki wydobywcze mają korelację 0,85. Trzymanie obu daje niewiele więcej "
     "rozproszenia niż trzymanie jednej w podwójnej wielkości.",
     ["dywersyfikacja", "zmiennosc", "koncentracja"]),

    ("koncentracja", "Koncentracja portfela",
     "Udział największych pozycji w całości portfela.",
     ["Podaje się zwykle jako udział największej pozycji i sumę pierwszej piątki. "
      "Koncentracja nie jest sama w sobie błędem — jest świadomym wyborem, dopóki "
      "wiadomo, że się ją ma.",
      "Najczęstszy przypadek jest niezamierzony: jedna pozycja rośnie przez dwa lata "
      "i po cichu robi się z niej połowa portfela. Wynik całości zaczyna wtedy zależeć "
      "od jednej spółki, choć nikt takiej decyzji nie podjął."],
     "Portfel z 18 spółek, w którym jedna waży 42%, jest w praktyce portfelem jednej "
     "spółki z siedemnastoma dodatkami.",
     ["dywersyfikacja", "korelacja", "zmiennosc"]),

    ("zmiennosc", "Zmienność",
     "Miara tego, jak mocno wartość instrumentu waha się w czasie.",
     ["Liczona jako odchylenie standardowe stóp zwrotu, zwykle podawana w skali roku. "
      "Wysoka zmienność oznacza duże wahania w obie strony — nie oznacza samych spadków.",
      "Zmienność jest najczęściej używanym przybliżeniem ryzyka, ale mierzy tylko wahania "
      "kursu. Nie mówi nic o ryzyku, że spółka po prostu przestanie istnieć, ani o tym, "
      "czy cena jest sensowna."],
     "Akcja o rocznej zmienności 40% waha się mniej więcej dwa razy mocniej niż szeroki "
     "indeks akcji, którego zmienność wynosi zwykle 15–20%.",
     ["korelacja", "beta", "obsuniecie"]),

    ("beta", "Beta",
     "Miara wrażliwości instrumentu na ruchy całego rynku.",
     ["Beta równa 1 oznacza, że instrument porusza się mniej więcej tak jak rynek. Powyżej "
      "1 — mocniej, poniżej — słabiej. Beta ujemna oznaczałaby ruch w przeciwną stronę, "
      "co wśród akcji jest rzadkością.",
      "Beta opisuje przeszłość i potrafi się zmieniać. Spółka zadłużona ma zwykle wyższą "
      "betę niż ta sama spółka bez długu, bo każde wahanie wyniku uderza mocniej "
      "w kapitał właścicieli."],
     "Spółka o becie 1,4 przy wzroście indeksu o 10% zyskiwała historycznie około 14% — "
     "i tyle samo traciła przy spadku.",
     ["zmiennosc", "benchmark", "korelacja"]),

    ("obsuniecie", "Obsunięcie kapitału",
     "Największy spadek wartości portfela od szczytu do dołka.",
     ["Angielski termin <em>drawdown</em>. To miara, która najlepiej opisuje, jak trudno "
      "było wytrzymać daną strategię — bo strata przeżywana jest inaczej niż średnia "
      "roczna stopa zwrotu w tabelce.",
      "Ważny jest nie tylko rozmiar obsunięcia, ale i czas powrotu do poprzedniego "
      "szczytu. Spadek o 50% wymaga późniejszego wzrostu o 100%, żeby wyjść na zero."],
     "Portfel wart 100 000 zł spadł do 68 000 zł, zanim odbił. Maksymalne obsunięcie "
     "wyniosło 32%.",
     ["zmiennosc", "stopa-zwrotu", "dywersyfikacja"]),

    # ---------------------------------------------------------- instrumenty
    ("etf", "ETF — fundusz notowany na giełdzie",
     "Fundusz kupowany jak akcja, który odwzorowuje zachowanie indeksu, sektora lub surowca.",
     ["Kupując jedną jednostkę ETF, stajesz się pośrednio właścicielem koszyka, który "
      "fundusz trzyma — czasem kilkuset spółek naraz. To najprostszy sposób na szeroką "
      "dywersyfikację bez kupowania każdej spółki osobno.",
      "ETF-y dzieli się między innymi na akumulujące (dywidendy zostają w funduszu) "
      "i dystrybuujące (dywidendy trafiają na rachunek). Najważniejszym parametrem, który "
      "znasz z góry na pewno, jest opłata za zarządzanie."],
     "ETF na indeks S&P 500 z opłatą 0,07% rocznie daje ekspozycję na 500 największych "
     "amerykańskich spółek za koszt 7 zł rocznie od każdych 10 000 zł.",
     ["ter", "dywersyfikacja", "benchmark", "indeks"]),

    ("ter", "TER — wskaźnik kosztów całkowitych",
     "Roczny koszt zarządzania funduszem, wyrażony jako procent wartości inwestycji.",
     ["Nie płacisz go osobno — jest odejmowany z wyniku funduszu, więc bywa niewidoczny. "
      "Tym bardziej warto go sprawdzać, bo to jedyna liczba w całym zestawieniu, którą "
      "znasz z góry na pewno. Przyszłej stopy zwrotu nie zna nikt.",
      "Przy długim horyzoncie różnice, które wyglądają na kosmetyczne, robią się duże. "
      "Koszt działa co roku i od coraz większego kapitału."],
     "Przy 20 latach i 7% rocznie fundusz za 0,07% zostawia około 12% więcej kapitału niż "
     "identyczny fundusz za 0,45%.",
     ["etf", "prowizja-maklerska", "stopa-zwrotu"]),

    ("indeks", "Indeks giełdowy",
     "Wskaźnik pokazujący zmianę wartości koszyka spółek reprezentujących rynek lub jego część.",
     ["Indeks nie jest instrumentem, który da się kupić — jest miarą. Kupić da się fundusz, "
      "który go odwzorowuje.",
      "Skład indeksu i sposób ważenia spółek mają duże znaczenie. Indeks ważony "
      "kapitalizacją jest zdominowany przez największe spółki, więc wynik kilku firm "
      "potrafi przesądzić o zachowaniu całości."],
     "W WIG20 kilka największych spółek odpowiada za większą część zmian indeksu niż "
     "pozostałe kilkanaście razem.",
     ["wig20", "etf", "benchmark", "kapitalizacja"]),

    ("wig20", "WIG20, mWIG40, sWIG80",
     "Główne indeksy warszawskiej giełdy, dzielące spółki według wielkości.",
     ["WIG20 skupia dwadzieścia największych i najpłynniejszych spółek, mWIG40 kolejne "
      "czterdzieści średnich, a sWIG80 osiemdziesiąt mniejszych. Obok nich stoi WIG — "
      "indeks szeroki, obejmujący prawie cały rynek.",
      "Podział bywa mylący dla nowych inwestorów: WIG20 jest silnie obciążony sektorem "
      "finansowym i paliwowym, więc jego zachowanie nie opisuje całej polskiej "
      "gospodarki."],
     "Spółka rosnąca latami w sWIG80 może awansować do mWIG40 — awans zwykle podnosi "
     "zainteresowanie funduszy, bo część z nich musi trzymać skład indeksu.",
     ["indeks", "gpw", "kapitalizacja", "blue-chip"]),

    ("gpw", "GPW — Giełda Papierów Wartościowych w Warszawie",
     "Główny rynek obrotu akcjami w Polsce, działający od 1991 roku.",
     ["Na rynku głównym notowanych jest kilkaset spółek. Obok niego działa NewConnect — "
      "rynek dla mniejszych i młodszych firm, z łagodniejszymi wymogami informacyjnymi "
      "i wyraźnie wyższym ryzykiem.",
      "Sesja na GPW trwa w dni robocze od 9:00 do 17:00, z fazą zamknięcia do 17:05. "
      "Spółki publikują informacje cenotwórcze przez system ESPI."],
     "Spółka z rynku głównego ma obowiązek publikować raporty okresowe i informacje "
     "poufne — spółka z NewConnect podlega lżejszemu reżimowi.",
     ["espi", "wig20", "plynnosc", "blue-chip"]),

    ("blue-chip", "Blue chip",
     "Duża, płynna spółka o ugruntowanej pozycji, zwykle wchodząca w skład głównego indeksu.",
     ["Określenie nieformalne, ale używane konsekwentnie: blue chip to spółka, którą da "
      "się kupić i sprzedać za duże kwoty bez ruszania kursem, i o której wiadomo, że "
      "istnieje od lat.",
      "Nie oznacza bezpieczeństwa. Duże spółki też tracą po kilkadziesiąt procent — "
      "różnica polega na płynności i dostępności informacji, nie na gwarancji wyniku."],
     "Na GPW za blue chipy uchodzą spółki z WIG20, na rynku amerykańskim — spółki "
     "z indeksu Dow Jones i największe firmy z S&P 500.",
     ["wig20", "plynnosc", "kapitalizacja"]),

    ("plynnosc", "Płynność",
     "Łatwość kupna lub sprzedaży instrumentu bez wpływania na jego cenę.",
     ["Mierzy się ją zwykle średnim dziennym obrotem i szerokością spreadu. Wysoka "
      "płynność oznacza, że zlecenie zostanie zrealizowane blisko ostatniej ceny.",
      "Przy spółkach o niskiej płynności sama próba sprzedaży większej pozycji potrafi "
      "zbić kurs o kilka procent. To ryzyko, którego nie widać w żadnym wskaźniku "
      "wyceny."],
     "Przy dziennym obrocie 200 tys. zł sprzedaż pakietu za 100 tys. zł jest połową "
     "całego dnia handlu — bez zbicia ceny raczej się nie uda.",
     ["spread", "wolumen", "blue-chip"]),

    ("spread", "Spread",
     "Różnica między najlepszą ceną kupna a najlepszą ceną sprzedaży.",
     ["To pierwszy, natychmiastowy koszt każdej transakcji: kupujesz po cenie wyższej, "
      "sprzedajesz po niższej. Przy płynnych spółkach spread wynosi ułamek procenta, "
      "przy mało płynnych potrafi sięgnąć kilku procent.",
      "Spread jest kosztem niewidocznym w zestawieniu prowizji, ale realnym — przy "
      "częstym handlu potrafi przewyższyć wszystkie opłaty maklerskie razem wzięte."],
     "Kupno po 10,20 zł i jednoczesna sprzedaż po 10,00 zł oznacza spread 2% — tyle "
     "tracisz w sekundę po wejściu w pozycję.",
     ["plynnosc", "prowizja-maklerska", "wolumen"]),

    ("wolumen", "Wolumen obrotu",
     "Liczba akcji, które zmieniły właściciela w danym okresie.",
     ["Wolumen pokazuje, ile faktycznie było handlu. Duży ruch kursu przy niskim "
      "wolumenie znaczy mniej niż taki sam ruch przy wysokim — w pierwszym przypadku "
      "wystarczyło kilka zleceń.",
      "Skoki wolumenu towarzyszą zwykle publikacji wyników, komunikatom spółki i wejściu "
      "lub wyjściu spółki z indeksu."],
     "Spółka handlowana zwykle po 50 tys. akcji dziennie notuje w dniu raportu 900 tys. — "
     "to sygnał, że informacja była istotna.",
     ["plynnosc", "spread", "espi"]),

    ("krotka-sprzedaz", "Krótka sprzedaż",
     "Transakcja zarabiająca na spadku kursu, oparta na sprzedaży pożyczonych akcji.",
     ["Inwestor pożycza akcje, sprzedaje je, a później odkupuje — licząc, że taniej. "
      "Udział akcji sprzedanych krótko podaje się w procentach akcji dostępnych "
      "w obrocie.",
      "Wysoki udział krótkiej sprzedaży bywa czytany dwojako: jako sygnał, że duzi gracze "
      "spodziewają się spadku, albo jako paliwo do gwałtownego wzrostu, gdy dobre "
      "informacje zmuszają ich do szybkiego odkupu."],
     "Gdy 15% akcji spółki jest sprzedanych krótko, dobry raport potrafi wywołać ruch "
     "wzmocniony zamykaniem tych pozycji.",
     ["wolumen", "zmiennosc", "raport-kwartalny"]),

    # ---------------------------------------------------------- koszty i podatki
    ("prowizja-maklerska", "Prowizja maklerska",
     "Opłata pobierana przez brokera za wykonanie zlecenia.",
     ["Podawana zwykle jako procent wartości transakcji z określoną kwotą minimalną. "
      "To ta kwota minimalna decyduje o opłacalności małych zleceń.",
      "Prowizja to nie jedyny koszt. Do rachunku dochodzą spread, opłata za przewalutowanie "
      "przy instrumentach zagranicznych i czasem opłata za prowadzenie rachunku."],
     "Prowizja 0,29% z minimum 5 zł przy zleceniu na 500 zł oznacza realny koszt 1% — "
     "trzykrotnie więcej niż stawka nominalna.",
     ["spread", "ter", "podatek-belki"]),

    ("podatek-belki", "Podatek Belki",
     "Dziewiętnastoprocentowy podatek od zysków kapitałowych.",
     ["Obejmuje zyski ze sprzedaży akcji, ETF-ów i innych instrumentów oraz dywidendy "
      "i odsetki. Przy rachunku maklerskim w Polsce broker wystawia PIT-8C, a rozliczenia "
      "dokonujesz sam w zeznaniu rocznym.",
      "Zyski i straty z instrumentów rozliczanych w ten sam sposób można kompensować, "
      "a stratę rozliczyć w kolejnych latach. Przy dywidendach zagranicznych dochodzi "
      "kwestia podatku pobranego u źródła.",
      "To opis ogólny, nie porada podatkowa — sytuacje indywidualne potrafią się różnić."],
     "Zysk 10 000 zł ze sprzedaży akcji i strata 4 000 zł na innej pozycji dają podstawę "
     "6 000 zł i podatek 1 140 zł.",
     ["dywidenda", "prowizja-maklerska", "stopa-zwrotu"]),

    # ---------------------------------------------------------- makro
    ("inflacja", "Inflacja",
     "Wzrost ogólnego poziomu cen, zmniejszający siłę nabywczą pieniądza.",
     ["Mierzona najczęściej wskaźnikiem cen konsumpcyjnych. Dla inwestora jest naturalnym "
      "punktem odniesienia: wynik niższy od inflacji oznacza realną stratę, mimo dodatniej "
      "liczby na rachunku.",
      "Inflacja przekłada się na rynek przez stopy procentowe. Wyższa inflacja to zwykle "
      "wyższe stopy, a te obniżają wycenę przyszłych zysków — najmocniej w spółkach, "
      "których zyski są dopiero przed nimi."],
     "Portfel zarobił 4% przy inflacji 6%. Realnie stracił około 2% siły nabywczej.",
     ["cpi", "stopa-procentowa", "benchmark", "stopa-zwrotu"]),

    ("cpi", "CPI — wskaźnik cen konsumpcyjnych",
     "Miara inflacji oparta na koszyku dóbr i usług kupowanych przez gospodarstwa domowe.",
     ["Publikowany co miesiąc, w Polsce przez Główny Urząd Statystyczny. Podaje się go "
      "w ujęciu rocznym (do tego samego miesiąca rok wcześniej) i miesięcznym.",
      "Obok CPI podaje się inflację bazową — z wyłączeniem cen żywności i energii, które "
      "wahają się najmocniej. Banki centralne patrzą przede wszystkim na nią, bo lepiej "
      "opisuje trwały trend cen."],
     "Odczyt CPI na poziomie 3,8% przy prognozie 3,5% to zaskoczenie w górę — rynek "
     "przesuwa wtedy oczekiwania co do obniżek stóp.",
     ["inflacja", "stopa-procentowa", "rpp"]),

    ("stopa-procentowa", "Stopa procentowa",
     "Cena pieniądza w gospodarce, ustalana przez bank centralny.",
     ["Wyższe stopy oznaczają droższy kredyt, wyższe oprocentowanie obligacji i wyższą "
      "poprzeczkę, którą muszą przeskoczyć inwestycje w akcje.",
      "Rynek wycenia nie sam poziom stóp, tylko oczekiwaną ścieżkę ich zmian. Dlatego "
      "decyzja zgodna z oczekiwaniami często nie rusza kursami, a jedno zdanie z "
      "konferencji po niej — owszem."],
     "Podwyżka stóp o 0,25 punktu procentowego zgodna z oczekiwaniami zwykle nie zmienia "
     "notowań. Sygnał, że kolejnych podwyżek będzie więcej, niż sądzono — zmienia.",
     ["rpp", "inflacja", "dlug-netto"]),

    ("rpp", "RPP, EBC, Fed",
     "Organy decydujące o stopach procentowych w Polsce, strefie euro i Stanach Zjednoczonych.",
     ["Rada Polityki Pieniężnej ustala stopy w Polsce i zbiera się zwykle raz w miesiącu. "
      "Europejski Bank Centralny odpowiada za strefę euro, a amerykańska Rezerwa Federalna "
      "za dolara.",
      "Decyzje Fedu mają wpływ globalny, bo przekładają się na kurs dolara i wycenę "
      "aktywów na całym świecie — także na warszawskiej giełdzie."],
     "Posiedzenia tych trzech instytucji to najczęściej najważniejsze pozycje w kalendarzu "
     "makroekonomicznym danego miesiąca.",
     ["stopa-procentowa", "inflacja", "cpi"]),
]

PO_SLUGU = {h[0]: h for h in HASLA}


def adresy() -> list[str]:
    return ["/slownik"] + [f"/slownik/{h[0]}" for h in HASLA]


def _nazwa(slug: str) -> str:
    h = PO_SLUGU.get(slug)
    return h[1] if h else slug


def zbuduj_haslo(slug: str) -> str | None:
    h = PO_SLUGU.get(slug)
    if not h:
        return None
    _, nazwa, krotka, akapity, przyklad, powiazane = h
    sciezka = f"/slownik/{slug}"
    czysta = nazwa.split(" — ")[0].split(",")[0]

    bloki = [
        render.sekcja("Wyjaśnienie", *akapity),
        render.sekcja("Przykład", render.esc(przyklad)),
    ]
    linki = [(f"/slownik/{p}", _nazwa(p).split(" — ")[0]) for p in powiazane
             if p in PO_SLUGU]
    if linki:
        bloki.append(render.sekcja("Powiązane pojęcia",
                                   html_dodatkowy=render.chipsy(linki)))

    bloki.append(render.zacheta(
        f"Zobacz {czysta} na żywo",
        "Portevo pokazuje ten i kilkadziesiąt innych wskaźników przy konkretnych "
        "spółkach — razem z kalendarzem wyników i Twoim portfelem.",
        drugi=("/slownik", "Cały słownik")))
    bloki.append(render.zastrzezenie())

    okruchy = [("/slownik", "Słownik"), ("", czysta)]
    tytul = f"{czysta} — co to jest? Definicja | Portevo"
    opis = f"{krotka} Wyjaśnienie z przykładem, po polsku."

    return render.strona(
        sciezka=sciezka, tytul=tytul[:70], opis=opis,
        h1=f"{czysta} — co to jest?", lead=render.esc(krotka),
        nadtytul="Słownik giełdowy", okruchy=okruchy, bloki=bloki,
        jsonld=[
            {
                "@context": "https://schema.org",
                "@type": "DefinedTerm",
                "name": czysta,
                "description": krotka,
                "url": site.absolute(sciezka),
                "inDefinedTermSet": site.absolute("/slownik") + "#zbior",
                "inLanguage": "pl-PL",
            },
            jsonld.strona(sciezka, tytul, opis),
            jsonld.okruchy(okruchy),
        ],
    )


def zbuduj_spis() -> str:
    grupy = {
        "Wyniki spółek": ["eps", "konsensus-analitykow", "zaskoczenie-wynikami",
                          "raport-kwartalny", "sezon-wynikow", "espi", "guidance"],
        "Wskaźniki": ["cz", "kapitalizacja", "dywidenda", "marza-netto", "ebitda",
                      "roe", "dlug-netto", "cena-docelowa"],
        "Portfel i wynik": ["xirr", "twr", "stopa-zwrotu", "benchmark",
                            "dywersyfikacja", "korelacja", "koncentracja",
                            "zmiennosc", "beta", "obsuniecie"],
        "Instrumenty i rynek": ["etf", "ter", "indeks", "wig20", "gpw", "blue-chip",
                                "plynnosc", "spread", "wolumen", "krotka-sprzedaz"],
        "Koszty i podatki": ["prowizja-maklerska", "podatek-belki"],
        "Makroekonomia": ["inflacja", "cpi", "stopa-procentowa", "rpp"],
    }

    bloki = []
    for tytul, slugi in grupy.items():
        pozycje = []
        for s in slugi:
            h = PO_SLUGU.get(s)
            if h:
                pozycje.append((f"/slownik/{s}", h[1].split(" — ")[0], h[2]))
        bloki.append(render.sekcja(tytul, html_dodatkowy=render.karty(pozycje)))

    bloki.append(render.zacheta(
        "Od definicji do praktyki",
        "Wszystkie te wskaźniki widzisz w Portevo przy konkretnych spółkach — "
        "z porównaniem do mediany branży, żeby liczba miała do czego się odnieść.",
        drugi=("/wyniki-finansowe", "Wyniki spółek")))
    bloki.append(render.zastrzezenie())

    tytul = "Słownik giełdowy — pojęcia inwestycyjne po polsku | Portevo"
    opis = (f"{len(HASLA)} pojęć giełdowych wyjaśnionych po polsku, z przykładami: "
            "EPS, C/Z, EBITDA, XIRR, ETF, dywersyfikacja, korelacja i inne.")
    okruchy = [("", "Słownik")]

    return render.strona(
        sciezka="/slownik", tytul=tytul, opis=opis,
        h1="Słownik pojęć giełdowych",
        lead="Krótkie, uczciwe definicje z przykładem liczbowym. Bez żargonu, którego "
             "nie da się sprawdzić, i bez zdań, które brzmią mądrze, a nic nie znaczą.",
        nadtytul="Wiedza", okruchy=okruchy, szeroki_naglowek=True, bloki=bloki,
        jsonld=[
            jsonld.strona("/slownik", tytul, opis, typ="CollectionPage"),
            jsonld.okruchy(okruchy),
            jsonld.zbior_pojec("/slownik", "Słownik giełdowy Portevo", opis,
                               [(h[0], h[1].split(" — ")[0], h[2]) for h in HASLA]),
        ],
    )
