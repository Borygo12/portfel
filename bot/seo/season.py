"""Sezon wyników — strona z żywym kalendarzem najbliższych raportów.

To jest odpowiedź na jedyny zarzut, którego nie da się odeprzeć wobec stron
pozycjonowanych: opowiadają o produkcie zamiast go pokazać. Człowiek, który
wpisał „kiedy wyniki spółek”, chce zobaczyć LISTĘ DAT, a nie akapit o tym, że
mamy kalendarz. Ta strona daje mu listę od razu — prawdziwe daty, prawdziwe
spółki, prawdziwe prognozy — i dopiero pod nią tłumaczy, jak z tego korzystać.

Skąd dane: `upcoming.rynek_usa()` (kalendarz Nasdaqa, ten sam, którym żyje
zakładka Earnings) i `upcoming.najblizsze()` dla GPW z cache raportów. Oba
źródła mają twardy budżet czasu i wolno im zwrócić pustkę — wtedy sekcji po
prostu nie ma, a strona nadal się broni treścią.

Uwaga na przyszłość: **ta strona nie może stać się drugim
`/kalendarz-wynikow-spolek`.** Tamta opisuje funkcję aplikacji („co potrafi
kalendarz”), ta odpowiada na pytanie o bieżący sezon („kto raportuje teraz”).
Gdyby obie zaczęły mówić to samo, Google wybierze jedną i to zwykle nie tę,
na której nam zależy.
"""

from __future__ import annotations

import datetime as dt

from . import companies, dates, jsonld, logos, render, upcoming

SCIEZKA = "/sezon-wynikow"

#: Ile dni pokazujemy na liście dziennej. Dwa tygodnie to kompromis: dalej
#: terminy są w większości szacowane, a strona rośnie w nieczytelną ścianę.
DNI = 12


def _kwartal_sezonu(dzis: dt.date) -> tuple[str, str]:
    """(„za IV kwartał 2025”, „styczeń–luty”) — który sezon właśnie trwa.

    Spółki raportują za kwartał POPRZEDNI, a szczyt sezonu przypada mniej
    więcej na drugi miesiąc po jego zakończeniu. Dlatego nazwa sezonu nie jest
    kwartałem kalendarzowym, w którym jesteśmy.
    """
    kwartal_biezacy = (dzis.month - 1) // 3 + 1
    poprzedni = kwartal_biezacy - 1 or 4
    rok = dzis.year if poprzedni != 4 else dzis.year - 1
    rzymskie = {1: "I", 2: "II", 3: "III", 4: "IV"}
    miesiace = {1: "kwiecień–maj", 2: "lipiec–sierpień",
                3: "październik–listopad", 4: "styczeń–luty"}
    return f"{rzymskie[poprzedni]} kwartał {rok}", miesiace[poprzedni]


def _dni_usa() -> str:
    """Lista dzienna największych amerykańskich raportów."""
    dni = upcoming.rynek_usa(dni=DNI, na_dzien=7)
    if not dni:
        return ""

    czesci = []
    for data, pozycje in dni[:8]:
        wiersze = [{
            "logo": (logos.znak(p["spolka"], 34) if p["spolka"] else ""),
            "tytul": f"{p['nazwa']} ({p['symbol']})",
            "podtytul": upcoming.PORY.get(p["pora"], ""),
            "wartosc": (f"EPS {render.liczba(p['eps'])}"
                        if p.get("eps") is not None else ""),
            "nota": (f"{p['prognozy']} prognoz" if p.get("prognozy") else ""),
            "adres": p["adres"],
        } for p in pozycje]
        czesci.append(render.wiersze(
            wiersze,
            naglowek=(dates.z_dniem_tygodnia(data).capitalize(),
                      f"{len(pozycje)} największych spółek")))
    return "".join(czesci)


def _lista_gpw() -> str:
    pozycje = upcoming.najblizsze(dni=45, rynek="GPW", limit=12)
    if len(pozycje) < 2:
        return ""
    wiersze = [{
        "logo": logos.znak(p["spolka"], 34),
        "tytul": f"{p['nazwa']} ({companies.ticker(p['spolka'])})",
        "podtytul": p["spolka"].get("sector_pl") or "GPW",
        "wartosc": dates.krotko(p["data"]),
        "nota": "termin szacowany" if p["szacowany"] else "termin potwierdzony",
        "adres": p["adres"],
    } for p in pozycje]
    return render.wiersze(wiersze,
                          naglowek=("Warszawska giełda", "najbliższe 45 dni"),
                          wiecej=("/wyniki-finansowe/gpw", "Wszystkie spółki z GPW"))


def zbuduj() -> str:
    dzis = dt.date.today()
    sezon, okno = _kwartal_sezonu(dzis)

    tytul = f"Sezon wyników {dzis.year} — kto raportuje teraz | Portevo"
    opis = (f"Sezon wyników za {sezon}: kiedy publikują największe spółki z USA "
            f"i GPW, jakie są prognozy analityków i na co patrzeć w raportach. "
            f"Aktualizowane codziennie.")
    lead = (f"Trwa sezon publikacji raportów za <strong>{render.esc(sezon)}</strong>. "
            f"Poniżej terminy najbliższych publikacji — najpierw giełdy amerykańskie "
            f"dzień po dniu, potem warszawska. Lista bierze się z tego samego "
            f"kalendarza, który działa w aplikacji, więc zmienia się razem z nim.")

    bloki = []

    usa = _dni_usa()
    if usa:
        bloki.append(render.sekcja(
            "Kto raportuje w najbliższych dniach — USA",
            "Spółki o kapitalizacji powyżej 5 mld dolarów, dzień po dniu. "
            "„Przed otwarciem sesji” oznacza publikację rano czasu nowojorskiego, "
            "„po zamknięciu” — po godzinie 22:00 w Polsce, a reakcję kursu zobaczysz "
            "dopiero następnego dnia.",
            kotwica="usa", html_dodatkowy=usa))

    gpw = _lista_gpw()
    if gpw:
        bloki.append(render.sekcja(
            "Najbliższe raporty na GPW",
            "Warszawskie spółki publikują raporty w szerszym oknie niż amerykańskie, "
            "a część terminów pochodzi z harmonogramów, które spółka może jeszcze "
            "zmienić — takie pozycje są opisane jako szacowane.",
            kotwica="gpw", html_dodatkowy=gpw))

    if not usa and not gpw:
        # Świeżo uruchomiony serwer nie ma jeszcze nic w cache. Zamiast pustej
        # sekcji dajemy uczciwe zdanie i link tam, gdzie dane na pewno są.
        bloki.append(render.sekcja(
            "Kalendarz najbliższych publikacji",
            "Terminy najbliższych raportów zbierają się właśnie w tle. "
            "Pełny, aktualizowany na bieżąco kalendarz wyników jest w aplikacji.",
            html_dodatkowy=render.chipsy([
                ("/earnings", "Otwórz kalendarz wyników"),
                ("/wyniki-finansowe", "Spis spółek A–Z")])))

    bloki.append(render.sekcja(
        "Czym jest sezon wyników",
        f"Sezon wyników to kilka tygodni w kwartale, w których większość spółek "
        f"publikuje raporty za miniony okres. Dla raportów za {render.esc(sezon)} "
        f"szczyt przypada na {render.esc(okno)}. Otwierają go zwykle wielkie banki "
        f"amerykańskie, potem raportuje technologia, a na końcu handel detaliczny.",
        "Rynek nie reaguje na wysokość zysku, tylko na <strong>różnicę między "
        "wynikiem a prognozą</strong> — i na to, co spółka mówi o kolejnym kwartale. "
        "Dlatego zdarza się, że firma pokazuje rekordowy zysk, a kurs spada: "
        "rekord był już w cenie, a prognoza rozczarowała.",
        lista=[
            "<b>Data i pora publikacji</b> — przed sesją czy po jej zamknięciu.",
            "<b>Konsensus analityków</b> — wraz z liczbą prognoz, z których powstał.",
            "<b>Historia zaskoczeń</b> — jak często spółka bije prognozy.",
            "<b>Reakcja kursu</b> po poprzednich raportach — miara ryzyka trzymania "
            "pozycji przez publikację.",
        ],
        kotwica="co-to"))

    pary = [
        ("Kiedy zaczyna się sezon wyników?",
         f"Raporty za {sezon} spółki publikują głównie w miesiącach {okno}. "
         f"Pierwsze są duże banki amerykańskie, warszawskie spółki raportują "
         f"zwykle później, bo mają na to więcej czasu."),
        ("Gdzie sprawdzić, kiedy spółka publikuje wyniki?",
         "Na liście powyżej, w kalendarzu wyników w aplikacji Portevo albo na "
         "podstronie konkretnej spółki — każda z 266 spółek w katalogu ma własną, "
         "z terminem, prognozami i historią reakcji kursu."),
        ("Dlaczego kurs spada mimo dobrych wyników?",
         "Bo liczy się różnica wobec oczekiwań, a nie sama wartość zysku. Jeśli rynek "
         "spodziewał się jeszcze lepszego wyniku albo spółka obniżyła prognozę na "
         "kolejny kwartał, reakcja bywa ujemna mimo rekordowego kwartału."),
        ("Czy terminy są pewne?",
         "Część jest potwierdzona komunikatem spółki, część szacowana na podstawie "
         "poprzednich lat — te drugie są przy pozycji wyraźnie opisane i mogą się "
         "przesunąć."),
    ]
    bloki.append(render.sekcja("Najczęstsze pytania", kotwica="pytania",
                               html_dodatkowy=render.faq(pary)))

    bloki.append(render.sekcja(
        "Powiązane",
        html_dodatkowy=render.chipsy([
            ("/kalendarz-wynikow-spolek", "Jak działa kalendarz wyników"),
            ("/wyniki-finansowe/usa", "Spółki z USA"),
            ("/wyniki-finansowe/gpw", "Spółki z GPW"),
            # Poradnik o sezonie wyników opowiada, JAK się przygotować; ta strona
            # mówi, KTO raportuje teraz. Wzajemny link porządkuje ten podział
            # i dla Google, i dla czytelnika.
            ("/poradniki/sezon-wynikow-jak-sie-przygotowac",
             "Sezon wyników — jak się przygotować"),
            ("/poradniki/jak-czytac-raport-kwartalny", "Jak czytać raport kwartalny"),
            ("/poradniki/kiedy-spolki-publikuja-wyniki", "Kiedy spółki publikują wyniki"),
            ("/slownik/konsensus-analitykow", "Konsensus analityków"),
        ])))

    bloki.append(render.zacheta(
        "Nie przegap raportu spółki, którą masz",
        "W aplikacji kalendarz wyróżnia spółki z Twojego portfela i listy "
        "obserwowanych, a przy każdej pokazuje prognozę i historię reakcji kursu.",
        adres="/earnings", etykieta="Otwórz kalendarz wyników",
        drugi=("/wyniki-finansowe", "Przeglądaj spółki A–Z")))
    bloki.append(render.zastrzezenie())

    okruchy = [("", f"Sezon wyników {dzis.year}")]

    return render.strona(
        sciezka=SCIEZKA,
        tytul=tytul,
        opis=opis,
        h1=f"Sezon wyników {dzis.year} — kto raportuje w najbliższych dniach",
        lead=lead,
        nadtytul=f"Raporty za {sezon}",
        okruchy=okruchy,
        szeroki_naglowek=True,
        aktualizacja=dates.dzis(),
        bloki=bloki,
        jsonld=[
            jsonld.strona(SCIEZKA, tytul, opis, typ="CollectionPage",
                          zmieniono=dzis.isoformat()),
            jsonld.okruchy(okruchy),
            jsonld.pytania(pary),
        ],
    )


# --------------------------------------------------------------- blok dla /funkcje


def blok_kalendarza() -> str:
    """Skrócona lista najbliższych raportów — do wklejenia na podstronie funkcji.

    Podstrona „Kalendarz wyników spółek” opisywała funkcję, nie pokazując ani
    jednej daty. Ten blok to naprawia, ale świadomie jest krótszy niż
    `/sezon-wynikow`: tam lista jest treścią strony, tu dowodem, że funkcja
    naprawdę działa.
    """
    dni = upcoming.rynek_usa(dni=7, na_dzien=5)
    czesci = []
    for data, pozycje in dni[:3]:
        wiersze = [{
            "logo": (logos.znak(p["spolka"], 34) if p["spolka"] else ""),
            "tytul": f"{p['nazwa']} ({p['symbol']})",
            "podtytul": upcoming.PORY.get(p["pora"], ""),
            "wartosc": (f"EPS {render.liczba(p['eps'])}"
                        if p.get("eps") is not None else ""),
            "adres": p["adres"],
        } for p in pozycje]
        czesci.append(render.wiersze(
            wiersze, naglowek=(dates.z_dniem_tygodnia(data).capitalize(), "")))

    gpw = upcoming.najblizsze(dni=45, rynek="GPW", limit=5)
    if gpw:
        czesci.append(render.wiersze([{
            "logo": logos.znak(p["spolka"], 34),
            "tytul": f"{p['nazwa']} ({companies.ticker(p['spolka'])})",
            "podtytul": p["spolka"].get("sector_pl") or "GPW",
            "wartosc": dates.krotko(p["data"]),
            "nota": "szacowany" if p["szacowany"] else "",
            "adres": p["adres"],
        } for p in gpw], naglowek=("Najbliżej na GPW", "")))

    if not czesci:
        return ""

    return render.sekcja(
        "Najbliższe publikacje wyników",
        "Wycinek żywego kalendarza — tak samo wyglądają dane w aplikacji, tyle że "
        "tam obejmują cały rynek i wyróżniają spółki z Twojego portfela.",
        kotwica="najblizsze",
        html_dodatkowy="".join(czesci)
        + render.chipsy([(SCIEZKA, "Zobacz cały sezon wyników"),
                         ("/earnings", "Otwórz kalendarz w aplikacji")]))
