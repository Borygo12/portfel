"""Podstrony sektorowe — wyniki spółek zebrane w branże.

Po co, skoro jest już spis A–Z i 266 podstron pojedynczych spółek: ludzie
szukają hasłami „wyniki spółek technologicznych”, „kiedy banki publikują
wyniki”, „raporty spółek energetycznych”. Na takie zapytanie strona
z pojedynczą spółką nie odpowiada, a spis A–Z odpowiada za słabo — to lista
bez tezy. Strona sektorowa jest dokładnie na miarę pytania: mówi, czego szukać
w raportach TEJ branży, i pokazuje wszystkie jej spółki naraz.

Drugi powód jest strukturalny. Katalog ma 266 podstron podpiętych dziś tylko
pod jeden spis. Warstwa sektorów wkłada między nie stronę pośrednią, dzięki
czemu każda spółka jest oddalona od strony głównej o dwa kliknięcia, a nie
o zanurzenie w liście dwustu sześćdziesięciu odnośników — i tak samo widzi to
robot rozdzielający „moc” linków.

Treść każdej branży jest pisana ręcznie i CELOWO nie jest wymienna: opis
„spółki z tego sektora publikują raporty kwartalne” dałby jedenaście
bliźniaczych stron, czyli jedenaście powodów, żeby Google uznał je za
wypełniacz. To, co odróżnia raport banku od raportu producenta leków, jest
wiedzą wartą zapisania — i tylko taka strona ma prawo istnieć.
"""

from __future__ import annotations

import datetime as dt

from . import companies, dates, jsonld, logos, render, upcoming

PREFIKS = "/wyniki-finansowe/sektor/"

#: slug → opis branży. `sektor_pl` musi zgadzać się z wartością z `companies.json`,
#: bo to po niej dobierane są spółki.
SEKTORY = {

    "technologia": {
        "sektor_pl": "technologia",
        "h1": "Wyniki spółek technologicznych — terminy i prognozy",
        "tytul": "Wyniki spółek technologicznych — kalendarz | Portevo",
        "opis": "Kiedy spółki technologiczne publikują wyniki kwartalne. Terminy "
                "raportów, prognozy analityków i reakcje kursu — Nasdaq, NYSE i GPW, "
                "po polsku.",
        "lead": "Producenci półprzewodników, twórcy oprogramowania i dostawcy chmury "
                "raportują pierwsi w sezonie i najmocniej ruszają indeksami. Tu masz "
                "ich terminy, konsensus analityków i historię reakcji kursu.",
        "akapity": [
            "Technologia jest sektorem, w którym <strong>sama wysokość zysku znaczy "
            "najmniej</strong>. Kursy reagują na prognozę na kolejny kwartał, "
            "na tempo wzrostu przychodów z powtarzalnych usług i na wydatki "
            "inwestycyjne — bo to one mówią, czy spółka wierzy w popyt, o którym "
            "opowiada na konferencji wynikowej.",
            "Druga cecha to zależności w łańcuchu. Raport jednego producenta układów "
            "potrafi przestawić kurs kilkunastu spółek, które dopiero będą raportować, "
            "bo mówi coś o popycie w całej branży. Dlatego w tej sekcji opłaca się "
            "patrzeć na terminy sąsiadów, a nie tylko na jedną spółkę.",
        ],
        "lista": [
            "<b>Prognoza na kolejny kwartał</b> — w technologii przebicie konsensusu "
            "przy słabej prognozie kończy się spadkiem częściej niż wzrostem.",
            "<b>Marża brutto</b> — pokazuje, czy spółka podnosi ceny, czy kupuje "
            "wzrost rabatami.",
            "<b>Wydatki inwestycyjne</b> — rosnące nakłady na serwery i fabryki "
            "przekładają się na wynik dopiero za kilka kwartałów.",
        ],
    },

    "finanse": {
        "sektor_pl": "finanse",
        "h1": "Wyniki banków i spółek finansowych — kalendarz raportów",
        "tytul": "Wyniki banków — terminy raportów kwartalnych | Portevo",
        "opis": "Kiedy banki i spółki finansowe publikują wyniki kwartalne. Terminy, "
                "prognozy analityków i historia reakcji kursu — GPW i giełdy "
                "amerykańskie.",
        "lead": "Banki otwierają sezon wyników po obu stronach Atlantyku i są "
                "pierwszym sygnałem o kondycji gospodarki: widzą spłacalność kredytów "
                "wcześniej niż ktokolwiek inny.",
        "akapity": [
            "Wynik banku rządzi się własnymi prawami. Najważniejsze liczby to "
            "<strong>wynik odsetkowy</strong> — czyli różnica między tym, ile bank "
            "zarabia na kredytach, a ile płaci za depozyty — oraz "
            "<strong>odpisy na złe kredyty</strong>. Rosnące odpisy potrafią "
            "skasować dobry kwartał, nawet gdy przychody biją prognozy.",
            "W polskich bankach dochodzi trzeci element, którego nie ma w USA: koszty "
            "ryzyka prawnego kredytów walutowych. To pozycja jednorazowa z nazwy, "
            "a powtarzalna w praktyce — i warto sprawdzić, czy konsensus analityków "
            "w ogóle ją uwzględnia.",
        ],
        "lista": [
            "<b>Wynik odsetkowy netto</b> — reaguje na decyzje banku centralnego "
            "z kilkumiesięcznym opóźnieniem.",
            "<b>Koszty ryzyka</b> — pierwsze miejsce, w którym widać pogorszenie "
            "sytuacji gospodarstw domowych i firm.",
            "<b>Współczynnik wypłacalności</b> — od niego zależy, czy będzie "
            "dywidenda.",
        ],
    },

    "ochrona-zdrowia": {
        "sektor_pl": "ochrona zdrowia",
        "h1": "Wyniki spółek z sektora ochrony zdrowia",
        "tytul": "Wyniki spółek medycznych i farmaceutycznych | Portevo",
        "opis": "Terminy publikacji wyników spółek farmaceutycznych, biotechnologicznych "
                "i medycznych. Prognozy analityków i reakcje kursu — po polsku.",
        "lead": "Farmacja, biotechnologia i sprzęt medyczny — branża, w której raport "
                "kwartalny bywa mniej ważny niż jedno zdanie o wynikach badania "
                "klinicznego.",
        "akapity": [
            "To jedyny sektor, w którym <strong>kurs potrafi zignorować wynik "
            "finansowy w całości</strong>. Dla dużej firmy farmaceutycznej liczy się "
            "termin wygaśnięcia ochrony patentowej najlepiej sprzedającego się leku "
            "i to, czym zamierza go zastąpić. Dla mniejszej biotechnologii — wynik "
            "badania i decyzja urzędu rejestracyjnego.",
            "Stąd praktyczny wniosek: przy spółkach z tej branży historia reakcji "
            "kursu po wynikach mówi mniej niż zwykle, bo część największych ruchów "
            "wydarzyła się w dni bez raportu. Warto patrzeć na obie rzeczy naraz.",
        ],
        "lista": [
            "<b>Sprzedaż kluczowego leku</b> — zwykle jedna pozycja odpowiada za "
            "większość zysku.",
            "<b>Prognoza roczna</b> — jej podniesienie albo obcięcie porusza kursem "
            "mocniej niż sam kwartał.",
            "<b>Wydatki na badania</b> — koszt dziś, jedyne źródło przychodów za "
            "kilka lat.",
        ],
    },

    "handel-i-dobra-konsumpcyjne": {
        "sektor_pl": "handel i dobra konsumpcyjne",
        "h1": "Wyniki spółek handlowych i konsumenckich",
        "tytul": "Wyniki spółek handlowych — terminy raportów | Portevo",
        "opis": "Kiedy sieci handlowe, producenci odzieży i spółki konsumenckie "
                "publikują wyniki. Terminy, prognozy analityków i reakcje kursu.",
        "lead": "Sieci handlowe, moda, motoryzacja i rozrywka — spółki, których wyniki "
                "są najkrótszą drogą do odpowiedzi, jak naprawdę wygląda portfel "
                "przeciętnego konsumenta.",
        "akapity": [
            "W handlu liczy się <strong>sprzedaż porównywalna</strong> — wzrost "
            "w sklepach działających od ponad roku. Firma może pokazać rosnące "
            "przychody, otwierając nowe punkty, i jednocześnie tracić klientów "
            "w starych; dopiero ta jedna liczba to rozdziela.",
            "Druga rzecz to sezonowość. Czwarty kwartał odpowiada u wielu spółek za "
            "większość rocznego zysku, więc porównywanie go z trzecim nie ma sensu — "
            "porównuje się rok do roku, i tak liczone są też prognozy analityków "
            "w naszym kalendarzu.",
        ],
        "lista": [
            "<b>Sprzedaż porównywalna</b> — odsiewa wzrost wynikający z samego "
            "otwierania sklepów.",
            "<b>Marża brutto</b> — spada, gdy firma musi wyprzedawać zapasy "
            "z rabatem.",
            "<b>Zapasy</b> — rosnące szybciej niż sprzedaż zapowiadają przeceny "
            "w kolejnym kwartale.",
        ],
    },

    "przemysl": {
        "sektor_pl": "przemysł",
        "h1": "Wyniki spółek przemysłowych — terminy raportów",
        "tytul": "Wyniki spółek przemysłowych — kalendarz | Portevo",
        "opis": "Terminy publikacji wyników spółek przemysłowych, budowlanych "
                "i transportowych. Prognozy analityków i historia reakcji kursu.",
        "lead": "Producenci maszyn, budownictwo, transport i zbrojeniówka — branża, "
                "w której o przyszłym zysku mówi portfel zamówień, a nie kwartał, "
                "który właśnie się skończył.",
        "akapity": [
            "Raport spółki przemysłowej czyta się od końca: najpierw "
            "<strong>portfel zamówień</strong> i nowe kontrakty, potem dopiero zysk. "
            "Produkcja rozliczana jest miesiącami, więc dzisiejszy wynik pochodzi "
            "z zamówień sprzed roku, a dzisiejsze zamówienia zobaczysz w wyniku "
            "za kilka kwartałów.",
            "Drugi element to koszty materiałów i energii. Spółka, która sprzedaje "
            "po cenach z kontraktu podpisanego przed podwyżkami, oddaje całą "
            "różnicę z marży — i to jest typowy powód, dla którego dobre przychody "
            "idą w parze z rozczarowującym zyskiem.",
        ],
        "lista": [
            "<b>Portfel zamówień</b> — najlepszy dostępny wyprzedzający sygnał "
            "przychodów.",
            "<b>Marża operacyjna</b> — pokazuje, czy firma umie przenieść wzrost "
            "kosztów na klienta.",
            "<b>Wykorzystanie mocy produkcyjnych</b> — poniżej pewnego progu każdy "
            "kontrakt jest na granicy opłacalności.",
        ],
    },

    "media-i-telekomunikacja": {
        "sektor_pl": "media i telekomunikacja",
        "h1": "Wyniki spółek medialnych i telekomunikacyjnych",
        "tytul": "Wyniki spółek medialnych i telekomów | Portevo",
        "opis": "Kiedy telekomy, platformy streamingowe i spółki medialne publikują "
                "wyniki kwartalne. Terminy, prognozy i reakcje kursu — po polsku.",
        "lead": "Operatorzy komórkowi, platformy wideo, gry i reklama internetowa — "
                "spółki rozliczane z liczby klientów równie surowo jak z zysku.",
        "akapity": [
            "W tej branży rynek patrzy najpierw na <strong>liczbę abonentów "
            "i przychód na klienta</strong>. Platforma, która dołożyła miliony "
            "użytkowników, ale zarabia na każdym mniej niż kwartał wcześniej, "
            "zwykle traci na kursie mimo świetnych przychodów.",
            "U telekomów dochodzi ciężar inwestycji w sieć: zysk księgowy bywa "
            "niski, bo pochłania go amortyzacja, a to, ile firma naprawdę zarabia, "
            "widać dopiero w przepływach pieniężnych. Przy spółkach growych z GPW "
            "obowiązuje jeszcze jedna zasada — wynik kwartału zależy od terminu "
            "premiery, więc porównywanie kwartał do kwartału nie ma sensu.",
        ],
        "lista": [
            "<b>Liczba klientów i odejścia</b> — pierwsza liczba, którą sprawdza rynek.",
            "<b>Przychód na użytkownika</b> — mówi, czy wzrost jest opłacalny.",
            "<b>Harmonogram premier</b> — u producentów gier decyduje o całym roku.",
        ],
    },

    "dobra-podstawowe": {
        "sektor_pl": "dobra podstawowe",
        "h1": "Wyniki spółek z sektora dóbr podstawowych",
        "tytul": "Wyniki spółek spożywczych i FMCG | Portevo",
        "opis": "Terminy raportów spółek spożywczych, handlu detalicznego i produktów "
                "codziennego użytku. Prognozy analityków i reakcje kursu.",
        "lead": "Żywność, chemia gospodarcza, sieci spożywcze — najbardziej "
                "przewidywalna część giełdy, w której zaskoczeniem bywa sam brak "
                "zaskoczenia.",
        "akapity": [
            "Spółki sprzedające rzeczy kupowane co tydzień mają stabilny popyt, więc "
            "gra toczy się o <strong>marżę</strong>: czy firma zdołała podnieść ceny "
            "szybciej, niż drożały surowce. W raportach tego sektora warto szukać "
            "rozbicia wzrostu sprzedaży na część cenową i wolumenową — rosnąca "
            "sprzedaż przy spadającym wolumenie oznacza, że klienci już zaczęli "
            "wybierać tańsze zamienniki.",
            "To także branża dywidendowa. Dla części inwestorów raport kwartalny jest "
            "tu tylko sprawdzeniem, czy wypłata jest bezpieczna — i dlatego reakcje "
            "kursu po wynikach są zwykle łagodniejsze niż w technologii.",
        ],
        "lista": [
            "<b>Wolumen a cena</b> — rozbicie wzrostu sprzedaży mówi wszystko "
            "o sile marki.",
            "<b>Marża brutto</b> — reaguje na ceny surowców rolnych i kurs walut.",
            "<b>Przepływy pieniężne</b> — z nich wypłacana jest dywidenda.",
        ],
    },

    "surowce-i-materialy": {
        "sektor_pl": "surowce i materiały",
        "h1": "Wyniki spółek surowcowych i materiałowych",
        "tytul": "Wyniki spółek surowcowych — terminy raportów | Portevo",
        "opis": "Kiedy spółki wydobywcze, chemiczne i hutnicze publikują wyniki. "
                "Terminy raportów, prognozy analityków i historia reakcji kursu.",
        "lead": "Kopalnie, huty i chemia — spółki, których wynik jest w dużej mierze "
                "funkcją ceny towaru na światowym rynku i kursu dolara.",
        "akapity": [
            "Przy spółce surowcowej <strong>notowania miedzi, węgla czy nawozów "
            "zdradzają wynik kwartału na długo przed jego publikacją</strong>. "
            "Dlatego zaskoczeniem bywa nie sam zysk, tylko koszt wydobycia, "
            "odpisy z tytułu utraty wartości aktywów albo obciążenia podatkowe.",
            "Druga rzecz to waluta. Spółka sprzedająca w dolarach i płacąca "
            "w złotych ma wynik, którym rusza kurs walutowy — czasem mocniej niż "
            "sama produkcja.",
        ],
        "lista": [
            "<b>Koszt wydobycia na jednostkę</b> — jedyna część wyniku, na którą "
            "spółka naprawdę ma wpływ.",
            "<b>Odpisy aktualizujące</b> — potrafią zamienić dobry kwartał w stratę "
            "księgową.",
            "<b>Ekspozycja walutowa</b> — przychody w dolarach przy kosztach "
            "w złotych.",
        ],
    },

    "energetyka": {
        "sektor_pl": "energetyka i media komunalne",
        "h1": "Wyniki spółek energetycznych i użyteczności publicznej",
        "tytul": "Wyniki spółek energetycznych — kalendarz | Portevo",
        "opis": "Terminy publikacji wyników spółek energetycznych i dystrybucyjnych. "
                "Prognozy analityków, historia zaskoczeń i reakcje kursu.",
        "lead": "Wytwarzanie i dystrybucja energii — biznes regulowany, w którym "
                "decyzja urzędu potrafi znaczyć dla wyniku więcej niż popyt.",
        "akapity": [
            "Wynik spółki energetycznej rozkłada się na dwie zupełnie różne części: "
            "<strong>regulowaną dystrybucję</strong> o przewidywalnej marży "
            "i <strong>wytwarzanie</strong>, które zależy od cen energii i uprawnień "
            "do emisji. Zysk łączny bywa więc średnią z części spokojnej i bardzo "
            "zmiennej — i dopiero rozbicie na segmenty pokazuje, co się właściwie "
            "wydarzyło.",
            "W polskiej energetyce dochodzą inwestycje w moce i przekształcenia "
            "aktywów węglowych, które przez lata będą pochłaniać gotówkę. To zwykle "
            "ważniejsza informacja z raportu niż sam zysk kwartału.",
        ],
        "lista": [
            "<b>Wynik segmentów</b> — dystrybucja i wytwarzanie żyją w innych "
            "światach.",
            "<b>Nakłady inwestycyjne</b> — decydują o dywidendzie i zadłużeniu.",
            "<b>Koszty uprawnień do emisji</b> — pozycja, która potrafi zjeść marżę "
            "wytwarzania.",
        ],
    },

    "nieruchomosci": {
        "sektor_pl": "nieruchomości",
        "h1": "Wyniki spółek z branży nieruchomości",
        "tytul": "Wyniki spółek nieruchomościowych i REIT | Portevo",
        "opis": "Terminy raportów deweloperów i funduszy nieruchomości. Prognozy "
                "analityków, historia zaskoczeń i reakcje kursu — po polsku.",
        "lead": "Deweloperzy i fundusze wynajmu — sektor, w którym zysk księgowy "
                "i gotówka w kasie rozjeżdżają się bardziej niż gdziekolwiek indziej.",
        "akapity": [
            "U dewelopera przychód pojawia się dopiero przy przekazaniu lokali, "
            "więc <strong>kwartał bez odbiorów wygląda na katastrofalny, choć "
            "sprzedaż mieszkań mogła być rekordowa</strong>. Właściwym wyprzedzającym "
            "wskaźnikiem jest liczba podpisanych umów, a nie zysk.",
            "W funduszach wynajmu wynik księgowy zmienia przeszacowanie wartości "
            "nieruchomości — pozycja bezgotówkowa, która potrafi zamienić rentowny "
            "rok w stratę i odwrotnie. Dlatego patrzy się tam na przepływy z najmu "
            "i poziom zadłużenia, bo to one decydują o wypłatach.",
        ],
        "lista": [
            "<b>Umowy sprzedaży</b> — u deweloperów wyprzedzają przychód o kilka "
            "kwartałów.",
            "<b>Przeszacowania wartości</b> — zmieniają wynik, nie zmieniając gotówki.",
            "<b>Koszt długu</b> — najczulszy punkt całej branży przy wysokich stopach.",
        ],
    },

    "paliwa-i-energia": {
        "sektor_pl": "paliwa i energia",
        "h1": "Wyniki spółek paliwowych i naftowych",
        "tytul": "Wyniki spółek paliwowych — terminy raportów | Portevo",
        "opis": "Kiedy spółki naftowe i gazowe publikują wyniki kwartalne. Terminy, "
                "prognozy analityków i historia reakcji kursu po raportach.",
        "lead": "Wydobycie, rafinacja i sprzedaż paliw — wynik rozpięty między ceną "
                "ropy, marżą rafineryjną i kursem dolara.",
        "akapity": [
            "Dla spółki przerabiającej ropę najważniejszą liczbą kwartału jest "
            "<strong>marża rafineryjna</strong> — różnica między wartością produktów "
            "a ceną surowca. Jest publicznie obserwowalna w trakcie kwartału, więc "
            "sam wynik rzadko zaskakuje; zaskakują odpisy, remonty instalacji "
            "i zmiany wartości zapasów.",
            "Efekt zapasów wart jest osobnej uwagi: gdy ropa tanieje, spółka księguje "
            "stratę na surowcu kupionym drożej — mimo że jej podstawowy biznes działa "
            "bez zmian. To najczęstszy powód, dla którego zysk raportowany i wynik "
            "oczyszczony różnią się o setki milionów.",
        ],
        "lista": [
            "<b>Marża rafineryjna</b> — znana rynkowi jeszcze przed raportem.",
            "<b>Efekt zapasów</b> — księgowy skutek zmiany ceny ropy.",
            "<b>Postoje remontowe</b> — planowane, ale zawsze widoczne w wolumenach.",
        ],
    },
}


def sciezka(slug: str) -> str:
    return PREFIKS + slug


def adresy() -> list[str]:
    """Adresy wszystkich stron sektorowych — do sitemapy i spisu w aplikacji."""
    return [sciezka(s) for s in SEKTORY]


def spis() -> list[tuple[str, str, int]]:
    """[(adres, nazwa branży, liczba spółek), …] — do linkowania z innych stron."""
    grupy = companies.sektory()
    out = []
    for slug, cfg in SEKTORY.items():
        ile = len(grupy.get(cfg["sektor_pl"], []))
        if ile:
            out.append((sciezka(slug), cfg["sektor_pl"], ile))
    return sorted(out, key=lambda x: -x[2])


def _kalendarz_sektora(lista: list[dict], nazwa: str) -> str:
    """Najbliższe raporty spółek TEJ branży — z żywego kalendarza, jeśli są w cache."""
    slugi = {s["slug"] for s in lista}
    pozycje = [p for p in upcoming.najblizsze(dni=30) if p["spolka"]["slug"] in slugi]
    if len(pozycje) < 2:
        return ""

    wiersze = [{
        "logo": logos.znak(p["spolka"], 34),
        "tytul": f"{p['nazwa']} ({companies.ticker(p['spolka'])})",
        "podtytul": "GPW" if p["rynek"] == "GPW" else "USA",
        "wartosc": dates.krotko(p["data"]),
        "nota": ("termin szacowany" if p["szacowany"]
                 else (f"prognoza EPS {render.liczba(p['eps'])}"
                       if p.get("eps") is not None else "")),
        "adres": p["adres"],
    } for p in pozycje[:10]]

    return render.sekcja(
        f"Najbliższe raporty — {nazwa}",
        "Terminy pobrane z kalendarza Portevo. Data szacowana oznacza, że spółka "
        "nie potwierdziła jeszcze dnia publikacji i może go przesunąć.",
        kotwica="najblizsze",
        html_dodatkowy=render.wiersze(
            wiersze, naglowek=(f"Kalendarz wyników — {nazwa}", "najbliższe 30 dni"),
            wiecej=("/kalendarz-wynikow-spolek", "Pełny kalendarz wyników")))


def zbuduj(slug: str) -> str | None:
    cfg = SEKTORY.get((slug or "").strip().lower())
    if not cfg:
        return None
    lista = companies.sektory().get(cfg["sektor_pl"], [])
    if not lista:
        return None

    gpw = [s for s in lista if s["market"] == "GPW"]
    usa = [s for s in lista if s["market"] == "USA"]
    adres = sciezka(slug)
    nazwa = cfg["sektor_pl"]

    bloki = [render.statystyki([
        ("Spółek w katalogu", str(len(lista))),
        ("Z GPW", str(len(gpw))),
        ("Z giełd USA", str(len(usa))),
    ])]

    bloki.append(render.sekcja(
        f"Czego szukać w raportach: {nazwa}",
        *cfg["akapity"], lista=cfg["lista"], kotwica="na-co-patrzec"))

    kal = _kalendarz_sektora(lista, nazwa)
    if kal:
        bloki.append(kal)

    for tytul, grupa, opis in (
            ("Spółki z GPW", gpw,
             "Warszawskie spółki z tej branży — z terminem najbliższego raportu "
             "i historią reakcji kursu na poprzednie publikacje."),
            ("Spółki z giełd amerykańskich", usa,
             "Amerykańska część branży. Ich raporty wyznaczają ton całemu sektorowi, "
             "także spółkom z Warszawy.")):
        if not grupa:
            continue
        bloki.append(render.sekcja(
            tytul, opis,
            html_dodatkowy=render.kafle([{
                "logo": logos.znak(s, 34),
                "tytul": s["name"],
                "podtytul": f"{companies.ticker(s)} · {companies.gielda_krotka(s)}",
                "adres": companies.adres(s),
            } for s in sorted(grupa, key=lambda x: x["name"].lower())])))

    pary = [
        (f"Kiedy spółki z sektora „{nazwa}” publikują wyniki?",
         "Terminy różnią się spółka po spółce — amerykańskie raportują zwykle "
         "2–5 tygodni po zakończeniu kwartału, warszawskie mają na to więcej czasu. "
         "Aktualne daty znajdziesz na liście najbliższych raportów wyżej "
         "i w kalendarzu wyników Portevo."),
        ("Ile spółek z tej branży znajdę w Portevo?",
         f"W katalogu jest ich {len(lista)}: {len(gpw)} z GPW i {len(usa)} "
         f"z giełd amerykańskich. Każda ma własną podstronę z terminem raportu, "
         f"prognozami analityków i historią reakcji kursu."),
        ("Czy dane są darmowe?",
         "Tak. Kalendarz wyników, terminy raportów i prognozy analityków są w Portevo "
         "bez opłat i bez zakładania konta."),
    ]
    bloki.append(render.sekcja("Najczęstsze pytania", kotwica="pytania",
                               html_dodatkowy=render.faq(pary)))

    inne = [(a, f"{n} ({ile})") for a, n, ile in spis() if a != adres]
    bloki.append(render.sekcja(
        "Inne branże",
        html_dodatkowy=render.chipsy(inne[:10] + [
            ("/wyniki-finansowe", "Wszystkie spółki A–Z"),
            ("/kalendarz-wynikow-spolek", "Kalendarz wyników"),
        ])))

    bloki.append(render.zacheta(
        "Cała branża w jednym kalendarzu",
        "W aplikacji zobaczysz wszystkie te spółki na osi czasu, z prognozami "
        "i własnym portfelem w tle — a raporty firm, które obserwujesz, będą "
        "wyróżnione.",
        adres="/earnings", etykieta="Otwórz kalendarz wyników",
        drugi=("/wyniki-finansowe", "Spis spółek A–Z")))
    bloki.append(render.zastrzezenie())

    okruchy = [("/wyniki-finansowe", "Wyniki spółek"), ("", nazwa.capitalize())]

    return render.strona(
        sciezka=adres,
        tytul=cfg["tytul"],
        opis=cfg["opis"],
        h1=cfg["h1"],
        lead=cfg["lead"],
        nadtytul="Branża",
        okruchy=okruchy,
        szeroki_naglowek=True,
        aktualizacja=dates.dzis(),
        bloki=bloki,
        jsonld=[
            jsonld.strona(adres, cfg["tytul"], cfg["opis"], typ="CollectionPage",
                          zmieniono=dt.date.today().isoformat()),
            jsonld.okruchy(okruchy),
            jsonld.pytania(pary),
            jsonld.lista_pozycji(
                cfg["h1"], [(companies.adres(s), s["name"]) for s in lista]),
        ],
    )
