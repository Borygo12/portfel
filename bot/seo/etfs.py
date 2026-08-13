"""Podstrony z listami funduszy ETF.

Skąd treść: z `etf/catalog.py`, czyli z tego samego ręcznie utrzymywanego
katalogu, na którym stoi skaner ETF w aplikacji. Każdy fundusz ma tam jedno
zdanie napisane po ludzku („co ten fundusz właściwie robi”) — i to jest
dokładnie ta treść, której szuka ktoś wpisujący „jaki ETF na cały świat”.

Czego tu świadomie NIE MA: cen, stóp zwrotu i opłat. Te liczby aplikacja
dociąga z Yahoo na żywo dla funduszu, który użytkownik akurat otworzył.
Wpisanie ich na stronę pozycjonowaną wymagałoby odpytania stu czternastu
symboli przy każdym wejściu robota — a nieaktualna stopa zwrotu na stronie
o inwestowaniu jest gorsza niż jej brak. Strona daje więc dobór funduszu
(to, co da się rzetelnie opisać słowem), a liczby zaczynają się w aplikacji.

Podział na podstrony idzie za tym, jak ludzie pytają: osobno „ETF na cały
świat”, osobno „ETF dywidendowe”, osobno obligacje i złoto. Każda lista jest
inna i każda ma własny wstęp — pięć stron z tym samym akapitem byłoby pięcioma
powodami, żeby Google uznał je za wypełniacz.
"""

from __future__ import annotations

from . import jsonld, logos, render

try:
    from etf import catalog as _kat
except Exception:  # noqa: BLE001 — brak modułu nie może zdjąć całej warstwy SEO
    _kat = None

BAZA = "/etf"

#: slug → (tytuł strony, warunek doboru funduszy, teksty)
STRONY = {

    "": {
        "sciezka": BAZA,
        "h1": "Lista funduszy ETF dostępnych polskiemu inwestorowi",
        "tytul": "Lista ETF — fundusze dostępne w Polsce | Portevo",
        "opis": "Katalog funduszy ETF, które kupisz przez polskiego brokera: akcje, "
                "obligacje, złoto i surowce. Co robi każdy z nich, opisane po ludzku "
                "i po polsku.",
        "lead": "Fundusze, które realnie da się kupić z polskiego rachunku "
                "maklerskiego — z jednym zdaniem o tym, co każdy z nich właściwie "
                "robi i dla kogo ma sens.",
        "akapity": [
            "ETF to fundusz notowany na giełdzie: kupujesz go jak akcję, a w środku "
            "siedzi cały koszyk spółek albo obligacji. Dla większości inwestorów "
            "<strong>jeden szeroki fundusz akcyjny załatwia więcej niż dziesięć "
            "starannie wybranych spółek</strong>, bo daje dywersyfikację, na którą "
            "przy pojedynczych walorach trzeba by wielu lat i dużego kapitału.",
            "Przy wyborze liczą się cztery rzeczy: co fundusz kupuje, w jakiej "
            "walucie jest notowany, czy wypłaca dywidendę czy zostawia ją w środku "
            "(fundusz akumulujący) oraz ile kosztuje jego prowadzenie. Ostatnią "
            "z nich — opłatę TER — a także skład i wyniki, sprawdzisz w skanerze ETF "
            "w aplikacji.",
        ],
        "filtr": lambda e: True,
        "grupuj": "region",
    },

    "swiatowe": {
        "sciezka": f"{BAZA}/swiatowe",
        "h1": "ETF na cały świat — fundusze globalne",
        "tytul": "ETF na cały świat — lista funduszy globalnych | Portevo",
        "opis": "Fundusze ETF obejmujące spółki z całego świata: co jest w środku, "
                "czym się różnią i dla kogo mają sens. Po polsku, bez marketingu.",
        "lead": "Jeden fundusz zamiast wybierania rynków — spółki z całego globu "
                "w jednym zleceniu. Poniżej te, które kupisz z polskiego rachunku.",
        "akapity": [
            "Fundusz globalny jest najprostszą możliwą odpowiedzią na pytanie „w co "
            "zainwestować”: kupuje kilka tysięcy spółek naraz, więc "
            "<strong>upadek pojedynczej firmy jest w nim niezauważalny</strong>, "
            "a Ty nie musisz zgadywać, który rynek wypadnie lepiej.",
            "Uwaga na dwie rzeczy. Po pierwsze, „cały świat” w praktyce oznacza "
            "dziś w większości Stany Zjednoczone — tak wyglądają wagi rynkowe. "
            "Po drugie, fundusz notowany w euro albo dolarze niesie ryzyko "
            "walutowe wobec złotego, niezależnie od tego, jak radzą sobie spółki.",
        ],
        "filtr": lambda e: e.get("region") in ("world", "exus"),
        "grupuj": "sector",
    },

    "dywidendowe": {
        "sciezka": f"{BAZA}/dywidendowe",
        "h1": "ETF dywidendowe — fundusze wypłacające zysk",
        "tytul": "ETF dywidendowe — lista funduszy wypłacających | Portevo",
        "opis": "Fundusze ETF wypłacające dywidendę: czym różnią się od "
                "akumulujących, dla kogo mają sens i jak są opodatkowane w Polsce.",
        "lead": "Fundusze, które przelewają wypłacone dywidendy na rachunek zamiast "
                "zostawiać je w środku — oraz to, co warto wiedzieć, zanim się na "
                "nie postawi.",
        "akapity": [
            "Fundusz <strong>dystrybuujący</strong> wypłaca dywidendy spółek na "
            "Twój rachunek, <strong>akumulujący</strong> reinwestuje je "
            "automatycznie w środku. To nie jest różnica w zyskowności, tylko "
            "w tym, gdzie ten zysk ląduje — i w podatkach: każda wypłata jest "
            "opodatkowana od razu, a w funduszu akumulującym podatek płacisz "
            "dopiero przy sprzedaży.",
            "Stąd praktyczny wniosek, który rzadko pada w reklamach: przy budowaniu "
            "kapitału na lata fundusz akumulujący jest zwykle korzystniejszy "
            "podatkowo, a wypłacający ma sens wtedy, gdy chcesz z portfela "
            "realnie żyć. Osobna sprawa to rozliczenie podatku od zagranicznych "
            "wypłat — trzeba je wykazać samodzielnie w rocznym zeznaniu.",
        ],
        "filtr": lambda e: e.get("sector") == "dividend" or e.get("acc") is False,
        "grupuj": "region",
    },

    "obligacje": {
        "sciezka": f"{BAZA}/obligacje",
        "h1": "ETF na obligacje — spokojna część portfela",
        "tytul": "ETF obligacyjne — lista funduszy | Portevo",
        "opis": "Fundusze ETF na obligacje skarbowe i korporacyjne: po co je mieć, "
                "czym różni się fundusz krótko- od długoterminowego.",
        "lead": "Dług państw i firm w formie funduszu — część portfela, która ma "
                "hamować spadki, a nie zarabiać najwięcej.",
        "akapity": [
            "Obligacje w portfelu pełnią rolę balastu: gdy akcje tracą, "
            "<strong>ich kurs zwykle zachowuje się spokojniej albo rośnie</strong>, "
            "co ogranicza obsunięcie całości. Cena tej stabilności jest jawna — "
            "w długim terminie obligacje dają mniej niż akcje.",
            "Kluczowa liczba to czas trwania (duration): im dłuższy, tym mocniej "
            "kurs funduszu reaguje na zmiany stóp procentowych. Fundusz "
            "długoterminowy przy rosnących stopach potrafi stracić kilkanaście "
            "procent — co dla wielu osób jest zaskoczeniem, bo „obligacje” brzmią "
            "bezpiecznie.",
        ],
        "filtr": lambda e: e.get("asset") == "bond" or e.get("sector") == "bond",
        "grupuj": "region",
    },

    "zloto-i-surowce": {
        "sciezka": f"{BAZA}/zloto-i-surowce",
        "h1": "ETF na złoto i surowce",
        "tytul": "ETF na złoto i surowce — lista funduszy | Portevo",
        "opis": "Fundusze dające ekspozycję na złoto, metale i koszyki surowców. "
                "Czym różnią się od kupna kruszcu i po co je trzymać w portfelu.",
        "lead": "Złoto, metale i koszyki towarów — aktywa, które zachowują się "
                "inaczej niż akcje i właśnie w tym tkwi ich rola.",
        "akapity": [
            "Złoto nie wypłaca odsetek ani dywidendy, więc jego wycena to czysta "
            "kwestia zaufania do walut i obligacji. W portfelu trzyma się je nie "
            "dlatego, że ma dużo zarobić, tylko dlatego, że "
            "<strong>bywa mocne wtedy, gdy reszta portfela jest słaba</strong>.",
            "Formalnie większość „ETF-ów na złoto” to ETC — instrumenty dłużne "
            "zabezpieczone fizycznym kruszcem, nie fundusze. Dla inwestora "
            "z rachunku maklerskiego różnica jest praktyczna: liczy się to, czy "
            "produkt ma pokrycie w metalu w skarbcu, czy tylko w kontraktach.",
        ],
        "filtr": lambda e: (e.get("asset") == "commodity"
                            or e.get("sector") in ("gold", "commodity")),
        "grupuj": "region",
    },
}


def adresy() -> list[str]:
    return [cfg["sciezka"] for cfg in STRONY.values()]


def _fundusze(cfg) -> list[dict]:
    if not _kat:
        return []
    return [e for e in _kat.CATALOG if cfg["filtr"](e)]


def _etykieta(pole: str, wartosc: str) -> str:
    if not _kat:
        return wartosc
    slownik = _kat.REGION_LABEL if pole == "region" else _kat.SECTOR_LABEL
    return slownik.get(wartosc, wartosc)


def _kafle_funduszy(lista: list[dict]) -> str:
    """Wiersze z funduszami. Symbol wchodzi w podtytuł, bo to po nim się szuka."""
    return render.wiersze([{
        # Fundusze nie mają pobranych logotypów — monogram z nazwy jest tu
        # rozwiązaniem docelowym, a nie prowizorką: dwie litery na kolorowym
        # kafelku rozróżniają pozycje na liście równie dobrze.
        "logo": logos.znak({"symbol": e["sym"], "name": e["name"]}, 34),
        "tytul": e["name"],
        "podtytul": f"{e['sym']} · {e['cur']} · "
                    + ("akumulujący" if e.get("acc") else "wypłacający dywidendę"),
        "nota": e.get("note") or "",
    } for e in lista])


def zbuduj(slug: str = "") -> str | None:
    cfg = STRONY.get((slug or "").strip().lower())
    if not cfg:
        return None
    lista = _fundusze(cfg)
    if not lista:
        return None

    sciezka = cfg["sciezka"]
    bloki = [render.statystyki([
        ("Funduszy na liście", str(len(lista))),
        ("Akumulujących", str(sum(1 for e in lista if e.get("acc")))),
        ("Wypłacających", str(sum(1 for e in lista if e.get("acc") is False))),
    ])]

    bloki.append(render.sekcja("Co warto wiedzieć przed wyborem",
                               *cfg["akapity"], kotwica="wstep"))

    grupy: dict[str, list[dict]] = {}
    for e in lista:
        grupy.setdefault(e.get(cfg["grupuj"]) or "inne", []).append(e)

    for klucz, fundusze in sorted(grupy.items(), key=lambda kv: -len(kv[1])):
        bloki.append(render.sekcja(
            _etykieta(cfg["grupuj"], klucz),
            html_dodatkowy=_kafle_funduszy(
                sorted(fundusze, key=lambda x: x["name"].lower()))))

    pary = [
        ("Czy te fundusze kupię u polskiego brokera?",
         "Tak — to katalog funduszy notowanych na giełdach europejskich, dostępnych "
         "z typowego polskiego rachunku maklerskiego. Dostępność pojedynczego "
         "funduszu zależy jednak od konkretnego brokera i warto ją sprawdzić przed "
         "złożeniem zlecenia."),
        ("Czym różni się fundusz akumulujący od wypłacającego?",
         "Akumulujący reinwestuje dywidendy w środku, wypłacający przelewa je na "
         "rachunek. Przy długim oszczędzaniu akumulujący jest zwykle wygodniejszy "
         "podatkowo, bo podatek płacisz dopiero przy sprzedaży."),
        ("Gdzie sprawdzę opłatę i skład funduszu?",
         "W skanerze ETF w aplikacji Portevo — tam liczby (opłata TER, skład, wyniki, "
         "waluta) dociągają się na żywo dla wybranego funduszu."),
    ]
    bloki.append(render.sekcja("Najczęstsze pytania", kotwica="pytania",
                               html_dodatkowy=render.faq(pary)))

    inne = [(c["sciezka"], c["h1"].split(" — ")[0])
            for k, c in STRONY.items() if c["sciezka"] != sciezka]
    bloki.append(render.sekcja(
        "Powiązane",
        html_dodatkowy=render.chipsy(inne + [
            ("/skaner-etf", "Jak działa skaner ETF"),
            ("/slownik/etf", "Co to jest ETF"),
            ("/slownik/ter", "Opłata za zarządzanie (TER)"),
            ("/portfel-inwestycyjny", "Portfel inwestycyjny"),
        ])))

    bloki.append(render.zacheta(
        "Prześwietl fundusz przed zakupem",
        "Skaner ETF w aplikacji pokazuje opłatę, skład, walutę i wyniki funduszu, "
        "a także to, jak nachodzi on na spółki, które masz już w portfelu.",
        adres="/narzedzia", etykieta="Otwórz skaner ETF",
        drugi=("/portfel-inwestycyjny", "Zobacz moduł portfela")))
    bloki.append(render.zastrzezenie())

    okruchy = ([("", "ETF")] if not slug
               else [(BAZA, "ETF"), ("", cfg["h1"].split(" — ")[0])])

    return render.strona(
        sciezka=sciezka,
        tytul=cfg["tytul"],
        opis=cfg["opis"],
        h1=cfg["h1"],
        lead=cfg["lead"],
        nadtytul="Fundusze ETF",
        okruchy=okruchy,
        szeroki_naglowek=True,
        bloki=bloki,
        jsonld=[
            jsonld.strona(sciezka, cfg["tytul"], cfg["opis"], typ="CollectionPage"),
            jsonld.okruchy(okruchy),
            jsonld.pytania(pary),
        ],
    )
