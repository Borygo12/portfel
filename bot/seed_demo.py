"""Zasiew portfela demonstracyjnego — dane, które nowa osoba widzi przed zalogowaniem.

Cel: pokazać działającą aplikację, a nie puste ramki. Kwoty świadomie skromne
(rząd kilkunastu tysięcy złotych), żeby wyglądało jak portfel zwykłego człowieka,
a nie jak przechwałka.

Uruchomienie:
    python bot/seed_demo.py --email demo@przyklad.pl
    python bot/seed_demo.py --email demo@przyklad.pl --wipe    # najpierw czyści

Konto musi już istnieć w Supabase. Zapis idzie kluczem serwisowym, bo wstawiamy
wiersze „w cudzym imieniu" — dlatego user_id podajemy jawnie.
"""

import argparse
import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import requests  # noqa: E402

import supabase_auth  # noqa: E402

KONTO = "DEMO-1"
WALUTA = "PLN"

# (ticker, nazwa, sztuk, cena zakupu w PLN, ile dni temu kupione)
# Miks świadomie zwyczajny: kilka spółek z GPW, dwie zagraniczne przez XTB i ETF.
# Część na plusie, część na minusie — portfel bez ani jednej straty wygląda fałszywie.
POZYCJE = [
    ("PKN.PL", "Orlen",      20, 132.00, 520),
    ("PKO.PL", "PKO BP",     40, 118.00, 470),
    ("CDR.PL", "CD Projekt",  8, 210.00, 300),
    ("KGH.PL", "KGHM",       10, 380.00, 180),
]

# zamknięte pozycje — bez nich zakładka „Zamknięte" i statystyki są puste
ZAMKNIETE = [
    ("JSW.PL",  "JSW",          15,  38.20,  31.10, 420, 260),
    ("CCC.PL",  "CCC",          10,  62.00,  84.50, 380, 200),
    ("PZU.PL",  "PZU",          25,  44.80,  51.30, 350, 120),
    ("TSLA.US", "Tesla",         3, 980.00, 1120.00, 300,  90),
]

WPLATY = [(560, 7000.0), (400, 4000.0), (210, 2000.0), (95, 1000.0)]


def _dzien(ile_temu: int) -> str:
    return (_dt.date.today() - _dt.timedelta(days=ile_temu)).isoformat() + "T10:15:00"


def _rest(table: str, rows: list) -> None:
    if not rows:
        return
    r = requests.post(
        f"{supabase_auth.URL}/rest/v1/{table}",
        headers={
            "apikey": supabase_auth.SERVICE,
            "Authorization": f"Bearer {supabase_auth.SERVICE}",
            "Content-Type": "application/json",
            "Prefer": "resolution=ignore-duplicates,return=minimal",
        },
        data=json.dumps(rows, ensure_ascii=False, default=str).encode("utf-8"),
        timeout=60,
    )
    if r.status_code >= 300:
        raise SystemExit(f"Błąd zapisu do {table}: HTTP {r.status_code} {r.text[:300]}")


def _skasuj(table: str, uid: str) -> None:
    requests.delete(
        f"{supabase_auth.URL}/rest/v1/{table}",
        params={"user_id": f"eq.{uid}"},
        headers={"apikey": supabase_auth.SERVICE,
                 "Authorization": f"Bearer {supabase_auth.SERVICE}",
                 "Prefer": "return=minimal"},
        timeout=60,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Portfel demonstracyjny")
    ap.add_argument("--email", required=True)
    ap.add_argument("--wipe", action="store_true", help="skasuj wcześniejsze dane tego konta")
    args = ap.parse_args()

    rows = supabase_auth._service_get("profiles", {"email": f"eq.{args.email.lower()}",
                                                   "select": "id"})
    uid = (rows[0].get("id") if rows else "") or ""
    if not uid:
        print(f"Nie ma konta {args.email} w Supabase.")
        return 1
    print(f"Konto: {args.email} ({uid})")

    if args.wipe:
        for t in ("cash_ops", "closed_positions", "accounts", "watchlist"):
            _skasuj(t, uid)
        print("Poprzednie dane skasowane.")

    teraz = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    _rest("accounts", [{
        "user_id": uid, "account": KONTO, "currency": WALUTA, "broker": "XTB",
        "label": "Portfel demonstracyjny",
        "date_from": _dzien(560)[:10], "date_to": _dt.date.today().isoformat(),
        "imported_at": teraz, "fees": "",
    }])

    ops = []
    n = 0

    for dni, kwota in WPLATY:
        n += 1
        ops.append({"user_id": uid, "account": KONTO, "op_id": f"D{n}",
                    "type": "Deposit", "ticker": "", "instrument": "",
                    "time": _dzien(dni), "amount": kwota,
                    "comment": "Wplata na rachunek", "product": ""})

    for ticker, nazwa, ile, cena, dni in POZYCJE:
        n += 1
        wartosc = round(ile * cena, 2)
        ops.append({"user_id": uid, "account": KONTO, "op_id": f"B{n}",
                    "type": "Stock purchase", "ticker": ticker, "instrument": nazwa,
                    "time": _dzien(dni), "amount": -wartosc,
                    "comment": f"OPEN BUY {ile} @ {cena}", "product": "AKCJE"})

    for ticker, nazwa, ile, kupno, sprzedaz, dni_o, dni_z in ZAMKNIETE:
        n += 1
        ops.append({"user_id": uid, "account": KONTO, "op_id": f"C{n}o",
                    "type": "Stock purchase", "ticker": ticker, "instrument": nazwa,
                    "time": _dzien(dni_o), "amount": -round(ile * kupno, 2),
                    "comment": f"OPEN BUY {ile} @ {kupno}", "product": "AKCJE"})
        n += 1
        ops.append({"user_id": uid, "account": KONTO, "op_id": f"C{n}z",
                    "type": "Stock sell", "ticker": ticker, "instrument": nazwa,
                    "time": _dzien(dni_z), "amount": round(ile * sprzedaz, 2),
                    "comment": f"CLOSE SELL {ile} @ {sprzedaz}", "product": "AKCJE"})

    _rest("cash_ops", ops)
    print(f"Operacje: {len(ops)}")

    zamk = []
    for ticker, nazwa, ile, kupno, sprzedaz, dni_o, dni_z in ZAMKNIETE:
        zysk = round(ile * (sprzedaz - kupno), 2)
        zamk.append({
            "user_id": uid, "key": f"{ticker}|{dni_z}|{ile}", "account": KONTO,
            "instrument": nazwa, "category": "AKCJE", "ticker": ticker, "type": "BUY",
            "volume": ile, "open_price": kupno, "open_time": _dzien(dni_o),
            "close_price": sprzedaz, "close_time": _dzien(dni_z),
            "profit": zysk, "gross_profit": zysk,
            "purchase_value": round(ile * kupno, 2), "sale_value": round(ile * sprzedaz, 2),
            "commission": 0.0, "swap": 0.0, "rollover": 0.0,
            "close_origin": "demo", "position_id": f"DEMO-{ticker}",
        })
    _rest("closed_positions", zamk)
    print(f"Pozycje zamknięte: {len(zamk)}")

    obs = [{"user_id": uid, "symbol": s, "name": nm, "type": "EQUITY",
            "exchange": ex, "currency": cur}
           for s, nm, ex, cur in [
               ("CDR.WA", "CD Projekt", "WSE", "PLN"),
               ("PKN.WA", "Orlen", "WSE", "PLN"),
               ("NVDA", "NVIDIA", "NMS", "USD"),
               ("MSFT", "Microsoft", "NMS", "USD"),
           ]]
    _rest("watchlist", obs)
    print(f"Obserwowane: {len(obs)}")

    wplacone = sum(k for _, k in WPLATY)
    print(f"\nGotowe. Wpłacone łącznie: {wplacone:,.0f} zł, "
          f"{len(POZYCJE)} otwartych pozycji, {len(ZAMKNIETE)} zamkniętych.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
