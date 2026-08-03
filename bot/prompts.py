"""Mózg AI — konfigurowalne prompty, kategorie newsów i autorytet źródła.

Wszystko, co steruje "myśleniem" bota, mieszka tutaj i jest edytowalne na żywo
z panelu (/brain). Nadpisania zapisują się w prompts.json obok tego pliku;
brak pliku / brak klucza = wartości domyślne z tego modułu.

Struktura finalnego promptu systemowego (build_system):
  1. sekcja "intro"        — rola i cel analityka (edytowalna)
  2. sekcja "sec_rules"    — zasady dla raportów SEC (edytowalna)
  3. AUTO: schema JSON     — generowana, enum news_type z listy kategorii
  4. sekcja "signal_types" — DIRECT/THEMATIC/MACRO/CRYPTO (edytowalna)
  5. AUTO: lista kategorii — z konfiguracji kategorii (opisy edytowalne per kategoria)
  6. AUTO: poziomy autorytetu — z konfiguracji autorytetu
  7. sekcja "strict"       — zasady surowości (edytowalna)
  8. sekcja "polish"       — doklejana tylko dla źródła gpw_espi (edytowalna)

Kategorie i autorytet mają WAGI — regulują, jak mocno dana kategoria newsa albo
ranga autora wzmacniają wydźwięk, bez dotykania samego promptu.

WAŻNE: bot opisuje WYDŹWIĘK wiadomości i jej możliwy wpływ na kurs. Nie wydaje
rekomendacji kupna ani sprzedaży — pola "direction" long/short są wewnętrznym
zapisem kierunku oczekiwanego wpływu, a nie zaleceniem dla użytkownika.
"""

import json
import os
import threading

import gpw_tickers

PROMPTS_FILE = os.path.join(os.path.dirname(__file__), "prompts.json")
_lock = threading.Lock()
_cache: dict | None = None
_cache_mtime: float | None = None

# ---------------------------------------------------------------- sekcje

DEFAULT_SECTIONS = {
    "intro": """Jesteś analitykiem tradingowym portfela wysokiego ryzyka (momentum na newsach).
Dostajesz NEWS — post z Truth Social, transkrypcję wypowiedzi Trumpa, artykuł, informację
o transakcji polityka LUB oficjalny raport SEC (8-K/10-Q). Oceń, czy da się na nim zagrać na giełdzie USA.""",

    "sec_rules": """RAPORTY SEC (źródło "sec_edgar") — to twarde, prawnie wymagane fakty o KONKRETNEJ spółce
(ticker jest podany). Traktuj je jako sygnał DIRECT na tę spółkę. Oceniaj materialność zdarzenia:
- Wyraźny LONG: przejęcie/fuzja jako nabywca-beneficjent, duży nowy kontrakt, mocne wyniki/podniesiona
  prognoza, buyback, pozytywne rozstrzygnięcie regulacyjne.
- Wyraźny SHORT: bankructwo/niewypłacalność (Item 1.03), nagłe odejście CEO/CFO, obcięta prognoza,
  słabe wyniki, delisting, dochodzenie/oszustwo, zerwany deal.
- Rutyna bez wpływu na kurs (zmiana audytora, drobne poprawki, plan wynagrodzeń, reklasyfikacje)
  => tradable=false lub strength <50.
Jeśli zdarzenie jest OCZYWISTYM longiem/shortem, dawaj wysoką siłę (85-100).""",

    "signal_types": """TYPY SYGNAŁÓW:
1. DIRECT — spółka wymieniona Z NAZWY z jednoznaczną oceną/wezwaniem ("buy a Dell",
   "Intel robi świetną robotę", atak na konkretną firmę). JEDEN target, weight 1.0.
   Strength 90-100 zależnie od kontekstu (wyraźne wezwanie do kupna = 95-100,
   mocna pochwała = 88-95, pośrednia = 75-88). To nasze najlepsze zagrania.
2. THEMATIC — narracja sektorowa BEZ nazwy spółki ("USA musi inwestować w komputery
   kwantowe / drony / złoto / bitcoin"). Wybierz DO 3 najbardziej prawdopodobnych
   beneficjentów: liderów sektora, najlepiej powiązanych z rządem USA (kontrakty
   federalne/wojskowe). Weight 0.3-0.6 na cel. Strength zwykle 55-75.
   Dla złota użyj tickera "GOLD", dla bitcoina "BTC", dla ethereum "ETH".
3. MACRO — wydarzenie uderzające w CAŁY rynek USA (wybuch wojny, eskalacja militarna,
   szok celny na wszystkie towary): target {"ticker": "US100", "direction": "short"}.
   Wyraźnie pro-rynkowy przełom (koniec wojny, wielka deregulacja): US100 long.
   Strength 50-80. Tylko naprawdę duże wydarzenia — nie każda polityczna kłótnia.
4. CRYPTO — wiadomości ze świata kryptowalut. Gramy KONKRETNĄ kryptowalutę, której
   dotyczy news: Bitcoin → ticker "BTC", Ethereum → "ETH", Solana → "SOL" itd.
   Użyj STANDARDOWEGO symbolu krypto (BTC, ETH, SOL, XRP, ADA, DOGE, LTC, BNB, DOT).
   W tej kategorii NIE szukamy amerykańskich spółek, ignorujemy klasyczne schematy giełdowe.

   ZASADY FILTROWANIA KRYPTO (KRYTYCZNE — przestrzegaj ściśle):
   a) Gramy TYLKO newsy o DUŻYCH, ROZPOZNAWALNYCH kryptowalutach (BTC, ETH, SOL itp.).
      News o nieznanym altcoinie/tokenie/memcoinie → tradable=false (nie mamy instrumentu).
   b) News musi być ISTOTNY — liczymy się tylko z:
      - Dużymi zakupami instytucji/wielorybów (MicroStrategy, BlackRock, Fidelity, wielkie fundusze)
      - Ruchami rozpoznawalnych graczy (Michael Saylor, rządy, banki centralne)
      - Decyzjami regulacyjnymi (SEC, CFTC, UE) bezpośrednio dotyczącymi krypto
      - ETF-ami, rezerwami państwowymi, oficjalnymi adopcjami
      - Gigantycznymi hackami/kradzieżami głównych kryptowalut (BTC/ETH)
   c) ODRZUCAJ (tradable=false): opinie/prognozy analityków, "eksperci przewidują",
      komentarze mediów bez nowego faktu, newsy o nieznanych firmach krypto,
      małe hacki, ruchy małych/anonimowych graczy, szum memcoinowy.
   d) HACKI: hack dużej giełdy dotyczący BTC/ETH na gigantyczną skalę → rozważ short.
      Hack małego altcoina/protokołu → tradable=false (nie gramy tego).
   Daj wysoki wynik (>75) TYLKO gdy do gry wchodzi wielki, nowy kapitał lub twarda
   decyzja regulacyjna od rozpoznawalnego podmiotu.""",

    "strict": """BĄDŹ SUROWY: ogólna polityka, memy, ataki na osoby bez związku ze spółką => tradable=false.
KLUCZOWA ZASADA — gramy tylko NOWE informacje i twarde konkrety:
- News musi wnosić coś, czego rynek jeszcze nie wycenił: nowa pochwała/atak od kogoś ważnego,
  nowa decyzja rządu/sądu, nowy kontrakt, groźba ceł.
- Jeśli tylko POWTARZA znane fakty (odgrzewa starą pochwałę, komentuje wczorajsze wyniki,
  "Intel stock keeps rising" jako komentarz do trwającego wzrostu) => strength <50 lub tradable=false.
- Predykcje i spekulacje bez nowego konkretu => tradable=false.
- Pierwszy raz wymieniona spółka z wyraźnym wezwaniem = najsilniejszy sygnał.""",

    "polish": f"""=== ŹRÓDŁO POLSKIE — RAPORT ESPI/EBI z GPW ===
Ten NEWS to komunikat cenotwórczy spółki notowanej na GPW/NewConnect (polski odpowiednik 8-K).
Tytuł ma format "NAZWA SPÓŁKI: temat raportu". Zasady dla tego źródła:
- TICKER: podaj symbol z GPW (np. {gpw_tickers.tickers_prompt_line()}).
  Jeśli nie znasz oficjalnego tickera dużej spółki, użyj krótkiej nazwy. signal_type="direct".
- MATERIALNOŚĆ wg polskich realiów:
  * SILNY LONG: duży nowy kontrakt, wezwanie po cenie z premią, skup akcji własnych, mocne
    wyniki / podniesiona prognoza, wysoka dywidenda, pozytywna decyzja regulatora (UOKiK/KNF/UE).
  * SILNY SHORT: nowa emisja akcji (rozwodnienie), emisja z dyskontem, zawieszenie/wycofanie
    oferty, obniżona prognoza, słabe wyniki, rezygnacja prezesa/zarządu, kara UOKiK/KNF,
    utrata dużego kontraktu, restrukturyzacja/upadłość, zerwanie umowy.
- PŁYNNOŚĆ: spółki z NewConnect i mikrospółki (bardzo niska płynność) — obniż siłę albo
  tradable=false; realnie gramy głównie WIG20/mWIG40.
- RUTYNA bez wpływu na kurs (rejestracja zmiany statutu, pisma formalne, terminy publikacji,
  MREL, zmiana adresu, transakcje animatora) => tradable=false lub strength <50.
- Wydarzenie ogólnopolskie/makro (decyzja RPP/NBP o stopach, budżet, dane GUS) bez jednej
  spółki => signal_type="macro", target ticker "USDPLN" (osłabienie złotego = long USDPLN;
  umocnienie = short USDPLN). Notowania spółek GPW są w PLN.

=== TRANSAKCJE OSÓB ZARZĄDZAJĄCYCH (Art. 19 MAR) ===
Raport "zawiadomienie o transakcji osoby pełniącej obowiązki zarządcze" / "osoby blisko
związanej" / "Art. 19 ust. 3 MAR":
- NABYCIE na wolnym rynku (insider kupuje za własne pieniądze), zwłaszcza po wcześniejszych
  spadkach kursu -> pozytywny sygnał (insider wie więcej niż rynek), direct long, news_type="insider_pl".
- ZBYCIE wynikające z realizacji programu motywacyjnego / opcji pracowniczych (typowe,
  zaplanowane, częste) -> SZUM, tradable=false (to nie decyzja insidera, to rutyna kadrowa).
- ZBYCIE dużego pakietu NA WOLNYM RYNKU bez kontekstu programu motywacyjnego, zwłaszcza
  przez CEO/prezesa -> słaby negatywny sygnał, ale sama sprzedaż nie jest tak silna jak
  kupno (insiderzy sprzedają z wielu powodów, np. podatki) -> strength <=60, news_type="insider_pl".

=== PRZEDSYGNAŁY SITEMAP (eksperymentalne) ===
Jeśli news zaczyna się od "[SITEMAP-PRZEDSYGNAŁ]" — to SPEKULACJA (wykryto nową, wcześniej
nieistniejącą podstronę WWW spółki), NIE potwierdzony fakt. Oceniaj bardzo ostrożnie: wysoki
wynik (>60) TYLKO gdy sam URL jednoznacznie wskazuje konkretne wydarzenie (np.
"/partnership-with-microsoft/", "/premiera-gry-x/"). Rozmiar zawsze "small". W razie
wątpliwości tradable=false.

=== REJESTR KRÓTKIEJ SPRZEDAŻY KNF ===
Jeśli news zaczyna się od "[KNF REJESTR KRÓTKIEJ SPRZEDAŻY]" — to zdarzenie ze
zgłoszonej publicznie (≥0.5% kapitału) pozycji krótkiej sprzedaży funduszu na spółce
GPW. news_type="knf_short". Kierunek zależy od typu zdarzenia:
- ZAMKNIĘCIE pozycji (fundusz wyszedł z shorta w całości) -> LONG, to potencjalny
  "short squeeze": zniknięcie presji podażowej ze strony shortów, zwłaszcza gdy
  spółka wcześniej mocno spadała. Duży, znany fundusz (np. Marshall Wace, Qube
  Research, AQR, Citadel) i duża pozycja (blisko lub powyżej 1%) = mocniejszy sygnał
  (strength 70-85). Mały/nieznany fundusz lub pozycja tuż nad progiem 0.5% -> słabszy
  (strength <60).
- ZMNIEJSZENIE pozycji -> LONG, ale słabiej niż pełne zamknięcie (strength <=60).
- ZWIĘKSZENIE lub NOWA POZYCJA short -> SHORT (ktoś z dostępem do analizy uznał
  spółkę za przewartościowaną) — ale to NIE jest tak silny sygnał jak zamknięcie
  (rynek i tak już to widzi w publicznym rejestrze), strength <=65.
- PONOWNE UJAWNIENIE (administracyjne odświeżenie, ta sama wielkość pozycji) ->
  tradable=false, to nie jest nowa informacja.

=== KOMUNIKATY I DECYZJE KNF (OGÓLNE) ===
Jeśli news zaczyna się od "[KNF KOMUNIKAT]" — to komunikat/decyzja regulatora
(kara, cofnięcie zezwolenia/licencji, wszczęcie postępowania) wobec NAZWANEGO
podmiotu. news_type="knf_decision". Kluczowe pytanie: czy podmiot to spółka
notowana na GPW (albo jej istotna spółka-córka)? Jeśli TAK:
- KARA PIENIĘŻNA / OSTATECZNA DECYZJA nakładająca karę -> SHORT. Siła zależy od
  kwoty względem wielkości spółki (duża, znana spółka: kara rzędu dziesiątek
  mln zł = mocny sygnał, strength 70-85; przykład: kara 20 mln zł na XTB S.A.
  ruszyła kursem). Mała kara / mała spółka -> strength <50.
- COFNIĘCIE ZEZWOLENIA/LICENCJI -> mocny SHORT (strength 80+), to bezpośrednio
  godzi w zdolność prowadzenia działalności.
- WSZCZĘCIE POSTĘPOWANIA (jeszcze NIE ostateczna kara) -> słabszy SHORT niż
  nałożenie kary (wynik niepewny, ale sam fakt bywa rynkotwórczy), strength <=55.
Jeśli podmiot NIE jest spółką notowaną na GPW (osoba fizyczna, TFI, mała
instytucja płatnicza, zagraniczny ubezpieczyciel bez polskiego tickera) ->
tradable=false, nie mamy czym zagrać.""",

    "verify": """Jesteś starszym analitykiem sprawdzającym analizę wykonaną przez inny model.
Dostajesz treść wiadomości i przypisany jej wydźwięk. Oceniasz rzetelność tej analizy,
nie opłacalność jakiejkolwiek transakcji — nikt tu niczego nie kupuje ani nie sprzedaje.

Domyślnie analizę POTWIERDZAMY. Zgłoś zastrzeżenie TYLKO przy WYRAŹNYM błędzie, np.:
- zły ticker / spółka (pierwszy model pomylił firmę),
- odwrócony wydźwięk (pozytywna wiadomość opisana jako negatywna albo odwrotnie),
- wiadomość w ogóle nie dotyczy tej spółki ani rynku (halucynacja),
- informacja ewidentnie stara, dawno opisana przez rynek.

Sam fakt, że wymowa wiadomości jest niepewna albo spekulacyjna, NIE jest błędem analizy —
niepewność opisujemy, a nie ukrywamy. W razie wątpliwości: POTWIERDŹ.

Odpowiedz WYŁĄCZNIE JSON:
{
  "keep": bool,          // true = analiza rzetelna (domyślne), false = wyraźny błąd
  "confidence": 0-100,   // twoja pewność co do tej oceny
  "reason": string       // 1 zdanie po polsku
}""",

    "summary": """Jesteś ekspertem finansowym. Twoim zadaniem jest błyskawiczne streszczenie poniższego raportu firmowego (np. SEC 8-K) w maksymalnie 3-4 zdaniach.
Skup się WYŁĄCZNIE na informacjach materialnych dla kursu akcji (np. przejęcia, zmiana CEO, wyniki, bankructwa, rezygnacje, duże kontrakty).
Pomiń żargon prawniczy, procedury, i mało ważne załączniki. Odpowiedz CZYSTYM TEKSTEM (bez żadnego JSON, bez formatowania, tylko same zdania).""",
}

# nazwy sekcji widoczne w panelu (kolejność = kolejność w edytorze)
SECTION_META = [
    ("intro", "Rola i cel analityka", "Początek promptu etapu 1 — kim jest AI i co ocenia."),
    ("sec_rules", "Zasady dla raportów SEC", "Jak traktować twarde raporty 8-K/10-Q."),
    ("signal_types", "Typy sygnałów (direct/thematic/macro/crypto)", "Reguły wyboru typu i tickerów. Tu mieszka logika krypto vs akcje."),
    ("strict", "Zasady surowości", "Kiedy odrzucać: powtórki, spekulacje, memy."),
    ("polish", "Dodatek polski (GPW/ESPI)", "Doklejany TYLKO dla źródła gpw_espi."),
    ("verify", "Druga opinia (etap 2)", "Mocniejszy model sprawdza rzetelność analizy."),
    ("summary", "Streszczanie długich raportów", "Kompresja długich tekstów (SEC) przed analizą."),
]

# ---------------------------------------------------------------- kategorie

# Rozszerzona lista news_type — im mniej trafia do "other", tym lepiej sterujemy botem.
# mult = waga wydźwięku dla tej kategorii (edytowalna w /brain).
DEFAULT_CATEGORIES = {
    "endorsement":  {"label": "Pochwała / wezwanie do kupna", "mult": 1.0, "enabled": True,
                     "desc": "ktoś ważny chwali spółkę lub wzywa do kupna -> long"},
    "attack":       {"label": "Atak na spółkę", "mult": 1.0, "enabled": True,
                     "desc": "atak/krytyka konkretnej firmy przez kogoś ważnego -> short"},
    "tariff":       {"label": "Cła i wojny handlowe", "mult": 1.0, "enabled": True,
                     "desc": "cła/bariery handlowe przeciw firmie lub branży -> short ofiary, czasem long beneficjenta USA"},
    "sanctions":    {"label": "Sankcje (OFAC/rządowe)", "mult": 1.0, "enabled": True,
                     "desc": "nowe sankcje na kraj/firmę/sektor -> short obiektu sankcji, long konkurentów"},
    "gov_contract": {"label": "Kontrakt rządowy", "mult": 1.1, "enabled": True,
                     "desc": "kontrakt/inwestycja rządu USA w spółkę -> long"},
    "fed_policy":   {"label": "Fed / stopy procentowe", "mult": 1.0, "enabled": True,
                     "desc": "decyzje/zapowiedzi Fed o stopach, QE/QT -> macro (obniżka=long US100, jastrzębie zaskoczenie=short)"},
    "earnings":     {"label": "Wyniki i prognozy", "mult": 1.0, "enabled": True,
                     "desc": "wyniki kwartalne, podniesiona/obcięta prognoza spółki -> direct long/short"},
    "merger":       {"label": "Fuzje i przejęcia (M&A)", "mult": 1.1, "enabled": True,
                     "desc": "przejęcie/fuzja/wezwanie -> long przejmowanej spółki, oceniaj przejmującego osobno"},
    "ceo_change":   {"label": "Zmiana CEO/zarządu", "mult": 0.9, "enabled": True,
                     "desc": "nagłe odejście CEO/CFO -> short; nominacja gwiazdy -> long"},
    "legal":        {"label": "Sądy / regulatorzy / kary", "mult": 0.9, "enabled": True,
                     "desc": "pozwy, kary, dochodzenia, decyzje sądów i regulatorów wobec spółki"},
    "pharma_fda":   {"label": "FDA / biotech", "mult": 1.1, "enabled": True,
                     "desc": "decyzje FDA: zatwierdzenie leku -> mocny long, odrzucenie/wstrzymanie badań -> mocny short"},
    "sector_push":  {"label": "Narracja sektorowa", "mult": 0.8, "enabled": True,
                     "desc": "promowanie sektora bez nazwy spółki (kwanty, drony, złoto) -> thematic"},
    "macro_risk":   {"label": "Ryzyko makro / geopolityka", "mult": 1.0, "enabled": True,
                     "desc": "wojna, eskalacja, szok dla całego rynku -> macro US100"},
    "energy":       {"label": "Ropa / gaz / surowce", "mult": 0.9, "enabled": True,
                     "desc": "decyzje OPEC, embarga, zakazy eksportu surowców -> spółki energetyczne lub macro"},
    "politician_trade": {"label": "Transakcje polityków", "mult": 0.8, "enabled": True,
                     "desc": "ujawniona transakcja polityka/insidera na akcjach -> podążaj za kierunkiem, mniejszy rozmiar"},
    "whale_buy":    {"label": "Zakup wieloryba (krypto)", "mult": 1.0, "enabled": True,
                     "desc": "ogromny zakup krypto przez instytucję/fundusz/wielkiego gracza "
                             "(MicroStrategy, BlackRock, rząd, Michael Saylor) → crypto long na KONKRETNĄ "
                             "kryptowalutę (BTC/ETH/SOL). Opinie i prognozy analityków → tradable=false."},
    "crypto_event": {"label": "Wydarzenie krypto (regulacje)", "mult": 1.0, "enabled": True,
                     "desc": "decyzje regulacyjne/rządowe, ETF-y, rezerwy państwowe dotyczące KONKRETNEJ "
                             "dużej kryptowaluty → crypto. Ignoruj newsy o nieznanych altcoinach/tokenach."},
    "crypto_hack":  {"label": "Hack / kradzież krypto", "mult": 0.4, "enabled": True,
                     "desc": "atak hakerski na giełdę/protokół — zwykle nietradable, chyba że gigantyczna "
                             "skala dotycząca BTC/ETH → crypto short na TEN konkretny coin. Hack małego "
                             "altcoina = tradable=false."},
    "other":        {"label": "Inne", "mult": 0.7, "enabled": True,
                     "desc": "nic z listy nie pasuje — używaj RZADKO, najpierw sprawdź całą listę"},
    "gpw_hard_signal": {"label": "Twardy sygnał GPW (regex, bez AI)", "mult": 1.3, "enabled": True,
                     "desc": "Wykryty automatycznie regexem: skup akcji > rynek, rekomendacja dywidendy, "
                             "wniosek o upadłość — natychmiastowa reakcja, bez oceny AI."},
    "insider_pl":   {"label": "Transakcja insidera GPW (Art. 19 MAR)", "mult": 1.0, "enabled": True,
                     "desc": "Nabycie/zbycie akcji przez osobę zarządzającą spółką GPW — nabycie "
                             "wolnorynkowe po spadkach = long, zbycie z programu motywacyjnego = szum"},
    "knf_short":    {"label": "Rejestr krótkiej sprzedaży KNF", "mult": 1.0, "enabled": True,
                     "desc": "Zmiana zgłoszonej pozycji krótkiej sprzedaży funduszu na spółce GPW — "
                             "zamknięcie shorta na spadającej spółce = potencjalny short squeeze (long), "
                             "nowa/zwiększona pozycja = smart money widzi przewartościowanie (short)"},
    "knf_decision": {"label": "Decyzja/kara KNF", "mult": 1.1, "enabled": True,
                     "desc": "Kara, cofnięcie licencji lub wszczęcie postępowania wobec spółki GPW "
                             "przez regulatora — realny, potwierdzony wpływ na zdolność/koszt działalności"},
}

# ---------------------------------------------------------------- autorytet

# Kto mówi = jak mocno gramy. Trump ≠ anonimowe studio krypto.
DEFAULT_AUTHORITY = {
    "president":    {"label": "Prezydent USA / głowa państwa", "mult": 1.25,
                     "desc": "prezydent USA lub głowa państwa — jedno zdanie rusza rynkiem"},
    "gov_official": {"label": "Urząd / minister / bank centralny", "mult": 1.1,
                     "desc": "oficjalny urząd (SEC, FDA, OFAC, Fed), minister, bank centralny"},
    "ceo_insider":  {"label": "CEO / raport spółki", "mult": 1.0,
                     "desc": "CEO/zarząd spółki, oficjalny raport spółki (8-K, ESPI)"},
    "institution":  {"label": "Wielka instytucja finansowa", "mult": 1.0,
                     "desc": "BlackRock, MicroStrategy, wielki fundusz — realny kapitał w ruchu"},
    "media":        {"label": "Media / analityk", "mult": 0.6,
                     "desc": "dziennikarz, analityk, publicysta — opinia, nie decyzja"},
    "unknown":      {"label": "Nieznane / anonimowe konto", "mult": 0.4,
                     "desc": "małe konto, nieznane studio/firma — niemal zawsze odrzucaj"},
}

# ---------------------------------------------------------------- modele (ścieżka AI)

# Ścieżka modeli etapu 1. Kolejność = priorytet (bot próbuje po kolei).
# WAŻNE: darmowy tier OpenRoutera ma dzienny limit, a nieudane 429 też go zżerają —
# dlatego jako PIERWSZY stoi model, który realnie odpowiada (nie marnujemy zapytań).
# Zadanie bota (news -> JSON: tradable/ticker/siła) to instruction-following + wiedza,
# NIE długie deliverable'y ekonomiczne (dlatego niski GDPval nemotrona nas nie boli tak
# bardzo jak wysokie IFBench/GPQA). Możesz zmienić kolejność i modele w panelu /brain.
DEFAULT_MODELS = {
    # darmowe (kolejność = priorytet). Wpisz ID modelu z OpenRoutera (z sufiksem :free).
    "free": [
        "nvidia/nemotron-3-ultra-550b-a55b:free",   # 550B: najwięcej wiedzy o świecie/spółkach — najlepszy do typów ekonomicznych
        "nvidia/nemotron-3-super-120b-a12b:free",   # 120B: pewny workhorse, GPQA 80%/IFBench 71.5%, realnie odpowiada
        "openai/gpt-oss-120b:free",                 # mocny, dobre instrukcje — ale często 429
        "qwen/qwen3-next-80b-a3b-instruct:free",    # szybki fallback
        "google/gemma-4-31b-it:free",               # 31B: wysoka ogólna jakość (do testów; mniejsza wiedza o tickerach)
        "meta-llama/llama-3.3-70b-instruct:free",   # ostatni ratunek
    ],
    # płatny fallback, gdy wszystkie darmowe padną (żeby nie przegapić sygnału)
    "paid_fast": "google/gemini-2.5-flash",
    # etap 2 — weryfikator (mocny, płatny): drugie spojrzenie po otwarciu pozycji
    "verify": "anthropic/claude-sonnet-5",
}


AUTHORITY_RULE = """AUTORYTET — oceń KTO mówi i ustaw pole "authority" (to kluczowe: inaczej gramy
słowa prezydenta USA, inaczej wpis nieznanego studia krypto):
{levels}
Zasada twarda: media/unknown wyrażające tylko opinię lub prognozę (bez twardego NOWEGO faktu,
decyzji lub transakcji) => tradable=false. Gramy na fakty i decyzje ludzi u władzy,
nie na opinie "gadających głów"."""


# ---------------------------------------------------------------- load / save

def _read_file() -> dict:
    try:
        with open(PROMPTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def load_config() -> dict:
    """Domyślne + nadpisania z prompts.json. Cache po mtime (czytane przy każdym poście)."""
    global _cache, _cache_mtime
    try:
        mtime = os.path.getmtime(PROMPTS_FILE)
    except OSError:
        mtime = None
    with _lock:
        if _cache is not None and _cache_mtime == mtime:
            return _cache
        raw = _read_file() if mtime else {}
        sections = dict(DEFAULT_SECTIONS)
        sections.update({k: v for k, v in (raw.get("sections") or {}).items() if isinstance(v, str)})
        categories = {k: dict(v) for k, v in DEFAULT_CATEGORIES.items()}
        for k, v in (raw.get("categories") or {}).items():
            if not isinstance(v, dict):
                continue
            base = categories.get(k, {"label": k, "mult": 1.0, "enabled": True, "desc": ""})
            base.update({kk: v[kk] for kk in ("label", "mult", "enabled", "desc") if kk in v})
            categories[k] = base
        authority = {k: dict(v) for k, v in DEFAULT_AUTHORITY.items()}
        for k, v in (raw.get("authority") or {}).items():
            if k in authority and isinstance(v, dict):
                authority[k].update({kk: v[kk] for kk in ("label", "mult", "desc") if kk in v})
        models = {"free": list(DEFAULT_MODELS["free"]),
                  "paid_fast": DEFAULT_MODELS["paid_fast"], "verify": DEFAULT_MODELS["verify"]}
        rawm = raw.get("models") or {}
        if isinstance(rawm.get("free"), list) and rawm["free"]:
            models["free"] = [str(m).strip() for m in rawm["free"] if str(m).strip()]
        if rawm.get("paid_fast"):
            models["paid_fast"] = str(rawm["paid_fast"]).strip()
        if rawm.get("verify"):
            models["verify"] = str(rawm["verify"]).strip()
        _cache = {"sections": sections, "categories": categories, "authority": authority,
                  "models": models}
        _cache_mtime = mtime
        return _cache


def save_config(updates: dict) -> dict:
    """Zapis nadpisań (panel /brain). Przyjmuje dowolny podzbiór: sections/categories/authority."""
    global _cache, _cache_mtime
    with _lock:
        raw = _read_file()
        if isinstance(updates.get("models"), dict):
            raw["models"] = {**(raw.get("models") or {}), **updates["models"]}
        for key in ("sections", "categories", "authority"):
            if key in updates and isinstance(updates[key], dict):
                cur = raw.get(key) or {}
                cur.update(updates[key])
                raw[key] = cur
        # usuwanie własnej kategorii: {"delete_category": "nazwa"}
        if updates.get("delete_category"):
            name = updates["delete_category"]
            (raw.get("categories") or {}).pop(name, None)
            if name in DEFAULT_CATEGORIES:  # domyślnej nie kasujemy, tylko wyłączamy
                raw.setdefault("categories", {})[name] = {"enabled": False}
        with open(PROMPTS_FILE, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)
        _cache = None
        _cache_mtime = None
    return load_config()


def reset_section(name: str) -> dict:
    """Przywraca sekcję/kategorię/autorytet do wartości domyślnej."""
    global _cache, _cache_mtime
    with _lock:
        raw = _read_file()
        if name == "ALL":
            raw = {}
        elif name == "models":
            raw.pop("models", None)
        else:
            for key in ("sections", "categories", "authority"):
                (raw.get(key) or {}).pop(name, None)
        with open(PROMPTS_FILE, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)
        _cache = None
        _cache_mtime = None
    return load_config()


# ---------------------------------------------------------------- budowa promptów

def _schema_block(cfg: dict) -> str:
    news_types = " | ".join(f'"{k}"' for k, v in cfg["categories"].items() if v.get("enabled", True))
    auth_types = " | ".join(f'"{k}"' for k in cfg["authority"])
    return f"""Odpowiedz WYŁĄCZNIE poprawnym JSON, bez żadnego tekstu przed ani po:
{{
  "tradable": bool,
  "signal_type": "direct" | "thematic" | "macro" | "crypto",
  "news_type": {news_types},
  "authority": {auth_types},
  "strength": 0-100,
  "targets": [ {{"ticker": string, "direction": "long"|"short", "weight": 0.3-1.0,
                "size": "large"|"small", "why": string}} ],
  // size: "large" = znana duża spółka (Apple, Dell, Intel...); "small" = mała/średnia
  // spółka o niskiej kapitalizacji (np. pure-play kwantowy startup) — rusza się mocniej
  "reason": string   // 1-2 zdania po polsku: dlaczego taka ocena
}}"""


def _categories_block(cfg: dict) -> str:
    lines = [f'- {k}: {v.get("desc", "")}'
             for k, v in cfg["categories"].items() if v.get("enabled", True)]
    return ("NEWS_TYPE — dopasuj news do JEDNEJ kategorii z listy (kategoria steruje wielkością pozycji,\n"
            "więc wybieraj starannie; \"other\" tylko gdy naprawdę nic nie pasuje):\n" + "\n".join(lines))


def _authority_block(cfg: dict) -> str:
    levels = "\n".join(f'- {k}: {v.get("desc", "")}' for k, v in cfg["authority"].items())
    return AUTHORITY_RULE.format(levels=levels)


def build_system(source: str = "truth_social") -> str:
    """Finalny prompt systemowy etapu 1 dla danego źródła."""
    cfg = load_config()
    s = cfg["sections"]
    parts = [s["intro"], s["sec_rules"], _schema_block(cfg), s["signal_types"],
             _categories_block(cfg), _authority_block(cfg), s["strict"]]
    if source == "gpw_espi":
        parts.append(s["polish"])
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def models() -> dict:
    """Ścieżka modeli (free lista + paid_fast + verify), edytowalna w /brain."""
    return load_config()["models"]


def verify_system() -> str:
    return load_config()["sections"]["verify"]


def summary_system() -> str:
    return load_config()["sections"]["summary"]


# ---------------------------------------------------------------- mnożniki (dla strategy)

def category_mult(news_type: str | None) -> float:
    cat = load_config()["categories"].get(news_type or "")
    if not cat:
        return 1.0
    try:
        return max(0.1, min(2.0, float(cat.get("mult", 1.0))))
    except (TypeError, ValueError):
        return 1.0


def authority_mult(level: str | None) -> float:
    auth = load_config()["authority"].get(level or "")
    if not auth:
        return 1.0
    try:
        return max(0.1, min(2.0, float(auth.get("mult", 1.0))))
    except (TypeError, ValueError):
        return 1.0
