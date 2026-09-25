"""„Najciekawsze zagrania" — przesuwany pasek nad panelem Insajderów.

Ze świeżych zgłoszeń (ostatnie 30 dni ujawnień) wybieramy kilkanaście, o których
warto opowiedzieć. Każda transakcja dostaje punkty za sygnały i kary za szum:

* **konflikt interesów** (najcenniejszy) — polityk kupuje spółkę z branży, którą
  nadzoruje jego komisja; urzędnik — z branży swojego resortu; polityk — spółkę
  ze stanu, który reprezentuje; prezydent — z branży zależnej od decyzji
  administracji (tylko duże salda, patrz niżej);
* **kwota** — logarytmicznie, bo 10 mln $ nie jest dziesięć razy ciekawsze niż 1 mln $;
* **rekord osoby** — największa transakcja w jej historii mówi więcej niż sama kwota;
* **klaster** — kilka różnych osób kupuje tę samą spółkę w ciągu trzech tygodni;
* **przekonanie** — prezes albo dyrektor finansowy kupuje na rynku, bez planu 10b5-1;
* **znana osoba** — z ręcznego katalogu (Pelosi, Buffett, Musk…);
* **pod prąd** — zakup po spadku kursu o ponad 25%;
* **spóźnione zgłoszenie** — ujawnione po terminie.

Kary: sprzedaże zaplanowane z góry, realizacja opcji menedżerskich, fundusze
bez branży, opóźnione portfele 13F. Prezydent i gabinet: transakcje tej samej
spółki z jednego formularza sklejamy w SALDO — konto Trumpa prowadzą zewnętrzni
zarządzający, którzy potrafią w miesiąc kupić i sprzedać tę samą spółkę po kilka
razy. Kupno za 0,5–1 mln $ i sprzedaż za tyle samo to przetasowanie, nie sygnał.

Skąd wiemy, kto co nadzoruje:
* składy komisji Kongresu — `unitedstates/congress-legislators` (domena publiczna,
  to samo repozytorium, z którego mamy portrety i partie); tylko OBECNE składy,
  więc byli członkowie nie dostają etykiety konfliktu;
* branża spółki — kod SIC z rejestru SEC (`data.sec.gov/submissions`), razem
  z adresem siedziby (stan); raz pobrany leży w bazie miesiąc;
* kilka branż, których kod SIC nie oddaje (zdrowie zwierząt to dla SIC „leki",
  giełdy towarowe to „usługi finansowe", fundusze sektorowe nie mają kodu wcale),
  jest dopisanych ręcznie w `NADPISANE`.

Lista liczy się w tle (`jobs._petla_wyroznione`) i leży gotowa w `kv` — żądanie
aplikacji nigdy jej nie buduje. Narracje: zawsze jest wersja z szablonu (fakty
złożone w zdania); model językowy dopisuje ładniejszą w tle, raz na pozycję.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import math
import re
import time

import requests

from . import people, store

log = logging.getLogger("insiders.wyroznione")

OKNO_DNI = 30                 # ile dni wstecz patrzymy na daty UJAWNIENIA
ILE = 16                      # ile pozycji ma pasek
PLN_USD = 3.7                 # zgrubnie — tylko do porównania kwot między giełdami
KLUCZ_LISTY = "wyr:lista"

_SEC_UA = {"User-Agent": "Portevo borygoo45@gmail.com"}

# ------------------------------------------------------------------ branże

SEKTORY: dict[str, str] = {
    "leki": "leki i biotechnologia",
    "medtech": "sprzęt medyczny",
    "zdrowie": "ubezpieczenia zdrowotne i szpitale",
    "zwierzeta": "zdrowie zwierząt",
    "zbrojenia": "zbrojenia i lotnictwo wojskowe",
    "kosmos": "lotnictwo i kosmos",
    "cyber": "cyberbezpieczeństwo",
    "banki": "banki i finanse",
    "ubezpieczenia": "ubezpieczenia",
    "gieldy": "giełdy i rynki kapitałowe",
    "krypto": "kryptowaluty",
    "nieruchomosci": "nieruchomości i budownictwo mieszkaniowe",
    "ropa": "ropa i gaz",
    "energetyka": "energetyka i media",
    "gornictwo": "górnictwo i metale",
    "chemia": "chemia",
    "rolnictwo": "rolnictwo i żywność",
    "uzywki": "tytoń i alkohol",
    "polprzewodniki": "półprzewodniki",
    "technologie": "technologie i oprogramowanie",
    "telekom": "telekomunikacja i media",
    "motoryzacja": "motoryzacja",
    "transport": "transport i lotnictwo cywilne",
    "budownictwo": "budownictwo i infrastruktura",
    "edukacja": "edukacja",
    "bigtech": "największe spółki technologiczne",
}

# (od, do, branża) — zakresy kodów SIC; kolejność bez znaczenia, spółka może
# należeć do kilku branż naraz
_SIC: list[tuple[int, int, str]] = [
    (100, 999, "rolnictwo"), (1000, 1099, "gornictwo"), (1220, 1241, "gornictwo"),
    (1311, 1389, "ropa"), (1400, 1499, "gornictwo"), (1500, 1799, "budownictwo"),
    (1531, 1531, "nieruchomosci"), (2000, 2079, "rolnictwo"), (2080, 2085, "uzywki"),
    (2086, 2099, "rolnictwo"), (2100, 2199, "uzywki"), (2800, 2829, "chemia"),
    (2833, 2836, "leki"), (2840, 2869, "chemia"), (2870, 2879, "rolnictwo"),
    (2870, 2879, "chemia"), (2890, 2899, "chemia"), (2911, 2999, "ropa"),
    (3240, 3299, "budownictwo"), (3310, 3399, "gornictwo"), (3480, 3489, "zbrojenia"),
    (3523, 3524, "rolnictwo"), (3570, 3579, "technologie"), (3661, 3669, "telekom"),
    (3672, 3679, "polprzewodniki"), (3711, 3716, "motoryzacja"), (3720, 3729, "kosmos"),
    (3720, 3729, "zbrojenia"), (3760, 3769, "kosmos"), (3760, 3769, "zbrojenia"),
    (3795, 3795, "zbrojenia"), (3812, 3812, "zbrojenia"), (3826, 3826, "medtech"),
    (3841, 3851, "medtech"), (4011, 4099, "transport"), (4210, 4231, "transport"),
    (4400, 4499, "transport"), (4512, 4581, "transport"), (4610, 4619, "ropa"),
    (4800, 4899, "telekom"), (4900, 4991, "energetyka"), (4922, 4925, "ropa"),
    (5047, 5047, "medtech"), (5122, 5122, "leki"), (5171, 5172, "ropa"),
    (6000, 6199, "banki"), (6200, 6211, "gieldy"), (6211, 6299, "banki"),
    (6300, 6323, "ubezpieczenia"), (6324, 6324, "zdrowie"), (6325, 6411, "ubezpieczenia"),
    (6500, 6553, "nieruchomosci"), (6798, 6798, "nieruchomosci"),
    (7370, 7379, "technologie"), (8000, 8099, "zdrowie"), (8200, 8299, "edukacja"),
    (8731, 8731, "leki"),
]

# Ręczne dopiski: branże, których kod SIC nie oddaje, i fundusze sektorowe.
NADPISANE: dict[str, set[str]] = {
    **{t: {"zwierzeta", "leki", "rolnictwo"} for t in ("ZTS", "ELAN", "IDXX", "PAHC", "NEOG")},
    **{t: {"gieldy", "rolnictwo"} for t in ("CME", "ICE")},       # CFTC → komisje rolnictwa
    **{t: {"gieldy"} for t in ("CBOE", "NDAQ", "MKTX", "TW", "VIRT", "IBKR", "SCHW", "HOOD")},
    **{t: {"krypto", "gieldy"} for t in ("COIN", "MSTR", "MARA", "RIOT", "CLSK", "HUT",
                                         "CORZ", "GLXY", "BTBT", "CRCL", "BLSH")},
    **{t: {"krypto"} for t in ("IBIT", "FBTC", "GBTC", "ARKB", "BITB", "ETHA", "BITO")},
    **{t: {"cyber", "technologie"} for t in ("CRWD", "PANW", "FTNT", "ZS", "S", "OKTA",
                                             "CYBR", "NET", "TENB", "RPD", "QLYS", "CHKP")},
    **{t: {"zbrojenia", "technologie"} for t in ("PLTR", "BAH", "LDOS", "CACI", "SAIC",
                                                 "KTOS", "AVAV", "PSN", "BBAI")},
    **{t: {"kosmos", "zbrojenia"} for t in ("RKLB", "LUNR", "ASTS", "KRMN", "PL", "RDW")},
    **{t: {"bigtech", "technologie"} for t in ("GOOGL", "GOOG", "META", "AMZN", "AAPL",
                                               "MSFT", "NVDA")},
    **{t: {"polprzewodniki"} for t in ("NVDA", "AMD", "INTC", "AVGO", "QCOM", "MU", "TSM",
                                       "ASML", "AMAT", "LRCX", "KLAC", "MRVL", "SMH", "SOXX")},
    **{t: {"leki"} for t in ("XLV", "IBB", "XBI", "VHT", "XPH")},
    **{t: {"zbrojenia"} for t in ("ITA", "XAR", "PPA", "SHLD", "DFEN")},
    **{t: {"ropa"} for t in ("XLE", "XOP", "OIH", "VDE", "USO")},
    **{t: {"banki"} for t in ("XLF", "KRE", "KBE", "VFH")},
    **{t: {"energetyka"} for t in ("XLU", "VPU", "URA", "NLR")},
    **{t: {"nieruchomosci"} for t in ("XHB", "ITB", "VNQ")},
    **{t: {"gornictwo"} for t in ("GDX", "GDXJ", "SLV", "GLD", "COPX", "MP", "USAR", "LAC")},
}
# fundusze bez kodu SIC, które NIE są funduszem jednej branży — szum
_ETF_SZEROKIE = {"SPY", "VOO", "IVV", "QQQ", "VTI", "IWM", "DIA", "VEA", "VWO", "EFA",
                 "AGG", "BND", "TLT", "IEF", "SHY", "VTV", "VUG", "RSP", "SCHD", "VIG"}

# ------------------------------------------------------------- komisje Kongresu

_KOMISJE_URL = "https://unitedstates.github.io/congress-legislators/committees-current.json"
_SKLADY_URL = "https://unitedstates.github.io/congress-legislators/committee-membership-current.json"

# id komisji (bez przedrostka izby: H/S + skrót) → (polska nazwa, branże)
KOMISJE: dict[str, tuple[str, set[str]]] = {
    "HSAG": ("Komisja Rolnictwa Izby", {"rolnictwo", "zwierzeta", "gieldy", "krypto", "uzywki"}),
    "SSAF": ("Komisja Rolnictwa Senatu", {"rolnictwo", "zwierzeta", "gieldy", "krypto", "uzywki"}),
    "HSAS": ("Komisja Sił Zbrojnych Izby", {"zbrojenia", "kosmos", "cyber"}),
    "SSAS": ("Komisja Sił Zbrojnych Senatu", {"zbrojenia", "kosmos", "cyber"}),
    "HSBA": ("Komisja Usług Finansowych Izby", {"banki", "gieldy", "krypto", "ubezpieczenia",
                                                "nieruchomosci"}),
    "SSBK": ("Komisja Bankowa Senatu", {"banki", "gieldy", "krypto", "ubezpieczenia",
                                        "nieruchomosci"}),
    "HSIF": ("Komisja Energii i Handlu Izby", {"leki", "medtech", "zdrowie", "telekom",
                                               "technologie", "ropa", "energetyka",
                                               "motoryzacja", "chemia", "uzywki", "bigtech"}),
    "SSCM": ("Komisja Handlu Senatu", {"telekom", "technologie", "transport", "motoryzacja",
                                       "kosmos", "bigtech"}),
    "HSPW": ("Komisja Transportu i Infrastruktury Izby", {"transport", "budownictwo"}),
    "SSEG": ("Komisja Energii Senatu", {"ropa", "energetyka", "gornictwo"}),
    "HSII": ("Komisja Zasobów Naturalnych Izby", {"ropa", "gornictwo"}),
    "SSEV": ("Komisja Środowiska i Robót Publicznych Senatu", {"chemia", "budownictwo",
                                                               "energetyka"}),
    "SSHR": ("Komisja Zdrowia, Edukacji i Pracy Senatu", {"leki", "medtech", "zdrowie",
                                                         "edukacja"}),
    "SSFI": ("Komisja Finansów Senatu", {"zdrowie", "leki", "uzywki"}),
    "HSWM": ("Komisja Środków i Sposobów Izby", {"zdrowie", "leki", "uzywki"}),
    "HSSY": ("Komisja Nauki i Kosmosu Izby", {"kosmos", "polprzewodniki"}),
    "HSHM": ("Komisja Bezpieczeństwa Krajowego Izby", {"cyber"}),
    "SSGA": ("Komisja Bezpieczeństwa Krajowego Senatu", {"cyber"}),
    "HLIG": ("Komisja ds. Wywiadu Izby", {"zbrojenia", "cyber"}),
    "SLIN": ("Komisja ds. Wywiadu Senatu", {"zbrojenia", "cyber"}),
    "HSED": ("Komisja Edukacji i Pracy Izby", {"edukacja"}),
    "SPAG": ("Specjalna Komisja ds. Starzenia Senatu", {"zdrowie", "leki"}),
    "HSVR": ("Komisja ds. Weteranów Izby", {"zdrowie"}),
    "SSVA": ("Komisja ds. Weteranów Senatu", {"zdrowie"}),
    "HSZS": ("Komisja ds. rywalizacji z Chinami", {"polprzewodniki"}),
    # Komisje ogólne (budżet, regulamin, etyka) nie mają „swojej" branży. Komisje
    # budżetowe (HSAP/SSAP) mają ją dopiero w podkomisjach — patrz `_PODKOMISJE`.
}

# Podkomisje: słowo w nazwie → branże. Działa dla każdej komisji, także budżetowej
# („Defense", „Agriculture, …, Food and Drug Administration").
_PODKOMISJE: list[tuple[re.Pattern, set[str]]] = [
    (re.compile(r"\bDefense\b|Tactical Air|Seapower|Strategic Forces|Airland", re.I), {"zbrojenia"}),
    (re.compile(r"Cyber", re.I), {"cyber"}),
    (re.compile(r"Space|Aeronautics|Aviation", re.I), {"kosmos", "transport"}),
    (re.compile(r"Livestock|Dairy|Poultry", re.I), {"zwierzeta", "rolnictwo"}),
    (re.compile(r"Food and Drug|\bHealth\b|Health Care", re.I), {"leki", "medtech", "zdrowie"}),
    (re.compile(r"Commodit|Derivatives", re.I), {"gieldy", "rolnictwo"}),
    (re.compile(r"Digital Assets", re.I), {"krypto"}),
    (re.compile(r"Capital Markets|Securities", re.I), {"gieldy", "banki"}),
    (re.compile(r"Financial Institutions|Financial Services", re.I), {"banki"}),
    (re.compile(r"Housing", re.I), {"nieruchomosci"}),
    (re.compile(r"\bInsurance\b", re.I), {"ubezpieczenia"}),
    (re.compile(r"\bEnergy\b|Water and Power", re.I), {"energetyka", "ropa"}),
    (re.compile(r"Mining|Mineral", re.I), {"gornictwo"}),
    (re.compile(r"Communications|Telecommunications|Media", re.I), {"telekom"}),
    (re.compile(r"Antitrust|Intellectual Property|Internet|Privacy, Technology", re.I), {"bigtech"}),
    (re.compile(r"Railroads|Pipelines|Highways|Surface Transportation|Maritime", re.I), {"transport"}),
    (re.compile(r"Chemical", re.I), {"chemia"}),
    (re.compile(r"Agriculture", re.I), {"rolnictwo"}),
]
# Komisje bez własnej branży, które mają ją dopiero w podkomisjach
_NAZWY_OGOLNE = {
    "HSAP": "Komisja Budżetowa Izby", "SSAP": "Komisja Budżetowa Senatu",
    "HSJU": "Komisja Sądownictwa Izby", "SSJU": "Komisja Sądownictwa Senatu",
    "HSGO": "Komisja Nadzoru Izby", "HSFA": "Komisja Spraw Zagranicznych Izby",
    "SSFR": "Komisja Spraw Zagranicznych Senatu", "HSSM": "Komisja Małych Firm Izby",
    "SSSB": "Komisja Małych Firm Senatu",
}
_FUNKCJE = {"Chairman": "przewodniczący", "Chair": "przewodniczący",
            "Ranking Member": "lider mniejszości", "Vice Chairman": "wiceprzewodniczący",
            "Vice Chair": "wiceprzewodniczący", "Cochairman": "współprzewodniczący"}

# ----------------------------------------------------------- urzędy (OGE)

_URZEDY: list[tuple[re.Pattern, str, set[str]]] = [
    (re.compile(r"Defense|Navy|Army|Air Force", re.I), "Departament Obrony", {"zbrojenia", "kosmos", "cyber"}),
    (re.compile(r"Health and Human", re.I), "Departament Zdrowia", {"leki", "medtech", "zdrowie"}),
    (re.compile(r"Department of Energy", re.I), "Departament Energii", {"ropa", "energetyka"}),
    (re.compile(r"Interior", re.I), "Departament Zasobów Wewnętrznych", {"ropa", "gornictwo"}),
    (re.compile(r"Agriculture", re.I), "Departament Rolnictwa", {"rolnictwo", "zwierzeta"}),
    (re.compile(r"Treasury", re.I), "Departament Skarbu", {"banki", "gieldy", "krypto"}),
    (re.compile(r"Federal Reserve", re.I), "Rezerwa Federalna", {"banki", "gieldy"}),
    (re.compile(r"Commerce", re.I), "Departament Handlu", {"polprzewodniki", "telekom", "bigtech"}),
    (re.compile(r"Transportation", re.I), "Departament Transportu", {"transport", "motoryzacja"}),
    (re.compile(r"Homeland", re.I), "Departament Bezpieczeństwa Krajowego", {"cyber", "transport"}),
    (re.compile(r"Housing and Urban", re.I), "Departament Mieszkalnictwa", {"nieruchomosci"}),
    (re.compile(r"Environmental Protection", re.I), "Agencja Ochrony Środowiska", {"chemia", "ropa", "energetyka"}),
    (re.compile(r"Veterans", re.I), "Departament ds. Weteranów", {"zdrowie", "leki"}),
    (re.compile(r"Aeronautics and Space|NASA", re.I), "NASA", {"kosmos"}),
    (re.compile(r"National Intelligence", re.I), "Wywiad krajowy", {"zbrojenia", "cyber"}),
    (re.compile(r"Department of State", re.I), "Departament Stanu", {"zbrojenia"}),
    (re.compile(r"Education", re.I), "Departament Edukacji", {"edukacja"}),
    (re.compile(r"Science and Technology Policy", re.I), "Biuro Polityki Naukowej",
     {"polprzewodniki", "technologie", "bigtech"}),
]
# Prezydent decyduje o wszystkim, więc etykietę dostaje tylko to, o czym jego
# administracja decyduje najgłośniej — i tylko przy dużym saldzie (`PREZYDENT_OD`).
_PREZYDENT_SEKTORY = {"leki", "zdrowie", "zbrojenia", "ropa", "krypto", "banki", "polprzewodniki"}
PREZYDENT_OD = 1_000_000


# ------------------------------------------------------------------ pomocnicze


def _usd(t: dict, pole: str = "lo") -> float:
    """Kwota w dolarach. SEC podaje kwotę dokładną (lo = hi), Kongres i OGE —
    przedział, z którego bierzemy dolną granicę: tyle NA PEWNO."""
    lo, hi = t.get("amt_lo"), t.get("amt_hi")
    v = (lo if lo is not None else hi) if pole == "lo" else (hi if hi is not None else lo)
    v = float(v or 0)
    return v / PLN_USD if (t.get("cur") or "") == "PLN" else v


def _srodek(t: dict) -> float:
    return (_usd(t, "lo") + _usd(t, "hi")) / 2


def _sektory_sic(sic: int | None) -> set[str]:
    if not sic:
        return set()
    return {s for od, do, s in _SIC if od <= sic <= do}


def _stan(wiersz: dict) -> str:
    """Stan, który polityk reprezentuje: „TX-17" → „TX"."""
    ex = wiersz.get("extra") or {}
    s = (ex.get("state") or "").upper()
    if not s:
        m = re.search(r"-([a-z]{2})\d*$", wiersz.get("id") or "")
        s = m.group(1).upper() if m else ""
    return s[:2]


# --------------------------------------------------------- dane zewnętrzne


def sklady(max_wiek: float = 24 * 3600) -> dict[str, list[dict]]:
    """bioguide → komisje i podkomisje z branżami. Pobierane raz na dobę."""
    hit = store.kv_get("wyr:komisje")
    if isinstance(hit, dict) and time.time() - float(hit.get("at") or 0) < max_wiek:
        return hit["dane"]
    try:
        komisje = requests.get(_KOMISJE_URL, timeout=60).json()
        czlonkowie = requests.get(_SKLADY_URL, timeout=60).json()
    except Exception as e:  # noqa: BLE001 — stary skład lepszy niż żaden
        log.info("Składy komisji: %s", e)
        return (hit or {}).get("dane") or {}
    nazwy: dict[str, tuple[str, str]] = {}          # pełne id → (id komisji, nazwa podkomisji)
    for k in komisje:
        kid = k.get("thomas_id") or ""
        nazwy[kid] = (kid, "")
        for p in k.get("subcommittees") or []:
            nazwy[kid + (p.get("thomas_id") or "")] = (kid, p.get("name") or "")
    out: dict[str, list[dict]] = {}
    for pelne, lista in czlonkowie.items():
        kid, pod = nazwy.get(pelne, (pelne[:4], ""))
        nazwa, sektory = KOMISJE.get(kid, ("", set()))
        if pod:
            dodatkowe = set()
            for wzor, s in _PODKOMISJE:
                if wzor.search(pod):
                    dodatkowe |= s
            if not dodatkowe:
                continue                  # podkomisja bez branży niczego nie dokłada
            sektory = dodatkowe
            nazwa = nazwa or _NAZWY_OGOLNE.get(kid, "")
        if not sektory or not nazwa:
            continue
        for c in lista or []:
            b = c.get("bioguide")
            if not b:
                continue
            out.setdefault(b, []).append({
                "id": pelne, "nazwa": nazwa, "pod": pod, "sektory": sorted(sektory),
                "funkcja": _FUNKCJE.get(c.get("title") or "", ""),
            })
    store.kv_set("wyr:komisje", {"at": time.time(), "dane": out})
    return out


def _mapa_cik() -> dict[str, int]:
    hit = store.kv_get("wyr:cik")
    if isinstance(hit, dict) and time.time() - float(hit.get("at") or 0) < 7 * 86400:
        return hit["dane"]
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=_SEC_UA, timeout=60)
        r.raise_for_status()
        dane = {v["ticker"].upper(): int(v["cik_str"]) for v in r.json().values()}
    except Exception as e:  # noqa: BLE001
        log.info("Mapa CIK: %s", e)
        return (hit or {}).get("dane") or {}
    store.kv_set("wyr:cik", {"at": time.time(), "dane": dane})
    return dane


def profil(ticker: str, cik: dict[str, int] | None = None, pobierz: bool = True) -> dict:
    """{sic, opis, stan, nazwa, sektory} spółki. Z bazy, a gdy nie ma — z SEC."""
    t = (ticker or "").upper()
    klucz = f"wyr:spolka:{t}"
    hit = store.kv_get(klucz)
    if isinstance(hit, dict) and time.time() - float(hit.get("at") or 0) < 30 * 86400:
        return {**hit, "sektory": sorted(set(hit.get("sektory") or []) | NADPISANE.get(t, set()))}
    wynik = {"sic": None, "opis": "", "stan": "", "nazwa": "", "sektory": []}
    if t.endswith(".WA") or not pobierz:
        return {**wynik, "sektory": sorted(NADPISANE.get(t, set()))}
    nr = (cik or _mapa_cik()).get(t.replace(".", "-")) or (cik or {}).get(t)
    if nr:
        try:
            time.sleep(0.12)                          # SEC: poniżej 10 zapytań na sekundę
            r = requests.get(f"https://data.sec.gov/submissions/CIK{nr:010d}.json",
                             headers=_SEC_UA, timeout=30)
            if r.status_code == 200:
                d = r.json()
                sic = int(d.get("sic") or 0) or None
                adres = ((d.get("addresses") or {}).get("business") or {})
                wynik = {"sic": sic, "opis": d.get("sicDescription") or "",
                         "stan": (adres.get("stateOrCountry") or "").upper(),
                         "nazwa": d.get("name") or "", "sektory": sorted(_sektory_sic(sic))}
        except Exception as e:  # noqa: BLE001
            log.debug("Profil %s: %s", t, e)
            return {**wynik, "sektory": sorted(NADPISANE.get(t, set()))}
    store.kv_set(klucz, {**wynik, "at": time.time()})
    return {**wynik, "sektory": sorted(set(wynik["sektory"]) | NADPISANE.get(t, set()))}


# ------------------------------------------------------------------ konflikty


def konflikty(osoba: dict, ticker: str, prof: dict, komisje: dict, saldo_usd: float) -> list[dict]:
    """Dlaczego ta transakcja może budzić pytania. Lista od najmocniejszego powodu.

    `waga` 1.0 = bezpośredni nadzór (komisja/urząd nad branżą), mniej = słabsze
    powiązanie (stan, prezydent)."""
    sektory = set(prof.get("sektory") or [])
    out: list[dict] = []
    src = osoba.get("source")
    ex = osoba.get("extra") or {}

    if src in ("house", "senat") and sektory:
        for k in komisje.get(ex.get("bioguide") or "", []):
            wspolne = sektory & set(k["sektory"])
            if not wspolne:
                continue
            waga = 1.0 + (0.3 if k.get("pod") else 0) + (0.3 if k.get("funkcja") else 0)
            out.append({"typ": "komisja", "waga": waga, "komisja": k["nazwa"], "pod": k.get("pod", ""),
                        "funkcja": k.get("funkcja", ""), "sektor": SEKTORY[sorted(wspolne)[0]],
                        "etykieta": _krotka_komisja(k["nazwa"])})
    if src in ("house", "senat") and prof.get("stan") and prof["stan"] == _stan(osoba):
        out.append({"typ": "stan", "waga": 0.45, "stan": prof["stan"],
                    "etykieta": f"Spółka ze stanu {prof['stan']}"})
    if src == "oge" and osoba.get("cat") == "rzad" and sektory:
        for wzor, nazwa, s in _URZEDY:
            if wzor.search(osoba.get("org") or ""):
                wspolne = sektory & s
                if wspolne:
                    out.append({"typ": "urzad", "waga": 1.2, "urzad": nazwa,
                                "sektor": SEKTORY[sorted(wspolne)[0]], "etykieta": nazwa})
                break
    if src == "oge" and osoba.get("cat") == "prezydent" and abs(saldo_usd) >= PREZYDENT_OD:
        wspolne = sektory & _PREZYDENT_SEKTORY
        if wspolne:
            out.append({"typ": "prezydent", "waga": 0.6, "sektor": SEKTORY[sorted(wspolne)[0]],
                        "etykieta": "Branża zależna od decyzji rządu"})
    # najmocniejszy powód pierwszy; jedna komisja nie powinna trafić dwa razy
    # (komisja i jej podkomisja) — zostaje wyższa waga
    out.sort(key=lambda k: -k["waga"])
    widziane, czyste = set(), []
    for k in out:
        klucz = (k["typ"], k.get("komisja") or k.get("urzad") or k.get("stan") or "")
        if klucz in widziane:
            continue
        widziane.add(klucz)
        czyste.append(k)
    return czyste


def _krotka_komisja(nazwa: str) -> str:
    """„Komisja Rolnictwa Izby" → „Komisja Rolnictwa" — na etykietę w pasku."""
    return re.sub(r"\s+(Izby|Senatu)$", "", nazwa)


# ------------------------------------------------------------------- kandydaci


def _kandydaci(od: str) -> list[dict]:
    """Świeże zgłoszenia, z których w ogóle warto wybierać. Progi odcinają tysiące
    drobnych sprzedaży prezesów, zanim zaczniemy liczyć cokolwiek droższego."""
    rows = store._rows(
        "select * from trades where filed >= ? and ticker != '' and ("
        "  source in ('house','senat','oge')"
        "  or (source='sec' and side='buy' and coalesce(amt_lo,0) >= 50000)"
        "  or (source='sec' and side='sell' and planned=0 and coalesce(amt_lo,0) >= 2000000)"
        "  or (source='gpw' and side='buy' and coalesce(amt_lo,0) >= 150000)"
        "  or (source='gpw' and side='sell' and coalesce(amt_lo,0) >= 2000000)"
        "  or (source='f13' and coalesce(amt_lo,0) >= 20000000)"
        ")", (od,))
    return rows


def _grupuj(rows: list[dict]) -> list[dict]:
    """Jedna pozycja = osoba + spółka + formularz. Kongres potrafi zgłosić jeden
    zakup w trzech wierszach (trzy konta), a Trump w jednym formularzu kupuje
    i sprzedaje tę samą spółkę — wtedy liczy się saldo."""
    grupy: dict[tuple, list[dict]] = {}
    for t in rows:
        # jedno zgłoszenie = jedno saldo; kupno i sprzedaż tej samej spółki
        # w jednym formularzu to najczęściej przestawienie pozycji między kontami
        klucz = (t["person"], t["ticker"], t.get("filed") or "")
        grupy.setdefault(klucz, []).append(t)
    out = []
    for (pid, tick, filed), lista in grupy.items():
        kup = [t for t in lista if t["side"] == "buy"]
        spr = [t for t in lista if t["side"] == "sell"]
        brutto_k = sum(_srodek(t) for t in kup)
        brutto_s = sum(_srodek(t) for t in spr)
        saldo = brutto_k - brutto_s
        przetasowanie = False
        if kup and spr:
            # saldo mniejsze niż połowa większej ze stron = zarządzający przestawił
            # pozycję tam i z powrotem; nic tu nie ma do opowiadania
            przetasowanie = abs(saldo) < 0.5 * max(brutto_k, brutto_s)
        strona = "buy" if saldo >= 0 else "sell"
        glowne = kup if strona == "buy" else spr
        lo = sum(_usd(t, "lo") for t in glowne) - (sum(_usd(t, "hi") for t in (spr if strona == "buy" else kup)))
        hi = sum(_usd(t, "hi") for t in glowne) - (sum(_usd(t, "lo") for t in (spr if strona == "buy" else kup)))
        mieszana = bool(kup and spr)
        lo_org = sum(float(t.get("amt_lo") or 0) for t in glowne)
        hi_org = sum(float(t.get("amt_hi") or t.get("amt_lo") or 0) for t in glowne)
        out.append({
            "person": pid, "ticker": tick, "filed": filed, "side": strona,
            "date": max(t["date"] for t in glowne), "source": lista[0]["source"],
            "trades": sorted(lista, key=lambda t: t["date"]),
            "usd_lo": max(0.0, lo) if mieszana else sum(_usd(t, "lo") for t in glowne),
            "usd_hi": max(0.0, hi) if mieszana else sum(_usd(t, "hi") for t in glowne),
            "saldo": saldo, "mieszana": mieszana, "przetasowanie": przetasowanie,
            # kwota do pokazania w walucie zgłoszenia
            "lo": None if mieszana else lo_org, "hi": None if mieszana else hi_org,
            "net": round(saldo) if mieszana else None,
            "cur": lista[0].get("cur") or "USD",
        })
    return out


# ---------------------------------------------------------------- punktacja


def _punkty_kwoty(usd: float) -> float:
    return max(0.0, min(4.0, math.log10(max(usd, 1)) - 3.5))


def _klastry(od: str) -> dict[str, set[str]]:
    """ticker → osoby, które go KUPIŁY w oknie. Liczymy po dacie transakcji z szerszym
    zapasem (Kongres zgłasza z opóźnieniem), a potem zawężamy do 21 dni."""
    rows = store._rows("select person, ticker, date from trades where side='buy' and date >= ? "
                       "and ticker != '' and options=0", (od,))
    out: dict[str, list[tuple[str, str]]] = {}
    for r in rows:
        out.setdefault(r["ticker"], []).append((r["date"], r["person"]))
    return out  # type: ignore[return-value]


def _w_klastrze(zdarzenia: list[tuple[str, str]], dzien: str) -> set[str]:
    try:
        d0 = dt.date.fromisoformat(dzien)
    except ValueError:
        return set()
    osoby = set()
    for d, p in zdarzenia:
        try:
            if abs((dt.date.fromisoformat(d) - d0).days) <= 21:
                osoby.add(p)
        except ValueError:
            continue
    return osoby


def _rekord(pid: str, side: str, usd: float, przed: str) -> bool:
    """Czy to największa transakcja tej osoby w tę stronę (z co najmniej pięciu)."""
    rows = store._rows("select amt_lo, amt_hi, cur from trades where person=? and side=? "
                       "and filed < ? order by coalesce(amt_lo,0) desc limit 1",
                       (pid, side, przed))
    ile = store._rows("select count(*) as n from trades where person=? and side=? and filed < ?",
                      (pid, side, przed))[0]["n"]
    if ile < 5 or not rows:
        return False
    return usd > _usd(rows[0], "lo") * 1.0001


def _pierwszy_od_roku(pid: str, ticker: str, dzien: str) -> bool:
    od = (dt.date.fromisoformat(dzien) - dt.timedelta(days=365)).isoformat()
    n = store._rows("select count(*) as n from trades where person=? and side='buy' "
                    "and date >= ? and date < ?", (pid, od, dzien))[0]["n"]
    return n == 0


# który powód stoi na kafelku jako pierwszy (i barwi jego ramkę)
_KOLEJNOSC_TAGOW = ["konflikt", "klaster", "rekord", "przekonanie", "kwota", "pod_prad",
                    "znany", "spoznione"]


def _ranga(pid: str) -> int:
    """Miejsce w ręcznym katalogu ważności (1 = Pelosi)."""
    for i, p in enumerate(people.KATALOG):
        if p["id"] == pid:
            return i + 1
    return 9999


def ocen(g: dict, osoba: dict, prof: dict, komisje: dict, klastry: dict) -> dict:
    """Punkty, etykiety i zdania „dlaczego to tu jest" dla jednej pozycji."""
    pkt = 0.0
    tagi: list[dict] = []
    kup = g["side"] == "buy"
    src = g["source"]
    kat = (people.curated(g["person"]) or {}).get("cat") or osoba.get("cat") or ""

    if g["przetasowanie"]:
        return {"pkt": -99.0, "tagi": [], "konflikty": []}

    usd = g["usd_lo"] if not g["mieszana"] else abs(g["saldo"])
    pkt += _punkty_kwoty(usd)
    if usd >= 1_000_000:
        tagi.append({"k": "kwota", "l": "Ponad 1 mln $" if usd < 5e6 else
                     "Ponad 5 mln $" if usd < 25e6 else "Ponad 25 mln $"})

    konf = konflikty(osoba, g["ticker"], prof, komisje, g["saldo"])
    if konf:
        # Konflikt przy zakupie za tysiąc dolarów to ciekawostka, przy milionie —
        # historia. 1 tys. $ → ×0,45, 100 tys. $ → ×0,75, 10 mln $ → ×1.
        skala = max(0.45, min(1.0, 0.45 + 0.15 * math.log10(max(usd, 1000) / 1000)))
        pkt += min(4.5, konf[0]["waga"] * 3.0 + sum(k["waga"] for k in konf[1:]) * 0.5)             * skala * (1 if kup else 0.7)
        tagi.insert(0, {"k": "konflikt", "l": konf[0]["etykieta"]})

    if kup and g["ticker"] in klastry:
        osoby = _w_klastrze(klastry[g["ticker"]], g["date"])
        if len(osoby) >= 3:
            pkt += min(3.0, 1.5 + 0.3 * (len(osoby) - 3))
            tagi.append({"k": "klaster", "l": f"{len(osoby)} insiderów kupuje", "n": len(osoby)})

    k = people.curated(g["person"]) or {}
    if kat in ("znani", "prezydent") or (k and _ranga(g["person"]) <= 12):
        pkt += 1.2
        tagi.append({"k": "znany", "l": "Znana osoba"})
    elif k:
        pkt += 0.4                        # w katalogu, ale nie z pierwszych stron gazet

    if usd >= 50_000 and _rekord(g["person"], g["side"], usd, g["filed"] or g["date"]):
        pkt += 1.0
        tagi.append({"k": "rekord", "l": "Rekord tej osoby"})

    rola = (osoba.get("role") or "")
    zaplanowane = any(t.get("planned") for t in g["trades"])
    opcje = any(t.get("options") for t in g["trades"])
    if src == "sec" and kup and not zaplanowane and not opcje and re.search(r"Prezes|CFO|finansowy", rola):
        pkt += 1.2
        tagi.append({"k": "przekonanie", "l": "Zarząd kupuje za swoje"})
        if _pierwszy_od_roku(g["person"], g["ticker"], g["date"]):
            pkt += 0.6
    if any("po terminie" in (t.get("note") or "") for t in g["trades"]):
        pkt += 0.4
        tagi.append({"k": "spoznione", "l": "Zgłoszone po terminie"})

    try:
        wiek = (dt.date.today() - dt.date.fromisoformat(g["filed"] or g["date"])).days
    except ValueError:
        wiek = 30
    pkt += 0.6 if wiek <= 2 else 0.3 if wiek <= 7 else 0

    # kary
    if not kup and not konf:
        pkt -= 0.7
    if zaplanowane:
        pkt -= 2.5
    if opcje and src == "sec":
        pkt -= 1.5
    if opcje and src in ("house", "senat"):
        pkt += 0.3                        # opcje call u polityka to świadomy zakład
    if not prof.get("sektory") and (g["ticker"] in _ETF_SZEROKIE or (not prof.get("sic") and src != "gpw")):
        pkt -= 1.5 if g["ticker"] in _ETF_SZEROKIE else 0.4
    if src == "f13":
        pkt -= 0.6
    tagi.sort(key=lambda t: _KOLEJNOSC_TAGOW.index(t["k"]) if t["k"] in _KOLEJNOSC_TAGOW else 99)
    if kat == "prezydent" and not konf:
        pkt -= 1.0                        # konto zarządzane — liczy się tylko to, co wyjątkowe
    return {"pkt": round(pkt, 2), "tagi": tagi, "konflikty": konf}


# ------------------------------------------------------------------- zdania


def _kwota_txt(lo: float | None, hi: float | None, cur: str = "USD") -> str:
    znak = "zł" if cur == "PLN" else "$"

    def f(v: float) -> str:
        a = abs(v)
        if a >= 1e9:
            return f"{v / 1e9:.1f}".replace(".", ",").replace(",0", "") + " mld"
        if a >= 1e6:
            return f"{v / 1e6:.1f}".replace(".", ",").replace(",0", "") + " mln"
        if a >= 1e3:
            return f"{round(v / 1e3):.0f} tys."
        return f"{v:.0f}"
    if lo is None and hi is None:
        return "kwota nieznana"
    if hi is None or lo is None or abs((hi or 0) - (lo or 0)) < 2:
        return f"{f(hi if hi is not None else lo)} {znak}"
    return f"{f(lo)}–{f(hi)} {znak}"


def zdania(poz: dict, osoba: dict, prof: dict, ret: float | None, spadek: float | None) -> list[str]:
    """Fakty „dlaczego to jest na liście" — pewne, bez przymiotników. Z nich składa
    się narracja zapasowa i one idą do modelu jako materiał."""
    out = []
    for k in poz["konflikty"]:
        if k["typ"] == "komisja":
            funkcja = f" ({k['funkcja']})" if k.get("funkcja") else ""
            pod = f", podkomisja „{k['pod']}”" if k.get("pod") else ""
            out.append(f"Mandat w komisji — {k['komisja']}{funkcja}{pod}. Komisja zajmuje się "
                       f"m.in. branżą: {k['sektor']}, do której należy ta spółka.")
        elif k["typ"] == "urzad":
            out.append(f"Pracuje w urzędzie: {k['urzad']}, który reguluje branżę: {k['sektor']}.")
        elif k["typ"] == "stan":
            out.append(f"Siedziba spółki leży w stanie {k['stan']}, który ta osoba reprezentuje w Kongresie.")
        elif k["typ"] == "prezydent":
            out.append(f"Branża ({k['sektor']}) zależy wprost od decyzji administracji. Majątkiem "
                       "prezydenta zarządzają zewnętrzni zarządzający, więc to nie musi być "
                       "osobista decyzja.")
    for t in poz["tagi"]:
        if t["k"] == "klaster":
            out.append(f"W ciągu trzech tygodni tę spółkę kupiło {t['n']} różnych insiderów.")
        elif t["k"] == "rekord":
            out.append("To największa transakcja tej osoby w naszej bazie.")
        elif t["k"] == "przekonanie":
            out.append("Zakup na rynku, za własne pieniądze i bez planu ustalonego z góry — "
                       "tak kupuje zarząd, który wierzy w spółkę.")
        elif t["k"] == "spoznione":
            out.append("Transakcja została zgłoszona po ustawowym terminie.")
    wlasciciele = {t.get("owner") or "" for t in poz.get("trades") or []}
    if len(wlasciciele) == 1 and "" not in wlasciciele:
        konto = {"małżonek": "Transakcja na koncie małżonka.",
                 "dziecko": "Transakcja na koncie dziecka.",
                 "wspólnie": "Transakcja na koncie wspólnym z małżonkiem."}.get(next(iter(wlasciciele)))
        if konto:
            out.append(konto + " Przepisy każą ujawniać także transakcje najbliższej rodziny.")
    if poz.get("mieszana"):
        out.append("W tym samym zgłoszeniu są i zakupy, i sprzedaże tej spółki — liczymy saldo.")
    if spadek is not None and spadek <= -25 and poz["side"] == "buy":
        out.append(f"Kupno po spadku kursu o {abs(spadek):.0f}% w trzy miesiące.")
    if ret is not None:
        znak = "+" if ret >= 0 else "−"
        out.append(f"Od dnia transakcji kurs: {znak}{abs(ret):.1f}%.".replace(".", ",", 1))
    return out


# --------------------------------------------------------------------- lista


def _kurs(ticker: str, dzien: str) -> tuple[float | None, float | None, dict | None]:
    """(zmiana od dnia transakcji %, zmiana w 3 mies. przed nią %, notowania)."""
    from . import perf
    try:
        px = perf.notowania(ticker)
    except Exception:  # noqa: BLE001
        px = None
    if not px or not px.get("c"):
        return None, None, None
    przy = perf.kurs_z_dnia(px, dzien)
    ret = round((px["c"][-1] / przy - 1) * 100, 1) if przy else None
    try:
        wczesniej = (dt.date.fromisoformat(dzien) - dt.timedelta(days=90)).isoformat()
        przed = perf.kurs_z_dnia(px, wczesniej)
    except ValueError:
        przed = None
    spadek = round((przy / przed - 1) * 100, 1) if przy and przed else None
    return ret, spadek, px


def _id(g: dict) -> str:
    return hashlib.sha1(f"{g['person']}|{g['ticker']}|{g['filed']}|{g['side']}".encode()).hexdigest()[:14]


def zbuduj(stop=None) -> dict:
    """Przelicza pasek i zapisuje go w `kv`. Woła to wątek tła co pół godziny."""
    t0 = time.time()
    dzis = dt.date.today()
    od = (dzis - dt.timedelta(days=OKNO_DNI)).isoformat()
    grupy = _grupuj(_kandydaci(od))
    osoby = store.people_rows(list({g["person"] for g in grupy}))
    komisje = sklady()
    klastry = _klastry((dzis - dt.timedelta(days=OKNO_DNI + 60)).isoformat())
    cik = _mapa_cik()

    # Profil SEC (branża, stan) pobieramy tam, gdzie może zmienić wynik: dla
    # polityków i rządu zawsze (konflikty), dla reszty dla najlepszych 60 po
    # wstępnej ocenie (kary za fundusz bez branży).
    polityczne = {g["ticker"] for g in grupy if g["source"] in ("house", "senat", "oge")}
    pobrane = 0
    for tick in sorted(polityczne):
        if stop is not None and stop.is_set():
            break
        if not store.kv_get(f"wyr:spolka:{tick}"):
            pobrane += 1
        profil(tick, cik)
    wstepne = []
    for g in grupy:
        prof = profil(g["ticker"], cik, pobierz=False)
        o = osoby.get(g["person"]) or {"id": g["person"], "source": g["source"]}
        wstepne.append((ocen(g, o, prof, komisje, klastry)["pkt"], g))
    wstepne.sort(key=lambda x: -x[0])
    for _, g in wstepne[:60]:
        profil(g["ticker"], cik)

    ocenione = []
    for _, g in wstepne[:120]:
        prof = profil(g["ticker"], cik, pobierz=False)
        o = osoby.get(g["person"]) or {"id": g["person"], "source": g["source"]}
        wynik = ocen(g, o, prof, komisje, klastry)
        if wynik["pkt"] < 2.5:
            continue
        ocenione.append({**g, **wynik, "prof": prof})
    ocenione.sort(key=lambda p: -p["pkt"])

    # Różnorodność: najwyżej dwie pozycje jednej osoby i jedna na spółkę i stronę,
    # a konflikty mają zarezerwowane miejsca — to one są solą tego paska.
    wybrane, na_osobe, spolki = [], {}, set()
    def _mozna(p: dict) -> bool:
        return na_osobe.get(p["person"], 0) < 2 and (p["ticker"], p["side"]) not in spolki
    def _wez(p: dict) -> None:
        wybrane.append(p)
        na_osobe[p["person"]] = na_osobe.get(p["person"], 0) + 1
        spolki.add((p["ticker"], p["side"]))
    for p in [p for p in ocenione if p["konflikty"] and p["konflikty"][0]["waga"] >= 1.0]:
        if len(wybrane) >= 7:
            break
        if _mozna(p):
            _wez(p)
    for p in ocenione:
        if len(wybrane) >= ILE:
            break
        if p not in wybrane and _mozna(p):
            _wez(p)
    wybrane.sort(key=lambda p: -p["pkt"])

    pozycje = []
    for p in wybrane:
        ret, spadek, _ = _kurs(p["ticker"], p["date"])
        if spadek is not None and spadek <= -25 and p["side"] == "buy":
            p["tagi"].append({"k": "pod_prad", "l": f"Po spadku {spadek:.0f}%".replace("-", "−")})
            p["tagi"].sort(key=lambda t: _KOLEJNOSC_TAGOW.index(t["k"]))
        o = osoby.get(p["person"]) or {}
        pozycje.append({
            "id": _id(p), "person": p["person"], "ticker": p["ticker"],
            "asset": (p["trades"][0].get("asset") or p["prof"].get("nazwa") or p["ticker"])[:90],
            "side": p["side"], "source": p["source"], "date": p["date"], "filed": p["filed"],
            "lo": p["lo"], "hi": p["hi"], "net": p["net"], "cur": p["cur"],
            "n": len(p["trades"]), "score": p["pkt"], "tags": p["tagi"],
            "conflicts": p["konflikty"], "sector": _sektor_txt(p["prof"]),
            "ret": ret, "why": zdania(p, o, p["prof"], ret, spadek),
            "uids": [t["uid"] for t in p["trades"]][:40],
        })
    wynik = {"at": time.time(), "items": pozycje,
             "stat": {"kandydaci": len(grupy), "ocenione": len(ocenione), "profile_pobrane": pobrane,
                      "konflikty": sum(1 for p in ocenione if p["konflikty"]),
                      "s": round(time.time() - t0, 1)}}
    store.kv_set(KLUCZ_LISTY, wynik)
    return wynik["stat"]


def _sektor_txt(prof: dict) -> str:
    s = prof.get("sektory") or []
    return SEKTORY.get(s[0], "") if s else ""


def lista() -> dict:
    hit = store.kv_get(KLUCZ_LISTY)
    return hit if isinstance(hit, dict) else {"at": 0, "items": []}


def pozycja(pid: str) -> dict | None:
    for p in lista().get("items") or []:
        if p["id"] == pid:
            return p
    return None


# ------------------------------------------------------------------- narracja


def narracja_szablon(p: dict, nazwa: str, rola: str) -> str:
    """Narracja bez modelu: kto, co, za ile, kiedy — i dlaczego to tu jest."""
    co = "kupno" if p["side"] == "buy" else "sprzedaż"
    kw = (_kwota_txt(p["lo"], p["hi"], p.get("cur") or "USD") if p.get("net") is None
          else f"saldo ok. {_kwota_txt(abs(p['net']), abs(p['net']))}")
    kto = f"{nazwa} ({rola})" if rola else nazwa
    pierwsze = (f"{kto} ujawnia {co} akcji {p['asset']} ({p['ticker']}) — {kw}. "
                f"Transakcja z {data_pl(p['date'])}, zgłoszona {data_pl(p['filed'])}.")
    return " ".join([pierwsze] + list(p.get("why") or []))


_MIESIACE = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia",
             "września", "października", "listopada", "grudnia"]


def data_pl(iso: str | None) -> str:
    try:
        d = dt.date.fromisoformat((iso or "")[:10])
    except ValueError:
        return iso or ""
    return f"{d.day} {_MIESIACE[d.month - 1]} {d.year}"


def podpis(p: dict) -> str:
    return f"{p['id']}|{len(p.get('why') or [])}|{p.get('ret')}"
