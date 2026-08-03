"""Wydarzenia ekonomiczne — to, co rusza rynkiem poza raportami spółek.

Źródło: publiczne API kalendarza FXStreet. Wybrane po testach, bo jako jedyne
dostępne bez klucza daje naraz cztery rzeczy, których potrzebujemy:
  * **Polskę** (dane GUS, decyzje RPP) obok reszty świata — investing.com i NBP
    odrzucają zapytania serwera, bankier renderuje kalendarz dopiero w przeglądarce;
  * **wagę** wydarzenia (NONE/LOW/MEDIUM/HIGH) — bez niej kalendarz to szum;
  * konsensus / poprzednią / rzeczywistą wartość;
  * opis, po co komu ten wskaźnik.

Nazwy tłumaczymy na polski tam, gdzie to ma sens (`_PL`); dla reszty zostaje
oryginał — lepszy niż tłumaczenie na siłę, bo owner i tak zna te skróty z rynku.
"""

import datetime as dt
import logging
import re
import unicodedata

import requests

from . import cache

log = logging.getLogger("earnings.econ")

API = "https://calendar-api.fxstreet.com/en/api/v1"
TTL_UPCOMING = 1800        # przyszłość: konsensus bywa korygowany
TTL_TODAY = 300            # dziś: odczyty wchodzą na bieżąco
TTL_PAST = 7 * 24 * 3600
TTL_DETAIL = 30 * 24 * 3600
TTL_HISTORY = 12 * 3600

_session = requests.Session()
_session.headers.update({**cache.UA, "Referer": "https://www.fxstreet.com/"})

IMPORTANCE = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}

# kraje, które realnie ruszają portfelem ownera (USA + Europa + Polska + Azja)
DEFAULT_COUNTRIES = [
    "US", "EMU", "DE", "PL", "UK", "CN", "JP", "FR", "IT", "ES", "CH", "CA",
]

_FLAGS = {"EMU": "🇪🇺", "UK": "🇬🇧"}

_NAMES = {
    "US": "USA", "EMU": "Strefa euro", "DE": "Niemcy", "PL": "Polska",
    "UK": "Wielka Brytania", "CN": "Chiny", "JP": "Japonia", "FR": "Francja",
    "IT": "Włochy", "ES": "Hiszpania", "CH": "Szwajcaria", "CA": "Kanada",
    "AU": "Australia", "NZ": "Nowa Zelandia", "KR": "Korea Płd.", "IN": "Indie",
    "BR": "Brazylia", "MX": "Meksyk", "RU": "Rosja", "TR": "Turcja",
    "CZ": "Czechy", "HU": "Węgry", "SE": "Szwecja", "NO": "Norwegia",
    "DK": "Dania", "NL": "Holandia", "AT": "Austria", "PT": "Portugalia",
    "IE": "Irlandia", "GR": "Grecja", "FI": "Finlandia", "ZA": "RPA",
    "SG": "Singapur", "HK": "Hongkong", "IL": "Izrael", "SA": "Arabia Saudyjska",
}

# Tłumaczenia najczęstszych pozycji. Podmieniamy dopasowany fragment W MIEJSCU,
# a nie całą nazwę — inaczej „Durable Goods Orders", „...ex Transportation" i
# „...(MoM)" zlewają się w trzy identyczne wiersze i kalendarz wygląda na zepsuty.
_PL = [
    ("interest rate decision", "Decyzja o stopach procentowych"),
    ("fomc statement", "Komunikat FOMC"),
    ("fomc minutes", "Protokół z posiedzenia FOMC"),
    ("fomc economic projections", "Projekcje gospodarcze FOMC"),
    ("fomc press conference", "Konferencja prasowa FOMC"),
    ("monetary policy statement", "Komunikat o polityce pieniężnej"),
    ("press conference", "Konferencja prasowa"),
    ("nonfarm payrolls", "Zatrudnienie poza rolnictwem (NFP)"),
    ("net change in employment", "Zmiana zatrudnienia"),
    ("unemployment rate", "Stopa bezrobocia"),
    ("employment change", "Zmiana zatrudnienia"),
    ("initial jobless claims", "Wnioski o zasiłek dla bezrobotnych"),
    ("continuing jobless claims", "Kontynuowane wnioski o zasiłek"),
    ("adp employment change", "Zatrudnienie ADP"),
    ("average hourly earnings", "Średnie wynagrodzenie godzinowe"),
    ("harmonized index of consumer prices", "Inflacja HICP"),
    ("consumer price index", "Inflacja CPI"),
    ("retail trade", "Obroty handlu detalicznego"),
    ("producer price index", "Inflacja producencka PPI"),
    ("core pce", "Inflacja bazowa PCE"),
    ("net inflation", "Inflacja bazowa"),
    ("core inflation", "Inflacja bazowa"),
    ("unemployment (mom)", "Bezrobocie rejestrowane"),
    ("unemployment (yoy)", "Bezrobocie rejestrowane"),
    ("beige book", "Beżowa Księga Fed"),
    ("fomc member", "Wystąpienie członka FOMC"),
    ("reference rate", "Stopa referencyjna"),
    ("personal consumption expenditures", "Wydatki konsumpcyjne PCE"),
    ("gross domestic product", "PKB"),
    ("retail sales", "Sprzedaż detaliczna"),
    ("industrial production", "Produkcja przemysłowa"),
    ("industrial output", "Produkcja przemysłowa"),
    ("ism manufacturing pmi", "ISM przemysł"),
    ("ism services pmi", "ISM usługi"),
    ("manufacturing pmi", "PMI przemysł"),
    ("services pmi", "PMI usługi"),
    ("composite pmi", "PMI złożony"),
    ("consumer confidence", "Nastroje konsumentów"),
    ("consumer sentiment", "Nastroje konsumentów"),
    ("michigan consumer sentiment", "Nastroje konsumentów (Michigan)"),
    ("trade balance", "Bilans handlowy"),
    ("current account", "Rachunek bieżący"),
    ("durable goods orders", "Zamówienia na dobra trwałe"),
    ("factory orders", "Zamówienia w przemyśle"),
    ("housing price index", "Indeks cen nieruchomości"),
    ("house price index", "Indeks cen nieruchomości"),
    ("building permits", "Pozwolenia na budowę"),
    ("housing starts", "Rozpoczęte budowy domów"),
    ("existing home sales", "Sprzedaż domów na rynku wtórnym"),
    ("new home sales", "Sprzedaż nowych domów"),
    ("crude oil inventories", "Zapasy ropy naftowej"),
    ("eia crude oil stocks", "Zapasy ropy (EIA)"),
    ("budget balance", "Saldo budżetu"),
    ("money supply", "Podaż pieniądza"),
    ("central bank fx reserves", "Rezerwy walutowe banku centralnego"),
    ("wages", "Wynagrodzenia"),
    ("speech", "Wystąpienie"),
    ("testifies", "Wystąpienie przed Kongresem"),
    ("bank holiday", "Dzień wolny — giełda zamknięta"),
    ("holiday", "Święto"),
]

# słowa, po których poznajemy bank centralny — decyzje i wystąpienia szefów.
# „Fed's Musalem speech" tak, „Philadelphia Fed Manufacturing Survey" nie — regionalne
# ankiety oddziałów Fed to zwykłe dane, nie polityka pieniężna, stąd apostrof w wzorcu.
_FED = re.compile(
    r"\bfomc\b|\bfed's\b|federal reserve|powell|beige book|"
    r"fed (interest )?rate decision", re.I)
#  UWAGA: bez samego „central bank" — łapało „Central Bank FX Reserves", które jest
#  zwykłym odczytem danych, nie decyzją banku
_CB = re.compile(
    r"interest rate decision|rate decision|monetary policy|rate statement|"
    r"\becb\b|lagarde|\bboe\b|\bboj\b|\bsnb\b|\bnbp\b|\brpp\b|"
    r"central bank.*(speech|decision|governor|president)", re.I)


def _flag(code: str) -> str:
    code = (code or "").upper()
    if code in _FLAGS:
        return _FLAGS[code]
    if len(code) != 2 or not code.isalpha():
        return "🏳️"
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in code)


# kwalifikatory, które odróżniają warianty tego samego wskaźnika
_QUALIFIERS = [
    (re.compile(r"\(MoM\)", re.I), "m/m"),
    (re.compile(r"\(YoY\)", re.I), "r/r"),
    (re.compile(r"\(QoQ\)", re.I), "kw/kw"),
    (re.compile(r"\(WoW\)", re.I), "tyg/tyg"),
    (re.compile(r"\bAnnualized\b", re.I), "annualizowane"),
    (re.compile(r"\bex\b", re.I), "bez"),
    (re.compile(r"\bPrelim(inary)?\b", re.I), "wstępny"),
    (re.compile(r"\bFinal\b", re.I), "finalny"),
    (re.compile(r"\bFlash\b", re.I), "szybki szacunek"),
    # „n.s.a" musi iść PRZED „s.a", inaczej zostaje „n.wyrównane sezonowo"
    (re.compile(r"(?<![\w.])n\.s\.a\.?", re.I), "niewyrównane sezonowo"),
    (re.compile(r"(?<![\w.])s\.a\.?", re.I), "wyrównane sezonowo"),
    (re.compile(r"\bPrice Index\b", re.I), "indeks cen"),
]


# dłuższe wzorce najpierw — „michigan consumer sentiment" musi wygrać z „consumer sentiment"
_PL_SORTED = sorted(_PL, key=lambda x: -len(x[0]))
_CORE = re.compile(r"^core\s+", re.I)


def _translate(name: str) -> str:
    """Nazwa po polsku z zachowaniem tego, co odróżnia warianty (m/m, r/r, bazowy…)."""
    text = (name or "").strip()
    # „Core X" po polsku brzmi „X bazowy", a nie „bazowa X" — stąd osobne przestawienie
    core = bool(_CORE.match(text))
    if core:
        text = _CORE.sub("", text)
    low = text.lower()
    for needle, pl in _PL_SORTED:
        at = low.find(needle)
        if at < 0:
            continue
        text = (text[:at] + pl + text[at + len(needle):]).strip()
        break
    for rx, pl in _QUALIFIERS:
        text = rx.sub(pl, text)
    # po podmianie zostaje czasem osierocone „Index" („Nastroje konsumentów Index")
    text = re.sub(r"\s+Index\b", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" -–")
    return f"{text} (bazowy)" if core else text


def _kind(raw: dict) -> str:
    name = raw.get("name") or ""
    if _FED.search(name):
        return "fed"
    if _CB.search(name):
        return "cb"
    if raw.get("isSpeech"):
        return "speech"
    # święta i dni wolne przychodzą jako całodniowe pozycje bez żadnej wagi —
    # nazwy bywają lokalne („Assumption of the Blessed Virgin Mary"), więc nie
    # da się ich rozpoznać po słowie kluczowym
    if raw.get("isAllDay") and IMPORTANCE.get(raw.get("volatility") or "NONE", 0) == 0:
        return "holiday"
    return "data"


def _strip_html(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = (t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#039;", "'")
          .replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">"))
    # w opisach FXStreet zdarzają się bajty spoza UTF-8 (widać je jako U+FFFD)
    t = "".join(c for c in t if unicodedata.category(c)[0] != "C" or c in "\n\t")
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _num(v):
    return float(v) if isinstance(v, (int, float)) else None


def _fmt_value(v, unit: str, potency: str) -> str:
    """„47.5" + unit „%" → „47,5%"; z potency B/M robimy „11,3 mld"."""
    if v is None:
        return ""
    mult = {"K": " tys.", "M": " mln", "B": " mld", "T": " bln"}.get((potency or "").upper(), "")
    txt = f"{v:,.2f}".replace(",", " ").replace(".", ",").rstrip("0").rstrip(",")
    u = unit or ""
    if u == "%":
        return f"{txt}%{mult}"
    if u:
        return f"{txt}{mult} {u}".strip()
    return f"{txt}{mult}"


def _event(raw: dict) -> dict:
    ts = raw.get("dateUtc") or ""
    when = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
    unit = raw.get("unit") or ""
    potency = raw.get("potency") or ""
    name = raw.get("name") or ""
    country = (raw.get("countryCode") or "").upper()
    return {
        "id": raw.get("id"),
        "event_id": raw.get("eventId"),
        "ts": int(when.timestamp()) if when else None,
        "date": when.date().isoformat() if when else "",
        "country": country,
        "country_name": _NAMES.get(country, country),
        "flag": _flag(country),
        "currency": raw.get("currencyCode") or "",
        "name": name,
        "name_pl": _translate(name),
        "importance": IMPORTANCE.get(raw.get("volatility") or "NONE", 0),
        "kind": _kind(raw),
        "all_day": bool(raw.get("isAllDay")),
        "tentative": bool(raw.get("isTentative")),
        "preliminary": bool(raw.get("isPreliminary")),
        "period": raw.get("periodType") or "",
        "period_date": (raw.get("periodDateUtc") or "")[:10],
        "actual": _num(raw.get("actual")),
        "consensus": _num(raw.get("consensus")),
        "previous": _num(raw.get("previous")),
        "revised": _num(raw.get("revised")),
        "actual_fmt": _fmt_value(_num(raw.get("actual")), unit, potency),
        "consensus_fmt": _fmt_value(_num(raw.get("consensus")), unit, potency),
        "previous_fmt": _fmt_value(_num(raw.get("previous")), unit, potency),
        "unit": unit,
        "potency": potency,
        "better": raw.get("isBetterThanExpected"),
        "deviation": _num(raw.get("ratioDeviation")),
        "has_history": bool(raw.get("hasHistorical")),
    }


def _fetch(start: str, end: str, countries: list, volatilities: str = "") -> list:
    """Surowa lista z API dla zakresu dat (ISO) i listy krajów.

    UWAGA: kraje trzeba podać jako POWTÓRZONY parametr (`countries=US&countries=PL`).
    Lista po przecinku zwraca 404 — sprawdzone.
    """
    query = "&".join(["volatilities=" + volatilities]
                     + [f"countries={c}" for c in countries])
    url = f"{API}/eventDates/{start}T00:00:00Z/{end}T23:59:59Z?&{query}"
    r = _session.get(url, timeout=40)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


def _ttl(end: str) -> int:
    today = dt.date.today().isoformat()
    if end < today:
        return TTL_PAST
    return TTL_TODAY if end == today else TTL_UPCOMING


# Rynki, na których owner faktycznie gra — te pokazujemy w całości.
CORE_COUNTRIES = ("PL", "US")

# Sama decyzja o stopach, bez protokołów, głosowań i „summary of opinions".
# Decyzja EBC czy BoJ rusza globalnym apetytem na ryzyko, protokół sprzed
# trzech tygodni już nie — a to on generuje większość szumu w kalendarzu.
_RATE_DECISION = re.compile(r"interest rate decision|\brate decision\b", re.I)

SCOPES = {
    "core": "Polska i USA + najważniejsze ze świata",
    "all": "Wszystkie kraje",
}


def _passes(e: dict, min_importance: int, scope: str, foreign_min: int) -> bool:
    """Czy wydarzenie w ogóle ma się pojawić w kalendarzu."""
    country = e["country"]

    # Polska ma u FXStreet konsekwentnie wagę LOW — nawet CPI i PKB. Dla ownera
    # to jednak rynek macierzysty, więc polskie odczyty przepuszczamy zawsze.
    if country == "PL":
        return e["importance"] >= 1 or e["kind"] in ("fed", "cb")

    if country == "US":
        return e["importance"] >= min_importance or e["kind"] in ("fed", "cb")

    if scope == "all":
        return e["importance"] >= min_importance or e["kind"] in ("fed", "cb")

    # Reszta świata: tylko to, co naprawdę rusza rynkiem — najwyższa waga
    # albo sama decyzja banku centralnego.
    return e["importance"] >= foreign_min or bool(_RATE_DECISION.search(e["name"]))


def events(start: str, end: str, countries: list | None = None,
           min_importance: int = 1, scope: str = "core",
           foreign_min: int = 3) -> list:
    """Wydarzenia w zakresie, posortowane po dacie i wadze.

    `scope="core"` (domyślnie) zostawia Polskę i USA w całości, a z pozostałych
    krajów przepuszcza wyłącznie odczyty o wadze `foreign_min` i decyzje o stopach.
    Bez tego jeden czwartek potrafi mieć 45 pozycji z pół świata i kalendarz
    przestaje się nadawać do czytania.
    """
    cc = [c.upper() for c in (countries or DEFAULT_COUNTRIES)]
    key = f"fxs-{start}-{end}-{'_'.join(cc)}"

    def build():
        return [_event(x) for x in _fetch(start, end, cc)]

    rows = cache.cached(key, _ttl(end), build) or []
    out = [e for e in rows if _passes(e, min_importance, scope, foreign_min)]
    out.sort(key=lambda e: (e["date"], -e["importance"], e["ts"] or 0))
    return out


def by_day(start: str, end: str, countries: list | None = None,
           min_importance: int = 1, scope: str = "core",
           foreign_min: int = 3) -> dict:
    out: dict = {}
    for e in events(start, end, countries, min_importance, scope, foreign_min):
        out.setdefault(e["date"], []).append(e)
    return out


# ---------------- szczegóły pojedynczego wydarzenia ----------------

def detail(event_id: str) -> dict:
    """Opis wskaźnika: po co się go liczy i co znaczy odczyt wyższy od prognozy."""
    def build():
        r = _session.get(f"{API}/events/{event_id}", timeout=25)
        r.raise_for_status()
        d = r.json() or {}
        return {
            "event_id": event_id,
            "category": ((d.get("category") or {}).get("name") or ""),
            "description": _strip_html(d.get("description") or ""),
            "rise": d.get("rise") or "",          # POSITIVE = wyższy odczyt sprzyja walucie
            "unit": d.get("unit") or "",
            "potency": d.get("potency") or "",
            "period": d.get("periodType") or "",
            "is_speech": bool(d.get("isSpeech")),
            "is_report": bool(d.get("isReport")),
            "source_name": d.get("sourceName") or "",
            "source_url": d.get("sourceUrl") or "",
        }

    return cache.cached(f"fxs-detail-{event_id}", TTL_DETAIL, build) or {"event_id": event_id}


def history(event_id: str, country: str, points: int = 12) -> list:
    """Poprzednie odczyty tego samego wskaźnika — do wykresu w szczegółach.

    API nie ma osobnej ścieżki na historię, więc bierzemy rok kalendarza dla
    danego kraju (jedno zapytanie, cache na pół doby) i filtrujemy po `eventId`.
    """
    today = dt.date.today()
    start = (today - dt.timedelta(days=400)).isoformat()
    end = today.isoformat()
    cc = (country or "US").upper()
    key = f"fxs-year-{cc}-{end}"

    def build():
        return [_event(x) for x in _fetch(start, end, [cc])]

    rows = cache.cached(key, TTL_HISTORY, build) or []
    hits = [e for e in rows if e["event_id"] == event_id]
    hits.sort(key=lambda e: e["ts"] or 0)

    # W hurtowej odpowiedzi starsze wpisy często mają puste `actual`, ale `previous`
    # kolejnej publikacji to dokładnie ten sam odczyt — uzupełniamy nim wstecz.
    for i, e in enumerate(hits[:-1]):
        if e["actual"] is None and hits[i + 1]["previous"] is not None:
            e["actual"] = hits[i + 1]["previous"]
            e["actual_fmt"] = _fmt_value(e["actual"], e["unit"], e["potency"])
            e["filled"] = True

    hits = [e for e in hits if e["actual"] is not None or e["consensus"] is not None]
    return hits[-points:]
