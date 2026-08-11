"""Podstrona wyników finansowych jednej spółki.

Skąd bierze się treść: z tego samego raportu, który w aplikacji zasila kartę
spółki (`earnings/report.py`) — konsensus na najbliższy kwartał, historia
zaskoczeń, reakcje kursu po poprzednich publikacjach, prognozy i marże. To są
dane, których nie ma nikt inny po polsku w jednym miejscu, więc strona ma treść
własną, a nie przepisany opis z Wikipedii.

Problem, który rozwiązuje `_dane()`: raport składa się z kilku zapytań do Yahoo
i Nasdaqa i przy zimnym cache potrafi trwać kilkanaście sekund. Robot Google ma
na stronę budżet czasu i strona, która myśli 15 sekund, po prostu wypada
z indeksowania. Dlatego czekamy najwyżej kilka sekund, a resztę dociągamy
w tle — pierwsze wejście dostaje stronę uboższą, każde kolejne pełną. Wersja
bez danych dostaje `noindex`, żeby pusta strona nie weszła do indeksu i nie
ciągnęła oceny domeny w dół.
"""

from __future__ import annotations

import concurrent.futures as futures
import datetime as dt
import logging
import threading

from . import companies, jsonld, render

log = logging.getLogger("seo.company")

TTL = 3 * 3600
#: Ile sekund wolno czekać na raport przy zimnym cache. Powyżej ~8 s rośnie
#: ryzyko, że robot uzna stronę za wolną i przerwie pobieranie.
BUDZET_S = 7.0

# Jeden mały pool na całą warstwę SEO. Robot potrafi wejść na 50 podstron naraz;
# bez ograniczenia liczby wątków wysłalibyśmy do Yahoo 50 równoległych zapytań
# i dostali blokadę, która zabrałaby dane także aplikacji.
_pool = futures.ThreadPoolExecutor(max_workers=3, thread_name_prefix="seo-report")
_w_toku: dict[str, futures.Future] = {}
_zamek = threading.Lock()

MIESIACE = ("stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
            "lipca", "sierpnia", "września", "października", "listopada", "grudnia")


def data_pl(iso: str) -> str:
    """„2026-08-12” → „12 sierpnia 2026”. Pusty napis, gdy daty nie ma."""
    try:
        d = dt.date.fromisoformat((iso or "")[:10])
    except (ValueError, TypeError):
        return ""
    return f"{d.day} {MIESIACE[d.month - 1]} {d.year}"


def _pobierz(symbol: str):
    from earnings import report as earn_report
    return earn_report.report(symbol)


def _dane(symbol: str, budzet: float = BUDZET_S):
    """Raport spółki z cache, a przy jego braku — z krótkim czekaniem.

    Zwraca `(dane, kompletne)`. `kompletne=False` znaczy „nie zdążyliśmy”,
    a nie „spółka nie istnieje” — dane dojdą do cache w tle.
    """
    from earnings import cache as e_cache

    swieze = e_cache.get(f"report-{symbol}", TTL)
    if swieze:
        return swieze, True

    with _zamek:
        zadanie = _w_toku.get(symbol)
        if zadanie is None or zadanie.done():
            zadanie = _pool.submit(_pobierz, symbol)
            _w_toku[symbol] = zadanie

    try:
        wynik = zadanie.result(timeout=budzet)
    except futures.TimeoutError:
        # Nie anulujemy — wątek ma dokończyć i zapisać do cache dla następnego wejścia.
        log.info("Raport %s nie zdążył w %.0fs — strona bez danych na żywo", symbol, budzet)
        return e_cache.get(f"report-{symbol}", 10 ** 9), False
    except Exception as e:  # noqa: BLE001
        log.warning("Raport %s: %s", symbol, e)
        return e_cache.get(f"report-{symbol}", 10 ** 9), False

    if not wynik or wynik.get("error"):
        return None, False
    return wynik, True


# --------------------------------------------------------------- kawałki treści


def _kafle(spolka: dict, d: dict) -> str:
    waluta = d.get("currency") or spolka.get("currency") or ""
    poz = []
    if d.get("price") is not None:
        zmiana = d.get("change_pct")
        poz.append(("Kurs", f"{render.liczba(d['price'])} {waluta}".strip(),
                    render.procent(zmiana) if zmiana is not None else "",
                    "up" if (zmiana or 0) > 0 else "down" if (zmiana or 0) < 0 else ""))
    if d.get("market_cap"):
        poz.append(("Kapitalizacja", render.duza(d["market_cap"], waluta)))
    nast = (d.get("next") or {}).get("date")
    if nast:
        poz.append(("Najbliższy raport", data_pl(nast),
                    "termin szacowany" if (d.get("next") or {}).get("estimate")
                    else "termin potwierdzony"))
    st = d.get("stats") or {}
    if st.get("beat_rate") is not None:
        poz.append(("Wyniki powyżej prognoz", f"{st['beat_rate']}%",
                    f"z {st.get('quarters', 0)} ostatnich kwartałów"))
    if st.get("avg_move_pct") is not None:
        poz.append(("Średni ruch kursu", f"{render.liczba(st['avg_move_pct'])}%",
                    "na sesji po publikacji"))
    if d.get("trailing_pe"):
        poz.append(("Wskaźnik C/Z", render.liczba(d["trailing_pe"])))
    return render.statystyki(poz) if poz else ""


def _sekcja_termin(spolka: dict, d: dict) -> str:
    nazwa = spolka["name"]
    nast = d.get("next") or {}
    waluta = d.get("currency") or spolka.get("currency") or ""
    akapity = []

    if nast.get("date"):
        kiedy = data_pl(nast["date"])
        pewnosc = ("Termin nie został jeszcze potwierdzony przez spółkę i może się "
                   "przesunąć." if nast.get("estimate")
                   else "Termin pochodzi z komunikatu spółki.")
        akapity.append(f"Najbliższy raport <strong>{render.esc(nazwa)}</strong> "
                       f"przypada na <strong>{render.esc(kiedy)}</strong>. {pewnosc}")
    else:
        akapity.append(
            f"Termin najbliższej publikacji wyników {render.esc(nazwa)} nie jest "
            "jeszcze znany. Spółki ogłaszają go zwykle na kilka tygodni przed "
            "raportem — kalendarz w aplikacji aktualizuje się sam, gdy data się pojawi.")

    if nast.get("eps") is not None:
        widelki = ""
        if nast.get("eps_low") is not None and nast.get("eps_high") is not None:
            widelki = (f" Prognozy analityków rozkładają się od "
                       f"{render.liczba(nast['eps_low'])} do "
                       f"{render.liczba(nast['eps_high'])} {render.esc(waluta)}.")
        akapity.append(
            f"Oczekiwany zysk na akcję (EPS) to <strong>"
            f"{render.liczba(nast['eps'])} {render.esc(waluta)}</strong>.{widelki} "
            "Rynek reaguje nie na samą wysokość zysku, tylko na różnicę między "
            "wynikiem a tą prognozą.")

    if nast.get("revenue") is not None:
        akapity.append(f"Oczekiwane przychody: <strong>"
                       f"{render.duza(nast['revenue'], waluta)}</strong>.")

    return render.sekcja(f"Kiedy {nazwa} publikuje wyniki", *akapity, kotwica="termin")


def _sekcja_historia(spolka: dict, d: dict) -> str:
    historia = [h for h in (d.get("history") or []) if h.get("quarter")]
    if not historia:
        return ""
    waluta = d.get("currency") or spolka.get("currency") or ""
    wiersze = []
    for h in reversed(historia[-10:]):
        zaskoczenie = h.get("surprise_pct")
        reakcja = h.get("reaction_pct")
        wiersze.append([
            data_pl(h["quarter"]) or h["quarter"],
            data_pl(h.get("date") or "") or "—",
            (render.liczba(h.get("estimate")), "num"),
            (render.liczba(h.get("eps")), "num"),
            (render.procent(zaskoczenie),
             "up" if (zaskoczenie or 0) > 0 else "down" if (zaskoczenie or 0) < 0 else "num"),
            (render.procent(reakcja),
             "up" if (reakcja or 0) > 0 else "down" if (reakcja or 0) < 0 else "num"),
        ])

    tabela = render.tabela(
        ["Kwartał", "Publikacja", ("Prognoza EPS", True), ("Wynik EPS", True),
         ("Zaskoczenie", True), ("Reakcja kursu", True)],
        wiersze,
        podpis=f"Wyniki kwartalne {spolka['name']} — prognoza, wykonanie i zachowanie "
               f"kursu na sesji po publikacji. Wartości EPS w {waluta or 'walucie notowania'}.",
    )

    st = d.get("stats") or {}
    akapity = []
    if st.get("beat_rate") is not None:
        akapity.append(
            f"W ostatnich {st.get('quarters', 0)} kwartałach spółka pobiła prognozy "
            f"analityków w <strong>{st['beat_rate']}%</strong> przypadków.")
    if st.get("avg_move_pct") is not None:
        naj = (f" Największy ruch wyniósł {render.liczba(st['max_move_pct'])}%."
               if st.get("max_move_pct") is not None else "")
        akapity.append(
            f"Średnia zmiana kursu na sesji po publikacji wyników to "
            f"<strong>{render.liczba(st['avg_move_pct'])}%</strong> — bez względu na "
            f"kierunek.{naj} To liczba, która mówi więcej o ryzyku trzymania pozycji "
            "przez raport niż sama prognoza zysku.")

    return render.sekcja("Jak kurs reagował na poprzednie wyniki", *akapity,
                         kotwica="historia", html_dodatkowy=tabela)


def _sekcja_prognozy(spolka: dict, d: dict) -> str:
    trend = [t for t in (d.get("trend") or []) if t.get("eps_avg") is not None]
    if not trend:
        return ""
    waluta = d.get("currency") or spolka.get("currency") or ""
    okresy = {"0q": "bieżący kwartał", "+1q": "następny kwartał",
              "0y": "bieżący rok", "+1y": "następny rok", "+5y": "5 lat",
              "-5y": "ostatnie 5 lat"}
    wiersze = []
    for t in trend:
        etykieta = okresy.get(t.get("period") or "", t.get("period") or "")
        if etykieta in ("5 lat", "ostatnie 5 lat"):
            continue
        wzrost = t.get("eps_growth")
        wiersze.append([
            etykieta,
            (render.liczba(t.get("eps_avg")), "num"),
            (render.liczba(t.get("eps_year_ago")), "num"),
            (render.procent(wzrost),
             "up" if (wzrost or 0) > 0 else "down" if (wzrost or 0) < 0 else "num"),
            (render.duza(t.get("rev_avg"), waluta), "num"),
            (str(int(t["analysts"])) if t.get("analysts") else "—", "num"),
        ])
    if not wiersze:
        return ""
    return render.sekcja(
        "Prognozy analityków na kolejne okresy",
        "Konsensus to średnia z prognoz wielu analityków. Im więcej ich stoi za "
        "liczbą, tym mniejsza szansa, że jest to pojedyncza pomyłka — ale zgodność "
        "prognoz nigdy nie jest gwarancją wyniku.",
        kotwica="prognozy",
        html_dodatkowy=render.tabela(
            ["Okres", ("Prognoza EPS", True), ("EPS rok wcześniej", True),
             ("Zmiana", True), ("Prognoza przychodów", True), ("Analityków", True)],
            wiersze,
            podpis=f"Prognozy dla {spolka['name']} — wartości EPS w "
                   f"{waluta or 'walucie notowania'}."),
    )


def _sekcja_marze(spolka: dict, d: dict) -> str:
    kwartaly = ((d.get("margins") or {}).get("quarterly") or [])[-8:]
    if len(kwartaly) < 2:
        return ""
    waluta = d.get("currency") or spolka.get("currency") or ""
    wiersze = []
    for k in reversed(kwartaly):
        wiersze.append([
            data_pl(k.get("date") or "") or (k.get("date") or ""),
            (render.duza(k.get("revenue"), waluta), "num"),
            (render.procent(k.get("gross_margin"), ze_znakiem=False), "num"),
            (render.procent(k.get("operating_margin"), ze_znakiem=False), "num"),
            (render.procent(k.get("net_margin"), ze_znakiem=False), "num"),
        ])
    return render.sekcja(
        "Przychody i marże kwartał po kwartale",
        "Marża pokazuje, ile ze sprzedaży zostaje w spółce. Rosnące przychody przy "
        "kurczącej się marży oznaczają, że wzrost jest kupowany kosztem rentowności — "
        "i to jest zwykle ciekawsza informacja niż sama dynamika sprzedaży.",
        kotwica="marze",
        html_dodatkowy=render.tabela(
            ["Kwartał", ("Przychody", True), ("Marża brutto", True),
             ("Marża operacyjna", True), ("Marża netto", True)],
            wiersze, podpis=f"Rachunek wyników {spolka['name']} kwartalnie."),
    )


def _sekcja_o_spolce(spolka: dict, d: dict) -> str:
    tick = companies.ticker(spolka)
    gielda = companies.gielda_pl(spolka)
    kraj = companies.kraj_pl(spolka)
    sektor = spolka.get("sector_pl")
    branza = spolka.get("industry")

    zdanie = f"<strong>{render.esc(spolka['legal'])}</strong> jest notowana na "
    zdanie += f"{render.esc(gielda)} pod tickerem <strong>{render.esc(tick)}</strong>"
    if kraj:
        zdanie += f", a jej siedziba mieści się w kraju: {render.esc(kraj)}"
    zdanie += "."
    if sektor:
        zdanie += (f" Spółka należy do sektora <strong>{render.esc(sektor)}</strong>"
                   + (f" (branża: {render.esc(branza)})" if branza else "") + ".")

    lista = [
        f"<b>Ticker:</b> {render.esc(tick)}"
        + (f" (symbol notowań: {render.esc(spolka['symbol'])})"
           if spolka["symbol"] != tick else ""),
        f"<b>Giełda:</b> {render.esc(gielda)}",
        f"<b>Waluta notowania:</b> {render.esc(d.get('currency') or spolka.get('currency') or '—')}",
    ]
    if sektor:
        lista.append(f"<b>Sektor:</b> {render.esc(sektor)}")
    if d.get("analysts"):
        lista.append(f"<b>Liczba analityków wydających prognozy:</b> "
                     f"{int(d['analysts'])}")
    if d.get("week52_low") is not None and d.get("week52_high") is not None:
        lista.append(f"<b>Zakres 52 tygodni:</b> {render.liczba(d['week52_low'])} – "
                     f"{render.liczba(d['week52_high'])}")
    if spolka.get("website"):
        lista.append(f'<b>Strona spółki:</b> <a href="{render.esc(spolka["website"])}" '
                     f'rel="nofollow noopener" target="_blank">'
                     f'{render.esc(spolka["website"])}</a>')

    return render.sekcja(f"O spółce {spolka['name']}", zdanie,
                         lista=lista, kotwica="o-spolce")


def _pytania(spolka: dict, d: dict) -> list:
    nazwa = spolka["name"]
    tick = companies.ticker(spolka)
    nast = d.get("next") or {}
    st = d.get("stats") or {}
    waluta = d.get("currency") or spolka.get("currency") or ""
    pary = []

    if nast.get("date"):
        pary.append((
            f"Kiedy {nazwa} publikuje wyniki?",
            f"Najbliższy raport przypada na {data_pl(nast['date'])}."
            + (" Termin jest szacowany i spółka może go przesunąć."
               if nast.get("estimate") else "")))
    else:
        pary.append((
            f"Kiedy {nazwa} publikuje wyniki?",
            "Termin najbliższej publikacji nie został jeszcze ogłoszony. "
            "Kalendarz wyników w Portevo aktualizuje się automatycznie, gdy spółka "
            "poda datę."))

    pary.append((
        f"Jaki jest ticker spółki {nazwa}?",
        f"{tick} — na giełdzie {companies.gielda_pl(spolka)}. "
        f"W serwisach z notowaniami spotkasz też zapis {spolka['symbol']}."))

    if nast.get("eps") is not None:
        pary.append((
            f"Ile wynosi prognoza zysku na akcję dla {nazwa}?",
            f"Konsensus analityków na najbliższy kwartał to "
            f"{render.liczba(nast['eps'])} {waluta} na akcję."
            + (f" Poszczególne prognozy mieszczą się w przedziale od "
               f"{render.liczba(nast['eps_low'])} do {render.liczba(nast['eps_high'])}."
               if nast.get("eps_low") is not None and nast.get("eps_high") is not None
               else "")))

    if st.get("avg_move_pct") is not None:
        pary.append((
            f"O ile zwykle zmienia się kurs {nazwa} po wynikach?",
            f"Średnio o {render.liczba(st['avg_move_pct'])}% na sesji po publikacji, "
            f"licząc w obie strony."
            + (f" Największy zanotowany ruch to {render.liczba(st['max_move_pct'])}%."
               if st.get("max_move_pct") is not None else "")))

    if st.get("beat_rate") is not None:
        pary.append((
            f"Czy {nazwa} zwykle bije prognozy analityków?",
            f"W ostatnich {st.get('quarters', 0)} kwartałach wynik przewyższył "
            f"prognozę w {st['beat_rate']}% przypadków. Historia nie przesądza "
            f"o kolejnym raporcie, ale pokazuje, jak ostrożnie analitycy podchodzą "
            f"do tej spółki."))

    pary.append((
        f"Gdzie sprawdzić wyniki finansowe {nazwa} po polsku?",
        "W Portevo — kalendarz wyników, prognozy analityków, historia zaskoczeń "
        "i reakcje kursu są dostępne bez opłat i bez zakładania konta."))
    return pary


# --------------------------------------------------------------- cała strona


def zbuduj(slug: str) -> tuple[str, bool] | None:
    """(HTML, czy_indeksowalna) albo None, gdy takiej spółki nie ma w katalogu."""
    spolka = companies.po_slugu(slug)
    if not spolka:
        return None

    d, kompletne = _dane(spolka["symbol"])
    d = d or {}
    nazwa = spolka["name"]
    tick = companies.ticker(spolka)
    sciezka = companies.adres(spolka)

    # Strona bez ani jednej liczby jest pusta — nie wpuszczamy jej do indeksu.
    ma_tresc = bool(d.get("price") is not None or d.get("history")
                    or (d.get("next") or {}).get("date") or d.get("trend"))

    tytul = f"Wyniki finansowe {nazwa} ({tick}) — terminy i prognozy"
    if len(tytul) > 62:
        tytul = f"Wyniki finansowe {nazwa} ({tick})"
    opis = (f"Kiedy {nazwa} publikuje wyniki kwartalne, prognozy analityków, "
            f"historia zaskoczeń i reakcja kursu po poprzednich raportach. "
            f"Ticker {tick}, {companies.gielda_pl(spolka)}.")[:300]

    lead = (f"Terminy publikacji raportów, konsensus analityków i to, co kurs "
            f"{render.esc(nazwa)} robił po poprzednich wynikach — zebrane w jednym "
            f"miejscu, po polsku.")

    bloki = []
    kafle = _kafle(spolka, d)
    if kafle:
        bloki.append(f"<section>{kafle}</section>")

    if not kompletne and not ma_tresc:
        bloki.append(render.sekcja(
            "Dane są w drodze",
            "Notowania i prognozy dla tej spółki właśnie się pobierają. Odśwież "
            "stronę za chwilę albo otwórz kartę spółki w aplikacji — tam dane "
            "dociągają się w tle."))

    for buduj in (_sekcja_termin, _sekcja_historia, _sekcja_prognozy,
                  _sekcja_marze, _sekcja_o_spolce):
        kawalek = buduj(spolka, d)
        if kawalek:
            bloki.append(kawalek)

    pary = _pytania(spolka, d)
    bloki.append(render.sekcja("Najczęstsze pytania", kotwica="pytania",
                               html_dodatkowy=render.faq(pary)))

    sasiedzi = companies.sasiedzi(spolka, 10)
    if sasiedzi:
        naglowek = (f"Inne spółki z sektora „{spolka['sector_pl']}”"
                    if spolka.get("sector_pl") else "Inne spółki")
        bloki.append(render.sekcja(
            naglowek,
            "Wyniki spółki najwięcej mówią w porównaniu z konkurencją z tej samej "
            "branży — to ona pokazuje, czy słaby kwartał był problemem firmy, "
            "czy całego rynku.",
            html_dodatkowy=render.chipsy(
                [(companies.adres(s), s["name"]) for s in sasiedzi])))

    bloki.append(render.sekcja(
        "Powiązane",
        html_dodatkowy=render.chipsy([
            ("/kalendarz-wynikow-spolek", "Kalendarz wyników spółek"),
            ("/wyniki-finansowe/" + ("gpw" if spolka["market"] == "GPW" else "usa"),
             "Wszystkie spółki z " + ("GPW" if spolka["market"] == "GPW" else "USA")),
            ("/poradniki/jak-czytac-raport-kwartalny", "Jak czytać raport kwartalny"),
            ("/slownik/eps", "Co to jest EPS"),
            ("/slownik/konsensus-analitykow", "Konsensus analityków"),
        ])))

    bloki.append(render.zacheta(
        f"Śledź {nazwa} w Portevo",
        "Dodaj spółkę do obserwowanych, a jej raport pojawi się wyróżniony "
        "w kalendarzu wyników. Wykres, wskaźniki i porównanie z branżą masz "
        "od razu obok.",
        adres=f"/?spolka={spolka['symbol']}",
        etykieta=f"Otwórz kartę {nazwa}",
        drugi=("/kalendarz-wynikow-spolek", "Zobacz kalendarz wyników")))
    bloki.append(render.zastrzezenie())

    okruchy = [("/wyniki-finansowe", "Wyniki spółek"),
               ("/wyniki-finansowe/" + ("gpw" if spolka["market"] == "GPW" else "usa"),
                "GPW" if spolka["market"] == "GPW" else "USA"),
               ("", nazwa)]

    byt = jsonld.spolka(
        spolka["legal"], tick, companies.gielda_pl(spolka),
        opis=(f"Spółka notowana na {companies.gielda_pl(spolka)}"
              + (f", sektor: {spolka['sector_pl']}" if spolka.get("sector_pl") else "")),
        strona_www=spolka.get("website") or "")

    html = render.strona(
        sciezka=sciezka,
        tytul=tytul + " | Portevo",
        opis=opis,
        h1=f"Wyniki finansowe {nazwa} ({tick})",
        lead=lead,
        nadtytul=("Spółki GPW" if spolka["market"] == "GPW" else "Spółki z USA"),
        okruchy=okruchy,
        szeroki_naglowek=True,
        aktualizacja=data_pl(dt.date.today().isoformat()),
        noindex=not ma_tresc,
        bloki=bloki,
        jsonld=[
            jsonld.strona_spolki(sciezka, tytul, opis, byt,
                                 zmieniono=dt.date.today().isoformat()),
            jsonld.okruchy(okruchy),
            jsonld.pytania(pary),
        ],
    )
    return html, ma_tresc


# --------------------------------------------------------------- spisy spółek


def _karta(s: dict) -> tuple:
    opis = s.get("sector_pl") or "spółka giełdowa"
    return (companies.adres(s), f"{s['name']} ({companies.ticker(s)})",
            f"Terminy publikacji wyników, prognozy analityków i reakcje kursu. "
            f"Sektor: {opis}.", s["market"])


def spis(rynek: str = "") -> str:
    """Strona zbiorcza: `/wyniki-finansowe`, `/wyniki-finansowe/gpw`, `.../usa`."""
    if rynek == "GPW":
        sciezka = "/wyniki-finansowe/gpw"
        h1 = "Wyniki finansowe spółek z GPW"
        tytul = "Wyniki finansowe spółek z GPW — terminy raportów | Portevo"
        opis = ("Kiedy spółki z warszawskiej giełdy publikują raporty kwartalne. "
                "Terminy, prognozy analityków i historia reakcji kursu dla spółek "
                "z WIG20, mWIG40 i sWIG80.")
        lead = ("Spółki notowane na Giełdzie Papierów Wartościowych w Warszawie — "
                "z terminem najbliższego raportu, prognozą zysku na akcję i historią "
                "tego, jak kurs zachowywał się po poprzednich publikacjach.")
        lista = companies.rynek("GPW")
        okruchy = [("/wyniki-finansowe", "Wyniki spółek"), ("", "GPW")]
    elif rynek == "USA":
        sciezka = "/wyniki-finansowe/usa"
        h1 = "Wyniki finansowe spółek z giełd amerykańskich"
        tytul = "Wyniki finansowe spółek z USA — kalendarz raportów | Portevo"
        opis = ("Terminy publikacji wyników kwartalnych największych spółek z Nasdaq "
                "i NYSE. Prognozy analityków, historia zaskoczeń i reakcje kursu — "
                "po polsku.")
        lead = ("Apple, Nvidia, Microsoft, Tesla i reszta spółek, których raporty "
                "poruszają całym rynkiem — z terminem publikacji, konsensusem "
                "analityków i historią reakcji kursu.")
        lista = companies.rynek("USA")
        okruchy = [("/wyniki-finansowe", "Wyniki spółek"), ("", "USA")]
    else:
        sciezka = "/wyniki-finansowe"
        h1 = "Wyniki finansowe spółek — kalendarz raportów A–Z"
        tytul = "Wyniki finansowe spółek — GPW i USA, spis A–Z | Portevo"
        opis = ("Spis spółek z terminami publikacji wyników kwartalnych. Giełda "
                "warszawska i giełdy amerykańskie, prognozy analityków i historia "
                "reakcji kursu — po polsku.")
        lead = ("Wybierz spółkę i sprawdź, kiedy publikuje wyniki, czego oczekują "
                "analitycy i jak kurs reagował na poprzednie raporty. "
                f"W katalogu jest {len(companies.SPOLKI)} spółek z GPW i giełd "
                "amerykańskich.")
        lista = companies.SPOLKI
        okruchy = [("", "Wyniki spółek")]

    bloki = []
    if not rynek:
        bloki.append(render.sekcja(
            "Wybierz rynek",
            html_dodatkowy=render.karty([
                ("/wyniki-finansowe/gpw", "Spółki z GPW",
                 f"{len(companies.rynek('GPW'))} spółek z warszawskiej giełdy — "
                 "od WIG20 po mniejsze spółki przemysłowe.", "Polska"),
                ("/wyniki-finansowe/usa", "Spółki z USA",
                 f"{len(companies.rynek('USA'))} największych spółek z Nasdaq i NYSE, "
                 "których raporty ruszają całym rynkiem.", "Świat"),
            ])))

    grupy = {}
    for s in lista:
        grupy.setdefault(s.get("sector_pl") or "pozostałe", []).append(s)

    for sektor, spolki in sorted(grupy.items(), key=lambda kv: -len(kv[1])):
        spolki = sorted(spolki, key=lambda x: x["name"].lower())
        bloki.append(render.sekcja(
            sektor.capitalize(),
            html_dodatkowy=render.chipsy(
                [(companies.adres(s), f"{s['name']} ({companies.ticker(s)})")
                 for s in spolki])))

    bloki.append(render.zacheta(
        "Kalendarz wyników na najbliższe dni",
        "Zamiast szukać spółka po spółce — zobacz od razu, kto raportuje w tym "
        "tygodniu, i wyróżnij te, które masz w portfelu.",
        adres="/kalendarz-wynikow-spolek", etykieta="Zobacz kalendarz wyników",
        drugi=("/", "Otwórz aplikację")))
    bloki.append(render.zastrzezenie())

    return render.strona(
        sciezka=sciezka, tytul=tytul, opis=opis, h1=h1, lead=lead,
        nadtytul="Spis spółek", okruchy=okruchy, szeroki_naglowek=True,
        bloki=bloki,
        jsonld=[
            jsonld.strona(sciezka, tytul, opis, typ="CollectionPage"),
            jsonld.okruchy(okruchy),
            jsonld.lista_pozycji(
                h1, [(companies.adres(s), s["name"]) for s in lista]),
        ],
    )
