"""Dane portfela w Supabase (Postgres) — operacje, pozycje zamknięte, cache cen.

Schemat tworzy migracja `supabase/migrations/0002_portfolio_multiuser.sql`,
nie ten plik. Tutaj jest wyłącznie dostęp.

Podział, który trzeba mieć w głowie czytając ten moduł:

* **dane użytkownika** (accounts, cash_ops, closed_positions, watchlist) idą przez
  `db.query` / `db.execute`, czyli w kontekście zalogowanego. RLS w bazie przycina
  wynik do jego wierszy — dlatego w SQL-u poniżej nie ma ani jednego
  `WHERE user_id = ...`. Kolumna wypełnia się sama (`default auth.uid()`).
* **wspólny cache rynkowy** (price_cache, price_meta, instrument_meta) idzie przez
  `db.shared_*`. Kurs Orlenu jest ten sam dla każdego, więc pobieramy go raz na
  wszystkich — to jest powód, dla którego koszt nie rośnie liniowo z użytkownikami.

Czasy trzymamy jako ISO string (UTC), kwoty jako double w walucie konta — tak jak
poprzednio, żeby reszta modułu nie musiała się zmieniać.
"""

import db

# ---------- dane użytkownika (RLS pilnuje rozdziału) ----------


def init() -> None:
    """Zostawione dla zgodności — schemat zakłada migracja SQL, nie aplikacja."""
    return None


def query(sql: str, params: tuple = ()) -> list:
    return db.query(sql, params)


def execute(sql: str, params: tuple = ()) -> None:
    db.execute(sql, params)


def executemany(sql: str, rows: list) -> None:
    db.executemany(sql, rows)


# ---------- pomocnicze zapisy ----------

def upsert_account(account: str, currency: str, date_from: str, date_to: str,
                   imported_at: str, broker: str = "") -> None:
    execute(
        """INSERT INTO accounts(account, currency, date_from, date_to, imported_at, broker)
           VALUES(%s,%s,%s,%s,%s,%s)
           ON CONFLICT(user_id, account) DO UPDATE SET
             currency=excluded.currency,
             date_from=LEAST(accounts.date_from, excluded.date_from),
             date_to=GREATEST(accounts.date_to, excluded.date_to),
             imported_at=excluded.imported_at,
             -- brokera z wykrycia nadpisujemy tylko wtedy, gdy coś wykryliśmy;
             -- ręczne ustawienie użytkownika ma zostać nietknięte
             broker=CASE WHEN excluded.broker != '' THEN excluded.broker ELSE accounts.broker END""",
        (account, currency, date_from, date_to, imported_at, broker),
    )


def set_account_fees(account: str, broker: str, fees) -> None:
    """Ręczne ustawienie brokera i stawek dla konta (formularz w aplikacji)."""
    import json as _json
    payload = fees if isinstance(fees, str) else _json.dumps(fees or {}, ensure_ascii=False)
    execute("UPDATE accounts SET broker=%s, fees=%s WHERE account=%s",
            ((broker or "").upper(), payload, account))


def insert_cash_ops(rows: list) -> int:
    """Wstawia operacje, pomija duplikaty (klucz user_id+account+op_id). Zwraca ile nowych."""
    before = query("SELECT COUNT(*) AS n FROM cash_ops")[0]["n"]
    executemany(
        """INSERT INTO cash_ops(account, op_id, type, ticker, instrument, time, amount, comment, product)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT DO NOTHING""",
        rows,
    )
    after = query("SELECT COUNT(*) AS n FROM cash_ops")[0]["n"]
    return after - before


def insert_closed_positions(rows: list) -> int:
    before = query("SELECT COUNT(*) AS n FROM closed_positions")[0]["n"]
    executemany(
        """INSERT INTO closed_positions(key, account, instrument, category, ticker, type,
             volume, open_price, open_time, close_price, close_time, profit, gross_profit,
             purchase_value, sale_value, commission, swap, rollover, close_origin, position_id)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT DO NOTHING""",
        rows,
    )
    after = query("SELECT COUNT(*) AS n FROM closed_positions")[0]["n"]
    return after - before


# ---------- obserwowane spółki ----------

def watch_add(symbol: str, name: str, typ: str, exchange: str, currency: str) -> None:
    execute(
        """INSERT INTO watchlist(symbol, name, type, exchange, currency)
           VALUES(%s,%s,%s,%s,%s)
           ON CONFLICT(user_id, symbol) DO UPDATE SET
             name=excluded.name, type=excluded.type,
             exchange=excluded.exchange, currency=excluded.currency""",
        (symbol, name, typ, exchange, currency),
    )


def watch_remove(symbol: str) -> None:
    execute("DELETE FROM watchlist WHERE symbol=%s", (symbol,))


def watch_symbols() -> set:
    return {r["symbol"] for r in query("SELECT symbol FROM watchlist")}


# ---------- wspólny cache cen (bez użytkownika) ----------

def get_prices(symbol: str) -> dict:
    """Zwraca {data: close} dla symbolu ze wspólnego cache."""
    return {r["date"]: r["close"] for r in db.shared_query(
        "SELECT date, close FROM price_cache WHERE symbol=%s ORDER BY date", (symbol,))}


def put_prices(symbol: str, series: dict, source: str, status: str, fetched_at: str) -> None:
    db.shared_executemany(
        """INSERT INTO price_cache(symbol, date, close) VALUES(%s,%s,%s)
           ON CONFLICT(symbol, date) DO UPDATE SET close=excluded.close""",
        [(symbol, d, c) for d, c in series.items()],
    )
    set_meta(symbol, source, status, fetched_at)


def get_price_meta(symbol: str):
    rows = db.shared_query("SELECT * FROM price_meta WHERE symbol=%s", (symbol,))
    return rows[0] if rows else None


def set_meta(symbol: str, source: str, status: str, fetched_at: str) -> None:
    """Zapis samych metadanych (np. rozwiązany symbol Yahoo), bez cen."""
    db.shared_execute(
        """INSERT INTO price_meta(symbol, source, last_fetch, status) VALUES(%s,%s,%s,%s)
           ON CONFLICT(symbol) DO UPDATE SET source=excluded.source,
             last_fetch=excluded.last_fetch, status=excluded.status""",
        (symbol, source, fetched_at, status),
    )


# ---------- kasowanie danych (zarządzanie raportami z UI) ----------

def delete_account(account: str) -> dict:
    """Usuwa konto wraz z operacjami i zamkniętymi pozycjami — tylko własne."""
    ops = query("SELECT COUNT(*) AS n FROM cash_ops WHERE account=%s", (account,))[0]["n"]
    execute("DELETE FROM cash_ops WHERE account=%s", (account,))
    execute("DELETE FROM closed_positions WHERE account=%s", (account,))
    execute("DELETE FROM accounts WHERE account=%s", (account,))
    return {"account": account, "ops_deleted": ops}


def wipe_all() -> None:
    """Czyści dane portfela ZALOGOWANEGO użytkownika. Wspólny cache cen zostaje."""
    execute("DELETE FROM cash_ops")
    execute("DELETE FROM closed_positions")
    execute("DELETE FROM accounts")
