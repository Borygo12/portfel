"""Dogrywka katalogu: dokłada spółki płacące dywidendę, których w nim nie ma.

Po co osobny skrypt zamiast rozszerzenia `make_catalog.py`: tamten buduje
katalog **od zera** i nadaje slugi na nowo. Puszczenie go po zaindeksowaniu
serwisu groziłoby zmianą slugu istniejącej spółki, a slug jest adresem URL —
zmiana kasuje pozycję strony w wyszukiwarce i zostawia po sobie czterysta
czwórkę. Ten skrypt **wyłącznie dopisuje**: wpisy, które już są, zostają
nietknięte co do znaku.

Katalog powstał pod kalendarz wyników, więc dobierany był pod płynność
i rozpoznawalność. Inwestora dywidendowego interesuje inny przekrój — fundusze
nieruchomości (REIT), spółki użyteczności publicznej i dobra podstawowe, czyli
firmy nudne, ale wypłacające regularnie od dekad. Kandydaci niżej to właśnie ta
luka, uzupełniona o polskich płatników, których zabrakło.

**Kandydat wchodzi do katalogu tylko wtedy, gdy naprawdę płaci.** Sprawdzamy to
historią wypłat, a nie samą obecnością w Yahoo — dopisanie spółki bez dywidendy
do katalogu pod narzędzie dywidendowe byłoby dokładaniem szumu, a przy okazji
kolejną chudą podstroną w sitemapie.

Uruchamiaj lokalnie: `python bot/seo/add_dividend_payers.py`
Po dopisaniu spółek uruchom `python bot/seo/make_logos.py`, inaczej nowe
pozycje zostaną z monogramem zamiast logotypu.
"""

from __future__ import annotations

import concurrent.futures as futures
import json
import os
import sys

TU = os.path.dirname(os.path.abspath(__file__))
CEL = os.path.join(TU, "companies.json")

#: Fundusze nieruchomości, spółki użyteczności publicznej, dobra podstawowe
#: i przemysł — trzon każdego portfela dywidendowego, którego katalog nie miał.
USA = """
O MAIN STAG VICI WPC NNN ADC EPRT
D NEE DUK SO AEP ED XEL WEC ES
MMM WM RSG ITW EMR DOV NDSN SWK
TGT KMB GIS HSY CL SYY ADM K
ADP PAYX AFL CINF TROW BEN
AMCR IP PKG NUE
"""

#: Polscy płatnicy, których w katalogu nie było.
GPW = """
SPL TIM AUTO AMB ELT
"""


def _kandydaci(istniejace: set[str]) -> list[str]:
    poz = ([f"{t}.WA" for t in dict.fromkeys(GPW.split())]
           + list(dict.fromkeys(USA.split())))
    return [s for s in poz if s.upper() not in istniejace]


def main() -> None:
    sys.path.insert(0, os.path.dirname(TU))
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    import dividend_lab
    from seo import make_catalog as mk

    with open(CEL, encoding="utf-8") as f:
        katalog = json.load(f)
    istniejace = {s["symbol"].upper() for s in katalog}
    uzyte = {s["slug"] for s in katalog}

    kandydaci = _kandydaci(istniejace)
    print(f"Katalog ma {len(katalog)} spółek. Sprawdzam {len(kandydaci)} kandydatów…")
    if not kandydaci:
        print("Nie ma czego dokładać.")
        return

    dane = {}
    with futures.ThreadPoolExecutor(max_workers=6) as pool:
        for sym, d in pool.map(mk._pytaj, kandydaci):
            if d:
                dane[sym] = d
    print(f"  dane z Yahoo: {len(dane)}/{len(kandydaci)}")

    dodane, bez_dywidendy, bez_danych = [], [], []
    for sym in kandydaci:
        d = dane.get(sym)
        if not d:
            bez_danych.append(sym)
            continue

        # Twardy warunek wejścia: musi mieć historię wypłat.
        wyplaty = dividend_lab.historia(sym)
        if not wyplaty:
            bez_dywidendy.append(sym)
            continue

        nazwa = mk.nazwa_krotka(d["legal"], sym)
        slug = mk.SLUGI.get(sym) or mk.slugify(nazwa)
        if not slug:
            continue
        if slug in uzyte or slug in mk.ZAJETE_SLUGI:
            slug = f"{slug}-{mk.slugify(sym.split('.')[0])}"
        uzyte.add(slug)

        gpw = sym.endswith(".WA")
        dodane.append({
            "symbol": sym, "slug": slug, "name": nazwa, "legal": d["legal"],
            "market": "GPW" if gpw else "USA",
            "exchange": d["exchange"] or ("Warsaw" if gpw else ""),
            "currency": d["currency"] or ("PLN" if gpw else "USD"),
            "sector": d["sector"],
            "sector_pl": mk.SEKTORY_PL.get(d["sector"], ""),
            "industry": d["industry"],
            "country": d["country"] or ("Poland" if gpw else ""),
            "website": d["website"],
        })
        print(f"  + {sym:8} {nazwa[:34]:36} /{slug}  ({len(wyplaty)} wypłat)")

    if not dodane:
        print("\nŻaden kandydat nie przeszedł.")
        return

    katalog += dodane
    # Ta sama kolejność i ten sam zapis co w `make_catalog`, żeby różnica
    # w repozytorium pokazywała wyłącznie dopisane wiersze.
    katalog.sort(key=lambda x: (x["market"] != "GPW", x["name"].lower()))
    with open(CEL, "w", encoding="utf-8") as f:
        json.dump(katalog, f, ensure_ascii=False, indent=1)
        f.write("\n")

    gpw_ile = sum(1 for x in katalog if x["market"] == "GPW")
    print(f"\nDopisano {len(dodane)}. Katalog ma teraz {len(katalog)} spółek "
          f"({gpw_ile} z GPW, {len(katalog) - gpw_ile} z USA).")
    if bez_dywidendy:
        print(f"Pominięte, bo nie płacą dywidendy: {' '.join(bez_dywidendy)}")
    if bez_danych:
        print(f"Pominięte, brak danych w Yahoo: {' '.join(bez_danych)}")
    print("\nURUCHOM TERAZ: python bot/seo/make_logos.py")


if __name__ == "__main__":
    main()
