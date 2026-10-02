"""Słownik wydarzeń makro po polsku — co to jest i co znaczy odczyt powyżej/poniżej prognozy.

Opis ze źródła kalendarza przychodzi po angielsku i mówi wyłącznie o walucie
(„wyższy odczyt jest pozytywny dla USD"). Inwestora w akcje obchodzi co innego:
czy to dobrze, czy źle dla giełdy — a tu odpowiedź bywa odwrotna niż dla waluty
(gorąca inflacja umacnia dolara i jednocześnie przecenia akcje).

Wpisy są pisane ręcznie i celowo ostrożne: „zwykle", „często". Rynek reaguje na
kontekst, nie na regułę — mocne dane z rynku pracy raz cieszą (gospodarka trzyma
się dobrze), raz straszą (Fed nie obniży stóp). Twarde liczby o tym, jak bywało,
liczy `impact.history`.

`stocks`: +1 = odczyt powyżej prognozy zwykle sprzyja akcjom, −1 = zwykle szkodzi,
0 = zależy od kontekstu albo nie ma liczby do porównania.
"""

import re

_INFLATION_HIGHER = ("Inflacja wyższa od prognozy oddala obniżki stóp (albo przybliża podwyżki). "
                     "Rentowności obligacji rosną, a akcje — zwłaszcza spółki wzrostowe "
                     "i technologiczne — zwykle tanieją.")
_INFLATION_LOWER = ("Inflacja niższa od prognozy daje bankowi centralnemu pole do obniżek stóp. "
                    "Zwykle rosną akcje i obligacje, najmocniej Nasdaq.")

_ENTRIES = [
    (r"interest rate decision|rate decision|reference rate", {
        "title": "Decyzja o stopach procentowych",
        "what": "Bank centralny ogłasza, ile kosztuje pieniądz: po jakiej stopie pożyczają "
                "sobie banki, a w ślad za tym — ile kosztują kredyty i ile dają lokaty.",
        "why": "To najważniejsza pojedyncza zmienna dla wycen. Niższe stopy podnoszą wartość "
               "przyszłych zysków spółek i zachęcają do ryzyka, wyższe robią odwrotnie. "
               "Sama decyzja jest zwykle znana z wyprzedzeniem — rynek rusza się na "
               "niespodziance i na tym, co bank zapowie na kolejne miesiące.",
        "higher": "Stopa wyższa od oczekiwań (podwyżka, której rynek nie wyceniał, albo brak "
                  "spodziewanej obniżki) zwykle uderza w akcje i umacnia walutę.",
        "lower": "Stopa niższa od oczekiwań (większe cięcie) zwykle podbija akcje i osłabia "
                 "walutę — chyba że rynek odczyta to jako sygnał, że bank boi się recesji.",
        "stocks": -1,
    }),
    (r"fomc press conference|press conference", {
        "title": "Konferencja prasowa po decyzji",
        "what": "Szef banku centralnego tłumaczy decyzję i odpowiada na pytania dziennikarzy. "
                "W przypadku Fed zaczyna się pół godziny po komunikacie.",
        "why": "Decyzja jest zwykle zgodna z oczekiwaniami, więc to tu pada prawdziwa "
               "informacja: jak bank ocenia inflację i rynek pracy oraz czy szykuje kolejne "
               "ruchy. Rynek potrafi zawrócić o 180 stopni w trakcie jednej odpowiedzi.",
        "higher": "Ton jastrzębi (nacisk na inflację, niechęć do obniżek) zwykle ciąży akcjom.",
        "lower": "Ton gołębi (gotowość do obniżek, obawy o rynek pracy) zwykle im pomaga.",
        "stocks": 0,
    }),
    (r"fomc statement|monetary policy statement|rate statement", {
        "title": "Komunikat po posiedzeniu",
        "what": "Krótki dokument publikowany razem z decyzją o stopach. Opisuje, jak bank "
                "widzi gospodarkę, i podaje wynik głosowania.",
        "why": "Inwestorzy porównują go słowo po słowie z poprzednim. Zmiana jednego "
               "sformułowania o inflacji albo ryzykach bywa ważniejsza niż sama decyzja.",
        "higher": "Zaostrzenie języka wobec inflacji zwykle szkodzi akcjom.",
        "lower": "Złagodzenie języka zwykle im sprzyja.",
        "stocks": 0,
    }),
    (r"fomc minutes|minutes", {
        "title": "Protokół z posiedzenia",
        "what": "Zapis dyskusji z posiedzenia sprzed około trzech tygodni: kto czego się "
                "obawiał i jak rozkładały się głosy.",
        "why": "Pokazuje, jak bardzo podzielony jest bank i w którą stronę przesuwa się "
               "większość. Jest spóźniony, więc rusza rynkiem tylko wtedy, gdy ujawnia coś, "
               "czego nie było na konferencji.",
        "higher": "", "lower": "", "stocks": 0,
    }),
    (r"fomc economic projections|interest rate projections", {
        "title": "Projekcje gospodarcze FOMC",
        "what": "Publikowane cztery razy w roku prognozy członków Fed: wzrost, bezrobocie, "
                "inflacja i — najważniejsze — „wykres kropek”, czyli gdzie każdy z nich widzi "
                "stopy za rok i dwa.",
        "why": "Kropki mówią wprost, ile obniżek lub podwyżek planuje Fed. Rynek porównuje je "
               "z własną wyceną i koryguje kursy, gdy się rozjeżdżają.",
        "higher": "Mniej obniżek w kropkach, niż wyceniał rynek — zwykle źle dla akcji.",
        "lower": "Więcej obniżek — zwykle dobrze.",
        "stocks": 0,
    }),
    (r"beige book", {
        "title": "Beżowa Księga",
        "what": "Raport Fed z opisem koniunktury w dwunastu okręgach, zbierany z rozmów "
                "z firmami. Wychodzi dwa tygodnie przed posiedzeniem.",
        "why": "Nie ma w nim liczb, ale to materiał, z którym członkowie Fed idą na "
               "posiedzenie. Rzadko rusza rynkiem.",
        "higher": "", "lower": "", "stocks": 0,
    }),
    (r"speech|testifies|fomc member", {
        "title": "Wystąpienie bankiera centralnego",
        "what": "Publiczne wystąpienie członka władz banku centralnego — przemówienie, "
                "panel albo przesłuchanie w parlamencie.",
        "why": "Bankierzy używają wystąpień, żeby przygotować rynek na przyszłe decyzje. "
               "Liczy się, kto mówi: szef banku i osoby z prawem głosu ważą więcej. "
               "Większość wystąpień przechodzi bez echa.",
        "higher": "Zapowiedź wyższych stóp na dłużej zwykle ciąży akcjom.",
        "lower": "Zapowiedź obniżek zwykle im pomaga.",
        "stocks": 0,
    }),
    (r"consumer confidence|consumer sentiment|michigan|\buom\b", {
        "title": "Nastroje konsumentów",
        "what": "Ankieta wśród gospodarstw domowych: jak oceniają swoją sytuację i czego "
                "spodziewają się po gospodarce. Badanie Uniwersytetu Michigan pyta też "
                "o oczekiwaną inflację.",
        "why": "Nastroje wyprzedzają wydatki. Oczekiwania inflacyjne z tej ankiety obserwuje Fed.",
        "higher": "Lepsze nastroje zapowiadają mocniejszą konsumpcję — lekko pozytywne dla akcji.",
        "lower": "Gorsze nastroje — lekko negatywne.",
        "stocks": 1,
    }),
    (r"jolts|job openings|job cuts|participation rate|underemployment", {
        "title": "Rynek pracy — dane uzupełniające",
        "what": "Liczba wolnych etatów (JOLTS), zapowiedziane zwolnienia (Challenger) albo "
                "odsetek ludzi aktywnych zawodowo. Dopełniają główny raport o zatrudnieniu.",
        "why": "Pokazują, czy firmy wciąż szukają ludzi. Dużo wakatów przy małej liczbie "
               "bezrobotnych oznacza presję na płace, a więc i na inflację.",
        "higher": "Więcej wakatów, niż oczekiwano: rynek pracy jest napięty — Fed ma mniej "
                  "powodów do obniżek.",
        "lower": "Mniej wakatów: rynek pracy stygnie, rosną szanse na obniżki stóp.",
        "stocks": 0,
    }),
    (r"core pce|personal consumption expenditures", {
        "title": "Inflacja PCE",
        "what": "Wskaźnik cen liczony z wydatków konsumentów. Wersja bazowa pomija żywność "
                "i energię.",
        "why": "To ulubiona miara inflacji Fed — właśnie do niej odnosi się cel 2%. Wychodzi "
               "po CPI, więc rzadko zaskakuje, ale to ona stoi w projekcjach Fed.",
        "higher": _INFLATION_HIGHER, "lower": _INFLATION_LOWER, "stocks": -1,
    }),
    (r"producer price index", {
        "title": "Inflacja producencka (PPI)",
        "what": "Zmiana cen, po jakich producenci sprzedają towary i usługi — inflacja "
                "„u źródła”, zanim dotrze na półki.",
        "why": "Wyprzedza inflację konsumencką i mówi o marżach firm: gdy koszty rosną "
               "szybciej niż ceny w sklepach, cierpią zyski.",
        "higher": _INFLATION_HIGHER, "lower": _INFLATION_LOWER, "stocks": -1,
    }),
    (r"consumer price index|harmonized index of consumer prices|inflation", {
        "title": "Inflacja konsumencka (CPI)",
        "what": "Zmiana cen koszyka towarów i usług kupowanych przez gospodarstwa domowe. "
                "Wersja bazowa pomija żywność i energię, których ceny skaczą najmocniej.",
        "why": "Najważniejszy odczyt miesiąca. Od inflacji zależy, co bank centralny zrobi "
               "ze stopami, a od stóp — wyceny wszystkiego innego.",
        "higher": _INFLATION_HIGHER, "lower": _INFLATION_LOWER, "stocks": -1,
    }),
    (r"nonfarm payrolls|adp employment|employment change|net change in employment", {
        "title": "Zmiana zatrudnienia",
        "what": "Ile etatów przybyło lub ubyło w gospodarce w ciągu miesiąca. W USA raport "
                "rządowy (NFP) wychodzi w pierwszy piątek miesiąca; ADP to jego prywatna "
                "zapowiedź dwa dni wcześniej.",
        "why": "Rynek pracy to druga, obok inflacji, rzecz, na którą patrzy Fed. Odczyt "
               "czyta się dwojako, zależnie od tego, czego rynek akurat się boi.",
        "higher": "Więcej etatów, niż oczekiwano: gospodarka jest mocna, ale Fed ma mniej "
                  "powodów do obniżek. Gdy rynek boi się inflacji — akcje spadają; gdy boi "
                  "się recesji — rosną.",
        "lower": "Mniej etatów: rosną szanse na obniżki stóp, co zwykle pomaga akcjom. "
                 "Bardzo słaby odczyt budzi jednak strach przed recesją i ciągnie je w dół.",
        "stocks": 0,
    }),
    (r"unemployment rate|unemployment", {
        "title": "Stopa bezrobocia",
        "what": "Odsetek osób aktywnych zawodowo, które szukają pracy i jej nie mają.",
        "why": "Fed ma dwa cele: stabilne ceny i pełne zatrudnienie. Rosnące bezrobocie "
               "popycha go do obniżek, ale jest też klasycznym zwiastunem recesji.",
        "higher": "Bezrobocie wyższe od prognozy zwiększa szanse na obniżki stóp, lecz "
                  "wyraźny skok rynek czyta jako ostrzeżenie przed recesją — akcje zwykle tracą.",
        "lower": "Bezrobocie niższe od prognozy potwierdza siłę gospodarki; dla akcji to "
                 "zwykle dobra wiadomość, o ile inflacja jest pod kontrolą.",
        "stocks": 0,
    }),
    (r"jobless claims", {
        "title": "Wnioski o zasiłek dla bezrobotnych",
        "what": "Liczba osób, które w minionym tygodniu po raz pierwszy zgłosiły się po "
                "zasiłek (wnioski nowe) albo nadal go pobierają (kontynuowane).",
        "why": "Najszybszy termometr rynku pracy — wychodzi co czwartek. Pojedynczy tydzień "
               "bywa zaszumiony, liczy się kierunek z kilku tygodni.",
        "higher": "Więcej wniosków, niż oczekiwano: rynek pracy słabnie. Rosną szanse na "
                  "obniżki stóp, ale i obawy o koniunkturę.",
        "lower": "Mniej wniosków: zwolnień jest mało, gospodarka trzyma się dobrze.",
        "stocks": 0,
    }),
    (r"average hourly earnings|wages|employment cost|unit labor costs", {
        "title": "Wynagrodzenia",
        "what": "Tempo wzrostu płac.",
        "why": "Płace to koszt firm i paliwo dla inflacji usług. Szybki wzrost wynagrodzeń "
               "utrudnia bankowi centralnemu obniżanie stóp.",
        "higher": "Płace rosnące szybciej od prognozy podnoszą obawy o inflację — zwykle źle "
                  "dla akcji i obligacji.",
        "lower": "Wolniejszy wzrost płac uspokaja obawy o inflację.",
        "stocks": -1,
    }),
    (r"gross domestic product", {
        "title": "PKB",
        "what": "Wartość wszystkiego, co gospodarka wytworzyła w kwartale. W USA podawana "
                "jako tempo kwartalne przeliczone na cały rok (annualizowane).",
        "why": "Najszersza miara koniunktury, ale spóźniona — opisuje kwartał, który już "
               "minął. Rynek zna ją w przybliżeniu z danych miesięcznych, więc rusza się "
               "tylko przy dużej niespodziance.",
        "higher": "Wzrost szybszy od prognozy: firmy sprzedają więcej, zyski rosną — zwykle "
                  "dobrze dla akcji, o ile nie podbija to obaw o inflację.",
        "lower": "Wzrost wolniejszy: słabsze zyski i ryzyko recesji — zwykle źle dla akcji.",
        "stocks": 1,
    }),
    (r"retail sales|retail trade|personal spending|personal income", {
        "title": "Sprzedaż detaliczna",
        "what": "Wartość sprzedaży w sklepach, restauracjach i internecie w ciągu miesiąca.",
        "why": "Konsumpcja to około dwóch trzecich amerykańskiej gospodarki. Ten odczyt mówi, "
               "czy ludzie wciąż wydają — a więc o przychodach większości spółek.",
        "higher": "Sprzedaż mocniejsza od prognozy: konsument ma się dobrze — zwykle dobrze "
                  "dla akcji, szczególnie handlu i dóbr konsumpcyjnych.",
        "lower": "Słabsza sprzedaż: konsument zaciska pasa — zwykle źle dla akcji.",
        "stocks": 1,
    }),
    (r"\bpmi\b|\bism\b|manufacturing (survey|index)", {
        "title": "Indeks PMI / ISM",
        "what": "Ankieta wśród menedżerów zakupów: czy zamówienia, produkcja i zatrudnienie "
                "w ich firmach rosną, czy maleją. Powyżej 50 punktów — sektor się rozwija, "
                "poniżej — kurczy.",
        "why": "Wychodzi na początku miesiąca, przed twardymi danymi, więc jako pierwszy "
               "pokazuje zwrot w koniunkturze. Składowa cen bywa czytana jak zapowiedź inflacji.",
        "higher": "Odczyt powyżej prognozy: firmy widzą więcej zamówień — zwykle dobrze dla "
                  "akcji, zwłaszcza przemysłu.",
        "lower": "Odczyt poniżej prognozy, a tym bardziej zejście pod 50: spowolnienie — "
                 "zwykle źle dla akcji.",
        "stocks": 1,
    }),
    (r"industrial production|industrial output|factory orders|durable goods", {
        "title": "Przemysł: produkcja i zamówienia",
        "what": "Ile wytworzyły fabryki, kopalnie i elektrownie (produkcja) albo ile zamówień "
                "spłynęło do producentów (zamówienia na dobra trwałe, zamówienia w przemyśle).",
        "why": "Zamówienia mówią o planach inwestycyjnych firm — to wskaźnik wyprzedzający. "
               "Odczyty bywają rozchwiane przez pojedyncze duże kontrakty, np. na samoloty.",
        "higher": "Odczyt powyżej prognozy: firmy inwestują — zwykle dobrze dla akcji.",
        "lower": "Odczyt poniżej prognozy: firmy wstrzymują wydatki — zwykle źle.",
        "stocks": 1,
    }),
    (r"housing starts|building permits|home sales|house price|housing price", {
        "title": "Rynek nieruchomości",
        "what": "Pozwolenia na budowę, rozpoczęte budowy, sprzedaż domów albo ich ceny.",
        "why": "Budownictwo najszybciej reaguje na zmiany stóp procentowych, więc jest "
               "wczesnym sygnałem, czy polityka banku centralnego już hamuje gospodarkę.",
        "higher": "Mocniejszy odczyt: popyt trzyma się mimo kosztu kredytu — dobrze dla "
                  "deweloperów i banków.",
        "lower": "Słabszy odczyt: drogi kredyt dusi popyt.",
        "stocks": 1,
    }),
    (r"trade balance|current account", {
        "title": "Bilans handlowy",
        "what": "Różnica między eksportem a importem (bilans handlowy) albo szerzej — "
                "wszystkimi przepływami z zagranicą (rachunek bieżący).",
        "why": "Wpływa głównie na walutę i na wyliczenie PKB. Giełda zwykle nie reaguje.",
        "higher": "Wyższe saldo (mniejszy deficyt) lekko wspiera walutę.",
        "lower": "Niższe saldo lekko ją osłabia.",
        "stocks": 0,
    }),
    (r"crude oil|eia", {
        "title": "Zapasy ropy",
        "what": "Tygodniowa zmiana zapasów ropy naftowej w USA.",
        "why": "Rusza ceną ropy, a przez nią spółkami paliwowymi i oczekiwaniami inflacyjnymi.",
        "higher": "Zapasy wyższe od prognozy: ropy jest dużo — cena zwykle spada.",
        "lower": "Zapasy niższe: podaż jest napięta — cena zwykle rośnie.",
        "stocks": 0,
    }),
    (r"money supply|fx reserves|budget balance", {
        "title": "Dane monetarne i budżetowe",
        "what": "Podaż pieniądza, rezerwy walutowe banku centralnego albo wynik budżetu państwa.",
        "why": "Dane tła — ważne dla ekonomistów, giełda zwykle ich nie zauważa.",
        "higher": "", "lower": "", "stocks": 0,
    }),
    (r"holiday", {
        "title": "Dzień wolny",
        "what": "Giełda w tym kraju jest zamknięta albo pracuje krócej.",
        "why": "Mniejsze obroty na świecie i brak notowań lokalnych spółek. Zlecenia złożone "
               "tego dnia zrealizują się dopiero na następnej sesji.",
        "higher": "", "lower": "", "stocks": 0,
    }),
]

_COMPILED = [(re.compile(rx, re.I), entry) for rx, entry in _ENTRIES]


def lookup(name: str) -> dict | None:
    """Wpis słownika dla angielskiej nazwy wydarzenia z kalendarza albo None."""
    for rx, entry in _COMPILED:
        if rx.search(name or ""):
            return entry
    return None


def annotate(event: dict) -> dict:
    """Dopisuje do wydarzenia ocenę odczytu Z PUNKTU WIDZENIA AKCJI.

    Źródło kalendarza ma własne pole „lepiej niż oczekiwano", ale liczone dla
    waluty: gorąca inflacja jest tam „lepsza", bo umacnia dolara. Kolorowanie
    takiego odczytu na zielono w aplikacji dla inwestorów giełdowych byłoby mylące.

    `verdict`: good / bad — odczyt zwykle sprzyja / szkodzi akcjom; neutral — różni
    się od prognozy, ale kierunek zależy od kontekstu; flat — równo z prognozą;
    None — nie ma czego porównać. Liczone przy każdej odpowiedzi, nie w cache —
    dzięki temu poprawka w słowniku działa od razu także dla starych dni.
    """
    entry = lookup(event.get("name") or "")
    stocks = (entry or {}).get("stocks", 0)
    actual, consensus = event.get("actual"), event.get("consensus")
    verdict = None
    side = None
    if actual is not None and consensus is not None:
        diff = actual - consensus
        if abs(diff) < 1e-9:
            verdict, side = "flat", "inline"
        else:
            side = "above" if diff > 0 else "below"
            if stocks == 0:
                verdict = "neutral"
            else:
                verdict = "good" if (diff > 0) == (stocks > 0) else "bad"
    event["stocks"] = stocks
    event["verdict"] = verdict
    event["side"] = side
    return event
