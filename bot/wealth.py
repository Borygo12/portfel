"""Portfele i majątek poza rachunkiem maklerskim.

Do tej pory Portevo miało jeden portfel: wszystko z wgranych raportów zliczone
razem. Ten moduł dokłada dwie rzeczy, o które prosił właściciel:

* **nazwane portfele**, do których przypisuje się rachunki maklerskie
  („Emerytura", „Spekulacja"),
* **majątek, którego żaden broker nie zna** — mieszkanie, działka, złoto,
  obligacje skarbowe.

**Jedno i drugie jest OPCJĄ.** Kto nie utworzy ani jednego portfela i nie doda
ani jednego aktywa, nie zobaczy żadnej różnicy: rachunki lądują w portfelu
domyślnym, a apka liczy dokładnie to co dziś. To jest warunek, którego nie
wolno złamać — dołożenie tej funkcji nie może popsuć widoku nikomu, kto jej
nie chce.

**Wycena idzie dwiema drogami i to jest sedno tego modułu.** Złoto, srebro
i kryptowaluty mają symbol rynkowy, więc wycenia je ten sam kod, co notowania
spółek — ilość razy kurs, bez pytania użytkownika o cokolwiek. Mieszkania
i działki nie mają kursu, więc mają listę wycen z datami: bieżąca wartość to
najnowszy wpis, a cała lista rysuje wykres wartości w czasie. Kolumna z jedną
kwotą byłaby prostsza, ale wtedy karta portfela z mieszkaniem miałaby płaską
kreskę zamiast wykresu — a wzrost wartości nieruchomości przez lata to
najciekawsza rzecz, jaka jest w takim portfelu do pokazania.
"""

from __future__ import annotations

import datetime as dt
import logging

import db

log = logging.getLogger("wealth")

#: Kategorie majątku. Klucz trafia do bazy, reszta steruje wyglądem i tym,
#: do której grupy aktywo wchodzi w Alokacji.
KATEGORIE = {
    "nieruchomosc": {"nazwa": "Nieruchomości", "ikona": "🏠", "klasa": "Nieruchomości"},
    "metal":        {"nazwa": "Metale szlachetne", "ikona": "🥇", "klasa": "Metale"},
    "krypto":       {"nazwa": "Kryptowaluty", "ikona": "₿", "klasa": "Kryptowaluty"},
    "obligacje":    {"nazwa": "Obligacje", "ikona": "📜", "klasa": "Obligacje"},
    "gotowka":      {"nazwa": "Gotówka i lokaty", "ikona": "💵", "klasa": "Gotówka"},
    "inne":         {"nazwa": "Inne", "ikona": "📦", "klasa": "Inne"},
}

#: Podpowiedzi symboli dla aktywów wycenianych z rynku. To nie jest zamknięta
#: lista — użytkownik może wpisać dowolny symbol, który zna nasze źródło
#: notowań — ale te załatwiają większość przypadków bez szukania.
SYMBOLE = [
    {"symbol": "GC=F", "nazwa": "Złoto (uncja)", "kategoria": "metal", "waluta": "USD"},
    {"symbol": "SI=F", "nazwa": "Srebro (uncja)", "kategoria": "metal", "waluta": "USD"},
    {"symbol": "PL=F", "nazwa": "Platyna (uncja)", "kategoria": "metal", "waluta": "USD"},
    {"symbol": "BTC-USD", "nazwa": "Bitcoin", "kategoria": "krypto", "waluta": "USD"},
    {"symbol": "ETH-USD", "nazwa": "Ethereum", "kategoria": "krypto", "waluta": "USD"},
    {"symbol": "SOL-USD", "nazwa": "Solana", "kategoria": "krypto", "waluta": "USD"},
]


# --------------------------------------------------------------- portfele


def portfele() -> list[dict]:
    rows = db.query(
        "SELECT id, name, color, icon, sort FROM portfolios ORDER BY sort, name")
    return [{"id": str(r["id"]), "nazwa": r["name"], "kolor": r["color"] or "",
             "ikona": r["icon"] or "", "sort": r["sort"]} for r in rows]


def dodaj_portfel(nazwa: str, kolor: str = "", ikona: str = "") -> dict:
    nazwa = (nazwa or "").strip()
    if not nazwa:
        raise ValueError("Portfel musi mieć nazwę")
    rows = db.query(
        "INSERT INTO portfolios (name, color, icon, sort) "
        "VALUES (%s, %s, %s, COALESCE((SELECT MAX(sort) + 1 FROM portfolios), 0)) "
        "ON CONFLICT (user_id, name) DO UPDATE SET color = EXCLUDED.color, "
        "icon = EXCLUDED.icon RETURNING id, name, color, icon, sort",
        (nazwa, kolor, ikona))
    r = rows[0]
    return {"id": str(r["id"]), "nazwa": r["name"], "kolor": r["color"] or "",
            "ikona": r["icon"] or "", "sort": r["sort"]}


def zmien_portfel(pid: str, nazwa: str = None, kolor: str = None,
                  ikona: str = None) -> None:
    pola, wart = [], []
    if nazwa is not None:
        pola.append("name = %s"); wart.append(nazwa.strip())
    if kolor is not None:
        pola.append("color = %s"); wart.append(kolor)
    if ikona is not None:
        pola.append("icon = %s"); wart.append(ikona)
    if not pola:
        return
    wart.append(pid)
    db.execute(f"UPDATE portfolios SET {', '.join(pola)} WHERE id = %s", tuple(wart))


def usun_portfel(pid: str) -> None:
    """Kasuje portfel. Rachunki i aktywa w nim ZOSTAJĄ — wracają do domyślnego.

    Świadomie: skasowanie nazwy grupy nie może kasować mieszkania ani historii
    rachunku. Baza ma na obu kluczach `on delete set null` i to jest właśnie
    ten powód.
    """
    db.execute("DELETE FROM portfolios WHERE id = %s", (pid,))


def przypisz_konto(account: str, pid: str | None) -> None:
    db.execute("UPDATE accounts SET portfolio_id = %s WHERE account = %s",
               (pid or None, account))


# --------------------------------------------------------------- majątek


def _wiersz_aktywa(r) -> dict:
    kat = KATEGORIE.get(r["category"]) or KATEGORIE["inne"]
    return {
        "id": str(r["id"]),
        "portfel_id": str(r["portfolio_id"]) if r["portfolio_id"] else None,
        "nazwa": r["name"],
        "kategoria": r["category"],
        "kategoria_nazwa": kat["nazwa"],
        "ikona": kat["ikona"],
        "klasa": kat["klasa"],
        "wycena": r["pricing"],
        "symbol": r["symbol"] or "",
        "ilosc": r["quantity"] or 0.0,
        "waluta": r["currency"] or "PLN",
        "koszt": r["cost"] or 0.0,
        "koszt_data": r["cost_date"] or "",
        "notatka": r["note"] or "",
    }


def aktywa() -> list[dict]:
    rows = db.query(
        "SELECT id, portfolio_id, name, category, pricing, symbol, quantity, "
        "currency, cost, cost_date, note FROM manual_assets ORDER BY sort, name")
    return [_wiersz_aktywa(r) for r in rows]


def dodaj_aktywo(dane: dict) -> dict:
    nazwa = (dane.get("nazwa") or "").strip()
    if not nazwa:
        raise ValueError("Aktywo musi mieć nazwę")
    kategoria = dane.get("kategoria") if dane.get("kategoria") in KATEGORIE else "inne"
    wycena = "auto" if dane.get("wycena") == "auto" else "manual"
    if wycena == "auto" and not (dane.get("symbol") or "").strip():
        raise ValueError("Aktywo wyceniane z rynku musi mieć symbol")

    rows = db.query(
        "INSERT INTO manual_assets (portfolio_id, name, category, pricing, symbol, "
        "quantity, currency, cost, cost_date, note, sort) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
        "COALESCE((SELECT MAX(sort) + 1 FROM manual_assets), 0)) "
        "RETURNING id, portfolio_id, name, category, pricing, symbol, quantity, "
        "currency, cost, cost_date, note",
        (dane.get("portfel_id") or None, nazwa, kategoria, wycena,
         (dane.get("symbol") or "").strip().upper(),
         float(dane.get("ilosc") or 0), (dane.get("waluta") or "PLN").upper(),
         float(dane.get("koszt") or 0), dane.get("koszt_data") or "",
         dane.get("notatka") or ""))
    aktywo = _wiersz_aktywa(rows[0])

    # Aktywo wyceniane ręcznie bez ani jednej wyceny byłoby warte zero i znikało
    # z wykresów. Pierwszą wycenę bierzemy więc z podanej wartości, a gdy jej
    # nie ma — z kosztu zakupu, bo to jedyna kwota, którą na pewno znamy.
    if aktywo["wycena"] == "manual":
        start = dane.get("wartosc")
        if start in (None, ""):
            start = aktywo["koszt"]
        if float(start or 0) > 0:
            dodaj_wycene(aktywo["id"], float(start),
                         dane.get("wartosc_data") or dt.date.today().isoformat())
    return aktywo


def zmien_aktywo(aid: str, dane: dict) -> None:
    mapa = {"nazwa": "name", "kategoria": "category", "symbol": "symbol",
            "ilosc": "quantity", "waluta": "currency", "koszt": "cost",
            "koszt_data": "cost_date", "notatka": "note", "portfel_id": "portfolio_id"}
    pola, wart = [], []
    for klucz, kolumna in mapa.items():
        if klucz in dane:
            v = dane[klucz]
            if klucz == "kategoria" and v not in KATEGORIE:
                continue
            if klucz == "portfel_id":
                v = v or None
            pola.append(f"{kolumna} = %s")
            wart.append(v)
    if not pola:
        return
    wart.append(aid)
    db.execute(f"UPDATE manual_assets SET {', '.join(pola)} WHERE id = %s", tuple(wart))


def usun_aktywo(aid: str) -> None:
    db.execute("DELETE FROM manual_assets WHERE id = %s", (aid,))


def dodaj_wycene(aid: str, wartosc: float, data: str = "", notatka: str = "") -> None:
    data = (data or dt.date.today().isoformat())[:10]
    db.execute(
        "INSERT INTO manual_valuations (asset_id, date, value, note) "
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (asset_id, date) DO UPDATE SET value = EXCLUDED.value, "
        "note = EXCLUDED.note",
        (aid, data, float(wartosc), notatka or ""))


def usun_wycene(aid: str, data: str) -> None:
    db.execute("DELETE FROM manual_valuations WHERE asset_id = %s AND date = %s",
               (aid, data[:10]))


def wyceny(aid: str = "") -> dict[str, list]:
    """{id_aktywa: [{data, wartosc}, …]} — posortowane od najstarszej."""
    if aid:
        rows = db.query(
            "SELECT asset_id, date, value FROM manual_valuations "
            "WHERE asset_id = %s ORDER BY date", (aid,))
    else:
        rows = db.query(
            "SELECT asset_id, date, value FROM manual_valuations ORDER BY date")
    out: dict[str, list] = {}
    for r in rows:
        out.setdefault(str(r["asset_id"]), []).append(
            {"data": r["date"], "wartosc": float(r["value"])})
    return out


# --------------------------------------------------------------- wycena


def _kursy(symbole: list[str]) -> dict:
    """{symbol: {price, currency}} — jednym żądaniem na wszystkie aktywa naraz.

    `live_quotes` pakuje po dwadzieścia symboli w jedno zapytanie, więc pytamy
    zbiorczo, a nie w pętli po aktywach. Przy dziesięciu pozycjach majątku
    różnica to jedno żądanie zamiast dziesięciu.

    Walutę bierzemy z odpowiedzi, a nie z tego, co wpisał użytkownik: złoto
    notowane jest w dolarach za uncję niezależnie od tego, co ktoś zaznaczył
    w formularzu, a pomyłka w tym polu zawyżyłaby wartość czterokrotnie.
    """
    symbole = [s for s in {s.strip().upper() for s in symbole} if s]
    if not symbole:
        return {}
    try:
        from portfolio import prices as pf_prices
        # `_quotes_for`, a nie `live_quotes`: to drugie przepuszcza symbol przez
        # mapowanie tickerów brokera, co oznacza zapytanie do bazy przy każdym
        # walorze. Nasze symbole to już symbole rynkowe (GC=F, BTC-USD), więc
        # tłumaczenie jest zbędne, a zależność od bazy byłaby wyłącznie kosztem.
        return pf_prices._quotes_for(symbole) or {}
    except Exception as e:  # noqa: BLE001
        log.warning("Kursy majątku: %s", e)
        return {}


def _przeliczniki(waluty: list[str]) -> dict:
    """{waluta: kurs do PLN}. PLN zawsze 1.0."""
    waluty = [w for w in {(w or "").upper() for w in waluty} if w and w != "PLN"]
    out = {"PLN": 1.0}
    if not waluty:
        return out
    try:
        from portfolio import prices as pf_prices
        for waluta, q in (pf_prices.live_fx(waluty) or {}).items():
            if isinstance(q, dict) and q.get("price"):
                out[waluta] = float(q["price"])
    except Exception as e:  # noqa: BLE001
        log.warning("Kursy walut dla majątku: %s", e)
    return out


def wartosc_aktywa(a: dict, historia: dict[str, list], kursy: dict,
                   przeliczniki: dict) -> dict:
    """Bieżąca wartość jednego aktywa w PLN plus skąd się wzięła.

    Zwracamy `zrodlo`, bo użytkownik ma prawo wiedzieć, czy patrzy na kurs
    z rynku, czy na kwotę, którą sam wpisał pół roku temu — to są dwie zupełnie
    różne liczby co do wiarygodności i nie wolno ich pokazywać identycznie.
    """
    if a["wycena"] == "auto" and a["symbol"]:
        q = kursy.get(a["symbol"].upper()) or {}
        kurs = q.get("price")
        if kurs is not None:
            waluta = (q.get("currency") or a["waluta"] or "PLN").upper()
            fx = przeliczniki.get(waluta, 1.0)
            wartosc = float(kurs) * float(a["ilosc"] or 0) * fx
            return {"wartosc": round(wartosc, 2), "zrodlo": "rynek", "kurs": kurs,
                    "kurs_waluta": waluta, "aktualne": True,
                    "data": dt.date.today().isoformat()}
        return {"wartosc": 0.0, "zrodlo": "rynek", "kurs": None,
                "kurs_waluta": "", "aktualne": False, "data": ""}

    lista = historia.get(a["id"]) or []
    if not lista:
        # Bez ani jednej wyceny bierzemy koszt zakupu. To nie jest wartość
        # rynkowa i tak jest oznaczone — ale zero byłoby gorsze, bo aktywo
        # zniknęłoby z wykresów, mimo że istnieje.
        return {"wartosc": round(float(a["koszt"] or 0), 2), "zrodlo": "koszt",
                "kurs": None, "kurs_waluta": "", "aktualne": False,
                "data": a["koszt_data"] or ""}
    ostatnia = lista[-1]
    return {"wartosc": round(ostatnia["wartosc"], 2), "zrodlo": "wycena",
            "kurs": None, "kurs_waluta": "", "aktualne": True,
            "data": ostatnia["data"]}


def majatek() -> dict:
    """Wszystkie aktywa ręczne z policzoną wartością i historią do wykresu."""
    lista = aktywa()
    if not lista:
        return {"aktywa": [], "razem": 0.0}

    historia = wyceny()
    kursy = _kursy([a["symbol"] for a in lista if a["wycena"] == "auto"])
    przeliczniki = _przeliczniki(
        [(kursy.get(a["symbol"].upper()) or {}).get("currency") or a["waluta"]
         for a in lista])

    out, razem = [], 0.0
    for a in lista:
        w = wartosc_aktywa(a, historia, kursy, przeliczniki)
        razem += w["wartosc"]
        out.append({**a, **w, "historia": historia.get(a["id"]) or [],
                    "zysk": round(w["wartosc"] - float(a["koszt"] or 0), 2)
                    if a["koszt"] else None})
    return {"aktywa": out, "razem": round(razem, 2)}
