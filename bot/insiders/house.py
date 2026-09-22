"""Izba Reprezentantów — raporty transakcji kongresmenów (Periodic Transaction Report).

Skąd: Biuro Urzędnika Izby publikuje co rok spis wszystkich zgłoszeń
(`{rok}FD.zip` z plikiem XML), a każde zgłoszenie typu „P" to osobny PDF.
Członek ma 45 dni od transakcji na zgłoszenie — stąd „daty transakcji"
sprzed miesiąca przy świeżych zgłoszeniach. To nie błąd, tylko prawo.

Dwa rodzaje PDF-ów i to jest najważniejsza pułapka modułu:
* **zgłoszone elektronicznie** (numer 2xxxxxxx) — mają warstwę tekstu, tabela
  daje się czytać wyrażeniem regularnym;
* **zgłoszone na papierze** (numer 8/9xxxxxx) — skan bez tekstu. Takich nie
  czytamy (część bardzo aktywnych kongresmenów składa właśnie tak), zapisujemy
  je tylko w statystyce, żeby było wiadomo, ile zgłoszeń pominęliśmy.

Gdy PDF ma tekst, ale wyrażenie nie znalazło w nim żadnej transakcji, a widać
znaczniki waloru (`[ST]`, `[OP]`), prosimy o odczyt darmowy model (`ai.py`).
Model przepisuje, nie liczy — liczby i tak sprawdzamy tym samym kodem.
"""

from __future__ import annotations

import datetime as dt
import io
import logging
import re
import time
import xml.etree.ElementTree as ET
import zipfile

import requests

from . import people, store

log = logging.getLogger("insiders.house")

BASE = "https://disclosures-clerk.house.gov/public_disc"
_UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")}
PRZERWA = 0.4                      # s między PDF-ami — serwer Izby nie jest mocny

KWOTY = {                          # przedziały z formularza
    "$1,001": 1001, "$15,000": 15000, "$15,001": 15001, "$50,000": 50000,
    "$50,001": 50001, "$100,000": 100000, "$100,001": 100001, "$250,000": 250000,
    "$250,001": 250001, "$500,000": 500000, "$500,001": 500001, "$1,000,000": 1000000,
    "$1,000,001": 1000001, "$5,000,000": 5000000, "$5,000,001": 5000001,
    "$25,000,000": 25000000, "$25,000,001": 25000001, "$50,000,000": 50000000,
}
WLASCICIEL = {"SP": "małżonek", "JT": "wspólnie", "DC": "dziecko"}
TYPY_WALOROW = {"ST", "OP", "EF"}  # akcje, opcje, ETF — obligacji na wykres nie kładziemy


def _kwota(s: str) -> float | None:
    s = s.replace(" ", "")
    if s in KWOTY:
        return float(KWOTY[s])
    try:
        return float(s.replace("$", "").replace(",", ""))
    except ValueError:
        return None


def _data_us(s: str) -> str:
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", (s or "").strip())
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else ""


# ------------------------------------------------------------------- spis


def spis(rok: int) -> list[dict]:
    """Zgłoszenia transakcji (typ P) z danego roku."""
    r = requests.get(f"{BASE}/financial-pdfs/{rok}FD.zip", headers=_UA, timeout=60)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        nazwa = next((n for n in z.namelist() if n.lower().endswith(".xml")), None)
        if not nazwa:
            return []
        root = ET.fromstring(z.read(nazwa))
    out = []
    for m in root:
        if (m.findtext("FilingType") or "").strip() != "P":
            continue
        out.append({
            "last": (m.findtext("Last") or "").strip(),
            "first": (m.findtext("First") or "").strip(),
            "state": (m.findtext("StateDst") or "").strip(),
            "docid": (m.findtext("DocID") or "").strip(),
            "filed": _data_us(m.findtext("FilingDate") or ""),
            "year": int(m.findtext("Year") or rok),
        })
    return out


# --------------------------------------------------------------- odczyt PDF

_TX = re.compile(
    r"\((?P<ticker>[A-Z][A-Z0-9.\-/]{0,9})\)\s*\[(?P<typ>[A-Z]{2})\]\s*"
    r"(?P<rodzaj>P|S\s*\(partial\)|S|E)\s+"
    r"(?P<data>\d{2}/\d{2}/\d{4})\s+(?P<powiad>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<kwota>\$[\d,]+(?:\s*-\s*\$[\d,]+)?|Over\s+\$[\d,]+|Spouse/DC\s+Over\s+\$[\d,]+)")


def tekst_pdf(dane: bytes) -> str:
    from pypdf import PdfReader
    try:
        r = PdfReader(io.BytesIO(dane))
        return "\n".join((p.extract_text() or "") for p in r.pages)
    except Exception as e:  # noqa: BLE001 — uszkodzony PDF to pusty tekst, nie awaria
        log.debug("PDF nieczytelny: %s", e)
        return ""


def _opis_opcji(opis: str) -> str:
    o = opis.lower()
    rodzaj = "opcje call" if "call" in o else "opcje put" if "put" in o else "opcje"
    czesci = [rodzaj]
    m = re.search(r"strike price (?:of )?\$?([\d,.]+)", opis, re.I)
    if m:
        czesci.append(f"cena wykonania {m.group(1).rstrip('.')} $")
    m = re.search(r"(?:expiration date of|expires?)\s+(\d{1,2}/\d{1,2}/\d{2,4})", opis, re.I)
    if m:
        d = m.group(1).split("/")
        rok = d[2] if len(d[2]) == 4 else "20" + d[2]
        czesci.append(f"wygasają {int(d[1]):02d}.{int(d[0]):02d}.{rok}")
    return " · ".join(czesci)


def czytaj(tekst: str) -> list[dict]:
    """Transakcje z tekstu raportu. Każda z tickerem — reszta nas nie interesuje.

    Etykiety pól w tych PDF-ach są zapisane czcionką, której znaki wychodzą
    z ekstrakcji jako NUL: „Filing Status" to „F\\0\\0\\0 S\\0\\0\\0". Bez ich
    usunięcia opis „D: Purchased 100 call options…" był nie do znalezienia,
    a nazwy walorów zaczynały się od śmieci.
    """
    plaski = (tekst or "").replace("\x00", "")
    plaski = re.sub(r"[ \t]*\n[ \t]*", " ", plaski)
    plaski = re.sub(r"\s{2,}", " ", plaski)
    trafienia = list(_TX.finditer(plaski))
    out = []
    for i, m in enumerate(trafienia):
        typ = m.group("typ")
        if typ not in TYPY_WALOROW:
            continue
        rodzaj = m.group("rodzaj").replace(" ", "")
        if rodzaj == "E":
            continue
        # Właściciel i nazwa waloru stoją tuż przed tickerem: „SP Bloom Energy
        # Corporation Class A Common Stock (BE)". Kod właściciela (SP/JT/DC) jest
        # najpewniejszym początkiem nazwy — bierzemy OSTATNI przed tickerem, bo
        # wcześniej w tym samym kawałku leży jeszcze opis poprzedniej transakcji.
        # Transakcje na własne nazwisko kodu nie mają; wtedy nazwę bierzemy
        # później z rejestru spółek po tickerze, zamiast zgadywać.
        poczatek = trafienia[i - 1].end() if i else 0
        przed = plaski[poczatek:m.start()]
        wl, nazwa = "", ""
        kody = list(re.finditer(r"(?:^|[\s.;?)])(SP|JT|DC)\s+(?=[A-Z0-9])", przed))
        if kody:
            wl = WLASCICIEL.get(kody[-1].group(1), "")
            nazwa = przed[kody[-1].end():]
        nazwa = re.sub(r"\s+", " ", nazwa).strip(" -:")[-120:]

        # opis (np. parametry opcji) — do następnej transakcji
        koniec = trafienia[i + 1].start() if i + 1 < len(trafienia) else len(plaski)
        ogon = plaski[m.end():koniec]
        opis = ""
        md = re.search(r"\bD\s*:\s*(.+?)(?=\s(?:SP|JT|DC)\s|\*|$)", ogon)
        if md:
            opis = md.group(1).strip()

        kw = m.group("kwota")
        if kw.lower().startswith(("over", "spouse")):
            lo, hi = _kwota(re.search(r"\$[\d,]+", kw).group(0)), None
        else:
            czesci = [c.strip() for c in kw.split("-")]
            lo = _kwota(czesci[0])
            hi = _kwota(czesci[1]) if len(czesci) > 1 else lo
        out.append({
            "ticker": m.group("ticker"), "typ": typ,
            "side": "buy" if rodzaj == "P" else "sell",
            "partial": "partial" in rodzaj,
            "date": _data_us(m.group("data")),
            "amt_lo": lo, "amt_hi": hi if hi is not None else lo,
            "owner": wl, "asset": nazwa,
            "note": _opis_opcji(opis) if typ == "OP" else "",
        })
    return out


def _pdf(rok: int, docid: str) -> bytes | None:
    # Zgłoszenie z przełomu roku potrafi leżeć w katalogu roku sąsiedniego
    # (spis podaje rok zgłoszenia, a plik trafia do roku raportu).
    for r in (rok, rok - 1, rok + 1):
        odp = requests.get(f"{BASE}/ptr-pdfs/{r}/{docid}.pdf", headers=_UA, timeout=40)
        if odp.status_code == 200 and odp.content[:5] == b"%PDF-":
            return odp.content
    return None


def _ticker_yahoo(t: str) -> str:
    return (t or "").upper().replace(".", "-").replace("/", "-")


def wczytaj(lata: list[int] | None = None, limit: int | None = None,
            stop=None, ai_zapas: bool = True) -> dict:
    """Przerabia nowe zgłoszenia z podanych lat. Zwraca statystykę i nowe uid."""
    dzis = dt.date.today()
    lata = lata or [dzis.year, dzis.year - 1]
    stat = {"zgloszen": 0, "nowe_zgloszenia": 0, "skany": 0, "puste": 0, "ai": 0,
            "transakcje": 0, "nowe_uid": []}
    for rok in lata:
        try:
            wpisy = spis(rok)
        except Exception as e:  # noqa: BLE001
            log.warning("Spis Izby %s: %s", rok, e)
            continue
        stat["zgloszen"] += len(wpisy)
        znane = store.seen_filter([f"house:{w['docid']}" for w in wpisy])
        # od najnowszych — przy pierwszym przebiegu świeże zgłoszenia są ważniejsze
        wpisy.sort(key=lambda w: w["filed"], reverse=True)
        for w in wpisy:
            if f"house:{w['docid']}" in znane:
                continue
            if stop is not None and stop.is_set():
                return stat
            if limit is not None and stat["nowe_zgloszenia"] >= limit:
                return stat
            stat["nowe_zgloszenia"] += 1
            time.sleep(PRZERWA)
            try:
                dane = _pdf(w["year"], w["docid"])
            except Exception as e:  # noqa: BLE001 — spróbujemy przy następnym przebiegu
                log.info("PDF %s: %s", w["docid"], e)
                continue
            status = "ok"
            tekst = tekst_pdf(dane) if dane else ""
            if not tekst.strip():
                status = "skan"
                stat["skany"] += 1
                pozycje = []
            else:
                pozycje = czytaj(tekst)
                # AI tylko wtedy, gdy wyrażenie nie rozpoznało ŻADNEGO wiersza. Raport
                # z samymi wymianami akcji (typ E — fuzja, wydzielenie spółki) też daje
                # zero transakcji, ale tu parser zadziałał dobrze i nie ma czego ratować.
                if not pozycje and ai_zapas and re.search(r"\[(ST|OP)\]", tekst) \
                        and not _TX.search(re.sub(r"\s+", " ", tekst.replace("\x00", ""))):
                    from . import ai
                    pozycje = ai.odczytaj_ptr(tekst) or []
                    if pozycje:
                        status = "ai"
                        stat["ai"] += 1
                if not pozycje:
                    stat["puste"] += 1
            nowe = _zapisz(w, pozycje)
            stat["transakcje"] += len(pozycje)
            stat["nowe_uid"] += nowe
            store.seen_add([f"house:{w['docid']}"])
            store.kv_set(f"housedoc:{w['docid']}", {"status": status, "n": len(pozycje),
                                                     "pid": people.for_house(w["last"], w["first"], w["state"])})
    return stat


def _zapisz(w: dict, pozycje: list[dict]) -> list[str]:
    pid = people.for_house(w["last"], w["first"], w["state"])
    kat = people.curated(pid)
    stan = w["state"]
    okreg = f"{stan[:2]}-{stan[2:]}" if len(stan) > 2 else stan
    store.upsert_people([{
        "id": pid,
        "name": kat["name"] if kat else people.nazwa_house(w["first"], w["last"]),
        "cat": "politycy",
        "role": f"Izba Reprezentantów · {okreg}",
        "org": "Kongres USA", "source": "house",
        # nazwisko i imię ze spisu zostają w surowej postaci — po nich
        # `kongres.py` dopasowuje członka w bazie congress-legislators
        "extra": {"short": people.nazwisko(kat["name"] if kat else w["last"]),
                  "state": okreg, "party": (kat or {}).get("party", ""),
                  "last": w["last"], "first": w["first"]},
    }])
    url = f"{BASE}/ptr-pdfs/{w['year']}/{w['docid']}.pdf"
    rows = []
    for n, p in enumerate(pozycje):
        t = _ticker_yahoo(p["ticker"])
        if not t or not p.get("date"):
            continue
        rows.append({
            "uid": f"house:{w['docid']}:{n}", "person": pid, "source": "house",
            "ticker": t, "asset": p.get("asset", "")[:120], "side": p["side"],
            "date": p["date"], "filed": w["filed"],
            "amt_lo": p.get("amt_lo"), "amt_hi": p.get("amt_hi"),
            "options": 1 if p.get("typ") == "OP" else 0,
            "owner": p.get("owner", ""),
            "note": ("częściowa sprzedaż" if p.get("partial") else p.get("note", ""))[:160],
            "url": url,
        })
    return store.add_trades(rows)
