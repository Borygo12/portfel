"""Kim są persony: klasy do śledzenia, ręczny katalog najważniejszych i nazewnictwo.

Większość person powstaje sama ze zgłoszeń: każdy prezes z Form 4 i każdy
kongresmen z rejestru Izby dostaje identyfikator i opis wyliczony z danych.
Ręczny katalog `KATALOG` robi trzy rzeczy, których dane same nie dadzą:

1. **Kolejność ważności** — lista na ekranie zaczyna się od Nancy Pelosi,
   nie od najaktywniejszego dyrektora spółki biotechnologicznej.
2. **Łączenie źródeł w jedną osobę** — Elon Musk ma dwa numery CIK w SEC
   (osobny dla starych zgłoszeń), Jensen Huang też. Bez katalogu byłyby to
   dwie różne persony z połową historii każda.
3. **Klasę „znani"** — Musk formalnie jest prezesem, ale nikt nie szuka go
   wśród „prezesów spółek"; szuka go z imienia.

Opisy są celowo ponadczasowe („od lat na czele…", nie „obecny prezes") — katalog
nie wie, że ktoś właśnie zmienił stanowisko, a zgłoszenia SEC wiedzą; aktualną
funkcję i tak pokazujemy z ostatniego formularza.

**Zdjęcia**: plik `{id}.jpg` w `bot/static/insiders/`. Wrzuca je właściciel
(ma do nich prawa) do `zdjęcia do apki strony/insajderzy/`, a skrypt
`insiders/zdjecia.py` przycina je do kwadratu i robi wersję rozmytą dla widoku
bez premium. Brak pliku = kółko ze znakiem zapytania.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
import unicodedata

# ---------------------------------------------------------------- klasy

KLASY = [
    {"id": "politycy", "label": "Politycy USA", "short": "Kongres",
     "desc": "Kongresmeni muszą zgłaszać transakcje w ciągu 45 dni (STOCK Act)."},
    {"id": "prezydent", "label": "Prezydent", "short": "Prezydent",
     "desc": "Formularze 278-T urzędu etyki (OGE) — konta zarządzane przez doradców."},
    {"id": "rzad", "label": "Rząd USA", "short": "Rząd",
     "desc": "Sekretarze i szefowie agencji — te same formularze co prezydent."},
    {"id": "znani", "label": "Znani ludzie", "short": "Znani",
     "desc": "Miliarderzy i legendy rynku, którzy zgłaszają transakcje w SEC."},
    {"id": "prezesi", "label": "Prezesi i zarząd", "short": "Zarząd",
     "desc": "CEO, CFO i reszta kadry — Form 4 w ciągu dwóch dni roboczych."},
    {"id": "rada", "label": "Rada dyrektorów", "short": "Rada",
     "desc": "Członkowie rad nadzorczych spółek z USA."},
    {"id": "wlasciciele", "label": "Główni udziałowcy", "short": "Udziałowcy",
     "desc": "Właściciele co najmniej 10% akcji — osoby i fundusze."},
    {"id": "gpw", "label": "Insiderzy GPW", "short": "GPW",
     "desc": "Zarządy, rady nadzorcze i osoby z nimi związane w spółkach z warszawskiej "
             "giełdy — powiadomienia MAR art. 19 z raportów ESPI."},
]
KLASY_ID = [k["id"] for k in KLASY]

# ------------------------------------------------------------ ręczny katalog
#
# `house`: (nazwisko, pierwsza litera imienia, stan) — tak Izba zapisuje członków.
#          Stan w kluczu, bo nazwiska się powtarzają (Johnson, Kelly, Miller…).
# `oge`:   slug z repozytorium open-cabinet.
# `sec`:   numery CIK z EDGAR (sprawdzone ręcznie na ostatnim Form 4 osoby).

KATALOG: list[dict] = [
    {"id": "nancy-pelosi", "name": "Nancy Pelosi", "cat": "politycy",
     "house": ("PELOSI", "N", "CA"), "party": "D", "state": "CA-11",
     "bio": "Wieloletnia przewodnicząca Izby Reprezentantów i najczęściej śledzony "
            "portfel Kongresu. W zgłoszeniach dominują transakcje męża, Paula "
            "Pelosiego — duże pakiety akcji i opcji call spółek technologicznych."},
    {"id": "donald-trump", "name": "Donald Trump", "cat": "prezydent",
     "oge": "trump-donald-j",
     "bio": "Prezydent Stanów Zjednoczonych. Majątkiem zarządzają doradcy na kontach "
            "zarządzanych, stąd tysiące pozycji w zgłoszeniach — głównie obligacje "
            "i największe spółki z indeksu S&P 500."},
    {"id": "elon-musk", "name": "Elon Musk", "cat": "znani", "sec": [1494730],
     "bio": "Założyciel SpaceX, szef Tesli i najbogatszy człowiek świata według "
            "większości rankingów. Jego zgłoszenia w SEC potrafią poruszyć kursem "
            "całego sektora."},
    {"id": "warren-buffett", "name": "Warren Buffett", "cat": "znani", "sec": [315090],
     "f13": [1067983],
     "bio": "Legenda inwestowania, przez dekady na czele Berkshire Hathaway. Zakupy "
            "Berkshire powyżej 10% akcji spółki trafiają do SEC jako Form 4 "
            "z jego nazwiskiem."},
    {"id": "mark-zuckerberg", "name": "Mark Zuckerberg", "cat": "znani", "sec": [1548760],
     "bio": "Założyciel Facebooka i szef Meta Platforms. Regularne sprzedaże akcji "
            "idą głównie przez fundację i plan 10b5-1 ustalony z wyprzedzeniem."},
    {"id": "jeff-bezos", "name": "Jeff Bezos", "cat": "znani", "sec": [1043298],
     "bio": "Założyciel Amazona. Sprzedaje akcje w dużych, zapowiadanych transzach — "
            "pieniądze trafiają m.in. do Blue Origin."},
    {"id": "jensen-huang", "name": "Jensen Huang", "cat": "znani", "sec": [1197649, 1106277],
     "bio": "Współzałożyciel i szef Nvidii — człowiek, na którego wystąpieniach rynek "
            "zawiesza oddech. Sprzedaże akcji idą planem 10b5-1."},
    {"id": "ryan-cohen", "name": "Ryan Cohen", "cat": "znani", "sec": [1767470],
     "bio": "Twórca Chewy i szef GameStopu. Jego zakupy akcji GME to jedne "
            "z największych zakupów insiderów ostatnich lat."},
    {"id": "michael-saylor", "name": "Michael Saylor", "cat": "znani", "sec": [1079782],
     "bio": "Twarz strategii „bitcoin w bilansie” — przerobił MicroStrategy (dziś "
            "Strategy) na największego firmowego posiadacza bitcoina."},
    {"id": "carl-icahn", "name": "Carl Icahn", "cat": "znani", "sec": [921669], "f13": [921669],
     "bio": "Najsłynniejszy inwestor aktywista Wall Street. Kupuje duże pakiety "
            "i walczy z zarządami o zmiany."},
    {"id": "bill-ackman", "name": "Bill Ackman", "cat": "znani", "sec": [1056513], "f13": [1336528],
     "bio": "Szef funduszu Pershing Square, znany z koncentrowanych, głośnych zakładów "
            "i publicznych kampanii."},
    {"id": "jamie-dimon", "name": "Jamie Dimon", "cat": "znani", "sec": [1195345],
     "bio": "Od prawie dwóch dekad na czele JPMorgan Chase, największego banku w USA."},
    {"id": "larry-ellison", "name": "Larry Ellison", "cat": "znani", "sec": [901999],
     "bio": "Współzałożyciel Oracle i jeden z najbogatszych ludzi świata."},
    {"id": "alex-karp", "name": "Alex Karp", "cat": "znani", "sec": [1823951],
     "bio": "Współzałożyciel i szef Palantira. Jeden z najaktywniej sprzedających "
            "akcje prezesów w USA."},
    {"id": "peter-thiel", "name": "Peter Thiel", "cat": "znani", "sec": [1211060],
     "bio": "Współzałożyciel PayPala i Palantira, pierwszy zewnętrzny inwestor Facebooka."},
    {"id": "michael-dell", "name": "Michael Dell", "cat": "znani", "sec": [908724],
     "bio": "Założyciel Dell Technologies, który zbudował firmę w akademiku."},
    {"id": "tim-cook", "name": "Tim Cook", "cat": "znani", "sec": [1214156],
     "bio": "Następca Steve'a Jobsa na czele Apple; zasiada też w radzie Nike."},
    {"id": "satya-nadella", "name": "Satya Nadella", "cat": "znani", "sec": [1513142],
     "bio": "Szef Microsoftu, który przestawił firmę na chmurę i sztuczną inteligencję."},
    {"id": "lisa-su", "name": "Lisa Su", "cat": "znani", "sec": [1405109],
     "bio": "Szefowa AMD, autorka jednego z największych zwrotów akcji w historii branży."},
    {"id": "sundar-pichai", "name": "Sundar Pichai", "cat": "znani", "sec": [1534753],
     "bio": "Szef Alphabetu i Google'a."},
    {"id": "andy-jassy", "name": "Andy Jassy", "cat": "znani", "sec": [1374545],
     "bio": "Twórca Amazon Web Services, następca Jeffa Bezosa na czele Amazona."},
    {"id": "dara-khosrowshahi", "name": "Dara Khosrowshahi", "cat": "znani", "sec": [1184237],
     "bio": "Szef Ubera, który wyprowadził firmę na stały zysk."},
    {"id": "marc-benioff", "name": "Marc Benioff", "cat": "znani", "sec": [1294693],
     "bio": "Założyciel i szef Salesforce."},
    {"id": "nelson-peltz", "name": "Nelson Peltz", "cat": "znani", "sec": [928265],
     "bio": "Inwestor aktywista, założyciel funduszu Trian."},
    {"id": "david-tepper", "name": "David Tepper", "cat": "znani", "sec": [1181531], "f13": [1656456],
     "bio": "Założyciel funduszu Appaloosa, słynny z zakładów na odbicie po kryzysach."},

    # ------------------------------------------------ Kongres (aktywni w 2025–2026)
    {"id": "josh-gottheimer", "name": "Josh Gottheimer", "cat": "politycy",
     "house": ("GOTTHEIMER", "J", "NJ"), "party": "D", "state": "NJ-05",
     "bio": "Jeden z najaktywniej handlujących kongresmenów — często opcjami na "
            "największe spółki technologiczne."},
    {"id": "marjorie-taylor-greene", "name": "Marjorie Taylor Greene", "cat": "politycy",
     "house": ("GREENE", "M", "GA"), "party": "R", "state": "GA-14",
     "bio": "Kongresmenka z Georgii, znana z bardzo częstych, drobnych zakupów "
            "akcji dużych spółek."},
    {"id": "ro-khanna", "name": "Ro Khanna", "cat": "politycy",
     "house": ("KHANNA", "R", "CA"), "party": "D", "state": "CA-17",
     "bio": "Kongresman z Doliny Krzemowej, rekordzista liczby zgłaszanych transakcji."},
    {"id": "michael-mccaul", "name": "Michael McCaul", "cat": "politycy",
     "house": ("MCCAUL", "M", "TX"), "party": "R", "state": "TX-10",
     "bio": "Jeden z najzamożniejszych członków Kongresu; w zgłoszeniach duże "
            "pakiety spółek technologicznych."},
    {"id": "rob-bresnahan", "name": "Rob Bresnahan", "cat": "politycy",
     "house": ("BRESNAHAN", "R", "PA"), "party": "R", "state": "PA-08",
     "bio": "Kongresman z Pensylwanii, jeden z najaktywniej handlujących w obecnej kadencji."},
    {"id": "cleo-fields", "name": "Cleo Fields", "cat": "politycy",
     "house": ("FIELDS", "C", "LA"), "party": "D", "state": "LA-06",
     "bio": "Kongresman z Luizjany; w zgłoszeniach częste zakupy dużych spółek technologicznych."},
    {"id": "dan-crenshaw", "name": "Dan Crenshaw", "cat": "politycy",
     "house": ("CRENSHAW", "D", "TX"), "party": "R", "state": "TX-02",
     "bio": "Kongresman z Teksasu, były komandos Navy SEAL."},
    {"id": "kelly-morrison", "name": "Kelly Morrison", "cat": "politycy",
     "house": ("MORRISON", "K", "MN"), "party": "D", "state": "MN-03",
     "bio": "Kongresmenka z Minnesoty — najwięcej zgłoszeń transakcji w Izbie w 2025–2026."},
    {"id": "dave-taylor", "name": "Dave Taylor", "cat": "politycy",
     "house": ("TAYLOR", "D", "OH"), "party": "R", "state": "OH-02",
     "bio": "Kongresman z Ohio, jeden z najaktywniej zgłaszających transakcje."},
    {"id": "suzan-delbene", "name": "Suzan DelBene", "cat": "politycy",
     "house": ("DELBENE", "S", "WA"), "party": "D", "state": "WA-01",
     "bio": "Kongresmenka ze stanu Waszyngton, była menedżerka Microsoftu."},
    {"id": "tom-kean", "name": "Tom Kean Jr.", "cat": "politycy",
     "house": ("KEAN", "T", "NJ"), "party": "R", "state": "NJ-07",
     "bio": "Kongresman z New Jersey."},
    {"id": "tim-moore", "name": "Tim Moore", "cat": "politycy",
     "house": ("MOORE", "T", "NC"), "party": "R", "state": "NC-14",
     "bio": "Kongresman z Karoliny Północnej, wcześniej przewodniczący tamtejszej izby stanowej."},
    {"id": "gil-cisneros", "name": "Gil Cisneros", "cat": "politycy",
     "house": ("CISNEROS", "G", "CA"), "party": "D", "state": "CA-31",
     "bio": "Kongresman z Kalifornii, zwycięzca loterii, który zainwestował wygraną."},
    {"id": "scott-peters", "name": "Scott Peters", "cat": "politycy",
     "house": ("PETERS", "S", "CA"), "party": "D", "state": "CA-50",
     "bio": "Kongresman z San Diego, jeden z najzamożniejszych w Izbie."},
    {"id": "byron-donalds", "name": "Byron Donalds", "cat": "politycy",
     "house": ("DONALDS", "B", "FL"), "party": "R", "state": "FL-19",
     "bio": "Kongresman z Florydy."},
    {"id": "jared-moskowitz", "name": "Jared Moskowitz", "cat": "politycy",
     "house": ("MOSKOWITZ", "J", "FL"), "party": "D", "state": "FL-23",
     "bio": "Kongresman z Florydy."},
    {"id": "debbie-wasserman-schultz", "name": "Debbie Wasserman Schultz", "cat": "politycy",
     "house": ("WASSERMAN SCHULTZ", "D", "FL"), "party": "D", "state": "FL-25",
     "bio": "Wieloletnia kongresmenka z Florydy."},
    {"id": "kevin-hern", "name": "Kevin Hern", "cat": "politycy",
     "house": ("HERN", "K", "OK"), "party": "R", "state": "OK-01",
     "bio": "Kongresman z Oklahomy, wcześniej przedsiębiorca."},
    {"id": "max-miller", "name": "Max Miller", "cat": "politycy",
     "house": ("MILLER", "M", "OH"), "party": "R", "state": "OH-07",
     "bio": "Kongresman z Ohio."},
    {"id": "april-mcclain-delaney", "name": "April McClain Delaney", "cat": "politycy",
     "house": ("DELANEY", "A", "MD"), "party": "D", "state": "MD-06",
     "bio": "Kongresmenka z Marylandu."},
    {"id": "steve-cohen", "name": "Steve Cohen", "cat": "politycy",
     "house": ("COHEN", "S", "TN"), "party": "D", "state": "TN-09",
     "bio": "Kongresman z Tennessee (nie mylić z inwestorem Steve'em Cohenem)."},
    {"id": "rick-allen", "name": "Rick Allen", "cat": "politycy",
     "house": ("ALLEN", "R", "GA"), "party": "R", "state": "GA-12",
     "bio": "Kongresman z Georgii."},
    {"id": "jonathan-jackson", "name": "Jonathan Jackson", "cat": "politycy",
     "house": ("JACKSON", "J", "IL"), "party": "D", "state": "IL-01",
     "bio": "Kongresman z Illinois."},
    {"id": "lloyd-doggett", "name": "Lloyd Doggett", "cat": "politycy",
     "house": ("DOGGETT", "L", "TX"), "party": "D", "state": "TX-37",
     "bio": "Wieloletni kongresman z Teksasu."},
    {"id": "virginia-foxx", "name": "Virginia Foxx", "cat": "politycy",
     "house": ("FOXX", "V", "NC"), "party": "R", "state": "NC-05",
     "bio": "Kongresmenka z Karoliny Północnej."},
    {"id": "mike-kelly", "name": "Mike Kelly", "cat": "politycy",
     "house": ("KELLY", "M", "PA"), "party": "R", "state": "PA-16",
     "bio": "Kongresman z Pensylwanii."},
    {"id": "julie-johnson", "name": "Julie Johnson", "cat": "politycy",
     "house": ("JOHNSON", "J", "TX"), "party": "D", "state": "TX-32",
     "bio": "Kongresmenka z Teksasu."},

    # ---------------------------------------------------------------- Senat
    # `senat`: (nazwisko, pierwsza litera imienia) jak w rejestrze eFD.
    {"id": "tommy-tuberville", "name": "Tommy Tuberville", "cat": "politycy",
     "senat": ("TUBERVILLE", "T"), "party": "R", "state": "AL",
     "bio": "Senator z Alabamy, były trener futbolu; jeden z najaktywniej handlujących "
            "w Senacie, znany ze spóźnionych zgłoszeń."},
    {"id": "dave-mccormick", "name": "Dave McCormick", "cat": "politycy",
     "senat": ("MCCORMICK", "D"), "party": "R", "state": "PA",
     "bio": "Senator z Pensylwanii, wcześniej szef funduszu Bridgewater."},
    {"id": "ron-wyden", "name": "Ron Wyden", "cat": "politycy",
     "senat": ("WYDEN", "R"), "party": "D", "state": "OR",
     "bio": "Senator z Oregonu; w zgłoszeniach głównie transakcje żony."},
    {"id": "rick-scott", "name": "Rick Scott", "cat": "politycy",
     "senat": ("SCOTT", "R"), "party": "R", "state": "FL",
     "bio": "Senator z Florydy, jeden z najzamożniejszych członków Kongresu."},
    {"id": "markwayne-mullin", "name": "Markwayne Mullin", "cat": "politycy",
     "senat": ("MULLIN", "M"), "oge": "markwayne-mullin", "party": "R",
     "bio": "Były senator z Oklahomy, dziś w rządzie — zgłoszenia z obu urzędów w jednym profilu."},

    # ------------------------------------------- fundusze (portfele z 13F)
    # `f13`: CIK funduszu, którego kwartalne portfele (13F-HR) pokazujemy jako
    # zmiany pozycji. Dzień transakcji = koniec kwartału (patrz insiders/f13.py).
    {"id": "michael-burry", "name": "Michael Burry", "cat": "znani", "f13": [1649339],
     "bio": "Inwestor, który przewidział krach 2008 roku („Big Short”). Zamknął fundusz "
            "Scion pod koniec 2025 roku — tu jego ostatnie ujawnione portfele."},
    {"id": "ray-dalio", "name": "Ray Dalio", "cat": "znani", "f13": [1350694],
     "bio": "Założyciel Bridgewater Associates, największego funduszu hedgingowego świata."},
    {"id": "stanley-druckenmiller", "name": "Stanley Druckenmiller", "cat": "znani", "f13": [1536411],
     "bio": "Legenda funduszy makro, wieloletni partner George'a Sorosa; dziś rodzinne biuro Duquesne."},
    {"id": "cathie-wood", "name": "Cathie Wood", "cat": "znani", "f13": [1697748],
     "bio": "Szefowa ARK Invest, specjalistka od spółek „przełomowych innowacji”."},
    {"id": "george-soros", "name": "George Soros", "cat": "znani", "f13": [1029160],
     "bio": "Człowiek, który „złamał Bank Anglii”; fundusz Soros Fund Management."},
    {"id": "dan-loeb", "name": "Dan Loeb", "cat": "znani", "f13": [1040273],
     "bio": "Aktywista z funduszu Third Point, znany z ostrych listów do zarządów."},
    {"id": "seth-klarman", "name": "Seth Klarman", "cat": "znani", "f13": [1061768],
     "bio": "Szef Baupost Group, autor kultowej książki o inwestowaniu w wartość."},
    {"id": "li-lu", "name": "Li Lu", "cat": "znani", "f13": [1709323],
     "bio": "Szef Himalaya Capital, inwestor ceniony przez Charliego Mungera."},
    {"id": "bill-gates", "name": "Bill Gates", "cat": "znani", "f13": [1166559],
     "bio": "Współzałożyciel Microsoftu; portfel Gates Foundation Trust."},
    {"id": "chase-coleman", "name": "Chase Coleman", "cat": "znani", "f13": [1167483],
     "bio": "Szef Tiger Global, jednego z największych funduszy technologicznych."},

    # ---------------------------------------------------------------- Polska
    # `gpw`: nazwisko i imię tak, jak stoją w powiadomieniach MAR („Iwiński Marcin").
    {"id": "marcin-iwinski", "name": "Marcin Iwiński", "cat": "znani", "gpw": ["iwinski marcin"],
     "bio": "Współzałożyciel CD Projektu, twórcy Wiedźmina i Cyberpunka; jeden "
            "z najbogatszych Polaków."},
    {"id": "michal-kicinski", "name": "Michał Kiciński", "cat": "znani", "gpw": ["kicinski michal"],
     "bio": "Współzałożyciel CD Projektu i jeden z jego największych akcjonariuszy."},
    {"id": "tomasz-biernacki", "name": "Tomasz Biernacki", "cat": "znani", "gpw": ["biernacki tomasz"],
     "bio": "Założyciel sieci Dino, najszybciej rosnącego detalisty w Polsce."},
    {"id": "dariusz-milek", "name": "Dariusz Miłek", "cat": "znani", "gpw": ["milek dariusz"],
     "bio": "Założyciel CCC, największego obuwniczego detalisty w Europie Środkowej."},
    {"id": "adam-goral", "name": "Adam Góral", "cat": "znani", "gpw": ["goral adam"],
     "bio": "Założyciel i prezes Asseco Poland."},
    {"id": "zygmunt-solorz", "name": "Zygmunt Solorz", "cat": "znani", "gpw": ["solorz zygmunt", "solorz-zak zygmunt"],
     "bio": "Twórca Polsatu i Grupy Polsat Plus, jeden z najbogatszych Polaków."},
    {"id": "michal-solowow", "name": "Michał Sołowow", "cat": "znani", "gpw": ["solowow michal"],
     "bio": "Inwestor giełdowy, właściciel m.in. Synthosu, Cersanitu i Barlinka."},
    {"id": "leszek-czarnecki", "name": "Leszek Czarnecki", "cat": "znani", "gpw": ["czarnecki leszek"],
     "bio": "Twórca Getin Holdingu i Idea Banku, wieloletni gracz rynku finansowego."},

    # ------------------------------------------------------------- gabinet
    {"id": "scott-bessent", "name": "Scott Bessent", "cat": "rzad", "oge": "bessent-scott",
     "bio": "Sekretarz skarbu USA, wcześniej zarządzający funduszem makro."},
    {"id": "howard-lutnick", "name": "Howard Lutnick", "cat": "rzad", "oge": "lutnick-howard",
     "bio": "Sekretarz handlu USA, wcześniej szef Cantor Fitzgerald."},
    {"id": "kevin-warsh", "name": "Kevin Warsh", "cat": "rzad", "oge": "warsh-kevin",
     "bio": "Ekonomista i bankier, wcześniej członek zarządu Rezerwy Federalnej."},
]

# Kolejność ważności. Pierwsza trójka dostaje w aplikacji złotą, srebrną
# i brązową ramkę — Pelosi, Trump i Musk to trzy nazwiska, od których ludzie
# zaczynają rozmowę o „insiderach". Dalej kongresmeni przeplatani z nazwiskami,
# które zna każdy — lista ma od pierwszego ekranu pokazywać obie strony tematu.
_KOLEJNOSC = [
    "nancy-pelosi", "donald-trump", "elon-musk", "warren-buffett", "josh-gottheimer",
    "mark-zuckerberg", "marjorie-taylor-greene", "jensen-huang", "ro-khanna", "jeff-bezos",
    "michael-mccaul", "ryan-cohen", "dan-crenshaw", "scott-bessent", "howard-lutnick",
    "rob-bresnahan", "michael-saylor", "cleo-fields", "bill-ackman", "carl-icahn",
]
_PIERWOTNA = {p["id"]: i for i, p in enumerate(KATALOG)}
KATALOG.sort(key=lambda p: (_KOLEJNOSC.index(p["id"]) if p["id"] in _KOLEJNOSC
                            else len(_KOLEJNOSC) + _PIERWOTNA[p["id"]]))
for _i, _p in enumerate(KATALOG):
    _p["rank"] = _i + 1

BY_ID = {p["id"]: p for p in KATALOG}
_BY_CIK = {cik: p["id"] for p in KATALOG for cik in p.get("sec", [])}
_BY_OGE = {p["oge"]: p["id"] for p in KATALOG if p.get("oge")}
_BY_HOUSE = {p["house"]: p["id"] for p in KATALOG if p.get("house")}
_BY_GPW = {k: p["id"] for p in KATALOG for k in p.get("gpw", [])}
_BY_SENAT = {p["senat"]: p["id"] for p in KATALOG if p.get("senat")}

PARTIE = {"D": "Demokraci", "R": "Republikanie", "I": "Niezależni"}


# ------------------------------------------------------------ identyfikatory


def _ascii(text: str) -> str:
    # „ł" nie rozkłada się w NFKD i bez tego znikało: Miłek → „mek"
    t = (text or "").replace("ł", "l").replace("Ł", "L")
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()


def slug(text: str) -> str:
    t = _ascii(text)
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:60] or "x"


def for_sec(cik) -> str:
    try:
        c = int(cik)
    except (TypeError, ValueError):
        return ""
    return _BY_CIK.get(c) or f"sec-{c}"


def for_house(last: str, first: str, state: str) -> str:
    klucz = ((last or "").upper().strip(), (first or "?").strip()[:1].upper(),
             (state or "")[:2].upper())
    return _BY_HOUSE.get(klucz) or f"house-{slug(last)}-{slug(first.split()[0] if first else '')}-{slug(state)}"


def for_senat(last: str, first: str, stan: str = "") -> str:
    l = re.sub(r",?\s*(jr|sr|iii|ii)\.?$", "", (last or "").strip(), flags=re.I)
    klucz = (l.upper(), (first or "?").strip()[:1].upper())
    return _BY_SENAT.get(klucz) or f"senat-{slug(l)}-{slug((first or '').split()[0] if first else '')}"


def klucz_gpw(nazwa: str) -> str:
    """„Iwiński Marcin" → „iwinski marcin" — po tym łączymy z katalogiem."""
    t = _ascii(nazwa)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z\- ]", " ", t.lower())).strip()


def for_gpw(nazwa: str) -> str:
    k = klucz_gpw(nazwa)
    return _BY_GPW.get(k) or f"gpw-{slug(k)}"


def for_oge(slug_: str) -> str:
    return _BY_OGE.get(slug_) or f"oge-{slug_}"


def curated(pid: str) -> dict | None:
    return BY_ID.get(pid)


# ------------------------------------------------------------------ nazwy

_FIRMA = re.compile(
    r"\b(INC|INCORPORATED|CORP|CORPORATION|LLC|L\.L\.C|LP|L\.P|LTD|LIMITED|FUND|FUNDS|"
    r"CAPITAL|TRUST|HOLDINGS?|PARTNERS|PARTNERSHIP|MANAGEMENT|ADVISORS?|VENTURES?|GROUP|"
    r"COMPANY|CO|PLC|AG|SA|NV|BV|GMBH|FOUNDATION|INVESTMENTS?|ASSOCIATES|SPV|MASTER|"
    r"OPPORTUNITY|OPPORTUNITIES|EQUITY|BANK|BANCORP|FINANCIAL|ASSET|ASSETS|"
    r"SP\.?\s*Z\s*O\.?\s*O|SPÓŁKA|SPOLKA|S\.A|SKA|FIZ|TFI|ASI|FUNDACJA|FUNDUSZ|HOLDING)\b\.?")
_SUFIKS = {"JR", "JR.", "SR", "SR.", "II", "III", "IV", "MD", "PHD", "DR"}


def czy_firma(name: str) -> bool:
    return bool(_FIRMA.search((name or "").upper()))


_MALE = {"of", "and", "the", "for", "de", "da", "del", "la", "on", "in", "at", "&"}
# nazwy, których zapisu nie zgadnie żadna reguła
_WLASNE = {"JPMORGAN": "JPMorgan", "AT&T": "AT&T", "IBM": "IBM", "AMD": "AMD", "HP": "HP",
           "UPS": "UPS", "CVS": "CVS", "PG&E": "PG&E", "3M": "3M", "AES": "AES", "CSX": "CSX",
           "IQVIA": "IQVIA", "SPDR": "SPDR", "ETF": "ETF", "REIT": "REIT", "USA": "USA"}


def _tytulowo(s: str) -> str:
    out = []
    for i, w in enumerate(s.split()):
        if w.upper() in _WLASNE:
            out.append(_WLASNE[w.upper()])
            continue
        if i and w.lower() in _MALE:
            out.append(w.lower())
            continue
        if len(w) <= 3 and w.upper() in {"LLC", "LP", "LTD", "II", "III", "IV", "USA", "AG", "SA", "NV", "PLC"}:
            out.append(w.upper())
        elif "-" in w:
            out.append("-".join(p[:1].upper() + p[1:].lower() for p in w.split("-")))
        elif w.startswith("MC") and len(w) > 3:
            out.append("Mc" + w[2:3].upper() + w[3:].lower())
        else:
            out.append(w[:1].upper() + w[1:].lower())
    return " ".join(out)


def nazwa_sec(raw: str) -> str:
    """„COOK TIMOTHY D" → „Timothy D Cook"; firmy zostają firmami.

    SEC zapisuje osoby jako NAZWISKO IMIĘ DRUGIE. Odwracamy to tylko dla ludzi —
    „Berkshire Hathaway Inc" czytane od tyłu byłoby nonsensem.
    """
    s = re.sub(r"\s+", " ", (raw or "").replace(",", " ")).strip()
    if not s:
        return ""
    if czy_firma(s):
        return _tytulowo(s)
    parts = s.split(" ")
    suf = [p for p in parts[1:] if p.upper().strip(".") in {x.strip(".") for x in _SUFIKS}]
    rest = [p for p in parts[1:] if p not in suf]
    if not rest:
        return _tytulowo(s)
    return _tytulowo(" ".join(rest + [parts[0]]))


def nazwa_house(first: str, last: str) -> str:
    f = (first or "").strip()
    m = re.search(r"\"([^\"]+)\"", f)
    if m:
        f = m.group(1)
    f = re.sub(r"\b(Dr|Hon)\.?\b", "", f).strip()
    pierwsze = f.split()[0] if f.split() else ""
    return f"{pierwsze} {last.strip()}".strip()


def nazwa_oge(raw: str) -> str:
    """„Bessent, Scott" → „Scott Bessent"; „Trump, Donald J." → „Donald J. Trump"."""
    if "," in (raw or ""):
        last, first = raw.split(",", 1)
        return f"{first.strip()} {last.strip()}".strip()
    return (raw or "").strip()


_PRZEDROSTKI = {"van", "von", "de", "del", "della", "la", "le", "di", "da", "du", "st", "st."}
_DWUCZLONOWE = {"taylor", "wasserman", "mcclain"}


def nazwisko(name: str) -> str:
    """Do podpisu pod twarzą na wykresie — miejsca jest na jedno słowo.

    „Van Epps", „De La Cruz" i nazwiska dwuczłonowe („Taylor Greene") zostają
    w całości — samo „Epps" pod zdjęciem nic by nikomu nie powiedziało."""
    parts = [p for p in (name or "").split() if p.upper().strip(".") not in {"JR", "SR", "II", "III", "IV"}]
    if not parts:
        return ""
    wynik = [parts[-1]]
    i = len(parts) - 2
    while i >= 1 and parts[i].lower() in _PRZEDROSTKI:
        wynik.insert(0, parts[i])
        i -= 1
    if len(wynik) == 1 and len(parts) >= 3 and parts[-2].lower() in _DWUCZLONOWE:
        wynik.insert(0, parts[-2])
    return " ".join(wynik)


# --------------------------------------------------------- funkcje po polsku

_TYTULY = [
    (r"\b(chief executive officer|ceo)\b", "Prezes (CEO)", "Prezes"),
    (r"\bpresident\b.*\b(ceo|chief executive)\b|\b(ceo|chief executive)\b.*\bpresident\b", "Prezes (CEO)", "Prezes"),
    (r"\b(chief financial officer|cfo)\b", "Dyrektor finansowy (CFO)", "CFO"),
    (r"\b(chief operating officer|coo)\b", "Dyrektor operacyjny (COO)", "COO"),
    (r"\b(chief technology officer|cto)\b", "Dyrektor ds. technologii (CTO)", "CTO"),
    (r"\b(chief accounting officer|principal accounting officer|cao)\b", "Główny księgowy", "Zarząd"),
    (r"\b(principal financial officer)\b", "Dyrektor finansowy (CFO)", "CFO"),
    (r"\b(principal executive officer)\b", "Prezes (CEO)", "Prezes"),
    (r"\b(chief legal officer|general counsel|clo)\b", "Dyrektor prawny", "Zarząd"),
    (r"\b(chief medical officer|cmo)\b", "Dyrektor medyczny", "Zarząd"),
    (r"\b(chief scientific officer|cso)\b", "Dyrektor naukowy", "Zarząd"),
    (r"\b(chief marketing officer)\b", "Dyrektor marketingu", "Zarząd"),
    (r"\b(chief people officer|chief human resources officer|chro)\b", "Dyrektor personalny", "Zarząd"),
    (r"\b(chief revenue officer|chief commercial officer)\b", "Dyrektor handlowy", "Zarząd"),
    (r"\b(executive chair(man)?)\b", "Prezes wykonawczy rady", "Prezes"),
    (r"\bchair(man|woman)?\b", "Przewodniczący rady", "Rada"),
    (r"\bpresident\b", "Prezes", "Prezes"),
    (r"\b(executive vice president|evp)\b", "Wiceprezes wykonawczy", "Zarząd"),
    (r"\b(senior vice president|svp)\b", "Starszy wiceprezes", "Zarząd"),
    (r"\b(vice president|vp)\b", "Wiceprezes", "Zarząd"),
    (r"\bdirector\b", "Członek rady dyrektorów", "Rada"),
]


def funkcja(title: str) -> tuple[str, str]:
    """(pełna nazwa funkcji po polsku, jedno słowo pod twarz na wykresie)."""
    t = (title or "").lower().strip()
    if not t or "see remarks" in t:
        return "", ""
    for wzor, pelna, krotka in _TYTULY:
        if re.search(wzor, t):
            return pelna, krotka
    return (title or "").strip(), "Zarząd"


def skroc_spolke(name: str) -> str:
    """„AMAZON COM INC" → „Amazon", „Bank of America Corp /DE/" → „Bank of America"."""
    s = re.sub(r"&amp;", "&", name or "")
    s = re.sub(r"\s*/[A-Za-z]{2,3}/?\s*$", "", s)            # dopisek stanu rejestracji
    s = re.sub(r"\s+(com|net)\.?(\s+inc\.?)?$", "", s.strip(), flags=re.I)  # „AMAZON COM INC"
    s = re.sub(r"[,.]?\s+(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|"
               r"holdings|group|n\.?v|s\.?a|l\.?p|llc)\.?$", "", s.strip(), flags=re.I)
    s = re.sub(r"[,.]?\s+(inc|corp|co|ltd|plc)\.?$", "", s.strip(), flags=re.I)
    s = s.strip(" ,.&")
    if s.isupper():
        return _tytulowo(s)
    # zapis mieszany z bazy („Bank Of America") — tylko małe słowa w środku
    return re.sub(r"(?<=\s)(Of|And|The|For)(?=\s)", lambda m: m.group(1).lower(), s)


_URZEDY = {
    "President of the United States": "Prezydent USA",
    "Vice President": "Wiceprezydent USA",
    "Secretary of the Treasury": "Sekretarz skarbu",
    "Secretary of Commerce": "Sekretarz handlu",
    "Secretary of State": "Sekretarz stanu",
    "Secretary of Defense": "Sekretarz obrony",
    "Secretary of War": "Sekretarz wojny",
    "Attorney General": "Prokurator generalny",
    "Secretary of the Interior": "Sekretarz zasobów wewnętrznych",
    "Secretary of Agriculture": "Sekretarz rolnictwa",
    "Secretary of Labor": "Sekretarz pracy",
    "Secretary of Health and Human Services": "Sekretarz zdrowia",
    "Secretary of Housing and Urban Development": "Sekretarz mieszkalnictwa",
    "Secretary of Transportation": "Sekretarz transportu",
    "Secretary of Energy": "Sekretarz energii",
    "Secretary of Education": "Sekretarz edukacji",
    "Secretary of Veterans Affairs": "Sekretarz ds. weteranów",
    "Secretary of Homeland Security": "Sekretarz bezpieczeństwa krajowego",
    "Director of National Intelligence": "Dyrektor wywiadu narodowego",
    "Administrator of the Environmental Protection Agency": "Szef agencji ochrony środowiska",
    "Administrator": "Administrator",
    "FAA Administrator": "Szef FAA (lotnictwo)",
    "NASA Administrator": "Szef NASA",
    "Director": "Dyrektor",
    "Chair": "Przewodniczący",
}


_RESORTY = {
    "Department of the Treasury": "skarbu", "Department of Commerce": "handlu",
    "Department of State": "stanu", "Department of Defense": "obrony", "Department of War": "wojny",
    "Department of Justice": "sprawiedliwości", "Department of the Interior": "zasobów wewnętrznych",
    "Department of Agriculture": "rolnictwa", "Department of Labor": "pracy",
    "Department of Health and Human Services": "zdrowia", "Department of Energy": "energii",
    "Department of Housing and Urban Development": "mieszkalnictwa",
    "Department of Transportation": "transportu", "Department of Education": "edukacji",
    "Department of Veterans Affairs": "ds. weteranów",
    "Department of Homeland Security": "bezpieczeństwa krajowego",
    "Social Security Administration": "ubezpieczeń społecznych",
    "Small Business Administration": "małych firm",
    "Environmental Protection Agency": "ochrony środowiska",
    "Office of Management and Budget": "budżetu",
}
_FUNKCJE_URZEDU = [
    ("Deputy Secretary", "Zastępca sekretarza"), ("Under Secretary", "Podsekretarz"),
    ("Assistant Secretary", "Asystent sekretarza"), ("Secretary", "Sekretarz"),
    ("Deputy Commissioner", "Zastępca komisarza"), ("Commissioner", "Komisarz"),
    ("Deputy Administrator", "Zastępca administratora"), ("Administrator", "Administrator"),
    ("Deputy Director", "Zastępca dyrektora"), ("Director", "Dyrektor"),
    ("Ambassador", "Ambasador"), ("Chairman", "Przewodniczący"), ("Chair", "Przewodniczący"),
    ("Governor", "Członek zarządu"), ("Counselor", "Doradca"), ("Advisor", "Doradca"),
]


def urzad(title: str, agency: str = "") -> str:
    """Stanowisko w administracji USA po polsku: „Sekretarz transportu",
    „Zastępca komisarza ds. ubezpieczeń społecznych". Czego nie znamy,
    zostaje po angielsku — lepsze to niż zmyślone tłumaczenie."""
    t = (title or "").strip()
    if t in _URZEDY and t not in ("Director", "Administrator", "Chair"):
        return _URZEDY[t]
    for en, pl in _URZEDY.items():
        if en.lower() in t.lower() and len(en) > 12:
            return pl
    rdzen = t.split(",")[0].strip()
    resort = _RESORTY.get((agency or "").strip())
    if not resort and "," in t:
        resort = _RESORTY.get(t.split(",", 1)[1].strip())
    for en, pl in _FUNKCJE_URZEDU:
        if rdzen.lower() == en.lower() or rdzen.lower().startswith(en.lower() + " "):
            if resort:
                return f"{pl} ({resort})" if pl.startswith(("Członek", "Doradca", "Ambasador")) \
                    else f"{pl} {'ds. ' if not resort.startswith('ds.') and pl.startswith(('Komisarz', 'Zastępca komisarza', 'Administrator', 'Zastępca administratora', 'Dyrektor', 'Zastępca dyrektora')) else ''}{resort}"
            return pl
    return t or agency


# ------------------------------------------------------------------ zdjęcia

_FOTO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "static", "insiders")
_foto_cache: dict = {"at": 0.0, "files": {}, "auto": {}}
# Sól nazw plików rozmytych. Plik rozmyty nie może nazywać się jak persona —
# wtedy ktoś bez premium odczytałby nazwisko z adresu obrazka w podglądzie sieci.
_SOL = "portevo-insajderzy-1"


def blur_name(pid: str) -> str:
    return hashlib.sha1(f"{_SOL}:{pid}".encode()).hexdigest()[:14]


def _lista(katalog: str) -> dict:
    files = {}
    try:
        for n in os.listdir(katalog):
            if n.endswith(".jpg"):
                files[n[:-4]] = int(os.path.getmtime(os.path.join(katalog, n)))
    except OSError:
        pass
    return files


def _katalog_auto() -> str:
    """Portrety pobrane przez serwer (oficjalne zdjęcia Kongresu) — na dysku danych."""
    import paths
    return os.path.join(paths.DATA_DIR, "insiders_foto")


def odswiez_zdjecia() -> None:
    _foto_cache["at"] = 0.0


def _pliki() -> tuple[dict, dict]:
    now = time.time()
    if now - _foto_cache["at"] >= 300:
        _foto_cache.update(at=now, files=_lista(_FOTO_DIR), auto=_lista(_katalog_auto()))
    return _foto_cache["files"], _foto_cache["auto"]


def foto_wlasciciela(pid: str) -> bool:
    return pid in _pliki()[0]


def plik_auto(nazwa: str) -> str:
    """Ścieżka pliku z katalogu portretów pobranych — do endpointu, który je podaje."""
    return os.path.join(_katalog_auto(), nazwa)


def foto(pid: str) -> str:
    """Adres zdjęcia albo pusty napis. Zdjęcie właściciela wygrywa z portretem
    pobranym automatycznie. Znacznik `v` zmienia się z plikiem — podmiana zdjęcia
    nie utknie w pamięci przeglądarki."""
    wl, auto = _pliki()
    if pid in wl:
        return f"/static/insiders/{pid}.jpg?v={wl[pid]}"
    if pid in auto:
        return f"/api/insiders/foto/{pid}.jpg?v={auto[pid]}"
    return ""


def foto_rozmyte(pid: str) -> str:
    wl, auto = _pliki()
    if pid in wl:
        return f"/static/insiders/b/{blur_name(pid)}.jpg"
    if pid in auto:
        return f"/api/insiders/foto/b/{blur_name(pid)}.jpg"
    return ""
