"""Katalog funkcji premium — jedno źródło prawdy dla telefonu i panelu web.

Aplikacja mobilna i HTML nie mają własnych list funkcji: pobierają tę stąd przez
`/api/premium/features`. Dzięki temu zmiana nazwy, opisu albo ceny to jedna edycja
w tym pliku, bez wypuszczania nowej wersji apki.

`status`:
  live    — działa dziś, kłódka blokuje realną funkcję
  soon    — zapowiedź; kafelek widać, ale opisany jest jako „wkrótce"
"""

from __future__ import annotations

# --------------------------------------------------------------------- cennik
# TODO(owner): ustalić docelowe ceny przed uruchomieniem płatności.
# `price_id` uzupełnia się identyfikatorami ze Stripe (keys/stripe.env).

PLANS = [
    {
        "id": "monthly",
        "label": "Miesięcznie",
        "price": 29.0,
        "currency": "PLN",
        "period": "mies.",
        "note": "Rezygnujesz kiedy chcesz",
        "price_id_env": "STRIPE_PRICE_MONTHLY",
    },
    {
        "id": "yearly",
        "label": "Rocznie",
        "price": 249.0,
        "currency": "PLN",
        "period": "rok",
        "note": "Dwa miesiące gratis",
        "badge": "Najczęściej wybierany",
        "highlight": True,
        "price_id_env": "STRIPE_PRICE_YEARLY",
    },
    {
        "id": "lifetime",
        "label": "Dożywotnio",
        "price": 699.0,
        "currency": "PLN",
        "period": "raz",
        "note": "Jedna płatność, wszystkie przyszłe funkcje",
        "price_id_env": "STRIPE_PRICE_LIFETIME",
    },
]

# ------------------------------------------------------------------- sekcje

GROUPS = [
    {"id": "bot", "label": "Bot newsowy", "desc": "Rynek reaguje na wiadomości w sekundy. Bot czyta je za Ciebie."},
    {"id": "alloc", "label": "Alokacja i ryzyko", "desc": "Nie tylko z czego składa się portfel, ale co z tego wynika."},
    {"id": "portfolio", "label": "Wyniki i rozliczenia", "desc": "Miary, których nie da się policzyć w arkuszu w pięć minut."},
    {"id": "market", "label": "Rynek i spółki", "desc": "Szukanie okazji i pilnowanie tego, co już obserwujesz."},
    {"id": "tools", "label": "Narzędzia", "desc": "Osobne przyrządy do konkretnej roboty — rozwijane jedno po drugim."},
]

# ------------------------------------------------------------------ funkcje

FEATURES: list[dict] = [
    # ---------------------------------------------------------------- narzędzia
    {
        "id": "tools.etf",
        "group": "tools",
        "screen": "tools",
        "status": "live",
        "icon": "🔬",
        "title": "Skaner ETF",
        "tagline": "Zobacz, co naprawdę kupujesz — zanim kupisz",
        "pitch": (
            "Nazwa funduszu nic nie mówi. „MSCI World” brzmi jak cały świat, a w praktyce "
            "w dwóch trzecich to Ameryka i w jednej piątej siedem spółek technologicznych. "
            "Skaner rozkłada każdy fundusz na czynniki pierwsze: co jest w środku, w jakich "
            "proporcjach, ile to kosztuje rocznie i jak mocno potrafi spaść. Wszystko "
            "wytłumaczone zwykłym językiem, z przeliczeniem na złotówki."
        ),
        "bullets": [
            "Filtry, których nie ma w apce maklera: region, sektor, waluta, klasa aktywów",
            "Pełny skład funduszu z wyjaśnieniem, ile z Twojego tysiąca trafia do każdej spółki",
            "Ocena ryzyka: zmienność roczna, największe obsunięcie, koncentracja koszyka",
            "Porównywarka do sześciu funduszy naraz — z macierzą korelacji",
            "Realny koszt roczny przeliczony na pieniądze, nie na procenty",
        ],
        "free_hint": "Bez premium widzisz listę funduszy i filtry — bez wnętrza i porównań.",
    },

    # ------------------------------------------------------------ bot newsowy
    {
        "id": "bot.signals",
        "group": "bot",
        "screen": "bot",
        "status": "live",
        "icon": "📡",
        "title": "Bot newsów na żywo",
        "tagline": "Zrozum wiadomość szybciej, niż zdążysz odświeżyć portal",
        "pitch": (
            "Bot nasłuchuje komunikatów ESPI, raportów SEC, kanałów rządowych i serwisów "
            "newsowych, a model językowy ocenia każdy z nich w kilka sekund: czy to w ogóle "
            "informacja istotna dla rynku, kogo dotyczy i jak mocny ma wydźwięk. Dostajesz "
            "gotową analizę z uzasadnieniem, zanim temat trafi na główną stronę portalu."
        ),
        "bullets": [
            "Nasłuch źródeł 24/7 — ESPI, SEC EDGAR, komunikaty rządowe, squawk",
            "Analiza po polsku z uzasadnieniem — wiesz, skąd taki wniosek",
            "Siła wydźwięku i autorytet źródła — wiesz, czemu ufać bardziej",
            "Pomiar: co kurs zrobił po godzinie i po dniu od analizy",
        ],
        "free_hint": "Bez premium widzisz ostatnie analizy z opóźnieniem i bez uzasadnienia.",
    },
    {
        "id": "bot.brain",
        "group": "bot",
        "screen": "bot",
        "status": "live",
        "icon": "🧠",
        "title": "Mózg AI — własne zasady",
        "tagline": "Ustaw, na co bot ma reagować, a co ma ignorować",
        "pitch": (
            "Serce bota to zestaw promptów i mnożników. W wersji premium możesz je edytować: "
            "podnieść wagę przejęć, ściszyć plotki, dopisać własne kategorie wiadomości i "
            "zmienić autorytet źródeł. Każda zmiana od razu widać w kolejnych sygnałach."
        ),
        "bullets": [
            "Edycja promptów w podziale na sekcje, z podglądem złożonej całości",
            "Kategorie wiadomości z własnymi mnożnikami siły",
            "Autorytet źródła — inaczej traktuj komunikat giełdowy, inaczej tweeta",
            "Powrót do ustawień domyślnych jednym przyciskiem",
        ],
        "free_hint": "Bez premium widzisz konfigurację, ale nie zapiszesz zmian.",
    },
    {
        "id": "bot.outcomes",
        "group": "bot",
        "screen": "bot",
        "status": "live",
        "icon": "📈",
        "title": "Sprawdzalność analiz",
        "tagline": "Zobacz, co kurs naprawdę robił po takich wiadomościach",
        "pitch": (
            "Przy każdej analizie bot zapisuje kurs spółki, a potem sprawdza go po godzinie "
            "i po dniu. Z tego powstaje liczba zamiast obietnicy: jak często kurs poszedł "
            "w stronę wskazanego wydźwięku i jak duży był to ruch."
        ),
        "bullets": [
            "Pomiar po 1 godzinie i po 1 dniu od analizy",
            "Skuteczność w podziale na źródła i kategorie wiadomości",
            "Średnia siła ruchu — czy to w ogóle był ruch wart uwagi",
        ],
        "free_hint": "Bez premium widzisz sam wynik zbiorczy, bez rozbicia na źródła.",
    },
    {
        "id": "bot.live",
        "group": "bot",
        "screen": "tools",
        "status": "live",
        "icon": "🎙",
        "title": "Wystąpienia na żywo",
        "tagline": "Słuchaj konferencji, zanim media zdążą ją streścić",
        "pitch": (
            "Konferencje prasowe, decyzje banków centralnych i wystąpienia polityków lecą "
            "na żywo. Komputer zamienia dźwięk na tekst, a model wyławia z niego zdania, "
            "które realnie dotyczą konkretnych spółek — razem z cytatem, na którym się oparł."
        ),
        "bullets": [
            "Transkrypcja na żywo z kanałów YouTube i zaplanowanych streamów",
            "Kalendarz wydarzeń: FDA, Fed, wystąpienia — z automatycznym dozorem",
            "Wyłapane fragmenty z cytatem i oceną, kogo dotyczą",
        ],
        "free_hint": "Bez premium widzisz kalendarz wydarzeń, ale bez transkrypcji i analiz.",
    },
    {
        "id": "bot.alerts",
        "group": "bot",
        "screen": "bot",
        "status": "soon",
        "icon": "🔔",
        "title": "Alerty push z newsów",
        "tagline": "Telefon zawibruje, gdy pojawi się mocny sygnał dla Twojej spółki",
        "pitch": (
            "Powiadomienie na telefon w momencie, w którym bot wykryje mocny sygnał dotyczący "
            "spółki z Twojego portfela albo listy obserwowanych. Z progiem siły, żeby nie "
            "dzwoniło przy każdej pierdole."
        ),
        "bullets": [
            "Próg siły sygnału — decydujesz, co jest warte wybudzenia",
            "Filtr: tylko moje spółki / tylko obserwowane / wszystko",
            "Cisza nocna i limit powiadomień na godzinę",
        ],
        "free_hint": "",
    },

    # ------------------------------------------------------- alokacja i ryzyko
    {
        "id": "alloc.risk",
        "group": "alloc",
        "screen": "allocation",
        "status": "live",
        "icon": "🎯",
        "title": "Rentgen ryzyka",
        "tagline": "Nie „ile masz w akcjach”, tylko „co Cię realnie boli”",
        "pitch": (
            "Wykres kołowy pokazuje podział. Rentgen pokazuje konsekwencje: który walor "
            "odpowiada za większość wahań portfela, jak bardzo jesteś skupiony (wskaźnik "
            "Herfindahla), ile portfela zależy od jednego kursu walutowego i jaka jest "
            "efektywna liczba pozycji — czyli na ilu naprawdę stoisz, a nie ile ich masz."
        ),
        "bullets": [
            "Wskaźnik koncentracji HHI i efektywna liczba pozycji",
            "Wkład każdej pozycji w zmienność całości, nie w wartość",
            "Ekspozycja walutowa netto po przewalutowaniu",
            "Ostrzeżenia progowe: jedna pozycja > 20%, jeden sektor > 40%",
        ],
        "free_hint": "Bez premium widzisz sam podział procentowy.",
    },
    {
        "id": "alloc.correlation",
        "group": "alloc",
        "screen": "allocation",
        "status": "live",
        "icon": "🕸",
        "title": "Mapa korelacji",
        "tagline": "Dziesięć spółek to nie dywersyfikacja, jeśli chodzą tak samo",
        "pitch": (
            "Macierz korelacji dziennych stóp zwrotu Twoich pozycji z ostatnich miesięcy. "
            "Od razu widać pary, które chodzą ramię w ramię — a to one sprawiają, że portfel "
            "spada mocniej, niż wynikałoby z liczby pozycji."
        ),
        "bullets": [
            "Macierz korelacji z podświetleniem par powyżej 0,8",
            "Średnia korelacja portfela — jedna liczba mówiąca o dywersyfikacji",
            "Wskazanie pozycji, których dołożenie najbardziej ją obniży",
        ],
        "free_hint": "",
    },
    {
        "id": "alloc.target",
        "group": "alloc",
        "screen": "allocation",
        "status": "soon",
        "icon": "⚖️",
        "title": "Alokacja docelowa i rebalancing",
        "tagline": "Ustal proporcje raz, potem tylko wyrównuj",
        "pitch": (
            "Zapisujesz docelowy podział (np. 60% akcje globalne, 25% Polska, 15% gotówka), "
            "a portfel sam pokazuje odchylenia od Twojego planu i kwoty potrzebne do "
            "wyrównania. Z uwzględnieniem kosztów, żeby wyrównywanie nie zjadło zysku."
        ),
        "bullets": [
            "Własne cele procentowe dla klas, rynków i sektorów",
            "Kwoty potrzebne do wyrównania każdej pozycji planu",
            "Próg tolerancji — rebalansuj dopiero przy odchyleniu ponad X%",
        ],
        "free_hint": "",
    },
    {
        "id": "alloc.lookthrough",
        "group": "alloc",
        "screen": "allocation",
        "status": "soon",
        "icon": "🔎",
        "title": "Prześwietlenie ETF-ów",
        "tagline": "Twoje trzy ETF-y mogą być w połowie tą samą siódemką spółek",
        "pitch": (
            "Rozkłada fundusze na czynniki pierwsze i pokazuje realną ekspozycję portfela: "
            "sektorową, geograficzną i na konkretne spółki — także te, które siedzą w kilku "
            "ETF-ach naraz i po cichu robią z Ciebie inwestora skupionego na jednej branży."
        ),
        "bullets": [
            "Rzeczywisty udział pojedynczych spółek liczony przez skład funduszy",
            "Nakładanie się funduszy — ile płacisz za to samo dwa razy",
            "Sektory i regiony po prześwietleniu, nie po nazwie funduszu",
        ],
        "free_hint": "",
    },
    {
        "id": "alloc.history",
        "group": "alloc",
        "screen": "allocation",
        "status": "soon",
        "icon": "📈",
        "title": "Alokacja w czasie",
        "tagline": "Jak portfel dryfował, gdy patrzyłeś gdzie indziej",
        "pitch": (
            "Wykres warstwowy pokazujący, jak zmieniał się podział portfela miesiąc po "
            "miesiącu. Widać na nim rzeczy, których nie widać w zestawieniu na dziś: "
            "powolne narastanie jednej pozycji i moment, w którym plan przestał obowiązywać."
        ),
        "bullets": [
            "Udziały klas i sektorów w czasie",
            "Rozbicie zmiany na „kupiłem” i „urosło samo”",
        ],
        "free_hint": "",
    },

    # ---------------------------------------------------- wyniki i rozliczenia
    {
        "id": "portfolio.benchmark",
        "group": "portfolio",
        "screen": "overview",
        "status": "live",
        "icon": "🏁",
        "title": "Pełne porównanie z rynkiem",
        "tagline": "Zarabiasz, czy tylko rynek rósł razem z Tobą",
        "pitch": (
            "Twoja krzywa na tle indeksów, ale z liczbami, które coś znaczą: alfa (ile dołożyłeś "
            "ponad rynek), beta (jak mocno reagujesz na jego ruchy), Sharpe i maksymalne "
            "obsunięcie kapitału. Liczone na Twoich przepływach, więc wpłaty nie zawyżają wyniku."
        ),
        "bullets": [
            "Alfa i beta względem wybranego benchmarku",
            "Sharpe, Sortino i maksymalne obsunięcie",
            "Najlepszy i najgorszy miesiąc, seria zysków i strat",
        ],
        "free_hint": "Bez premium porównasz krzywe, ale bez miar ryzyka.",
    },
    {
        "id": "portfolio.tax",
        "group": "portfolio",
        "screen": "more",
        "status": "soon",
        "icon": "🧾",
        "title": "Rozliczenie podatkowe",
        "tagline": "PIT-38 policzony z Twoich raportów, nie z pamięci",
        "pitch": (
            "Z wgranych raportów maklerskich liczy podstawę do PIT-38: przychody, koszty w "
            "metodzie FIFO, przewalutowanie po kursie NBP z dnia poprzedzającego, dywidendy z "
            "podatkiem u źródła i straty z lat ubiegłych do odliczenia. Do tego podpowiedź, "
            "które pozycje warto zamknąć przed końcem roku, żeby domknąć stratę."
        ),
        "bullets": [
            "FIFO i kursy NBP liczone automatycznie",
            "Dywidendy zagraniczne i podatek u źródła",
            "Symulacja „sprzedam teraz” — ile zapłacę podatku",
        ],
        "free_hint": "",
    },
    {
        "id": "portfolio.report",
        "group": "portfolio",
        "screen": "more",
        "status": "soon",
        "icon": "📄",
        "title": "Raport miesięczny PDF",
        "tagline": "Podsumowanie miesiąca na jednej kartce, na maila",
        "pitch": (
            "Pierwszego dnia miesiąca dostajesz PDF: wynik, co go zrobiło, zmiany w alokacji, "
            "koszty i porównanie z rynkiem. Dobre do archiwum i do rozmowy z kimś, kto nie "
            "ma dostępu do panelu."
        ),
        "bullets": ["Automatyczna wysyłka na e-mail", "Historia raportów do pobrania"],
        "free_hint": "",
    },

    # --------------------------------------------------------- rynek i spółki
    {
        "id": "market.screener",
        "group": "market",
        "screen": "company",
        "status": "soon",
        "icon": "🧮",
        "title": "Skaner spółek",
        "tagline": "Własne kryteria zamiast przeglądania setek tickerów",
        "pitch": (
            "Filtrujesz rynek po wskaźnikach, które już masz w karcie spółki: wycena, marże, "
            "zadłużenie, tempo wzrostu, wypłata dywidendy. Zestaw filtrów zapisujesz i wracasz "
            "do niego jednym kliknięciem."
        ),
        "bullets": [
            "Filtry po wszystkich wskaźnikach z karty spółki",
            "Zapisane skany z powiadomieniem o nowych trafieniach",
            "Porównanie wyników z medianą branży",
        ],
        "free_hint": "",
    },
    {
        "id": "market.alerts",
        "group": "market",
        "screen": "company",
        "status": "soon",
        "icon": "⏰",
        "title": "Alerty cenowe i wynikowe",
        "tagline": "Nie musisz sprawdzać kursu — to on odezwie się do Ciebie",
        "pitch": (
            "Ustaw próg ceny, zmianę dzienną albo termin publikacji wyników i dostaniesz "
            "powiadomienie. Alerty jadą przez konto, więc ustawione na telefonie działają "
            "też, gdy siedzisz przy panelu."
        ),
        "bullets": [
            "Progi cenowe w górę i w dół, zmiana dzienna",
            "Przypomnienie o wynikach spółek z portfela",
            "Wspólne dla telefonu i panelu web",
        ],
        "free_hint": "",
    },
    {
        "id": "market.ai",
        "group": "market",
        "screen": "company",
        "status": "soon",
        "icon": "💬",
        "title": "Asystent portfela",
        "tagline": "Zapytaj po polsku, co się dzieje z Twoimi pieniędzmi",
        "pitch": (
            "Model widzi Twoje pozycje, koszty i historię, więc odpowiada konkretnie: „co "
            "najbardziej ciągnęło portfel w dół w tym miesiącu”, „czy jestem przeważony na "
            "dolarze”, „co się wydarzyło w spółce X od mojego zakupu”."
        ),
        "bullets": [
            "Odpowiedzi na Twoich danych, nie na ogólnikach",
            "Podsumowanie sesji i tygodnia jednym akapitem",
            "Wyjaśnienie każdej liczby z panelu na żądanie",
        ],
        "free_hint": "",
    },
]

BY_ID = {f["id"]: f for f in FEATURES}


def catalog(viewer=None) -> dict:
    """Katalog do wysłania klientowi — z informacją, co ten konkretny widz odblokował."""
    premium = bool(viewer and viewer.premium)
    items = []
    for f in FEATURES:
        items.append({**f, "locked": not premium and f["status"] == "live",
                      "available": premium})
    return {
        "premium": premium,
        "groups": GROUPS,
        "features": items,
        "plans": PLANS,
        # jedno zdanie na górze strony sprzedażowej — łatwo podmienić w testach
        "headline": "Portfel widzi więcej, niż pokazuje",
        "subheadline": (
            "Wersja premium dokłada to, czego nie policzysz w arkuszu: ryzyko portfela, "
            "sygnały z wiadomości w czasie rzeczywistym i rozliczenia."
        ),
    }


def is_locked(feature_id: str, viewer) -> bool:
    """Czy tę funkcję trzeba zasłonić temu widzowi."""
    f = BY_ID.get(feature_id)
    if not f:
        return False
    if viewer and viewer.premium:
        return False
    return f["status"] == "live"
