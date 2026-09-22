"""Prezydent i gabinet — formularze 278-T urzędu etyki (OGE).

OGE publikuje te formularze jako SKANY z fatalnym OCR („Don.JdJln.tmp", kwoty
„$100 001 - $250 000" z literami zamiast cyfr). Własny odczyt byłby loterią,
więc korzystamy z repozytorium `tbrown034/open-cabinet` (licencja MIT), które
przepisuje nowe formularze automatycznie i weryfikuje wiersze z oryginałem.
Każda transakcja ma tam link do źródłowego PDF-u w OGE — pokazujemy go dalej.

Druga pułapka: repozytorium prawie nie podaje tickerów. „ABBOTT LABS" czy
„APPLIED MATLS INC" to skróty z wyciągów brokera. Mapujemy je w trzech krokach:
1. ticker, jeśli jest;
2. mapa z tego samego repozytorium (`asset-mappings.json`, pole `filedAs`);
3. własne dopasowanie do rejestru spółek SEC po rozwinięciu skrótów
   („MATLS" → „MATERIALS") i po prefiksie — broker ucina nazwy na 24 znakach.

Obligacji NIE mapujemy nigdy, nawet gdy nazwa emitenta pasuje do spółki:
„MICROSOFT CORP 3.3% DUE 2027" to dług Microsoftu, a nie jego akcje, i nie
może stanąć jako twarz na wykresie akcji.
"""

from __future__ import annotations

import bisect
import hashlib
import logging
import re

import requests

from . import people, store

log = logging.getLogger("insiders.oge")

RAW = "https://raw.githubusercontent.com/tbrown034/open-cabinet/main/data"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
_UA = {"User-Agent": "Portevo borygoo45@gmail.com"}

_OBLIGACJA = re.compile(r"\d+(\.\d+)?\s*%|\bDUE\b|\bB/E\b|\bRFDG\b|\bREV\b|\bBDS?\b|\bNOTES?\b|"
                        r"\bMUNI|\bTREAS|\bBILLS?\b|\bCD\b|\bMAT\b|\bSER\s+[A-Z0-9]+\b|\bBOND", re.I)

# Fundusz, ETF, rynek pieniężny: nazwa zaczyna się od nazwy towarzystwa („INVESCO
# PREMIER U.S. GOVERNMENT MONEY MARKET…"), więc dopasowanie po prefiksie trafiało
# w akcje samego towarzystwa (IVZ). Takie nazwy przyjmujemy wyłącznie z mapy
# dokładnej, gdzie ktoś już sprawdził, co to za fundusz.
_FUNDUSZ = re.compile(r"\bFUNDS?\b|\bETF\b|MONEY\s+MARKET|\bPORTFOLIO\b|\bINDEX\b|"
                      r"\bSERIES\b|\bINSTITUTIONAL\b|\bSHARES\b|\bTR\s+UNIT|\bFEDFUND", re.I)


def _to_akcja(sym: str) -> bool:
    """Fundusze inwestycyjne (DODFX) i rynku pieniężnego (SWVXX) mają pięcioliterowe
    symbole kończące się na X. To nie są akcje ani ETF-y z giełdy — na wykresie
    i w „co kupował" byłyby tylko szumem."""
    s = (sym or "").upper()
    return bool(s) and not (len(s) == 5 and s.endswith("X"))


_SKROTY = {
    "MATLS": "MATERIALS", "MATL": "MATERIAL", "PPTYS": "PROPERTIES", "PPTY": "PROPERTY",
    "HLDGS": "HOLDINGS", "HLDG": "HOLDING", "INTL": "INTERNATIONAL", "SYS": "SYSTEMS",
    "SVCS": "SERVICES", "SVC": "SERVICE", "CMNTY": "COMMUNITY", "BK": "BANK", "GRP": "GROUP",
    "MGMT": "MANAGEMENT", "AMER": "AMERICA", "ENTMT": "ENTERTAINMENT", "PWR": "POWER",
    "ELEC": "ELECTRIC", "WTR": "WATER", "WKS": "WORKS", "RLTY": "REALTY", "TR": "TRUST",
    "PERS": "PERSONAL", "PRODS": "PRODUCTS", "CHEMS": "CHEMICALS", "FINL": "FINANCIAL",
    "INDS": "INDUSTRIES", "LABS": "LABORATORIES", "COMMUNICATIONS": "COMMUNICATIONS",
    "TECHNOLOGIES": "TECHNOLOGIES", "PHARMACEUTICAL": "PHARMACEUTICALS", "FREIGHT": "FREIGHT",
    "CORP": "", "INC": "", "CO": "", "COM": "", "LTD": "", "PLC": "", "NEW": "", "F": "",
    "THE": "", "CL": "", "CLASS": "", "A": "", "B": "", "EQUITY": "", "SHS": "", "ORD": "",
    "IRELAND": "", "N": "", "V": "", "NV": "", "SA": "", "AG": "", "REIT": "", "HLDS": "HOLDINGS",
    "UNSOLICITED": "", "SOLICITED": "",
    "MTR": "MOTOR", "MTRS": "MOTORS", "SOUTHN": "SOUTHERN", "NATL": "NATIONAL", "MED": "MEDICAL",
    "STS": "STATES", "CMNTYS": "COMMUNITIES", "INDL": "INDUSTRIAL", "INVT": "INVESTMENT",
    "RES": "RESOURCES", "WHSE": "WAREHOUSE", "NAT": "NATURAL", "DEL": "", "WIS": "", "MD": "",
    "HLD": "HOLDINGS", "BANCSHARES": "BANCSHARES", "SVGS": "SAVINGS", "COMM": "COMMUNICATIONS",
    "ENGR": "ENGINEERING", "EQUIP": "EQUIPMENT", "MFG": "MANUFACTURING", "CTRS": "CENTERS",
    "CTR": "CENTER", "SOLUTIONS": "SOLUTIONS", "DEV": "DEVELOPMENT", "ENTERPRISES": "ENTERPRISES",
}


def _norm(nazwa: str) -> str:
    # „/DE/", „/MO/" — dopiski stanu rejestracji w nazwach z rejestru SEC
    s = re.sub(r"/[A-Z]{2,3}/?", " ", (nazwa or "").upper())
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    slowa = []
    tokeny = s.split()
    for i, w in enumerate(tokeny):
        if w in ("OF", "AND", "THE"):
            continue
        # „EQUITY" wyrzucamy tylko na końcu („TARGET CORP EQUITY"),
        # bo w środku bywa częścią nazwy („EQUITY RESIDENTIAL")
        if w == "EQUITY" and i < len(tokeny) - 1:
            slowa.append(w)
            continue
        w2 = _SKROTY.get(w, w)
        if w2:
            slowa.append(w2)
    return " ".join(slowa)


class Mapa:
    """Nazwa z wyciągu → ticker. Buduje się raz na przebieg."""

    def __init__(self):
        self.dokladne: dict[str, str] = {}
        self.sec_nazwy: list[tuple[str, str]] = []

    def zbuduj(self) -> "Mapa":
        try:
            r = requests.get(f"{RAW}/meta/asset-mappings.json", timeout=60)
            r.raise_for_status()
            for sym, e in (r.json().get("assets") or {}).items():
                if (e.get("instrumentType") or "common") not in ("common", "etf", "adr", "reit", ""):
                    continue
                for f in (e.get("filedAs") or []):
                    if isinstance(f, str) and not _OBLIGACJA.search(f):
                        self.dokladne[f.strip().upper()] = sym
        except Exception as e:  # noqa: BLE001
            log.warning("Mapa aktywów open-cabinet: %s", e)
        try:
            r = requests.get(SEC_TICKERS, headers=_UA, timeout=60)
            r.raise_for_status()
            widziane = set()
            for v in r.json().values():
                cik = v.get("cik_str")
                # pierwszy ticker spółki w tym pliku to jej główna linia notowań
                if cik in widziane:
                    continue
                widziane.add(cik)
                n = _norm(v.get("title", ""))
                if n:
                    self.sec_nazwy.append((n, v["ticker"].upper()))
            self.sec_nazwy.sort()
        except Exception as e:  # noqa: BLE001
            log.warning("Rejestr spółek SEC: %s", e)
        return self

    def ticker(self, opis: str, podany: str | None) -> str:
        t = self._ticker(opis, podany)
        return t if _to_akcja(t) else ""

    def _ticker(self, opis: str, podany: str | None) -> str:
        if podany:
            return podany.upper().replace(".", "-")
        o = (opis or "").strip()
        if not o or _OBLIGACJA.search(o):
            return ""
        t = self.dokladne.get(o.upper())
        if t:
            return t.replace(".", "-")
        if _FUNDUSZ.search(o):
            return ""
        n = _norm(o)
        if len(n) < 5:
            # Krótkie nazwy („NIKE", „AON", „IAC") tylko przy dokładnej zgodności —
            # po prefiksie „AON" pasowałoby do połowy rejestru.
            j = bisect.bisect_left(self.sec_nazwy, (n, ""))
            if n and j < len(self.sec_nazwy) and self.sec_nazwy[j][0] == n:
                return self.sec_nazwy[j][1].replace(".", "-")
            return ""
        # prefiks: broker ucina nazwę, więc „PALANTIR TECHNOLOGIES IN" ma być
        # początkiem „PALANTIR TECHNOLOGIES". Z kilku trafień bierzemy najkrótsze
        # — najbliższe temu, co zostało po ucięciu.
        i = bisect.bisect_left(self.sec_nazwy, (n, ""))
        kandydaci = []
        while i < len(self.sec_nazwy) and self.sec_nazwy[i][0].startswith(n):
            kandydaci.append(self.sec_nazwy[i])
            i += 1
            if len(kandydaci) > 6:
                break
        if not kandydaci:
            # albo odwrotnie: nazwa z wyciągu jest DŁUŻSZA od rejestrowej
            # („TARGET CORP EQUITY" → „TARGET")
            slowa = n.split()
            # co najmniej dwa słowa — samo „INVESCO" czy „GENERAL" to nie spółka
            for k in range(len(slowa) - 1, 1, -1):
                krotsza = " ".join(slowa[:k])
                if len(krotsza) < 6:
                    break
                j = bisect.bisect_left(self.sec_nazwy, (krotsza, ""))
                if j < len(self.sec_nazwy) and self.sec_nazwy[j][0] == krotsza:
                    return self.sec_nazwy[j][1].replace(".", "-")
            return ""
        if len(kandydaci) > 6:
            return ""                     # zbyt ogólne („AMERICAN") — lepiej nic
        return min(kandydaci, key=lambda x: len(x[0]))[1].replace(".", "-")


def _kwota(s: str) -> tuple[float | None, float | None]:
    liczby = [float(x.replace(",", "")) for x in re.findall(r"\$?([\d,]{4,})", s or "")]
    if not liczby:
        return None, None
    if len(liczby) == 1:
        return liczby[0], (None if "over" in (s or "").lower() else liczby[0])
    return liczby[0], liczby[1]


def _pobierz(url: str, klucz_etag: str, wymus: bool = False) -> dict | None:
    """Pobiera JSON tylko wtedy, gdy się zmienił (ETag). None = bez zmian."""
    etag = None if wymus else store.kv_get(klucz_etag)
    h = {"If-None-Match": etag} if etag else {}
    r = requests.get(url, headers=h, timeout=120)
    if r.status_code == 304:
        return None
    r.raise_for_status()
    dane = r.json()
    if r.headers.get("ETag"):
        store.kv_set(klucz_etag, r.headers["ETag"])
    return dane


def wczytaj(wymus: bool = False) -> dict:
    stat = {"urzednikow": 0, "zmienionych": 0, "transakcji": 0, "bez_tickera": 0, "nowe_uid": []}
    indeks = _pobierz(f"{RAW}/meta/officials-index.json", "oge:etag:index", wymus)
    if indeks is None:
        # indeks bez zmian — ale pliki urzędników i tak sprawdzamy (ETag na
        # każdym z osobna), bo repozytorium potrafi dopisać transakcje bez
        # ruszania spisu
        indeks = store.kv_get("oge:index") or {}
    else:
        store.kv_set("oge:index", indeks)
    urzednicy = (indeks or {}).get("officials") or []
    stat["urzednikow"] = len(urzednicy)
    mapa: Mapa | None = None

    for u in urzednicy:
        slug = u.get("slug")
        if not slug:
            continue
        klucz = f"oge:etag:{slug}"
        try:
            dane = _pobierz(f"{RAW}/officials/{slug}.json", klucz, wymus)
        except Exception as e:  # noqa: BLE001
            log.warning("OGE %s: %s", slug, e)
            continue
        if dane is None:
            continue
        stat["zmienionych"] += 1
        if mapa is None:
            mapa = Mapa().zbuduj()
        nowe = _zapisz(u, dane, mapa, stat)
        stat["nowe_uid"] += nowe
    if stat["zmienionych"]:
        log.info("OGE: %s", {k: v for k, v in stat.items() if k != "nowe_uid"})
    return stat


def _zapisz(u: dict, dane: dict, mapa: Mapa, stat: dict) -> list[str]:
    slug = u["slug"]
    pid = people.for_oge(slug)
    kat = people.curated(pid)
    trump = slug == "trump-donald-j"
    nazwa = kat["name"] if kat else people.nazwa_oge(u.get("name") or dane.get("name") or slug)
    store.upsert_people([{
        "id": pid, "name": nazwa,
        "cat": "prezydent" if trump else "rzad",
        "role": people.urzad(u.get("title") or dane.get("title") or "", u.get("agency", "")),
        "org": u.get("agency") or dane.get("agency") or "",
        "source": "oge",
        "extra": {"short": people.nazwisko(nazwa), "party": u.get("party") or dane.get("party") or "",
                  "title_en": u.get("title") or "", "departed": u.get("departedDate")},
    }])
    rows, liczniki = [], {}
    for t in dane.get("transactions") or []:
        typ = (t.get("type") or "").lower()
        side = "buy" if typ.startswith("purchase") else "sell" if typ.startswith("sale") else ""
        if not side or not t.get("date"):
            continue
        sym = mapa.ticker(t.get("description", ""), t.get("ticker"))
        if not sym:
            stat["bez_tickera"] += 1
            continue
        lo, hi = _kwota(t.get("amount", ""))
        # Ten sam walor, dzień i kwota potrafią wystąpić dwa razy (dwie transze,
        # dwa konta) — licznik wystąpień rozróżnia je w kluczu.
        podpis = "|".join(str(t.get(k, "")) for k in
                          ("description", "date", "type", "amount", "sourceUrl", "sourcePage", "sourceRow"))
        liczniki[podpis] = liczniki.get(podpis, 0) + 1
        uid = "oge:" + hashlib.sha1(f"{slug}|{podpis}|{liczniki[podpis]}".encode()).hexdigest()[:20]
        rows.append({
            "uid": uid, "person": pid, "source": "oge", "ticker": sym,
            "asset": (t.get("description") or "")[:120], "side": side, "date": t["date"][:10],
            # Repozytorium nie podaje dnia wpływu formularza, tylko jego datę
            # w nazwie pliku; najbliżej prawdy jest data najnowszego formularza
            # zawierającego ten wiersz — a gdy jej nie ma, sama transakcja.
            "filed": _data_zgloszenia(t, dane) or t["date"][:10],
            "amt_lo": lo, "amt_hi": hi,
            "owner": "", "note": "zgłoszone po terminie" if t.get("lateFilingFlag") else "",
            "url": t.get("sourceUrl") or "",
        })
    stat["transakcji"] += len(rows)
    return store.add_trades(rows)


def _data_zgloszenia(t: dict, dane: dict) -> str:
    url = t.get("sourceUrl") or ""
    for f in dane.get("sourceFilings") or []:
        if isinstance(f, dict) and f.get("url") == url and f.get("date"):
            return str(f["date"])[:10]
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", url)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return ""
