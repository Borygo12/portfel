"""Generator katalogu spółek — z listy kandydatów robi `companies.json`.

Uruchom RĘCZNIE, gdy chcesz dołożyć spółki albo odświeżyć nazwy i sektory:

    python bot/seo/make_catalog.py

Co robi: bierze listę tickerów niżej, pyta o każdy Yahoo Finance i **zapisuje
tylko te, dla których dane naprawdę wracają**. Spółki wycofane z obrotu,
przejęte i takie, których dostawca nie zna, wypadają same. To jest cała sól tego
skryptu: podstrona bez danych to podstrona bez treści, a kilkadziesiąt takich
adresów w sitemapie ciągnie w dół ocenę całej domeny.

Dlaczego to nie chodzi na serwerze: pytanie o kilkaset symboli trwa kilka minut
i przy każdym starcie kontenera byłoby marnotrawstwem, a przy okazji prosiłoby
się o blokadę od Yahoo. Katalog zmienia się parę razy w roku — plik w repozytorium
jest właściwą formą.

Uwaga przy dokładaniu spółek: **slug jest adresem URL i nie wolno go zmieniać
po zaindeksowaniu.** Zmiana slugu istniejącej spółki kasuje jej pozycję
w wyszukiwarce i wymaga przekierowania. Dokładanie nowych jest bezpieczne.
"""

from __future__ import annotations

import concurrent.futures as futures
import json
import os
import re
import unicodedata

import requests

TU = os.path.dirname(os.path.abspath(__file__))
CEL = os.path.join(TU, "companies.json")

# --------------------------------------------------------------- kandydaci

#: Warszawska giełda: WIG20, mWIG40 i szeroki wybór z sWIG80. Bez końcówki
#: „.WA" — skrypt dokleja ją sam, bo tak nazywa te spółki Yahoo.
GPW = """
ALE ALR BDX CDR CPS DNP JSW KGH KRU KTY LPP MBK OPL PCO PEO PGE PKN PKO PZU SPL
11B ABE ACP AMC ATT APR ASE BFT BHW BNP CAR CCC CIG CLN COG DAT DOM DVL ENA GPW
GTC HUG ING KGN MAB MIL MRB NEU PEP PLW PXM SLV SNT STP TEN TPE TXT VRC WPL XTB
ZEP ABS AGO ARH ATC BOS BRS DBC DEK ECH ERB GEA FTE LBW MCI MRC NWG OND OPN PBX
PCR PHN RBW RVU SHO STX TIM TOR TRK VOT WLT ZAP ZUE APT ASB ATR BML CMP CPG CRJ
EAT ENG ENT EUR FRO GNT IMC INL KPL KRC LWB MFO MOC MOL NNG PCF PEN PLZ PSW QRS
RFK SGN SKA SNK STL SWG TOA TRN TSG ULM VRG WWL
"""

#: Spółki z giełd amerykańskich, których raporty ruszają całym rynkiem —
#: plus te, o które w Polsce pyta się najczęściej (Tesla, Nvidia, Palantir).
USA = """
AAPL MSFT NVDA GOOGL AMZN META TSLA BRK-B AVGO LLY JPM V MA XOM UNH JNJ PG HD
COST ABBV WMT MRK KO PEP ORCL BAC CVX CRM AMD NFLX ADBE TMO MCD CSCO ACN ABT LIN
DHR INTC DIS WFC TXN VZ PM INTU IBM CAT QCOM NOW GE AMGN NKE UBER SPGI RTX HON
BKNG ISRG AMAT T PFE LOW GS DE BLK SYK PLD TJX ELV MDT LMT MU ADI C MDLZ GILD
BSX CB ADP SBUX MMC REGN VRTX CI SO ZTS CVS MO DUK PANW KLAC LRCX SNPS CDNS PYPL
SHOP COIN PLTR SOFI RIVN LCID F GM BA DAL AAL CCL ABNB DASH SNAP PINS RBLX U
CRWD NET DDOG MDB SNOW TTD SPOT ASML TSM BABA JD PDD NIO SE MELI ARM SMCI MSTR
HOOD GME EA TTWO ROKU LYFT ZM DOCU OKTA TWLO ETSY W CHWY DKNG
"""

# --------------------------------------------------------------- nazwy

#: Końcówki prawne obcinane z nazwy wyświetlanej. Ludzie szukają „Orlen",
#: nie „Polski Koncern Naftowy ORLEN Spółka Akcyjna".
SUFIKSY = [
    r"\bS\.?\s?A\.?$", r"\bSpółka Akcyjna$", r"\bSp[oó]{1}[lł]ka Akcyjna$",
    r"\bAlternatywna Sp[oó]{1}[lł]ka Inwestycyjna$",
    r"\bInc\.?$", r"\bIncorporated$", r"\bCorporation$", r"\bCorp\.?$",
    r"\bCompany$", r"\bCo\.?$", r"\bplc$", r"\bPLC$", r"\bN\.?V\.?$",
    r"\bLtd\.?$", r"\bLimited$", r"\bAG$", r"\bHoldings?$", r"\bGroup$",
    r"\bClass [A-C]$", r"\bLLC$", r"\bS\.?E\.?$", r"\bASA$", r"\b& Co\.?$",
    r"\band$", r"\(The\)$", r"^The\s+", r"\bCompanies$", r"\bTechnologies$", r",$",
]

#: Nazwy, których automat nie odgadnie. Dwa powody, dla których to jest potrzebne:
#: Yahoo gubi polskie znaki diakrytyczne („Kety" zamiast „Kęty", „Sniezka" zamiast
#: „Śnieżka") i podaje formy urzędowe zamiast prasowych.
NAZWY = {
    # GPW
    "ABE.WA": "Grupa AB", "ALE.WA": "Allegro", "ATT.WA": "Grupa Azoty",
    "BOS.WA": "Bank Ochrony Środowiska", "CDR.WA": "CD Projekt",
    "DBC.WA": "Dębica", "DNP.WA": "Dino Polska", "ENA.WA": "Enea",
    "FRO.WA": "Ferro", "FTE.WA": "Forte", "GPW.WA": "GPW", "GTC.WA": "GTC",
    "ING.WA": "ING Bank Śląski", "JSW.WA": "Jastrzębska Spółka Węglowa",
    "KGH.WA": "KGHM", "KGN.WA": "Kogeneracja", "KRU.WA": "Kruk",
    "KTY.WA": "Grupa Kęty", "LWB.WA": "Bogdanka", "MBK.WA": "mBank",
    "MCI.WA": "MCI Capital", "MOL.WA": "MOL", "NEU.WA": "Neuca",
    "OPL.WA": "Orange Polska", "OPN.WA": "Oponeo", "PCF.WA": "PCF Group",
    "PCO.WA": "Pepco", "PEO.WA": "Bank Pekao", "PGE.WA": "PGE",
    "PHN.WA": "Polski Holding Nieruchomości", "PKN.WA": "Orlen",
    "PKO.WA": "PKO BP", "PZU.WA": "PZU", "SKA.WA": "Śnieżka",
    "SNZ.WA": "Śnieżka", "SPL.WA": "Santander Bank Polska",
    "STX.WA": "Stalexport Autostrady", "SWG.WA": "Seco/Warwick",
    "TOA.WA": "Toya", "TPE.WA": "Tauron", "TXT.WA": "Text",
    "ULM.WA": "Ulma Construccion Polska", "XTB.WA": "XTB",
    "ZAP.WA": "Zakłady Azotowe Puławy", "11B.WA": "11 bit studios",
    # USA
    "AMZN": "Amazon", "ARM": "Arm", "ASML": "ASML", "BA": "Boeing",
    "BABA": "Alibaba", "BKNG": "Booking Holdings", "BRK-B": "Berkshire Hathaway",
    "CI": "Cigna", "DIS": "Walt Disney", "GOOGL": "Alphabet (Google)",
    "GS": "Goldman Sachs", "HD": "Home Depot", "HOOD": "Robinhood",
    "IBM": "IBM", "KO": "Coca-Cola", "LLY": "Eli Lilly", "LOW": "Lowe's",
    "MELI": "MercadoLibre", "META": "Meta Platforms",
    "MSTR": "Strategy (MicroStrategy)", "NKE": "Nike", "PDD": "PDD (Temu)",
    "PG": "Procter & Gamble", "PLTR": "Palantir", "QCOM": "Qualcomm",
    "REGN": "Regeneron", "RIVN": "Rivian", "SE": "Sea Limited",
    "SO": "Southern Company", "SOFI": "SoFi", "SPOT": "Spotify",
    "TJX": "TJX Companies", "TSM": "TSMC", "TTWO": "Take-Two Interactive",
    "U": "Unity", "UBER": "Uber",
}

#: Slugi ustawione ręcznie. Automat zamieniłby „&" na słowo i wyszłoby
#: „at-i-t" — adres, którego nikt nie przeczyta.
SLUGI = {
    "T": "att", "JNJ": "johnson-johnson", "PG": "procter-gamble",
    "SPGI": "sp-global",
    # Sama giełda też jest spółką notowaną, a „gpw" pod `/wyniki-finansowe/`
    # zajmuje spis spółek z warszawskiego parkietu — patrz ZAJETE_SLUGI.
    "GPW.WA": "gpw-sa",
}

#: Slugi, których spółce przydzielić NIE WOLNO, bo pod `/wyniki-finansowe/<slug>`
#: stoją już własne strony serwisu.
#:
#: Skąd to się wzięło: GPW S.A. dostała slug „gpw", czyli dokładnie adres spisu
#: spółek z warszawskiej giełdy. Trasa spisu jest zarejestrowana wcześniej niż
#: `/{slug}`, więc karta tej spółki po prostu nie istniała — jej adres podawał
#: listę. Sitemapa wymieniała ten adres dwa razy, z dwoma różnymi priorytetami,
#: a link z listy spółek prowadził z powrotem na tę samą listę.
ZAJETE_SLUGI = {"gpw", "usa", "sektor"}

SEKTORY_PL = {
    "Technology": "technologia",
    "Consumer Cyclical": "handel i dobra konsumpcyjne",
    "Industrials": "przemysł",
    "Financial Services": "finanse",
    "Healthcare": "ochrona zdrowia",
    "Communication Services": "media i telekomunikacja",
    "Consumer Defensive": "dobra podstawowe",
    "Basic Materials": "surowce i materiały",
    "Utilities": "energetyka i media komunalne",
    "Real Estate": "nieruchomości",
    "Energy": "paliwa i energia",
}


def slugify(tekst: str) -> str:
    """Nazwa → fragment adresu. Polskie znaki na łacińskie, „&" znika."""
    t = unicodedata.normalize("NFKD", tekst)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("ł", "l").replace("Ł", "L").replace("&", " ")
    t = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")
    return re.sub(r"-{2,}", "-", t)


def nazwa_krotka(pelna: str, symbol: str) -> str:
    if symbol in NAZWY:
        return NAZWY[symbol]
    n = pelna.strip()
    poprzednia = None
    while n != poprzednia:
        poprzednia = n
        for s in SUFIKSY:
            n = re.sub(s, "", n, flags=re.I).strip(" ,.&")
    return n or pelna


# --------------------------------------------------------------- pobieranie


def _pytaj(symbol: str):
    """Dane spółki z Yahoo albo None, gdy symbol nic nie zwraca."""
    from portfolio import market as pf_market

    for proba in (0, 1):
        try:
            crumb = pf_market._get_crumb(force=bool(proba))
            if not crumb:
                return symbol, None
            r = pf_market._session.get(
                "https://query2.finance.yahoo.com/v10/finance/quoteSummary/"
                f"{requests.utils.quote(symbol)}"
                "?modules=price,assetProfile"
                f"&crumb={requests.utils.quote(crumb)}", timeout=20)
            if r.status_code == 401 and proba == 0:
                continue
            if r.status_code != 200:
                return symbol, None
            wyniki = (r.json().get("quoteSummary") or {}).get("result") or []
            if not wyniki:
                return symbol, None
            node = wyniki[0]
            pr, ap = node.get("price") or {}, node.get("assetProfile") or {}
            pelna = pr.get("longName") or pr.get("shortName")
            if not pelna:
                return symbol, None
            return symbol, {"legal": pelna, "exchange": pr.get("exchangeName") or "",
                            "currency": pr.get("currency") or "",
                            "sector": ap.get("sector") or "",
                            "industry": ap.get("industry") or "",
                            "country": ap.get("country") or "",
                            "website": ap.get("website") or ""}
        except Exception as e:  # noqa: BLE001
            print(f"  błąd {symbol}: {str(e)[:80]}", flush=True)
            return symbol, None
    return symbol, None


def main() -> None:
    import sys
    sys.path.insert(0, os.path.dirname(TU))       # żeby zadziałał import `portfolio`
    # Konsola Windows startuje w cp1250 i wywala się na strzałce „→" oraz na
    # polskich znakach. Bez tej linijki skrypt kończy się wyjątkiem PO zapisaniu
    # pliku — wygląda jak awaria, choć katalog jest już gotowy.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — starszy Python albo przekierowane wyjście
        pass

    symbole = ([f"{t}.WA" for t in dict.fromkeys(GPW.split())]
               + list(dict.fromkeys(USA.split())))
    print(f"Sprawdzam {len(symbole)} symboli w Yahoo…")

    dane, odpadly = {}, []
    # sześć wątków: więcej i Yahoo zaczyna odrzucać zapytania
    with futures.ThreadPoolExecutor(max_workers=6) as pool:
        for i, (sym, d) in enumerate(pool.map(_pytaj, symbole), 1):
            (dane.__setitem__(sym, d) if d else odpadly.append(sym))
            if i % 25 == 0:
                print(f"  {i}/{len(symbole)}  działa: {len(dane)}", flush=True)

    katalog, uzyte = [], set()
    for sym, d in dane.items():
        nazwa = nazwa_krotka(d["legal"], sym)
        slug = SLUGI.get(sym) or slugify(nazwa)
        if not slug:
            continue
        # Kolizja z inną spółką ALBO z własną stroną serwisu — doklej ticker.
        if slug in uzyte or slug in ZAJETE_SLUGI:
            slug = f"{slug}-{slugify(sym.split('.')[0])}"
        uzyte.add(slug)
        gpw = sym.endswith(".WA")
        katalog.append({
            "symbol": sym, "slug": slug, "name": nazwa, "legal": d["legal"],
            "market": "GPW" if gpw else "USA",
            "exchange": d["exchange"] or ("Warsaw" if gpw else ""),
            "currency": d["currency"] or ("PLN" if gpw else "USD"),
            "sector": d["sector"],
            "sector_pl": SEKTORY_PL.get(d["sector"], ""),
            "industry": d["industry"],
            "country": d["country"] or ("Poland" if gpw else ""),
            "website": d["website"],
        })

    katalog.sort(key=lambda x: (x["market"] != "GPW", x["name"].lower()))
    with open(CEL, "w", encoding="utf-8") as f:
        json.dump(katalog, f, ensure_ascii=False, indent=1)

    gpw = sum(1 for x in katalog if x["market"] == "GPW")
    print(f"\nZapisano {len(katalog)} spółek ({gpw} z GPW, {len(katalog) - gpw} z USA)"
          f" → {os.path.relpath(CEL, os.path.dirname(TU))}")
    if odpadly:
        print(f"Odpadło {len(odpadly)} (brak danych w Yahoo): {' '.join(odpadly)}")
    bez = [x['symbol'] for x in katalog if not x["sector_pl"]]
    if bez:
        print(f"Bez sektora (uzupełnij SEKTORY_PL, jeśli trzeba): {' '.join(bez)}")


if __name__ == "__main__":
    main()
