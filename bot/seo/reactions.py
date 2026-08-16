"""Jak kurs reaguje na wyniki — ranking spółek, których nikt inny w Polsce nie liczy.

To jest jedyna sekcja serwisu, której treści **nie da się przepisać z Bankiera,
StockWatcha ani Investing.com**, bo tam jej po prostu nie ma. Terminy publikacji
i konsensus analityków mają wszyscy; odpowiedź na pytanie „ile ta spółka zwykle
skacze na sesji po raporcie" nie ma polskiego źródła. Dla serwisu bez linków
z zewnątrz to najcenniejsza rzecz, jaką ma — treść, do której ktoś może chcieć
podlinkować.

Skąd liczby: `earnings/report.py` zestawia daty publikacji z Nasdaqa z notowaniami
dziennymi z Yahoo i liczy zmianę kursu na pierwszej sesji po każdym raporcie
(`history[].reaction_pct`), a z nich `stats.avg_move_pct`, `max_move_pct`
i `beat_rate`. Ten moduł nic nie liczy od nowa — czyta gotowe wartości z cache
raportów i układa je w rankingi.

Dwa ograniczenia, które są na stronach powiedziane wprost, bo bez nich ranking
wprowadzałby w błąd:

* **Próbka jest krótka.** Zwykle cztery kwartały, czasem mniej. Średnia z czterech
  odczytów mówi o skłonności spółki do gwałtownych ruchów, ale nie jest prognozą
  najbliższej sesji i nie wolno jej tak przedstawiać.
* **Reakcja to nie ocena spółki.** Wysoki średni ruch znaczy tyle, że rynek
  bywa zaskakiwany — a to cecha wyceny i oczekiwań, nie jakości biznesu.
  Spółka o najspokojniejszym kursie nie jest gorsza, tylko przewidywalna.
"""

from __future__ import annotations

import datetime as dt
import logging

from . import companies, dates, jsonld, logos, pamiec, render

log = logging.getLogger("seo.reactions")

BAZA = "/reakcja-kursu-po-wynikach"

#: Dzień ostatniej zmiany tekstu — `lastmod` w sitemapie.
ZMIENIONO = "2026-08-16"

#: Jak stary może być raport, z którego bierzemy statystykę. Trzydzieści dni,
#: i to nie z lenistwa: **te liczby zmieniają się wyłącznie wtedy, gdy spółka
#: opublikuje nowy raport**, czyli raz na kwartał. Przy dobowym oknie ranking
#: kurczył się do kilkunastu spółek — tych, które ktoś akurat odwiedził w ciągu
#: doby — zamiast pokazywać sto czterdzieści, dla których dane są policzone
#: i nadal prawdziwe. Krótkie okno nie dawało tu świeższych danych, tylko mniej.
TTL_RAPORTU = 30 * 24 * 3600

#: Minimalna liczba kwartałów, żeby spółka weszła do rankingu. Poniżej trzech
#: „średnia" jest pojedynczym odczytem przebranym za statystykę — a ranking
#: zbudowany na jednym kwartale byłby losowaniem, nie danymi.
MIN_KWARTALOW = 3


# --------------------------------------------------------------- dane


def _z_cache() -> list[dict]:
    """Statystyki reakcji wszystkich spółek, których raport leży w cache."""
    try:
        from earnings import cache as e_cache
    except Exception as e:  # noqa: BLE001
        log.warning("Brak modułu cache: %s", e)
        return []

    wynik = []
    for s in companies.SPOLKI:
        raport = e_cache.get(f"report-{s['symbol']}", TTL_RAPORTU)
        if not raport:
            continue
        st = raport.get("stats") or {}
        sredni = st.get("avg_move_pct")
        kwartalow = st.get("quarters") or 0
        if not isinstance(sredni, (int, float)) or kwartalow < MIN_KWARTALOW:
            continue

        # Ostatnia znana reakcja — najciekawsza pojedyncza liczba dla czytelnika,
        # bo mówi, co stało się naprawdę, a nie co się zwykle dzieje.
        ostatnia, ostatnia_data = None, ""
        for h in reversed(raport.get("history") or []):
            if isinstance(h.get("reaction_pct"), (int, float)):
                ostatnia, ostatnia_data = h["reaction_pct"], h.get("date") or h.get("quarter") or ""
                break

        wynik.append({
            "spolka": s,
            "symbol": s["symbol"],
            "nazwa": s["name"],
            "adres": companies.adres(s),
            "rynek": s["market"],
            "sredni": round(float(sredni), 2),
            "najwiekszy": st.get("max_move_pct"),
            "powyzej_prognoz": st.get("beat_rate"),
            "kwartalow": kwartalow,
            "ostatnia": ostatnia,
            "ostatnia_data": (ostatnia_data or "")[:10],
            "kapitalizacja": raport.get("market_cap"),
        })
    wynik.sort(key=lambda p: -p["sredni"])
    return wynik


def wszystkie() -> list[dict]:
    return pamiec.zapamietane("reakcje", _z_cache)


def rynek(nazwa: str = "") -> list[dict]:
    return [p for p in wszystkie() if not nazwa or p["rynek"] == nazwa]


def najspokojniejsze(nazwa: str = "", limit: int = 25) -> list[dict]:
    return sorted(rynek(nazwa), key=lambda p: p["sredni"])[:limit]


def dla_spolki(slug: str) -> dict | None:
    return next((p for p in wszystkie() if p["spolka"]["slug"] == slug), None)


def sasiedzi_w_rankingu(slug: str, ile: int = 6) -> list[dict]:
    """Spółki o podobnej zmienności po wynikach — „skoro tu jesteś, zobacz też”."""
    poz = wszystkie()
    idx = next((i for i, p in enumerate(poz) if p["spolka"]["slug"] == slug), None)
    if idx is None:
        return []
    od = max(0, idx - ile // 2)
    return [p for p in poz[od:od + ile + 1] if p["spolka"]["slug"] != slug][:ile]


def miejsce(slug: str) -> tuple[int, int] | None:
    """(które miejsce, na ilu) w rankingu średniego ruchu. Do karty spółki."""
    poz = wszystkie()
    for i, p in enumerate(poz, start=1):
        if p["spolka"]["slug"] == slug:
            return i, len(poz)
    return None


def rozgrzej_zadania():
    return (("reakcje kursu po wynikach", wszystkie),)


# --------------------------------------------------------------- prezentacja


def _ruch(v) -> str:
    return render.procent(v, ze_znakiem=False) if isinstance(v, (int, float)) else "—"


def _kierunek(v) -> str:
    if not isinstance(v, (int, float)):
        return ""
    return "up" if v > 0 else ("down" if v < 0 else "")


def _tabela(pozycje) -> str:
    wiersze = []
    for i, p in enumerate(pozycje, start=1):
        wiersze.append([
            str(i),
            (p["nazwa"], "link", p["adres"]),
            companies.ticker(p["spolka"]),
            (_ruch(p["sredni"]), "num"),
            (_ruch(p["najwiekszy"]), "num"),
            (render.procent(p["ostatnia"]) if isinstance(p["ostatnia"], (int, float))
             else "—", _kierunek(p["ostatnia"]) or "num"),
            (f'{p["powyzej_prognoz"]}%' if isinstance(p["powyzej_prognoz"], (int, float))
             else "—", "num"),
        ])
    return render.tabela(
        ["#", "Spółka", "Ticker", ("Średni ruch", True), ("Największy", True),
         ("Ostatnia reakcja", True), ("Powyżej prognoz", True)],
        wiersze,
        f"Na podstawie ostatnich {MIN_KWARTALOW}–4 raportów każdej spółki")


def _wiersze(pozycje) -> str:
    return render.wiersze([{
        "logo": logos.znak(p["spolka"], 34),
        "tytul": f"{p['nazwa']} ({companies.ticker(p['spolka'])})",
        "podtytul": f"{p['kwartalow']} ostatnich raportów"
                    + (f" · ostatnio {render.procent(p['ostatnia'])}"
                       if isinstance(p["ostatnia"], (int, float)) else ""),
        "adres": p["adres"],
        "wartosc": _ruch(p["sredni"]),
        "nota": "średnio na sesji po wynikach",
    } for p in pozycje])


def _statystyki(pozycje) -> str:
    if not pozycje:
        return ""
    ruchy = [p["sredni"] for p in pozycje]
    naj = pozycje[0]
    spokojna = min(pozycje, key=lambda p: p["sredni"])
    return render.statystyki([
        ("Spółek w rankingu", str(len(pozycje)), f"min. {MIN_KWARTALOW} raporty"),
        ("Największa zmienność", _ruch(naj["sredni"]), naj["nazwa"]),
        ("Mediana", _ruch(sorted(ruchy)[len(ruchy) // 2]), "połowa spółek rusza się mniej"),
        ("Najspokojniejsza", _ruch(spokojna["sredni"]), spokojna["nazwa"]),
    ])


_DLACZEGO_BEZ_GPW = (
    "W rankingu są <strong>wyłącznie spółki z giełd amerykańskich</strong> i chcemy "
    "to powiedzieć wprost, zamiast zostawiać domysły. Żeby policzyć reakcję kursu, "
    "trzeba znać <strong>dokładną datę publikacji</strong> każdego minionego raportu — "
    "bez niej nie wiadomo, którą sesję sprawdzać. Dla spółek amerykańskich takie daty "
    "wstecz podaje kalendarz Nasdaqa. Dla warszawskiego parkietu <strong>nie ma "
    "źródła, które podawałoby je w formie nadającej się do liczenia</strong>: Yahoo "
    "zna tylko najbliższy termin, a Nasdaq spółek z GPW nie widzi wcale. Wolimy "
    "pokazać ranking bez GPW niż ranking z liczbami wziętymi z sufitu. Terminy "
    "publikacji spółek z Warszawy — te przyszłe — znajdziesz w kalendarzu wyników."
)

_JAK_LICZYMY = (
    "Bierzemy <strong>datę publikacji każdego raportu</strong> i sprawdzamy, o ile "
    "zmienił się kurs na pierwszej sesji po tej publikacji. „Średni ruch” to średnia "
    "z <strong>wartości bezwzględnych</strong> tych zmian — nie interesuje nas kierunek, "
    "tylko siła reakcji, bo spadek o 8% i wzrost o 8% są tak samo istotne dla kogoś, "
    "kto trzyma akcje przez wyniki. Daty publikacji pochodzą z Nasdaqa, notowania "
    "z Yahoo Finance."
)

_CO_TO_ZNACZY = (
    "Wysoki średni ruch nie znaczy, że spółka jest zła ani dobra — znaczy, że rynek "
    "bywa jej wynikami <strong>zaskakiwany</strong>. Tak zachowują się zwykle spółki "
    "wyceniane pod szybki wzrost, gdzie cała wycena zależy od jednego zdania w prognozie. "
    "Spółka na dole rankingu jest po prostu przewidywalna: rynek wie z grubsza, czego "
    "się spodziewać, więc raport niewiele zmienia."
)

_OSTRZEZENIE = (
    "Próbka jest krótka — zwykle cztery kwartały. To wystarczy, żeby zobaczyć "
    "<strong>skłonność</strong> spółki do gwałtownych ruchów, ale <strong>nie jest "
    "prognozą najbliższej sesji</strong> i nie należy jej tak traktować. Spółka, która "
    "trzy razy z rzędu skoczyła o 20%, przy czwartym raporcie równie dobrze może "
    "nie drgnąć."
)


def _faq_pary() -> list[tuple[str, str]]:
    return [
        ("Co dokładnie oznacza „średni ruch po wynikach”?",
         "Średnią z bezwzględnych zmian kursu na pierwszej sesji po publikacji "
         "raportu, z ostatnich trzech do czterech kwartałów. Bezwzględnych, bo liczy "
         "się siła reakcji, a nie jej kierunek."),
        ("Czy wysoka zmienność po wynikach to coś złego?",
         "Nie. To informacja o tym, że rynek bywa zaskakiwany wynikami tej spółki — "
         "typowe dla firm wycenianych pod szybki wzrost. O jakości biznesu nie mówi nic."),
        ("Czy na tej podstawie można przewidzieć następną sesję?",
         "Nie. Cztery odczyty pokazują skłonność do gwałtownych ruchów, ale nie "
         "prognozują konkretnego raportu. Portevo nie publikuje rekomendacji."),
        ("Dlaczego w rankingu nie ma spółek z GPW?",
         "Bo do policzenia reakcji potrzebna jest dokładna data publikacji każdego "
         "minionego raportu, a dla warszawskiej giełdy nie ma źródła, które podawałoby "
         "je wstecz. Nasdaq zna tylko spółki amerykańskie, a Yahoo dla GPW podaje "
         "wyłącznie najbliższy termin. Wolimy pominąć GPW niż zgadywać."),
        ("Dlaczego niektórych spółek nie ma w rankingu?",
         f"Bo mamy dla nich mniej niż {MIN_KWARTALOW} raporty z policzoną reakcją "
         "kursu. Średnia z jednego odczytu nie jest statystyką, więc takie spółki "
         "pomijamy zamiast pokazywać liczbę udającą dane."),
        ("Skąd pochodzą daty publikacji i notowania?",
         "Daty z kalendarza Nasdaqa, notowania dzienne z Yahoo Finance. Te same "
         "źródła zasilają kalendarz wyników i karty spółek w Portevo."),
    ]


# --------------------------------------------------------------- strony

STRONY = {
    "": {
        "tytul": "Reakcja kursu po wynikach — ranking spółek | Portevo",
        "h1": "Jak kurs reaguje na wyniki — ranking spółek",
        "opis": "O ile średnio rusza się kurs na sesji po publikacji raportu "
                "kwartalnego. Ranking spółek z Nasdaq i NYSE, policzony z dat "
                "publikacji i notowań dziennych.",
        "lead": "Terminy publikacji i prognozy analityków znajdziesz w wielu miejscach. "
                "Tego, ile dana spółka <strong>zwykle skacze</strong> na sesji po "
                "raporcie, nie liczy po polsku nikt — więc policzyliśmy to sami.",
        "rynek": "",
        "spokojne": False,
    },
    "usa": {
        "tytul": "Reakcja kursu po wynikach — spółki z USA | Portevo",
        "h1": "Reakcja kursu po wynikach — spółki z USA",
        "opis": "O ile średnio rusza się kurs amerykańskich spółek na sesji po "
                "raporcie kwartalnym. Ranking największych ruchów po wynikach.",
        "lead": "Na amerykańskim rynku dwucyfrowy ruch po wynikach nie jest niczym "
                "wyjątkowym — poniżej spółki, przy których trzymanie akcji przez "
                "raport jest osobną decyzją.",
        "rynek": "USA",
        "spokojne": False,
    },
    "najspokojniejsze": {
        "tytul": "Spółki najspokojniejsze po wynikach — ranking | Portevo",
        "h1": "Spółki, które po wynikach ledwo drgają",
        "opis": "Spółki o najmniejszej reakcji kursu na publikację raportu — "
                "ranking od najspokojniejszych, z GPW i z USA.",
        "lead": "Druga strona tego samego rankingu. Te spółki rynek zna na tyle dobrze, "
                "że raport niewiele w ich wycenie zmienia — co dla kogoś, kto nie chce "
                "niespodzianek, bywa ważniejsze niż lista rekordzistów.",
        "rynek": "",
        "spokojne": True,
    },
}


def adresy() -> list[str]:
    return [BAZA] + [f"{BAZA}/{s}" for s in STRONY if s]


def _linki_poboczne(slug: str) -> str:
    poz = [("", "Cały ranking"), ("usa", "Spółki z USA"),
           ("najspokojniejsze", "Najspokojniejsze")]
    return render.chipsy(
        [(f"{BAZA}/{s}" if s else BAZA, t) for s, t in poz if s != slug]
        + [("/kalendarz-wynikow-spolek", "Kalendarz wyników"),
           ("/sezon-wynikow", "Kto raportuje teraz"),
           ("/dywidendy", "Dywidendy spółek")])


def zbuduj(slug: str = "") -> str | None:
    cfg = STRONY.get(slug)
    if cfg is None:
        return None

    if cfg["spokojne"]:
        pozycje = najspokojniejsze(cfg["rynek"], limit=30)
    else:
        pozycje = rynek(cfg["rynek"])[:40]

    bloki = []
    if pozycje:
        bloki.append(_statystyki(rynek(cfg["rynek"])))
        bloki.append(render.sekcja(
            "Ranking spółka po spółce",
            html_dodatkowy=_tabela(pozycje)))
    else:
        bloki.append(render.sekcja(
            "Dane się jeszcze zbierają",
            "Reakcje kursu liczymy z raportów spółek, a te trafiają do pamięci "
            "serwera stopniowo. Wejdź na kartę konkretnej spółki — jej historia "
            "reakcji policzy się od razu.",
            html_dodatkowy=render.chipsy([
                ("/wyniki-finansowe/gpw", "Spółki z GPW"),
                ("/wyniki-finansowe/usa", "Spółki z USA")])))

    bloki.append(render.sekcja("Jak to liczymy", _JAK_LICZYMY))
    bloki.append(render.sekcja(
        "Dlaczego nie ma tu spółek z GPW", _DLACZEGO_BEZ_GPW,
        html_dodatkowy=render.chipsy([
            ("/kalendarz-wynikow-spolek", "Kalendarz wyników spółek z GPW"),
            ("/wyniki-finansowe/gpw", "Wszystkie spółki z GPW"),
            ("/dywidendy/gpw", "Dywidendy z GPW")])))
    bloki.append(render.sekcja("Co ta liczba właściwie mówi", _CO_TO_ZNACZY))

    if not cfg["spokojne"] and pozycje:
        spokojne = najspokojniejsze(cfg["rynek"], limit=6)
        if spokojne:
            bloki.append(render.sekcja(
                "Na drugim końcu skali",
                "Spółki, przy których raport przechodzi niemal bez echa.",
                html_dodatkowy=_wiersze(spokojne)
                + render.chipsy([(f"{BAZA}/najspokojniejsze",
                                  "Pełna lista najspokojniejszych")])))

    bloki.append(render.sekcja("Zanim to gdziekolwiek wykorzystasz", _OSTRZEZENIE))
    bloki.append(render.sekcja("Zobacz też", html_dodatkowy=_linki_poboczne(slug)))
    bloki.append(render.faq(_faq_pary()))
    bloki.append(render.zacheta(
        "Sprawdź, jak reagują Twoje spółki",
        "Dodaj spółkę do obserwowanych, a jej historię reakcji na wyniki zobaczysz "
        "razem z terminem najbliższego raportu.",
        "/", "Otwórz Portevo",
        drugi=("/kalendarz-wynikow-spolek", "Kalendarz wyników"),
        trzeci=("/sezon-wynikow", "Kto raportuje teraz")))
    bloki.append(render.zastrzezenie())

    sciezka = f"{BAZA}/{slug}" if slug else BAZA
    dane = [
        jsonld.strona(sciezka, cfg["tytul"], cfg["opis"],
                      zmieniono=dt.date.today().isoformat()),
        jsonld.okruchy([(BAZA, "Reakcja kursu po wynikach")]
                       + ([(sciezka, cfg["h1"])] if slug else [])),
        jsonld.pytania(_faq_pary()),
    ]
    if pozycje:
        dane.append(jsonld.lista_pozycji(
            cfg["h1"], [(p["adres"], p["nazwa"]) for p in pozycje[:25]]))

    return render.strona(
        sciezka=sciezka,
        tytul=cfg["tytul"],
        opis=cfg["opis"],
        h1=cfg["h1"],
        lead=cfg["lead"],
        nadtytul="Reakcja kursu",
        okruchy=([(None, "Reakcja kursu po wynikach")] if not slug
                 else [(BAZA, "Reakcja kursu po wynikach"), (None, cfg["h1"])]),
        aktualizacja=dates.dzis(),
        jsonld=dane,
        bloki=bloki,
    )
