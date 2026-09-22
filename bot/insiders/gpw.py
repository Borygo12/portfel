"""Insiderzy GPW — transakcje zarządów i rad nadzorczych spółek z warszawskiej giełdy.

Skąd prawnie: art. 19 MAR każe osobie pełniącej obowiązki zarządcze (i osobom
z nią blisko związanym) zgłosić każdą transakcję akcjami spółki, a spółka
publikuje to raportem ESPI. To polski odpowiednik amerykańskiego Form 4.

Skąd technicznie: raporty ESPI to wolny tekst w PDF-ach bez wspólnego wzoru, a ich
archiwum nie ma otwartego API. Bankier.pl przepisuje je do jednej tabeli („Transakcje
insiderów"): osoba, funkcja, kupno/sprzedaż, liczba akcji, cena, wartość, dzień
transakcji i publikacji. Projekt i tak korzysta z Bankiera (RSS ESPI w bocie), więc
to nie nowa zależność. Na ekranie podpisujemy źródło wprost.

Dwie drogi:
* **strona spółki** (`/gielda/notowania/akcje/{KOD}/insiderzy`) — pełna historia,
  bez stronicowania, a w nawigacji pełna nazwa z tickerem GPW („… (CDR)"). Tak
  wypełniamy bazę przy pierwszym przebiegu (~400 spółek, raz);
* **lista najnowszych** (`/gielda/transakcje-insiderow`) — 20 ostatnich wpisów
  z całej giełdy, co 20 minut. Dzięki niej powiadomienie o zakupie prezesa
  przychodzi tego samego dnia.

Bierzemy tylko „Kupno" i „Sprzedaż" — objęcie akcji w programie motywacyjnym czy
darowizna nie mówią nic o tym, co insider myśli o kursie (jak kody A/G w SEC).
Kwoty są w złotówkach (kolumna `cur` = „PLN").
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import logging
import re
import time

import requests

from . import people, store

log = logging.getLogger("insiders.gpw")

BASE = "https://www.bankier.pl"
LISTA_SPOLEK = [f"{BASE}/gielda/notowania/akcje", f"{BASE}/gielda/notowania/new-connect"]
NAJNOWSZE = f"{BASE}/gielda/transakcje-insiderow"
_UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
       "Accept-Language": "pl-PL,pl;q=0.9"}
PRZERWA = 1.2                      # s między stronami — to cudzy serwis, nie pukamy mocno
OD_ROKU = 3                        # ile lat historii bierzemy przy pierwszym przebiegu

_ses = requests.Session()
_ses.headers.update(_UA)


def _get(url: str) -> str:
    r = _ses.get(url, timeout=40)
    r.raise_for_status()
    return r.text


def _czysc(s: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _liczba(s: str) -> float | None:
    s = (s or "").replace("\xa0", " ")
    m = re.search(r"-?[\d ]+(?:,\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0).replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _waluta(s: str) -> str:
    s = (s or "").lower()
    for k, w in (("zł", "PLN"), ("pln", "PLN"), ("eur", "EUR"), ("usd", "USD"), ("$", "USD"),
                 ("€", "EUR")):
        if k in s:
            return w
    return "PLN"


def _dzien(s: str) -> str:
    """„2025-01-22" albo „od 2022-11-29 do 2022-11-30" — bierzemy ostatni dzień."""
    daty = re.findall(r"\d{4}-\d{2}-\d{2}", s or "")
    return daty[-1] if daty else ""


def _funkcja_krotko(rola: str) -> str:
    r = (rola or "").lower()
    if "prezes" in r and "wice" not in r:
        return "Prezes"
    if "zarząd" in r or "zarzad" in r or "prokurent" in r:
        return "Zarząd"
    if " rn" in f" {r}" or "nadzorcz" in r:
        return "Rada"
    if "blisko" in r:
        return "Bliski"
    if "akcjonariusz" in r:
        return "Akcjonariusz"
    return "Insider"


def _nazwa(surowa: str) -> str:
    """„Iwiński Marcin" → „Marcin Iwiński"; firmy zostają jak są."""
    s = re.sub(r"\s+", " ", surowa or "").strip()
    if not s or people.czy_firma(s):
        return s
    if "," in s:                           # „Donev, Ognian Ivanov"
        nazwisko, imiona = s.split(",", 1)
        return f"{imiona.strip()} {nazwisko.strip()}".strip()
    czesci = s.split(" ")
    if len(czesci) >= 2 and all(c[:1].isupper() for c in czesci):
        return " ".join(czesci[1:] + czesci[:1])
    return s


# --------------------------------------------------------------- lista spółek


def kody_spolek() -> list[str]:
    kody: list[str] = []
    for url in LISTA_SPOLEK:
        try:
            t = _get(url)
        except Exception as e:  # noqa: BLE001
            log.warning("Lista spółek %s: %s", url, e)
            continue
        for k in re.findall(r"quote\.html\?symbol=([A-Z0-9_\-]+)", t):
            if k not in kody:
                kody.append(k)
        time.sleep(PRZERWA)
    return kody


# ----------------------------------------------------------- strona spółki


def _wiersze(t: str) -> list[list[str]]:
    seg = re.sub(r"<svg.*?</svg>", "", t, flags=re.S)
    out = []
    for r in re.findall(r"<tr[^>]*>.*?</tr>", seg, re.S):
        komorki = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)
        if komorki:
            out.append(komorki)
    return out


def _osoba_z_komorki(kom: str) -> tuple[str, str, str]:
    """(osoba, funkcja, podmiot pośredni) z komórki z kilkoma polami.

    Obie strony Bankiera trzymają w jednej komórce nazwisko i podmiot, przez który
    poszła transakcja („Borisov Boris" + „(Kaliman RT AD)"); lista najnowszych
    dokłada tam jeszcze funkcję. Klucz transakcji budujemy z SAMEGO nazwiska —
    inaczej ta sama transakcja z dwóch stron zapisałaby się podwójnie."""
    spany = re.findall(r'<span class="a-span([^"]*)">(.*?)</span>', kom, re.S)
    if not spany:
        return _czysc(kom), "", ""
    osoba = next((_czysc(v) for k, v in spany if "-note" not in k and "-hint" not in k), "")
    rola = next((_czysc(v) for k, v in spany if "-note" in k), "")
    posr = next((_czysc(v) for k, v in spany if "-hint" in k), "").strip("() ")
    return osoba, rola, posr


def _ticker_z_nawigacji(t: str) -> tuple[str, str]:
    """(ticker GPW, pełna nazwa) z okruszków: „CD PROJEKT RED Spółka Akcyjna (CDR)"."""
    m = re.search(r'itemprop="name">([^<]{2,160}?)\s*\(([A-Z0-9]{2,8})\)</span>', t)
    if not m:
        return "", ""
    return m.group(2), html.unescape(m.group(1)).strip()


def _transakcja(kod: str, ticker: str, spolka: str, osoba: str, rola: str, posrednik: str,
                typ: str, wolumen: str, cena: str, wartosc: str, data: str, publ: str,
                licznik: dict) -> tuple[dict, dict] | None:
    t = typ.strip().lower()
    side = "buy" if t.startswith("kupno") else "sell" if t.startswith("sprzeda") else ""
    if not side:
        return None
    dzien = _dzien(data)
    if not dzien:
        return None
    sh = _liczba(wolumen)
    wart = _liczba(wartosc)
    cur = _waluta(cena or wartosc)
    px = (wart / sh) if (wart and sh) else _liczba(cena)
    if not wart and px and sh:
        wart = px * sh
    # Wpisy sprzed obowiązku podawania nazwiska mają „-- --" — to nie jedna osoba
    # na całej giełdzie, tylko anonimowy insider TEJ spółki.
    if not re.search(r"[^\W\d_]{2}", osoba or ""):
        osoba = ""
    nazwa = _nazwa(osoba)
    pid = people.for_gpw(osoba) if osoba else f"gpw-{kod.lower()}-bez-nazwiska"
    # klucz niezależny od drogi: lista najnowszych pisze „sprzedaż", strona spółki
    # „Sprzedaż" — ta sama transakcja nie może zapisać się dwa razy
    podpis = "|".join(re.sub(r"\s+", "", x.lower()) for x in
                      (kod, osoba, typ, wolumen, cena, dzien, _dzien(publ)))
    licznik[podpis] = licznik.get(podpis, 0) + 1
    uid = "gpw:" + hashlib.sha1(f"{podpis}|{licznik[podpis]}".encode()).hexdigest()[:20]
    kat = people.curated(pid)
    trans = {
        "uid": uid, "person": pid, "source": "gpw", "ticker": f"{ticker}.WA",
        "asset": spolka[:120], "side": side, "date": dzien, "filed": _dzien(publ) or dzien,
        "shares": round(sh, 4) if sh else None, "price": round(px, 4) if px else None,
        "amt_lo": round(wart, 2) if wart else None, "amt_hi": round(wart, 2) if wart else None,
        "owner": "przez podmiot powiązany" if posrednik else "",
        "note": posrednik[:120] if posrednik else "",
        "url": f"{BASE}/gielda/notowania/akcje/{kod}/insiderzy", "cur": cur,
    }
    persona = {
        "id": pid, "name": (kat or {}).get("name") or nazwa or "Insider (bez nazwiska)",
        "cat": (kat or {}).get("cat") or "gpw", "role": rola or "Osoba pełniąca obowiązki zarządcze",
        "org": people.skroc_spolke(spolka), "source": "gpw",
        "extra": {"short": _funkcja_krotko(rola), "ticker": f"{ticker}.WA",
                  "firma": people.czy_firma(osoba), "kod": kod, "gpw": True},
    }
    return trans, persona


def wczytaj_spolke(kod: str, od: str = "") -> dict:
    """Cała historia insiderów jednej spółki. Zapisuje też kod → ticker."""
    t = _get(f"{BASE}/gielda/notowania/akcje/{kod}/insiderzy")
    ticker, spolka = _ticker_z_nawigacji(t)
    if not ticker:
        store.kv_set(f"gpw:kod:{kod}", {"ticker": "", "at": time.time()})
        return {"kod": kod, "brak_tickera": True}
    store.kv_set(f"gpw:kod:{kod}", {"ticker": ticker, "spolka": spolka, "at": time.time()})
    trans, osoby, licznik = [], {}, {}
    for kom in _wiersze(t):
        if len(kom) < 8:
            continue
        osoba, _, posr = _osoba_z_komorki(kom[0])
        w = _transakcja(kod, ticker, spolka, osoba, _czysc(kom[1]), posr,
                        _czysc(kom[2]), _czysc(kom[3]), _czysc(kom[4]), _czysc(kom[5]),
                        _czysc(kom[6]), _czysc(kom[7]), licznik)
        if not w or (od and w[0]["date"] < od):
            continue
        trans.append(w[0])
        if w[1]["id"] not in osoby or w[0]["filed"] >= osoby[w[1]["id"]][0]:
            osoby[w[1]["id"]] = (w[0]["filed"], w[1])
    store.upsert_people([p for _, p in osoby.values()])
    nowe = store.add_trades(trans)
    return {"kod": kod, "ticker": ticker, "transakcje": len(trans), "nowe": len(nowe),
            "nowe_uid": nowe}


def historia(stop=None) -> dict:
    """Pierwsze wypełnienie: każda spółka z GPW i NewConnect, raz. Przerwane —
    rusza od miejsca, w którym stanęło (zrobione spółki pamięta `seen`)."""
    od = (dt.date.today() - dt.timedelta(days=365 * OD_ROKU)).isoformat()
    kody = kody_spolek()
    zrobione = store.seen_filter([f"gpwspolka:{k}" for k in kody])
    stat = {"spolek": len(kody), "przerobione": 0, "transakcje": 0, "bledy": 0}
    for kod in kody:
        if f"gpwspolka:{kod}" in zrobione:
            continue
        if stop is not None and stop.is_set():
            break
        try:
            w = wczytaj_spolke(kod, od)
            stat["transakcje"] += w.get("transakcje", 0)
        except Exception as e:  # noqa: BLE001 — jedna spółka nie zatrzymuje reszty
            stat["bledy"] += 1
            log.debug("GPW %s: %s", kod, e)
        store.seen_add([f"gpwspolka:{kod}"])
        stat["przerobione"] += 1
        time.sleep(PRZERWA)
    if stat["przerobione"]:
        log.info("GPW historia: %s", stat)
    return stat


# ------------------------------------------------------------ najnowsze wpisy


def biezace() -> dict:
    """20 ostatnich transakcji z całej giełdy. Spółkę bez znanego tickera
    wczytujemy od razu w całości — i tak trzeba ją poznać."""
    t = _get(NAJNOWSZE)
    trans, osoby, licznik, nowe_spolki = [], {}, {}, []
    for kom in _wiersze(t):
        if len(kom) < 8:
            continue
        mk = re.search(r"akcje/([A-Z0-9_\-]+)/insiderzy", kom[0])
        if not mk:
            continue
        kod = mk.group(1)
        znane = store.kv_get(f"gpw:kod:{kod}")
        if not znane:
            nowe_spolki.append(kod)
            continue
        if not znane.get("ticker"):
            continue
        osoba, rola, posr = _osoba_z_komorki(kom[1])
        w = _transakcja(kod, znane["ticker"], znane.get("spolka", kod), osoba, rola, posr,
                        _czysc(kom[2]), _czysc(kom[3]), _czysc(kom[4]), _czysc(kom[5]),
                        _czysc(kom[6]), _czysc(kom[7]), licznik)
        if w:
            trans.append(w[0])
            osoby[w[1]["id"]] = w[1]
    store.upsert_people(list(osoby.values()))
    nowe = store.add_trades(trans)
    od = (dt.date.today() - dt.timedelta(days=365 * OD_ROKU)).isoformat()
    for kod in dict.fromkeys(nowe_spolki):
        try:
            nowe += wczytaj_spolke(kod, od).get("nowe_uid", [])
        except Exception as e:  # noqa: BLE001
            log.debug("GPW %s: %s", kod, e)
        store.seen_add([f"gpwspolka:{kod}"])
        time.sleep(PRZERWA)
    return {"wpisow": len(trans), "nowe": len(nowe), "nowe_uid": nowe}
