"""Przeniesienie danych portfela z lokalnego SQLite do Supabase — jednorazowo.

Do uruchomienia RAZ, zanim wystartujesz serwer na nowej bazie. Stary plik
`bot/portfolio_data/portfolio.db` zostaje nietknięty — skrypt tylko czyta.

Uruchomienie (z katalogu projektu, przy uzupełnionym .env):

    python bot/migrate_sqlite_to_supabase.py --email twoj@email.pl

Na sucho, bez zapisu — żeby najpierw zobaczyć, co się przeniesie:

    python bot/migrate_sqlite_to_supabase.py --email twoj@email.pl --dry-run

Konto o podanym adresie musi już istnieć w Supabase, czyli musisz się choć raz
zalogować w aplikacji. Skrypt pisze kluczem serwisowym (omija RLS), bo wstawia
wiersze „w cudzym imieniu" — dlatego user_id podaje jawnie w każdym wierszu.

Dwie drogi zapisu, wybierane automatycznie:

* **rest** — przez API Supabase, potrzebny tylko SUPABASE_SERVICE_KEY. Wolniejsze,
  ale działa bez hasła do bazy, więc nadaje się na pierwsze uruchomienie.
* **postgres** — bezpośrednio, gdy w .env jest SUPABASE_DB_URL. Szybsze przy
  większych zbiorach.
"""

import argparse
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import db                # noqa: E402
import supabase_auth     # noqa: E402

SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "portfolio_data", "portfolio.db")

# tabela -> (kolumny w SQLite, czy wiersze należą do użytkownika)
TABLES = {
    "accounts": (["account", "currency", "broker", "label", "date_from", "date_to",
                  "imported_at", "fees"], True),
    "cash_ops": (["account", "op_id", "type", "ticker", "instrument", "time",
                  "amount", "comment", "product"], True),
    "closed_positions": (["key", "account", "instrument", "category", "ticker", "type",
                          "volume", "open_price", "open_time", "close_price", "close_time",
                          "profit", "gross_profit", "purchase_value", "sale_value",
                          "commission", "swap", "rollover", "close_origin", "position_id"], True),
    "watchlist": (["symbol", "name", "type", "exchange", "currency", "note"], True),
    "price_cache": (["symbol", "date", "close"], False),
    "price_meta": (["symbol", "source", "last_fetch", "status"], False),
    "instrument_meta": (["ticker", "quote_type", "sector", "industry", "long_name",
                         "fetched_at"], False),
}


def _sqlite_rows(con, table: str, columns: list) -> list:
    have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    if not have:
        return []
    cols = [c for c in columns if c in have]
    if not cols:
        return []
    rows = con.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
    return [(cols, tuple(r)) for r in rows]


def _rest_insert(table: str, columns: list, values: list) -> tuple[int, str]:
    """Wstawia partię wierszy przez API Supabase. Zwraca (ile poszło, błąd)."""
    import requests

    payload = [dict(zip(columns, row)) for row in values]
    r = requests.post(
        f"{supabase_auth.URL}/rest/v1/{table}",
        headers={
            "apikey": supabase_auth.SERVICE,
            "Authorization": f"Bearer {supabase_auth.SERVICE}",
            "Content-Type": "application/json",
            # duplikaty pomijamy zamiast wywracać całą partię — skrypt ma być
            # bezpieczny do powtórzenia, gdyby przerwał się w połowie
            "Prefer": "resolution=ignore-duplicates,return=minimal",
        },
        data=json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
        timeout=60,
    )
    if r.status_code >= 300:
        return 0, f"HTTP {r.status_code}: {r.text[:200]}"
    return len(values), ""


def resolve_user_id(email: str) -> str:
    rows = supabase_auth._service_get("profiles", {"email": f"eq.{email.lower()}",
                                                   "select": "id"})
    return (rows[0].get("id") if rows else "") or ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Przeniesienie portfela do Supabase")
    ap.add_argument("--email", required=True, help="adres konta w Supabase, do którego trafią dane")
    ap.add_argument("--dry-run", action="store_true", help="tylko policz, nic nie zapisuj")
    ap.add_argument("--transport", choices=["auto", "rest", "postgres"], default="auto",
                    help="auto = postgres gdy jest SUPABASE_DB_URL, inaczej rest")
    ap.add_argument("--batch", type=int, default=1000, help="wielkość partii zapisu")
    args = ap.parse_args()

    if not os.path.exists(SQLITE_PATH):
        print(f"Nie ma pliku {SQLITE_PATH} — nie ma czego przenosić.")
        return 1

    transport = args.transport
    if transport == "auto":
        transport = "postgres" if db.configured() else "rest"
    if transport == "postgres" and not db.configured():
        print("Brak SUPABASE_DB_URL — użyj --transport rest albo uzupełnij .env.")
        return 1
    if transport == "rest" and not (supabase_auth.URL and supabase_auth.SERVICE):
        print("Brak SUPABASE_URL / SUPABASE_SERVICE_KEY — nie ma czym pisać przez REST.")
        return 1
    print(f"Sposób zapisu: {transport}")

    user_id = resolve_user_id(args.email)
    if not user_id:
        print(f"W Supabase nie ma konta {args.email}. Zaloguj się raz w aplikacji i powtórz.")
        return 1
    print(f"Konto docelowe: {args.email} ({user_id})")

    con = sqlite3.connect(SQLITE_PATH)
    total = 0
    for table, (columns, per_user) in TABLES.items():
        try:
            data = _sqlite_rows(con, table, columns)
        except sqlite3.Error as e:
            print(f"  {table}: pomijam ({e})")
            continue
        if not data:
            print(f"  {table}: pusto")
            continue

        cols = data[0][0]
        values = [r[1] for r in data]
        target_cols = (["user_id"] + cols) if per_user else cols
        if per_user:
            values = [(user_id, *v) for v in values]

        print(f"  {table}: {len(values)} wierszy{' (na sucho)' if args.dry_run else ''}", flush=True)
        if args.dry_run:
            total += len(values)
            continue

        # partiami — jeden wielki zapis na cache cen przekracza limity i wywala
        # się w połowie, a wtedy nie wiadomo, co już poszło
        done, failed = 0, ""
        for i in range(0, len(values), args.batch):
            chunk = values[i:i + args.batch]
            if transport == "rest":
                n, err = _rest_insert(table, target_cols, chunk)
                if err:
                    failed = err
                    break
                done += n
            else:
                placeholders = ",".join(["%s"] * len(target_cols))
                db.shared_executemany(
                    f"INSERT INTO {table}({', '.join(target_cols)}) "
                    f"VALUES({placeholders}) ON CONFLICT DO NOTHING", chunk)
                done += len(chunk)
            if len(values) > args.batch:
                print(f"      {done}/{len(values)}", end="\r", flush=True)
                time.sleep(0.05)      # nie zasypujemy darmowego planu

        if failed:
            print(f"      PRZERWANE po {done} wierszach: {failed}")
            return 1
        if len(values) > args.batch:
            print(f"      {done}/{len(values)} gotowe    ")
        total += done

    con.close()
    print(f"\nRazem: {total} wierszy{' do przeniesienia' if args.dry_run else ' przeniesionych'}.")
    if args.dry_run:
        print("Powtórz bez --dry-run, żeby zapisać.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
