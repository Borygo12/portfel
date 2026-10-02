"""Konta emerytalne — IKE, IKZE i OKI: zasady, limity i rachunek podatkowy.

Trzy rzeczy, które ten moduł trzyma w jednym miejscu:

1. **Przepisy jako dane.** Limity wpłat rok po roku, stawki i zasady wypłaty
   stoją w tabelach na górze pliku. Co roku w listopadzie zmienia się jedna
   liczba — dopisuje się wtedy jeden wiersz, bez ruszania kodu i bez wydawania
   nowej wersji aplikacji (telefon pobiera to z `/api/retirement/overview`).
2. **Rachunek na rachunkach użytkownika.** Konto emerytalne to zwykły rachunek
   z etykietą (`accounts.kind`), więc wartość, wpłaty i wykres bierzemy z tego
   samego silnika co cały portfel — tylko policzonego dla samych rachunków IKE
   albo IKZE (`engine.compute_subset`).
3. **Uczciwość co do tego, czego nie wiemy.** Podatki liczymy wprost z ustawy,
   ale na uproszczeniach (jedna stawka PIT przez wszystkie lata, kursy z dziś
   dla pozycji zamkniętych). Dlatego każda kwota podatku jest „około" i wynik
   niesie listę założeń, którą ekran pokazuje pod liczbami.

Źródła liczb: obwieszczenia MRPiPS w Monitorze Polskim (limity), ustawa
z 20 kwietnia 2004 r. o IKE i IKZE, ustawa z 3 lipca 2026 r. o osobistych
kontach inwestycyjnych (wchodzi w życie 1 stycznia 2027 r.).
"""

from __future__ import annotations

import datetime as dt
import logging
import math

log = logging.getLogger("retirement")

KINDS = ("ike", "ikze", "oki")

BELKA = 0.19
#: zryczałtowany podatek przy wypłacie z IKZE po spełnieniu warunków
IKZE_RYCZALT = 0.10

# ------------------------------------------------------------------ limity
#
# rok -> (IKE, IKZE, IKZE dla prowadzących działalność). Trzecia wartość jest
# od 2021 r.; wcześniej limit był jeden dla wszystkich.
LIMITY: dict[int, tuple[float, float, float]] = {
    2012: (10578.0, 4030.80, 4030.80),
    2013: (11139.0, 4231.20, 4231.20),
    2014: (11238.0, 4495.20, 4495.20),
    2015: (11877.0, 4750.80, 4750.80),
    2016: (12165.0, 4866.00, 4866.00),
    2017: (12789.0, 5115.60, 5115.60),
    2018: (13329.0, 5331.60, 5331.60),
    2019: (14295.0, 5718.00, 5718.00),
    2020: (15681.0, 6272.40, 6272.40),
    2021: (15777.0, 6310.80, 9466.20),
    2022: (17766.0, 7106.40, 10659.60),
    2023: (20805.0, 8322.00, 12483.00),
    2024: (23472.0, 9388.80, 14083.20),
    2025: (26019.0, 10407.60, 15611.40),
    2026: (28260.0, 11304.00, 16956.00),
}

#: Od którego miesiąca zwykle znany jest limit na kolejny rok (obwieszczenie
#: wychodzi w listopadzie) — ekran pokazuje wtedy przypomnienie o dopisaniu.
OSTATNI_ROK = max(LIMITY)


def limit(kind: str, rok: int, jdg: bool = False) -> float:
    """Limit wpłat na dany rok. Dla roku spoza tabeli bierzemy ostatni znany —
    lepsza liczba sprzed roku z dopiskiem niż puste pole."""
    wiersz = LIMITY.get(rok) or LIMITY[OSTATNI_ROK if rok > OSTATNI_ROK else min(LIMITY)]
    if kind == "ike":
        return wiersz[0]
    if kind == "ikze":
        return wiersz[2] if jdg else wiersz[1]
    return 0.0


# ------------------------------------------------------------------ zasady
#
# Tekst zasad jest na serwerze z tego samego powodu co katalog premium: zmiana
# przepisu to jedna edycja tutaj, a nie wydanie aplikacji.

ZASADY: dict[str, dict] = {
    "ike": {
        "nazwa": "IKE",
        "pelna": "Indywidualne Konto Emerytalne",
        "haslo": "Zysk bez podatku Belki — jeśli doczekasz do 60 lat",
        "wiek": 60,
        "sekcje": [
            {
                "id": "korzysc", "tytul": "Co dostajesz", "ikona": "gwiazda",
                "punkty": [
                    "Zero podatku Belki (19%) od zysków, dywidend i odsetek — pod warunkiem wypłaty po spełnieniu warunków.",
                    "W trakcie oszczędzania sprzedajesz i kupujesz bez rozliczania PIT-38. Podatek nie hamuje procentu składanego.",
                    "Wpłacasz z pieniędzy już opodatkowanych, więc przy wypłacie nie płacisz nic — także od wpłaconego kapitału.",
                ],
            },
            {
                "id": "limit", "tytul": "Limit wpłat", "ikona": "pomiar",
                "punkty": [
                    "W 2026 r. możesz wpłacić łącznie 28 260 zł (trzykrotność prognozowanego przeciętnego wynagrodzenia).",
                    "Limit dotyczy roku kalendarzowego. Niewykorzystana część przepada — nie przechodzi na kolejny rok.",
                    "Liczą się wpłaty, nie wartość konta. Zysk wypracowany na IKE nie zużywa limitu.",
                    "Możesz mieć tylko jedno IKE naraz (w jednej instytucji). IKZE i OKI możesz mieć obok.",
                ],
            },
            {
                "id": "wyplata", "tytul": "Wypłata bez podatku", "ikona": "klucz",
                "punkty": [
                    "Masz skończone 60 lat — albo 55 lat i nabyte uprawnienia emerytalne.",
                    "Wpłacałeś w co najmniej 5 dowolnych latach kalendarzowych — albo ponad połowa wpłat trafiła na konto najpóźniej 5 lat przed wnioskiem.",
                    "Wypłata może być jednorazowa albo w ratach. Po pierwszej wypłacie nie można już wpłacać ani założyć nowego IKE.",
                ],
            },
            {
                "id": "zwrot", "tytul": "Gdy wypłacisz wcześniej", "ikona": "uwaga",
                "punkty": [
                    "To się nazywa zwrot. Płacisz 19% podatku wyłącznie od zysku — wpłacony kapitał wraca cały.",
                    "Czyli w najgorszym razie wychodzisz tak, jak na zwykłym rachunku. Kary nie ma.",
                    "Zwrot może być częściowy: wyjmujesz część, reszta pracuje dalej. Podatek liczony jest proporcjonalnie od zysku przypadającego na wypłacaną część.",
                    "Wypłacone środki nie odnawiają limitu — wpłat z danego roku nie da się „oddać” i wpłacić ponownie.",
                ],
            },
            {
                "id": "inne", "tytul": "Warto wiedzieć", "ikona": "oko",
                "punkty": [
                    "Dywidendy zagraniczne: podatek u źródła (np. 15% w USA) pobiera tamten kraj i IKE go nie odzyska. Oszczędzasz tylko polską dopłatę do 19%.",
                    "Dziedziczenie: wskazujesz osoby uprawnione. Wypłata dla nich jest bez podatku Belki i bez podatku od spadków.",
                    "Przeniesienie do innej instytucji (wypłata transferowa) nie jest zwrotem — nie płacisz podatku i nie tracisz stażu.",
                    "Konto może założyć osoba od 16 lat mająca polską rezydencję podatkową; niepełnoletni wpłacają tylko w latach, w których mają dochód z umowy o pracę.",
                ],
            },
        ],
    },
    "ikze": {
        "nazwa": "IKZE",
        "pelna": "Indywidualne Konto Zabezpieczenia Emerytalnego",
        "haslo": "Zwrot podatku co roku — za 10% przy wypłacie",
        "wiek": 65,
        "sekcje": [
            {
                "id": "korzysc", "tytul": "Co dostajesz", "ikona": "gwiazda",
                "punkty": [
                    "Wpłaty z danego roku odliczasz od dochodu w PIT. Przy stawce 12% wraca 12 gr z każdej złotówki, przy 32% — 32 gr, na podatku liniowym — 19 gr.",
                    "Zwrot przychodzi po rozliczeniu rocznym. Reinwestowany co roku pracuje jak dodatkowa wpłata.",
                    "W trakcie oszczędzania nie ma podatku Belki — tak samo jak na IKE.",
                ],
            },
            {
                "id": "limit", "tytul": "Limit wpłat", "ikona": "pomiar",
                "punkty": [
                    "W 2026 r.: 11 304 zł, a dla prowadzących działalność gospodarczą 16 956 zł.",
                    "Limit jest roczny i nie przechodzi dalej. Odliczasz tylko to, co faktycznie wpłaciłeś do 31 grudnia.",
                    "Możesz mieć jedno IKZE. Mieć jednocześnie IKE i IKZE wolno — i to się opłaca.",
                ],
            },
            {
                "id": "wyplata", "tytul": "Wypłata po 65 roku życia", "ikona": "klucz",
                "punkty": [
                    "Masz skończone 65 lat i wpłacałeś w co najmniej 5 latach kalendarzowych.",
                    "Płacisz zryczałtowane 10% od całej wypłacanej kwoty — kapitału i zysku. Bez podatku Belki, bez łączenia z innymi dochodami.",
                    "Wypłata jednorazowa albo w ratach przez co najmniej 10 lat (krócej, jeśli wpłacałeś krócej).",
                ],
            },
            {
                "id": "zwrot", "tytul": "Gdy wypłacisz wcześniej", "ikona": "uwaga",
                "punkty": [
                    "Cała kwota zwrotu — kapitał i zysk — jest doliczana do Twojego dochodu za ten rok i opodatkowana według skali (12% lub 32%).",
                    "Przy dużym koncie zwrot może wepchnąć Cię w drugi próg i kosztować 32% od części kwoty.",
                    "Zwrotu częściowego nie ma: z IKZE wyjmuje się wszystko albo nic. Wyjątkiem są pieniądze przeniesione do innej instytucji.",
                    "Oddajesz więc mniej więcej to, co wcześniej odliczyłeś — a czasem więcej, jeśli konto dużo zarobiło.",
                ],
            },
            {
                "id": "inne", "tytul": "Warto wiedzieć", "ikona": "oko",
                "punkty": [
                    "Najwięcej zyskują ci, którzy dziś są w progu 32%, a na emeryturze zapłacą 10%.",
                    "Dziedziczenie: osoba uprawniona płaci 10% ryczałtu, bez podatku od spadków.",
                    "Odliczenie wykazujesz w załączniku PIT/O. Broker wystawia potwierdzenie sumy wpłat za rok.",
                ],
            },
        ],
    },
    "oki": {
        "nazwa": "OKI",
        "pelna": "Osobiste Konto Inwestycyjne",
        "haslo": "Do 100 tys. zł bez podatku — i bez czekania do emerytury",
        "wiek": None,
        "start": "2027-01-01",
        "stawka_pct": 0.85,
        "limit_inwestycyjny": 100000.0,
        "limit_oszczednosciowy": 25000.0,
        "sekcje": [
            {
                "id": "korzysc", "tytul": "Jak to ma działać", "ikona": "gwiazda",
                "punkty": [
                    "Na OKI nie ma podatku Belki — ani od zysku ze sprzedaży, ani od dywidend i odsetek.",
                    "Zamiast niego jest coroczny podatek od wartości aktywów, ale dopiero od nadwyżki ponad kwotę wolną.",
                    "Kwota wolna: 100 000 zł średniej wartości aktywów w roku, w tym do 25 000 zł w aktywach oszczędnościowych (lokaty, obligacje detaliczne, gotówka w złotych).",
                ],
            },
            {
                "id": "podatek", "tytul": "Podatek od aktywów", "ikona": "pomiar",
                "punkty": [
                    "W 2027 r. stawka wynosi 0,85% nadwyżki ponad kwotę wolną.",
                    "Od 2028 r. to 19% stopy referencyjnej NBP z 31 października poprzedniego roku (nie mniej niż 0,1%).",
                    "Podatek płacisz niezależnie od wyniku — także w roku, w którym portfel stracił.",
                    "Podstawą jest średnia wartość ze wszystkich Twoich OKI w roku, a nie stan na 31 grudnia.",
                ],
            },
            {
                "id": "aktywa", "tytul": "Co się łapie na kwotę wolną", "ikona": "sito",
                "punkty": [
                    "Aktywa inwestycyjne: akcje polskich spółek, polskie obligacje, listy zastawne w złotych oraz fundusze i ETF-y trzymające co najmniej 70% w takich aktywach.",
                    "Aktywa oszczędnościowe (do 25 000 zł): pieniądze i lokaty w złotych, obligacje oszczędnościowe Skarbu Państwa.",
                    "Akcje i obligacje zagraniczne, waluty obce i fundusze bez progu 70% można trzymać na OKI, ale kwota wolna ich nie obejmuje — podatek od aktywów liczy się od pierwszej złotówki.",
                ],
            },
            {
                "id": "wyplata", "tytul": "Wpłaty i wypłaty", "ikona": "klucz",
                "punkty": [
                    "Nie ma limitu wpłat i nie ma blokady do emerytury — wypłacasz, kiedy chcesz, bez kary.",
                    "Kont OKI można mieć kilka w różnych instytucjach; kwota wolna jest jedna na osobę.",
                    "Konto założy każdy, kto ma skończone 18 lat.",
                    "OKI nie wyklucza IKE ani IKZE — można mieć wszystkie trzy.",
                ],
            },
            {
                "id": "inne", "tytul": "Kiedy i dla kogo", "ikona": "oko",
                "punkty": [
                    "Ustawa została uchwalona 3 lipca 2026 r. i podpisana przez prezydenta w sierpniu. Konta ruszają 1 stycznia 2027 r.",
                    "Kwoty wolne mają być waloryzowane od 2030 r.",
                    "Przy horyzoncie kilkudziesięciu lat IKE i IKZE zwykle wygrywają — coroczny podatek od aktywów kumuluje się. OKI pasuje do pieniędzy, których nie chcesz zamrażać do sześćdziesiątki.",
                    "Podatek u źródła od dywidend zagranicznych zostaje — tak jak na IKE.",
                ],
            },
        ],
    },
}

ZALOZENIA = [
    "Kwoty podatku są orientacyjne i nie zastępują rozliczenia ani porady doradcy podatkowego.",
    "Ulgę IKZE liczymy jedną stawką PIT dla wszystkich lat — tą, którą ustawisz.",
    "Zysk z pozycji zamkniętych w walutach obcych przeliczamy po dzisiejszym kursie.",
    "Zakładamy, że wypłacasz całość. Przy zwrocie częściowym z IKE podatek jest proporcjonalnie mniejszy.",
]


# ------------------------------------------------------------- rozpoznanie

def konta() -> list[dict]:
    """Rachunki użytkownika z rodzajem. Bez migracji 0011 wszystkie są zwykłe."""
    import db
    try:
        rows = db.query("SELECT account, currency, broker, label, kind, kind_source "
                        "FROM accounts ORDER BY account")
        gotowe = True
    except Exception:  # noqa: BLE001 — kolumny jeszcze nie ma
        rows = db.query("SELECT account, currency, broker, label FROM accounts ORDER BY account")
        gotowe = False
    return [{"konto": r["account"], "waluta": r["currency"], "broker": r.get("broker") or "",
             "etykieta": r.get("label") or "", "typ": (r.get("kind") or "") if gotowe else "",
             "zrodlo": (r.get("kind_source") or "") if gotowe else "",
             "gotowe": gotowe} for r in rows]


def typy_aktywow() -> dict[str, str]:
    """{id aktywa: rodzaj konta} dla majątku ręcznego. Pusto bez migracji."""
    import db
    try:
        rows = db.query("SELECT id, account_kind FROM manual_assets WHERE account_kind != ''")
    except Exception:  # noqa: BLE001
        return {}
    return {str(r["id"]): r["account_kind"] for r in rows}


def ustaw_typ_aktywa(aid: str, kind: str) -> bool:
    import db
    kind = kind if kind in KINDS else ""
    try:
        db.execute("UPDATE manual_assets SET account_kind=%s WHERE id=%s", (kind, aid))
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- rachunek

def _rok(d: str) -> int:
    return int((d or "0000")[:4] or 0)


def _przerzedz(dates: list, *serie: list, dokladne: int = 120, max_pkt: int = 360) -> tuple:
    """Ostatnie `dokladne` dni co dzień, starsze co kilka — żeby zakres „1M" miał
    z czego się narysować, a pięć lat historii nie ważyło pół megabajta."""
    n = len(dates)
    if n <= max_pkt:
        return (dates, *serie)
    stare = n - dokladne
    krok = max(1, math.ceil(stare / (max_pkt - dokladne)))
    idx = list(range(0, stare, krok)) + list(range(stare, n))
    return ([dates[i] for i in idx], *[[s[i] for i in idx] for s in serie])


def _zysk_zamknietych(konta_set: set) -> float:
    """Zysk z pozycji zamkniętych na tych rachunkach, w PLN (kurs z dziś)."""
    import db
    import wealth
    try:
        rows = db.query("SELECT account, SUM(profit) AS zysk FROM closed_positions GROUP BY account")
        waluty = {r["account"]: r["currency"] for r in db.query("SELECT account, currency FROM accounts")}
    except Exception as e:  # noqa: BLE001
        log.info("Zysk zamkniętych: %s", e)
        return 0.0
    rows = [r for r in rows if r["account"] in konta_set]
    if not rows:
        return 0.0
    kursy = wealth._przeliczniki([waluty.get(r["account"], "PLN") for r in rows])
    return sum(float(r["zysk"] or 0) * kursy.get((waluty.get(r["account"]) or "PLN").upper(), 1.0)
               for r in rows)


def _stawka_zwrotu(stawka: float) -> float:
    """Stawka, po której opodatkowany jest przedterminowy zwrot z IKZE.

    Zwrot to przychód „z innych źródeł" — idzie na skalę podatkową także u kogoś,
    kto działalność rozlicza liniowo. Dlatego 19% zamieniamy na 12%."""
    return 0.32 if stawka >= 0.32 else 0.12


def _policz(kind: str, konta_typu: list[dict], aktywa_typu: list[dict],
            profil: dict, dzis: dt.date) -> dict:
    """Komplet liczb dla jednego rodzaju konta."""
    from portfolio import engine as pf_engine

    jdg = bool(profil.get("jdg"))
    stawka = float(profil.get("stawka") or 0.12)
    rok_ur = profil.get("rok_ur")
    rok = dzis.year

    wartosc = wplaty = wyplaty = 0.0
    wplaty_lat: dict[int, float] = {}
    dyw_brutto = dyw_podatek = niezreal = 0.0
    seria = {"dates": [], "values": [], "invested": []}
    pozycje, xirr = [], None

    numery = {k["konto"] for k in konta_typu}
    d = pf_engine.compute_subset(numery) if numery else {"empty": True}
    if not d.get("empty"):
        s = d["summary"]
        wartosc += s["value"]
        wplaty += s["deposits"]
        wyplaty += s["withdrawals"]
        xirr = s.get("xirr_pct")
        dyw_brutto, dyw_podatek = s.get("dividends_gross", 0.0), s.get("dividends_tax", 0.0)
        for f in d["flows"]:
            if f["amount_pln"] > 0:
                wplaty_lat[_rok(f["date"])] = wplaty_lat.get(_rok(f["date"]), 0.0) + f["amount_pln"]
        niezreal = sum(p["pl_pln"] for p in d["positions"] if not p.get("no_price"))
        pozycje = [{"ticker": p["ticker"], "nazwa": p["name"], "wartosc": p["value_pln"],
                    "zysk": p["pl_pln"], "zysk_pct": p["pl_pct"]} for p in d["positions"][:12]]
        dts, vals, inv = _przerzedz(d["dates"], d["values"], d["invested"])
        seria = {"dates": dts, "values": vals, "invested": inv}
    zreal = _zysk_zamknietych(numery) if numery else 0.0

    # Majątek dopisany ręcznie albo z odczytu AI: znamy wartość i koszt, nie znamy
    # historii — więc koszt liczy się jako jedna wpłata w dniu zakupu.
    for a in aktywa_typu:
        wartosc += a["wartosc"]
        koszt = float(a.get("koszt") or 0)
        wplaty += koszt
        if koszt:
            r = _rok(a.get("koszt_data") or "") or rok
            wplaty_lat[r] = wplaty_lat.get(r, 0.0) + koszt
            niezreal += a["wartosc"] - koszt
        pozycje.append({"ticker": a.get("symbol") or "", "nazwa": a["nazwa"],
                        "wartosc": a["wartosc"],
                        "zysk": (a["wartosc"] - koszt) if koszt else None,
                        "zysk_pct": round((a["wartosc"] / koszt - 1) * 100, 2) if koszt else None})
    pozycje.sort(key=lambda p: -p["wartosc"])

    netto = wplaty - wyplaty
    zysk = wartosc - netto

    # ---- limit tego roku
    lim = limit(kind, rok, jdg)
    wplacono = wplaty_lat.get(rok, 0.0)
    koniec = dt.date(rok, 12, 31)
    dni = (koniec - dzis).days
    miesiecy = max(1, 12 - dzis.month + 1)
    zostalo = max(0.0, lim - wplacono)
    limit_out = {
        "rok": rok, "limit": lim, "wplacono": round(wplacono, 2),
        "zostalo": round(zostalo, 2),
        "pct": round(min(100.0, wplacono / lim * 100), 1) if lim else 0.0,
        "dni_do_konca": dni, "miesiecznie": round(zostalo / miesiecy, 2),
        "szacunek": rok > OSTATNI_ROK,
    }

    lata = []
    for r in sorted(set(wplaty_lat) | {rok}):
        l = limit(kind, r, jdg)
        lata.append({"rok": r, "wplaty": round(wplaty_lat.get(r, 0.0), 2), "limit": l,
                     "pct": round(min(100.0, wplaty_lat.get(r, 0.0) / l * 100), 1) if l else 0.0})
    lata_z_wplatami = sum(1 for r, v in wplaty_lat.items() if v > 0)

    # ---- tarcza podatkowa: ile Belki nie zapłaciłeś dzięki temu kontu
    t_dyw = max(0.0, BELKA * dyw_brutto - abs(dyw_podatek))
    t_zreal = BELKA * max(0.0, zreal)
    t_niezreal = BELKA * max(0.0, niezreal)
    tarcza = t_dyw + t_zreal + t_niezreal

    podatek = {
        "tarcza": round(tarcza, 2),
        "skladniki": [
            {"id": "sprzedaze", "nazwa": "Zysk ze sprzedaży", "kwota": round(t_zreal, 2),
             "opis": "19% od zysku z zamkniętych pozycji — na zwykłym rachunku zapłacone w PIT-38"},
            {"id": "dywidendy", "nazwa": "Dywidendy", "kwota": round(t_dyw, 2),
             "opis": "19% od dywidend minus podatek już pobrany za granicą"},
            {"id": "papierowy", "nazwa": "Zysk na otwartych pozycjach", "kwota": round(t_niezreal, 2),
             "opis": "19% od zysku, który jeszcze nie został zrealizowany"},
        ],
    }

    # ---- warunki wypłaty
    wiek_celu = ZASADY[kind]["wiek"]
    wiek = (rok - int(rok_ur)) if rok_ur else None
    lat_do = max(0, wiek_celu - wiek) if wiek is not None else None
    warunki = {
        "wiek_celu": wiek_celu, "wiek": wiek, "lat_do": lat_do,
        "rok_wyplaty": (int(rok_ur) + wiek_celu) if rok_ur else None,
        "wiek_ok": bool(wiek is not None and wiek >= wiek_celu),
        "lata_z_wplatami": lata_z_wplatami, "lat_wymaganych": 5,
        "staz_ok": lata_z_wplatami >= 5,
    }

    # ---- co się stanie, gdy wypłacisz teraz, a co po spełnieniu warunków
    if kind == "ike":
        pod_teraz = BELKA * max(0.0, zysk)
        pod_cel = 0.0
        opis_teraz = "19% podatku Belki od zysku. Wpłacony kapitał wraca w całości."
        opis_cel = "Bez podatku — ani od kapitału, ani od zysku."
        ulga_razem = ulga_rok = 0.0
        bilans = tarcza
    else:
        st_zwrotu = _stawka_zwrotu(stawka)
        pod_teraz = st_zwrotu * max(0.0, wartosc)
        pod_cel = IKZE_RYCZALT * max(0.0, wartosc)
        opis_teraz = (f"Cała kwota doliczona do dochodu i opodatkowana skalą "
                      f"({int(st_zwrotu * 100)}%). Zwrot tylko w całości.")
        opis_cel = "Ryczałt 10% od całej kwoty, bez podatku Belki."
        ulga_razem = sum(min(v, limit(kind, r, jdg)) * stawka for r, v in wplaty_lat.items())
        ulga_rok = min(wplacono, lim) * stawka
        bilans = ulga_razem + tarcza - pod_cel
        podatek["ulga_razem"] = round(ulga_razem, 2)
        podatek["ulga_rok"] = round(ulga_rok, 2)
        podatek["ulga_do_wziecia"] = round(zostalo * stawka, 2)
        podatek["ryczalt_na_koncu"] = round(pod_cel, 2)
        podatek["stawka"] = stawka
    podatek["bilans"] = round(bilans, 2)

    spelnione = warunki["wiek_ok"] and warunki["staz_ok"]
    wyplata = {
        "spelnione": spelnione,
        "teraz": {"podatek": round(pod_cel if spelnione else pod_teraz, 2),
                  "na_reke": round(wartosc - (pod_cel if spelnione else pod_teraz), 2),
                  "opis": opis_cel if spelnione else opis_teraz},
        "docelowo": {"podatek": round(pod_cel, 2), "na_reke": round(wartosc - pod_cel, 2),
                     "opis": opis_cel},
        "roznica": round(0.0 if spelnione else pod_teraz - pod_cel, 2),
        "czesciowo": kind == "ike",
    }

    return {
        "typ": kind,
        "ma_dane": bool(konta_typu or aktywa_typu),
        "konta": konta_typu,
        "aktywa": [{"id": a["id"], "nazwa": a["nazwa"], "wartosc": a["wartosc"]} for a in aktywa_typu],
        "wartosc": round(wartosc, 2), "wplaty": round(netto, 2), "zysk": round(zysk, 2),
        "zysk_pct": round(zysk / netto * 100, 2) if netto > 1e-9 else 0.0,
        "xirr_pct": xirr,
        "limit": limit_out, "lata": lata, "podatek": podatek,
        "warunki": warunki, "wyplata": wyplata,
        "seria": seria, "pozycje": pozycje[:12],
    }


def _zwykle(konta_zwykle: list[dict]) -> dict:
    """Wartość zwykłych rachunków w podziale pod OKI: aktywa polskie, zagraniczne, gotówka.

    Podział jest z grubsza — po notowaniu na GPW. Dla ETF-u decyduje jego skład
    (próg 70% polskich aktywów), którego stąd nie widać; ekran o tym mówi.
    """
    from portfolio import engine as pf_engine
    import wealth

    numery = {k["konto"] for k in konta_zwykle}
    out = {"polskie": 0.0, "zagraniczne": 0.0, "gotowka_pln": 0.0, "gotowka_obca": 0.0,
           "zysk": 0.0, "dywidendy_12m": 0.0}
    if not numery:
        return out
    d = pf_engine.compute_subset(numery)
    if d.get("empty"):
        return out
    for p in d["positions"]:
        if p.get("no_price"):
            continue
        klucz = "polskie" if p["ticker"].upper().endswith((".PL", ".WA")) else "zagraniczne"
        out[klucz] += p["value_pln"]
        out["zysk"] += max(0.0, p["pl_pln"])
    kursy = wealth._przeliczniki([a["currency"] for a in d["accounts"]])
    for a in d["accounts"]:
        got = float(a.get("cash") or 0)
        if (a["currency"] or "PLN").upper() == "PLN":
            out["gotowka_pln"] += got
        else:
            out["gotowka_obca"] += got * kursy.get(a["currency"].upper(), 1.0)
    out["dywidendy_12m"] = d["summary"].get("dividends_net_12m", 0.0)
    return {k: round(v, 2) for k, v in out.items()}


def meta(profil: dict | None = None) -> dict:
    """Zasady, limity i kalendarz — część darmowa, bez danych użytkownika."""
    dzis = dt.date.today()
    jdg = bool((profil or {}).get("jdg"))
    start_oki = dt.date.fromisoformat(ZASADY["oki"]["start"])
    return {
        "rok": dzis.year,
        "zasady": ZASADY,
        "limity": [{"rok": r, "ike": v[0], "ikze": v[1], "ikze_jdg": v[2]}
                   for r, v in sorted(LIMITY.items())],
        "limit_rok": {"ike": limit("ike", dzis.year), "ikze": limit("ikze", dzis.year, jdg),
                      "ikze_zwykly": limit("ikze", dzis.year), "ikze_jdg": limit("ikze", dzis.year, True)},
        "dni_do_konca_roku": (dt.date(dzis.year, 12, 31) - dzis).days,
        "oki": {"start": ZASADY["oki"]["start"], "dni_do_startu": max(0, (start_oki - dzis).days),
                "dziala": dzis >= start_oki, "stawka_pct": ZASADY["oki"]["stawka_pct"],
                "limit_inwestycyjny": ZASADY["oki"]["limit_inwestycyjny"],
                "limit_oszczednosciowy": ZASADY["oki"]["limit_oszczednosciowy"]},
        "zalozenia": ZALOZENIA,
        "belka": BELKA, "ikze_ryczalt": IKZE_RYCZALT,
    }


def przeglad(profil: dict) -> dict:
    """Pełny obraz kont emerytalnych zalogowanego użytkownika."""
    import wealth

    dzis = dt.date.today()
    wszystkie = konta()
    typy_akt = typy_aktywow()
    aktywa = []
    if typy_akt:
        try:
            aktywa = [dict(a, typ=typy_akt[a["id"]]) for a in wealth.majatek()["aktywa"]
                      if a["id"] in typy_akt]
        except Exception as e:  # noqa: BLE001
            log.warning("Majątek na kontach emerytalnych: %s", e)

    out = {"demo": False, "konta": wszystkie,
           "migracja": bool(wszystkie[0]["gotowe"]) if wszystkie else True}
    for kind in ("ike", "ikze"):
        out[kind] = _policz(kind, [k for k in wszystkie if k["typ"] == kind],
                            [a for a in aktywa if a["typ"] == kind], profil, dzis)
    try:
        out["zwykle"] = _zwykle([k for k in wszystkie if not k["typ"]])
    except Exception as e:  # noqa: BLE001
        log.warning("Zwykłe rachunki pod OKI: %s", e)
        out["zwykle"] = None
    out["razem"] = round(out["ike"]["wartosc"] + out["ikze"]["wartosc"], 2)
    out["korzysc_razem"] = round(out["ike"]["podatek"]["bilans"] + out["ikze"]["podatek"]["bilans"], 2)
    return out


def wykryte() -> dict:
    """Ile rachunków każdego rodzaju ma użytkownik — bez żadnych kwot.

    To idzie także do konta bez premium: wiadomość „rozpoznaliśmy u Ciebie IKE"
    jest powodem, żeby w ogóle zajrzeć pod zasłonę.
    """
    try:
        k = konta()
    except Exception:  # noqa: BLE001
        return {"ike": 0, "ikze": 0, "oki": 0, "wszystkie": 0}
    akt = typy_aktywow()
    out = {t: sum(1 for x in k if x["typ"] == t) + sum(1 for v in akt.values() if v == t)
           for t in KINDS}
    out["wszystkie"] = len(k)
    return out


# -------------------------------------------------------------------- demo

def demo(profil: dict) -> dict:
    """Przykładowe konto dla widoku bez premium.

    Liczby są zmyślone i stałe — ekran pokazuje je zamglone, jako kształt tego,
    co będzie po odblokowaniu. Prawdziwych danych konto bez premium nie dostaje
    w ogóle: o dostępie decyduje serwer, a rozmycie w aplikacji to tylko wygląd.
    """
    dzis = dt.date.today()
    rok = dzis.year

    def seria(start: float, miesieczna: float, wzrost: float, faza: float) -> dict:
        dni = 900
        dates, values, invested = [], [], []
        v = inv = start
        for i in range(dni):
            d = dzis - dt.timedelta(days=dni - 1 - i)
            if d.day == 5:
                v += miesieczna
                inv += miesieczna
            v *= 1 + wzrost / 365 + 0.006 * math.sin(i / 17.0 + faza) * math.cos(i / 5.3)
            dates.append(d.isoformat()); values.append(round(v, 2)); invested.append(round(inv, 2))
        return dict(zip(("dates", "values", "invested"), _przerzedz(dates, values, invested)))

    def konto(kind: str, s: dict, wplacono: float, lata_wplat: list) -> dict:
        wartosc, netto = s["values"][-1], s["invested"][-1]
        zysk = wartosc - netto
        lim = limit(kind, rok, bool(profil.get("jdg")))
        stawka = float(profil.get("stawka") or 0.12)
        zostalo = max(0.0, lim - wplacono)
        tarcza = BELKA * zysk
        if kind == "ike":
            pod_teraz, pod_cel, ulga = BELKA * zysk, 0.0, 0.0
        else:
            pod_teraz, pod_cel = _stawka_zwrotu(stawka) * wartosc, IKZE_RYCZALT * wartosc
            ulga = sum(v for _, v in lata_wplat) * stawka
        podatek = {"tarcza": round(tarcza, 2), "bilans": round(tarcza + ulga - pod_cel, 2),
                   "skladniki": [
                       {"id": "sprzedaze", "nazwa": "Zysk ze sprzedaży", "kwota": round(tarcza * .22, 2), "opis": ""},
                       {"id": "dywidendy", "nazwa": "Dywidendy", "kwota": round(tarcza * .11, 2), "opis": ""},
                       {"id": "papierowy", "nazwa": "Zysk na otwartych pozycjach", "kwota": round(tarcza * .67, 2), "opis": ""}]}
        if kind == "ikze":
            podatek.update(ulga_razem=round(ulga, 2), ulga_rok=round(wplacono * stawka, 2),
                           ulga_do_wziecia=round(zostalo * stawka, 2),
                           ryczalt_na_koncu=round(pod_cel, 2), stawka=stawka)
        return {
            "typ": kind, "ma_dane": True, "konta": [], "aktywa": [],
            "wartosc": wartosc, "wplaty": netto, "zysk": round(zysk, 2),
            "zysk_pct": round(zysk / netto * 100, 2), "xirr_pct": 11.4 if kind == "ike" else 9.8,
            "limit": {"rok": rok, "limit": lim, "wplacono": wplacono, "zostalo": zostalo,
                      "pct": round(wplacono / lim * 100, 1),
                      "dni_do_konca": (dt.date(rok, 12, 31) - dzis).days,
                      "miesiecznie": round(zostalo / max(1, 12 - dzis.month + 1), 2), "szacunek": False},
            "lata": [{"rok": r, "wplaty": v, "limit": limit(kind, r),
                      "pct": round(min(100.0, v / limit(kind, r) * 100), 1)} for r, v in lata_wplat],
            "podatek": podatek,
            "warunki": {"wiek_celu": ZASADY[kind]["wiek"], "wiek": 34, "lat_do": ZASADY[kind]["wiek"] - 34,
                        "rok_wyplaty": rok + ZASADY[kind]["wiek"] - 34, "wiek_ok": False,
                        "lata_z_wplatami": len(lata_wplat), "lat_wymaganych": 5,
                        "staz_ok": len(lata_wplat) >= 5},
            "wyplata": {"spelnione": False,
                        "teraz": {"podatek": round(pod_teraz, 2), "na_reke": round(wartosc - pod_teraz, 2), "opis": ""},
                        "docelowo": {"podatek": round(pod_cel, 2), "na_reke": round(wartosc - pod_cel, 2), "opis": ""},
                        "roznica": round(pod_teraz - pod_cel, 2), "czesciowo": kind == "ike"},
            "seria": s,
            "pozycje": [
                {"ticker": "VWCE.DE", "nazwa": "Vanguard FTSE All-World", "wartosc": round(wartosc * .46, 2), "zysk": round(zysk * .5, 2), "zysk_pct": 31.2},
                {"ticker": "ETFBW20TR.PL", "nazwa": "Beta ETF WIG20TR", "wartosc": round(wartosc * .27, 2), "zysk": round(zysk * .3, 2), "zysk_pct": 24.9},
                {"ticker": "PKN.PL", "nazwa": "Orlen", "wartosc": round(wartosc * .17, 2), "zysk": round(zysk * .2, 2), "zysk_pct": 18.3},
            ],
        }

    ike = konto("ike", seria(9000, 1800, 0.11, 0.0), 19800.0,
                [(rok - 2, 17600.0), (rok - 1, 21600.0), (rok, 19800.0)])
    ikze = konto("ikze", seria(4000, 800, 0.095, 1.7), 8800.0,
                 [(rok - 2, 8100.0), (rok - 1, 9600.0), (rok, 8800.0)])
    return {
        "demo": True, "konta": [], "migracja": True, "ike": ike, "ikze": ikze,
        "zwykle": {"polskie": 41200.0, "zagraniczne": 86400.0, "gotowka_pln": 5200.0,
                   "gotowka_obca": 1900.0, "zysk": 23800.0, "dywidendy_12m": 1840.0},
        "razem": round(ike["wartosc"] + ikze["wartosc"], 2),
        "korzysc_razem": round(ike["podatek"]["bilans"] + ikze["podatek"]["bilans"], 2),
    }
