"""Majątek z raportów rocznych OGE (formularz 278e) — prezydent i członkowie rządu.

Raport okresowy (278-T) mówi, co ktoś KUPIŁ i SPRZEDAŁ. Raport roczny (278e) mówi,
co MA: w części 6 („Other Assets and Income") jest każda pozycja każdego rachunku
z przedziałem wartości, np. „MERCK & COMPANY INC — $100,001 - $250,000". Z dwóch
rzeczy razem da się zbudować cały portfel:

* stan z najstarszego raportu = punkt startowy (`perf.portfel` wycenia te akcje
  od tego dnia i nakłada na nie transakcje — sprzedaże akcji sprzed okna wreszcie
  mają z czego zejść);
* kolejne raporty = punkty kontrolne na wykresie („zgłoszone: 294–1028 mln $");
* kategorie spoza giełdy (obligacje, gotówka, nieruchomości i firmy) — obraz
  całego majątku na koniec każdego roku.

Data stanu: raport roczny opisuje rok poprzedzający złożenie (raport podpisany
w czerwcu 2025 ma w nagłówku „2025", ale transakcje i wartości są za 2024), a
wartości podaje się na koniec okresu sprawozdawczego — przyjmujemy 31 grudnia
roku poprzedzającego złożenie.

PDF-y OGE mają warstwę tekstową (raport Trumpa za 2025: 927 stron, ~6 tys.
pozycji, ~88% wierszy rozpoznanych). Liczymy RAZ na plik w tle (`jobs`), wynik
w `kv` pod `maj:{pid}`.
"""

from __future__ import annotations

import io
import logging
import re
import time

import requests

from . import oge, people, store

log = logging.getLogger("insiders.majatek")

RAW = oge.RAW
_UA = {"User-Agent": "Portevo borygoo45@gmail.com"}

_WART = r"(None \(or less than \$1,001\)|\$[\d,]+ - \$[\d,]+|Over \$[\d,]+|\$[\d,]+)"
_WIERSZ = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+?)\s+(N/A|Yes|No)\s+" + _WART + r"(?:\s+(.*))?$")
_SMIECI = ("OGE Form", "Filer", "Part ", "#", "Instructions", "If you", "Note:", "Page Number")

# obligacje korporacyjne opisane po brokersku („OCCIDENTAL PETE SR DEBS-REG")
_OBLIGACJA_FIRM = re.compile(r"\bDEBS?\b|\bSR\b|SENIOR|\bREG S\b|UNSECURED|SECURED", re.I)
_GOTOWKA = re.compile(r"MONEY MARKET|\(CASH\)|\bCASH\b|BANK ACCOUNT|CHECKING|SAVINGS|TREASURY BILL|"
                      r"GOVERNMENT MONEY|SWEEP", re.I)
_FIRMY = re.compile(r"\bLLC\b|\bL\.?P\.?\b|UNDERLYING ASSETS|LOCATION:|PARTNERSHIP|TENANCY|"
                    r"\bGOLF\b|\bCORP\.? \(|\bMEMBER\b|REAL ESTATE|RESIDENTIAL|COMMERCIAL|"
                    r"\bPRIVATE\b|TRUMP|MAR-A-LAGO|\bJET\b|AIRCRAFT|ROYALT", re.I)
_FUNDUSZ = re.compile(r"\bFUND\b|\bFUNDS\b|\bTRUST\b|PORTFOLIO|\bSHARES\b", re.I)

KATEGORIE = {
    "akcje": "Akcje", "etf": "ETF-y", "obligacje": "Obligacje", "gotowka": "Gotówka i rynek pieniężny",
    "firmy": "Firmy i nieruchomości", "fundusze": "Inne fundusze", "inne": "Inne",
}


def _kwota(s: str) -> tuple[float, float]:
    if s.startswith("None"):
        return 0.0, 0.0
    liczby = [float(re.sub(r"[^\d]", "", x)) for x in re.findall(r"\$[\d,]+", s)]
    if s.startswith("Over"):
        return liczby[0], liczby[0] * 2          # „ponad 50 mln" — zgrubnie do dwukrotności
    return (liczby[0], liczby[-1]) if liczby else (0.0, 0.0)


def czytaj_pdf(dane: bytes) -> list[dict]:
    """Wiersze aktywów (części 2, 5 i 6) z tekstu PDF-u: numer, opis, wartość, rachunek."""
    from pypdf import PdfReader

    r = PdfReader(io.BytesIO(dane))
    surowe: list[tuple[str, str]] = []
    for strona in r.pages:
        t = strona.extract_text() or ""
        if not re.search(r"Part (2|5|6):", t):
            continue
        konto, bufor = "", ""
        for linia in t.split("\n"):
            linia = linia.strip()
            m = re.match(r"^(INVESTMENT ACCOUNT\s*#?\s*\d+|[A-Z][A-Z .&']{3,60} ACCOUNT\b.*)$", linia)
            if m and not _WIERSZ.match(linia):
                konto = linia[:60]
                continue
            if re.match(r"^\d+(\.\d+)*\s", linia):
                if bufor:
                    surowe.append((konto, bufor))
                bufor = linia
            elif bufor and linia and not linia.startswith(_SMIECI):
                bufor += " " + linia
        if bufor:
            surowe.append((konto, bufor))
    out = []
    for konto, b in surowe:
        m = _WIERSZ.match(b)
        if m:
            lo, hi = _kwota(m.group(4))
            out.append({"konto": konto, "opis": m.group(2).lstrip("*").strip(), "lo": lo, "hi": hi})
    return out


def rozloz(wiersze: list[dict], mapa: "oge.Mapa") -> dict:
    """Wiersze → kategorie (suma lo/hi) i pozycje giełdowe {ticker: [lo, hi]}."""
    kat = {k: [0.0, 0.0] for k in KATEGORIE}
    pozycje: dict[str, list[float]] = {}
    for w in wiersze:
        if w["hi"] <= 0:
            continue                               # sprzedane w ciągu roku / poniżej 1001 $
        opis = w["opis"]
        k, ticker = "inne", None
        if oge._OBLIGACJA.search(opis) or _OBLIGACJA_FIRM.search(opis):
            k = "obligacje"
        elif _GOTOWKA.search(opis):
            k = "gotowka"
        else:
            ticker = oge.etf(opis)
            if ticker:
                k = "etf"
            elif _FIRMY.search(opis):
                k = "firmy"
            else:
                ticker = mapa.ticker(opis, None)
                k = "akcje" if ticker else ("fundusze" if _FUNDUSZ.search(opis) else "inne")
        kat[k][0] += w["lo"]
        kat[k][1] += w["hi"]
        if ticker:
            p = pozycje.setdefault(ticker, [0.0, 0.0])
            p[0] += w["lo"]
            p[1] += w["hi"]
    return {"kategorie": {k: [round(a), round(b)] for k, (a, b) in kat.items()},
            "pozycje": {t: [round(a), round(b)] for t, (a, b) in pozycje.items()}}


def _raporty_roczne(slug: str) -> list[dict]:
    dane = store.kv_get(f"oge:filings:{slug}")
    if not dane:
        r = requests.get(f"{RAW}/officials/{slug}.json", headers=_UA, timeout=180)
        r.raise_for_status()
        dane = r.json().get("sourceFilings") or []
        store.kv_set(f"oge:filings:{slug}", dane)
    return [f for f in dane if isinstance(f, dict) and f.get("kind") == "annual-278e" and f.get("url")]


def odswiez(slugi: list[str] | None = None, stop=None) -> dict:
    """Czyta nowe raporty roczne. Każdy PDF raz (klucz: jego adres)."""
    if slugi is None:
        slugi = [p["oge"] for p in people.KATALOG if p.get("oge")]
    stat = {"osob": 0, "nowe_raporty": 0, "bledy": 0}
    mapa = None
    for slug in slugi:
        if stop is not None and stop.is_set():
            break
        pid = people.for_oge(slug)
        try:
            raporty = _raporty_roczne(slug)
        except Exception as e:  # noqa: BLE001
            log.info("Raporty roczne %s: %s", slug, e)
            stat["bledy"] += 1
            continue
        if not raporty:
            continue
        stat["osob"] += 1
        zapis = store.kv_get(f"maj:{pid}") or {"raporty": []}
        znane = {r["url"] for r in zapis["raporty"]}
        for f in raporty:
            if f["url"] in znane:
                continue
            try:
                r = requests.get(f["url"].replace(" ", "%20"), headers=_UA, timeout=300)
                r.raise_for_status()
                wiersze = czytaj_pdf(r.content)
            except Exception as e:  # noqa: BLE001
                log.info("Raport roczny %s %s: %s", slug, f["url"][-40:], e)
                stat["bledy"] += 1
                continue
            if mapa is None:
                mapa = oge.Mapa().zbuduj()
            rok = int(str(f.get("date"))[:4]) - 1
            zapis["raporty"].append({"url": f["url"], "zlozony": str(f.get("date"))[:10],
                                     "data": f"{rok}-12-31", "wierszy": len(wiersze),
                                     **rozloz(wiersze, mapa)})
            stat["nowe_raporty"] += 1
            time.sleep(1)
        zapis["raporty"].sort(key=lambda x: x["data"])
        store.kv_set(f"maj:{pid}", zapis)
    return stat


def raporty(pid: str) -> list[dict]:
    """Raporty roczne persony od najstarszego: data stanu, kategorie, pozycje."""
    z = store.kv_get(f"maj:{pid}")
    return (z or {}).get("raporty") or []
