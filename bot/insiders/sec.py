"""SEC Form 4 — transakcje prezesów, dyrektorów i dużych udziałowców spółek z USA.

Trzy drogi do tych samych danych, bo każda pokrywa inny kawałek czasu:

1. **Paczki kwartalne** („Insider Transactions Data Sets") — SEC co kwartał
   publikuje WSZYSTKIE formularze 3/4/5 jako tabele TSV. Jedna paczka to ~10 MB
   i kilkadziesiąt tysięcy transakcji. Tak budujemy historię (ostatnie dwa lata)
   bez pobierania każdego formularza z osobna.
2. **Dzienne indeksy** — między końcem ostatniej paczki a wczoraj. Indeks mówi,
   jakie formularze wpłynęły danego dnia; każdy trzeba pobrać osobno (~450
   dziennie), więc to najwolniejsza droga i idzie w tle od najnowszego dnia.
3. **Kanał „getcurrent"** — ostatnie zgłoszenia z dzisiaj, co kilka minut.
   Tylko dzięki niemu powiadomienie o zakupie przychodzi tego samego dnia.

Bierzemy wyłącznie kody **P** (zakup na rynku) i **S** (sprzedaż na rynku).
Reszta to przydziały akcji w wynagrodzeniu (A), wykonanie opcji (M), podatek
potrącony akcjami (F), darowizny (G) — z punktu widzenia „co insider myśli
o kursie" to szum. Sprzedaże poniżej 10 tys. $ też pomijamy: to zwykle
automatyczne transze, które zasłoniłyby wykres.

Klucz transakcji `sec:{numer zgłoszenia}:{kod}:{dzień}` jest ten sam we wszystkich
trzech drogach — zgłoszenie złożone z kilku transz w jeden dzień staje się jedną
transakcją ze średnią ceną, a ta sama transakcja przychodząca paczką i indeksem
nie zdubluje się.

Zasady SEC: nagłówek User-Agent z kontaktem i poniżej 10 zapytań na sekundę.
Trzymamy się pięciu. Po przekroczeniu SEC blokuje adres na 10 minut.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import logging
import os
import re
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile

import requests

from . import people, store

log = logging.getLogger("insiders.sec")

UA = {"User-Agent": os.environ.get("SEC_USER_AGENT", "Portevo borygoo45@gmail.com"),
      "Accept-Encoding": "gzip, deflate"}
LISTA = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
KWARTALY = 8                      # dwa lata historii
MIN_SPRZEDAZ = 10_000             # $ — patrz opis modułu
ODSTEP = 0.21                     # s między zapytaniami: ≤ 5 na sekundę

_ses = requests.Session()
_ses.headers.update(UA)
_rate = threading.Lock()
_ostatnie = [0.0]


class Zablokowane(RuntimeError):
    """SEC odcięło nas za tempo. Zadanie ma przerwać i spróbować za kwadrans."""


def _get(url: str, timeout: int = 30, stream: bool = False) -> requests.Response:
    with _rate:
        czekaj = _ostatnie[0] + ODSTEP - time.time()
        if czekaj > 0:
            time.sleep(czekaj)
        _ostatnie[0] = time.time()
    r = _ses.get(url, timeout=timeout, stream=stream)
    if r.status_code in (403, 429) and "sec.gov" in url:
        tekst = "" if stream else r.text[:400]
        if r.status_code == 429 or "Request Rate" in tekst or "Undeclared" in tekst:
            raise Zablokowane(f"SEC {r.status_code}: {tekst[:120]}")
    return r


# ------------------------------------------------------------------ pomocnicze

_MIES = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def _data(s: str) -> str:
    """„30-JUN-2026" albo „2026-06-30" → „2026-06-30". Bez `strptime` —
    `%b` zależy od ustawień regionalnych systemu, a tu miesiące są angielskie."""
    s = (s or "").strip()
    m = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", s)
    if m and m.group(2).upper() in _MIES:
        return f"{m.group(3)}-{_MIES[m.group(2).upper()]:02d}-{int(m.group(1)):02d}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return m.group(0) if m else ""


def ticker(sym: str) -> str:
    """Symbol ze zgłoszenia w zapisie Yahoo: „BRK.B" → „BRK-B"; śmieci → ''."""
    s = (sym or "").strip().upper().replace("/", "-").replace(".", "-")
    s = re.split(r"[\s,;]+", s)[0] if s else ""
    if s in ("", "NONE", "N-A", "NA", "-", "NULL", "NOT-APPLICABLE"):
        return ""
    return s if re.fullmatch(r"[A-Z0-9][A-Z0-9\-]{0,9}", s) else ""


def _liczba(v) -> float | None:
    try:
        x = float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return x if x == x else None          # NaN


def _prawda(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "t", "yes", "y")


def klasa(relacja: str) -> str:
    """Relacja z formularza → klasa w aplikacji. Funkcja w zarządzie wygrywa
    z miejscem w radzie: prezes zasiadający w radzie to dla czytelnika prezes."""
    r = (relacja or "").lower().replace(" ", "")
    if "officer" in r:
        return "prezesi"
    if "tenpercent" in r or "10%" in r:
        return "wlasciciele"
    if "director" in r:
        return "rada"
    return "wlasciciele"


_DOMYSLNA_FUNKCJA = {"rada": ("Członek rady dyrektorów", "Rada"),
                     "wlasciciele": ("Udziałowiec powyżej 10%", "Udziałowiec"),
                     "prezesi": ("Członek zarządu", "Zarząd")}


def _wybierz_wlasciciela(wl: list[dict]) -> dict:
    """Jedno zgłoszenie bywa wspólne dla kilku podmiotów (fundusz, jego zarządca
    i człowiek za nim stojący). Przypisujemy je jednej personie, bo inaczej na
    wykresie stanęłyby trzy twarze tej samej transakcji: najpierw komuś
    z katalogu, potem człowiekowi, na końcu pierwszej firmie z listy."""
    for o in wl:
        if people.for_sec(o["cik"]) in people.BY_ID:
            return o
    for o in wl:
        if not people.czy_firma(o["name"]):
            return o
    return wl[0]


def _persona(o: dict, spolka: str, sym: str) -> dict:
    pid = people.for_sec(o["cik"])
    kat = people.curated(pid)["cat"] if people.curated(pid) else klasa(o["rel"])
    pelna, krotka = people.funkcja(o.get("title", ""))
    auto = klasa(o["rel"])
    if not pelna:
        pelna, krotka = _DOMYSLNA_FUNKCJA.get(auto, ("", ""))
    return {
        "id": pid, "name": people.nazwa_sec(o["name"]), "cat": kat,
        "role": pelna, "org": people.skroc_spolke(spolka), "source": "sec",
        "extra": {"short": krotka, "ticker": sym, "cik": int(o["cik"]),
                  "firma": people.czy_firma(o["name"]), "klasa": auto},
    }


def _url(issuer_cik: str, acc: str) -> str:
    try:
        c = int(issuer_cik)
    except (TypeError, ValueError):
        return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum={acc}"
    return f"https://www.sec.gov/Archives/edgar/data/{c}/{acc.replace('-', '')}/{acc}-index.htm"


def _transakcja(acc: str, code: str, day: str, filed: str, sym: str, spolka: str,
                pid: str, sh: float, wartosc: float, posrednio: str, plan: bool,
                issuer_cik: str) -> dict | None:
    if code == "S" and wartosc < MIN_SPRZEDAZ:
        return None
    cena = (wartosc / sh) if sh else None
    return {
        "uid": f"sec:{acc}:{code}:{day}", "person": pid, "source": "sec",
        "ticker": sym, "asset": people.skroc_spolke(spolka),
        "side": "buy" if code == "P" else "sell", "date": day, "filed": filed or day,
        "shares": round(sh, 4) if sh else None,
        "price": round(cena, 4) if cena else None,
        "amt_lo": round(wartosc, 2) if wartosc else None,
        "amt_hi": round(wartosc, 2) if wartosc else None,
        "owner": "pośrednio" if posrednio else "",
        "note": posrednio[:120] if posrednio else "",
        "url": _url(issuer_cik, acc), "planned": 1 if plan else 0,
    }


# ------------------------------------------------------------ paczki kwartalne


def lista_kwartalow() -> list[tuple[str, str]]:
    """[(„2026q2", adres), …] od najnowszego. Adresy czytamy ze strony SEC,
    bo ścieżka potrafi się zmienić — paczka za 2026q2 leży już w innym
    katalogu niż wszystkie wcześniejsze."""
    r = _get(LISTA, timeout=30)
    r.raise_for_status()
    out = {}
    for href in re.findall(r'href="([^"]*?(\d{4}q[1-4])_form345\.zip)"', r.text):
        url, q = href
        out[q] = url if url.startswith("http") else "https://www.sec.gov" + url
    return sorted(out.items(), reverse=True)


def koniec_kwartalu(q: str) -> dt.date:
    rok, k = int(q[:4]), int(q[-1])
    if k == 4:
        return dt.date(rok, 12, 31)
    return dt.date(rok, 3 * k + 1, 1) - dt.timedelta(days=1)


def _tsv(z: zipfile.ZipFile, nazwa: str):
    """Czytnik TSV bez interpretowania cudzysłowów — w nazwach spółek bywają
    pojedyncze znaki ", które zwykły czytnik CSV wziąłby za początek pola
    i skleił z następnymi wierszami."""
    with z.open(nazwa) as f:
        tekst = io.TextIOWrapper(f, encoding="utf-8", errors="replace", newline="")
        for row in csv.DictReader(tekst, delimiter="\t", quoting=csv.QUOTE_NONE):
            yield row


def wczytaj_kwartal(q: str, url: str) -> dict:
    """Przerabia jedną paczkę kwartalną. Zwraca liczby do dziennika."""
    t0 = time.time()
    tmp = tempfile.NamedTemporaryFile(prefix=f"sec-{q}-", suffix=".zip", delete=False)
    try:
        with _get(url, timeout=180, stream=True) as r:
            r.raise_for_status()
            for chunk in r.iter_content(1 << 16):
                tmp.write(chunk)
        tmp.close()

        grupy: dict[tuple, dict] = {}
        with zipfile.ZipFile(tmp.name) as z:
            for row in _tsv(z, "NONDERIV_TRANS.tsv"):
                code = (row.get("TRANS_CODE") or "").strip()
                if code not in ("P", "S"):
                    continue
                sh = _liczba(row.get("TRANS_SHARES")) or 0.0
                px = _liczba(row.get("TRANS_PRICEPERSHARE")) or 0.0
                day = _data(row.get("TRANS_DATE"))
                if not day or sh <= 0:
                    continue
                key = (row["ACCESSION_NUMBER"], code, day)
                g = grupy.setdefault(key, {"sh": 0.0, "val": 0.0, "ind": ""})
                g["sh"] += sh
                g["val"] += sh * px
                if (row.get("DIRECT_INDIRECT_OWNERSHIP") or "").strip() == "I" and not g["ind"]:
                    g["ind"] = (row.get("NATURE_OF_OWNERSHIP") or "pośrednio").strip()

            potrzebne = {k[0] for k in grupy}
            zgl: dict[str, dict] = {}
            for row in _tsv(z, "SUBMISSION.tsv"):
                acc = row.get("ACCESSION_NUMBER")
                if acc in potrzebne and (row.get("DOCUMENT_TYPE") or "").strip() == "4":
                    zgl[acc] = row
            wlasc: dict[str, list] = {}
            for row in _tsv(z, "REPORTINGOWNER.tsv"):
                acc = row.get("ACCESSION_NUMBER")
                if acc in zgl:
                    wlasc.setdefault(acc, []).append({
                        "cik": row.get("RPTOWNERCIK") or "0",
                        "name": row.get("RPTOWNERNAME") or "",
                        "rel": row.get("RPTOWNER_RELATIONSHIP") or "",
                        "title": row.get("RPTOWNER_TITLE") or "",
                    })

        transakcje, osoby = [], {}
        for (acc, code, day), g in grupy.items():
            s = zgl.get(acc)
            wl = wlasc.get(acc)
            if not s or not wl:
                continue
            sym = ticker(s.get("ISSUERTRADINGSYMBOL"))
            if not sym:
                continue
            o = _wybierz_wlasciciela(wl)
            p = _persona(o, s.get("ISSUERNAME") or "", sym)
            t = _transakcja(acc, code, day, _data(s.get("FILING_DATE")), sym,
                            s.get("ISSUERNAME") or "", p["id"], g["sh"], g["val"],
                            g["ind"], _prawda(s.get("AFF10B5ONE")), s.get("ISSUERCIK") or "")
            if not t:
                continue
            transakcje.append(t)
            # najnowsze zgłoszenie decyduje o opisie persony (funkcja potrafi się zmienić)
            if p["id"] not in osoby or t["filed"] >= osoby[p["id"]][0]:
                osoby[p["id"]] = (t["filed"], p)

        store.upsert_people([p for _, p in osoby.values()])
        nowe = store.add_trades(transakcje)
        wynik = {"kwartal": q, "transakcje": len(transakcje), "nowe": len(nowe),
                 "osoby": len(osoby), "s": round(time.time() - t0, 1)}
        log.info("SEC %s: %s", q, wynik)
        return wynik
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def historia(kwartaly: int = KWARTALY) -> list[dict]:
    """Wczytuje brakujące paczki kwartalne (najnowsze najpierw)."""
    wyniki = []
    for q, url in lista_kwartalow()[:kwartaly]:
        if store.kv_get(f"secq:{q}"):
            continue
        w = wczytaj_kwartal(q, url)
        store.kv_set(f"secq:{q}", w)
        wyniki.append(w)
    return wyniki


def ostatni_kwartal() -> str:
    """Najnowsza WCZYTANA paczka — od dnia po jej końcu zaczyna się dzienny indeks."""
    wczytane = [k for k in _klucze_kv("secq:")]
    return max(wczytane) if wczytane else ""


def _klucze_kv(prefiks: str) -> list[str]:
    return [r[0][len(prefiks):] for r in store.conn().execute(
        "select key from kv where key like ?", (prefiks + "%",))]


# --------------------------------------------------------- pojedynczy formularz


def _tekst(el, sciezka: str) -> str:
    x = el.find(sciezka)
    return (x.text or "").strip() if x is not None and x.text else ""


def czytaj_formularz(xml: str, acc: str, filed: str) -> tuple[list[dict], dict | None]:
    """Form 4 w XML → (transakcje, persona). Pusta lista, gdy nie ma P/S."""
    m = re.search(r"<ownershipDocument>.*?</ownershipDocument>", xml, re.S)
    if not m:
        return [], None
    try:
        doc = ET.fromstring(m.group(0))
    except ET.ParseError:
        return [], None
    if _tekst(doc, "documentType") not in ("4",):
        return [], None
    sym = ticker(_tekst(doc, "issuer/issuerTradingSymbol"))
    if not sym:
        return [], None
    spolka = _tekst(doc, "issuer/issuerName")
    issuer_cik = _tekst(doc, "issuer/issuerCik")
    plan = _prawda(_tekst(doc, "aff10b5One"))

    wl = []
    for ro in doc.findall("reportingOwner"):
        rel = ro.find("reportingOwnerRelationship")
        flagi = []
        if rel is not None:
            if _prawda(_tekst(rel, "isDirector")):
                flagi.append("Director")
            if _prawda(_tekst(rel, "isOfficer")):
                flagi.append("Officer")
            if _prawda(_tekst(rel, "isTenPercentOwner")):
                flagi.append("TenPercentOwner")
            if _prawda(_tekst(rel, "isOther")):
                flagi.append("Other")
        wl.append({"cik": _tekst(ro, "reportingOwnerId/rptOwnerCik") or "0",
                   "name": _tekst(ro, "reportingOwnerId/rptOwnerName"),
                   "rel": ",".join(flagi),
                   "title": _tekst(rel, "officerTitle") if rel is not None else ""})
    if not wl:
        return [], None

    grupy: dict[tuple, dict] = {}
    for tr in doc.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _tekst(tr, "transactionCoding/transactionCode")
        if code not in ("P", "S"):
            continue
        day = _data(_tekst(tr, "transactionDate/value"))
        sh = _liczba(_tekst(tr, "transactionAmounts/transactionShares/value")) or 0.0
        px = _liczba(_tekst(tr, "transactionAmounts/transactionPricePerShare/value")) or 0.0
        if not day or sh <= 0:
            continue
        g = grupy.setdefault((code, day), {"sh": 0.0, "val": 0.0, "ind": ""})
        g["sh"] += sh
        g["val"] += sh * px
        if _tekst(tr, "ownershipNature/directOrIndirectOwnership/value") == "I" and not g["ind"]:
            g["ind"] = _tekst(tr, "ownershipNature/natureOfOwnership/value") or "pośrednio"
    if not grupy:
        return [], None

    o = _wybierz_wlasciciela(wl)
    p = _persona(o, spolka, sym)
    out = []
    for (code, day), g in grupy.items():
        t = _transakcja(acc, code, day, filed, sym, spolka, p["id"], g["sh"], g["val"],
                        g["ind"], plan, issuer_cik)
        if t:
            out.append(t)
    return out, p


def _pobierz_formularz(sciezka_txt: str, acc: str, filed: str) -> tuple[list[dict], dict | None]:
    r = _get(f"https://www.sec.gov/Archives/{sciezka_txt}", timeout=30)
    if r.status_code != 200:
        return [], None
    return czytaj_formularz(r.text, acc, filed)


def _zapisz(wyniki: list[tuple[list[dict], dict | None]]) -> list[str]:
    osoby = {p["id"]: p for _, p in wyniki if p}
    store.upsert_people(list(osoby.values()))
    return store.add_trades([t for ts, _ in wyniki for t in ts])


# ------------------------------------------------------------- dzienny indeks


def wczytaj_dzien(d: dt.date, stop: threading.Event | None = None) -> dict:
    """Wszystkie Form 4 z danego dnia. Dzień bez indeksu (weekend, święto)
    też uznajemy za zrobiony — inaczej wracalibyśmy do niego w kółko."""
    klucz = f"secday:{d.isoformat()}"
    if store.kv_get(klucz) is not None:
        return {"dzien": d.isoformat(), "pominiety": True}
    q = (d.month - 1) // 3 + 1
    url = f"https://www.sec.gov/Archives/edgar/daily-index/{d.year}/QTR{q}/form.{d:%Y%m%d}.idx"
    r = _get(url, timeout=40)
    if r.status_code in (403, 404):
        # Archiwum SEC stoi na S3, które na brakujący plik odpowiada 403, nie
        # 404. Indeks dnia pojawia się dopiero późnym wieczorem czasu USA — dla
        # świeżych dni to znaczy „jeszcze nie ma", a nie „nie będzie". Takiego
        # dnia NIE oznaczamy jako zrobiony, tylko odkładamy na kilka godzin;
        # starszy dzień bez indeksu (święto) zamykamy na dobre.
        if (dt.date.today() - d).days <= 4:
            store.kv_set(f"secday_try:{d.isoformat()}", time.time())
            return {"dzien": d.isoformat(), "jeszcze_nie_ma": True}
        store.kv_set(klucz, {"brak_indeksu": True})
        return {"dzien": d.isoformat(), "brak_indeksu": True}
    r.raise_for_status()

    pliki: dict[str, str] = {}
    for line in r.text.splitlines():
        m = re.match(r"^4\s+.+?\s+(\d+)\s+(\d{8})\s+(edgar/data/\S+\.txt)\s*$", line)
        if not m:
            continue
        acc = m.group(3).rsplit("/", 1)[-1][:-4]
        pliki.setdefault(acc, m.group(3))
    znane = store.seen_filter([f"acc:{a}" for a in pliki])
    wyniki, zrobione, nowe = [], [], 0
    filed = d.isoformat()
    for acc, sciezka in pliki.items():
        if f"acc:{acc}" in znane:
            continue
        if stop is not None and stop.is_set():
            break
        try:
            wyniki.append(_pobierz_formularz(sciezka, acc, filed))
            zrobione.append(f"acc:{acc}")
        except Zablokowane:
            raise
        except Exception as e:  # noqa: BLE001 — jeden zły formularz nie zatrzymuje dnia
            log.debug("Form 4 %s: %s", acc, e)
            zrobione.append(f"acc:{acc}")
        if len(wyniki) >= 60:
            nowe += len(_zapisz(wyniki))
            store.seen_add(zrobione)
            wyniki, zrobione = [], []
    nowe += len(_zapisz(wyniki))
    store.seen_add(zrobione)
    przerwany = stop is not None and stop.is_set()
    if not przerwany:
        store.kv_set(klucz, {"formularzy": len(pliki), "nowe": nowe})
    return {"dzien": d.isoformat(), "formularzy": len(pliki), "nowe": nowe,
            "przerwany": przerwany}


def dni_do_uzupelnienia(dzis: dt.date | None = None) -> list[dt.date]:
    """Dni od końca ostatniej paczki do wczoraj, od najnowszego — świeże dane są
    ważniejsze niż sprzed dwóch miesięcy, a całość schodzi około godziny."""
    q = ostatni_kwartal()
    if not q:
        return []
    start = koniec_kwartalu(q) + dt.timedelta(days=1)
    dzis = dzis or dt.date.today()
    dni = []
    d = dzis - dt.timedelta(days=1)
    teraz = time.time()
    while d >= start:
        if d.weekday() < 5 and store.kv_get(f"secday:{d.isoformat()}") is None:
            # dzień, którego indeksu jeszcze nie było — wracamy po 6 godzinach,
            # inaczej zegar pukałby o niego w kółko bez przerwy
            proba = store.kv_get(f"secday_try:{d.isoformat()}")
            if not proba or teraz - float(proba) > 6 * 3600:
                dni.append(d)
        d -= dt.timedelta(days=1)
    return dni


# --------------------------------------------------------------- kanał bieżący


CURRENT = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&company="
           "&dateb=&owner=include&start={start}&count=100&output=atom")
_NS = {"a": "http://www.w3.org/2005/Atom"}


def biezace(stron: int = 3) -> dict:
    """Najnowsze Form 4 z kanału SEC. Każde zgłoszenie jest tam dwa razy (raz
    pod spółką, raz pod osobą) — bierzemy je raz, po numerze."""
    pliki: dict[str, tuple[str, str]] = {}
    for strona in range(stron):
        r = _get(CURRENT.format(start=strona * 100), timeout=30)
        if r.status_code != 200:
            break
        try:
            wpisy = ET.fromstring(r.content).findall("a:entry", _NS)
        except ET.ParseError:
            break
        if not wpisy:
            break
        na_stronie = []
        for e in wpisy:
            link = e.find("a:link", _NS)
            href = link.get("href") if link is not None else ""
            m = re.search(r"/data/(\d+)/(\d{18})/(\d{10}-\d{2}-\d{6})-index", href or "")
            if not m:
                continue
            acc = m.group(3)
            kiedy = _data((e.findtext("a:updated", "", _NS) or "")[:10])
            pliki.setdefault(acc, (f"edgar/data/{m.group(1)}/{acc}.txt", kiedy))
            na_stronie.append(f"acc:{acc}")
        # cała strona już znana = starsze strony też; nie ma po co iść dalej
        if na_stronie and len(store.seen_filter(na_stronie)) == len(set(na_stronie)):
            break
    znane = store.seen_filter([f"acc:{a}" for a in pliki])
    wyniki, zrobione = [], []
    for acc, (sciezka, kiedy) in pliki.items():
        if f"acc:{acc}" in znane:
            continue
        try:
            wyniki.append(_pobierz_formularz(sciezka, acc, kiedy or dt.date.today().isoformat()))
        except Zablokowane:
            raise
        except Exception as e:  # noqa: BLE001
            log.debug("Form 4 %s: %s", acc, e)
        zrobione.append(f"acc:{acc}")
    nowe = _zapisz(wyniki)
    store.seen_add(zrobione)
    return {"zgloszen": len(pliki), "przerobione": len(zrobione), "nowe": len(nowe),
            "nowe_uid": nowe}
