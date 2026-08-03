"""SQLite dla modułu portfela — operacje gotówkowe, pozycje zamknięte, cache cen.

Baza: bot/portfolio_data/portfolio.db (tworzona automatycznie).
Wszystkie czasy trzymamy jako ISO string (UTC), kwoty jako REAL w walucie konta.
"""

import os
import sqlite3
import threading

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "portfolio_data")
DB_PATH = os.path.join(_DIR, "portfolio.db")

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    os.makedirs(_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account     TEXT PRIMARY KEY,
    currency    TEXT NOT NULL,
    broker      TEXT NOT NULL DEFAULT 'XTB',
    label       TEXT DEFAULT '',
    date_from   TEXT DEFAULT '',
    date_to     TEXT DEFAULT '',
    imported_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS cash_ops (
    account    TEXT NOT NULL,
    op_id      TEXT NOT NULL,
    type       TEXT NOT NULL,
    ticker     TEXT DEFAULT '',
    instrument TEXT DEFAULT '',
    time       TEXT NOT NULL,
    amount     REAL NOT NULL,
    comment    TEXT DEFAULT '',
    product    TEXT DEFAULT '',
    PRIMARY KEY (account, op_id)
);
CREATE INDEX IF NOT EXISTS idx_cash_ops_time ON cash_ops(time);
CREATE TABLE IF NOT EXISTS closed_positions (
    key            TEXT PRIMARY KEY,   -- position_id|close_time|volume (partial close = osobny wiersz)
    account        TEXT NOT NULL,
    instrument     TEXT DEFAULT '',
    category       TEXT DEFAULT '',
    ticker         TEXT DEFAULT '',
    type           TEXT DEFAULT '',
    volume         REAL DEFAULT 0,
    open_price     REAL DEFAULT 0,
    open_time      TEXT DEFAULT '',
    close_price    REAL DEFAULT 0,
    close_time     TEXT DEFAULT '',
    profit         REAL DEFAULT 0,
    gross_profit   REAL DEFAULT 0,
    purchase_value REAL DEFAULT 0,
    sale_value     REAL DEFAULT 0,
    commission     REAL DEFAULT 0,
    swap           REAL DEFAULT 0,
    rollover       REAL DEFAULT 0,
    close_origin   TEXT DEFAULT '',
    position_id    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS price_cache (
    symbol TEXT NOT NULL,   -- symbol źródłowy, np. 'genb.us' / '^spx' / 'usdpln'
    date   TEXT NOT NULL,   -- YYYY-MM-DD
    close  REAL NOT NULL,
    PRIMARY KEY (symbol, date)
);
CREATE TABLE IF NOT EXISTS watchlist (
    symbol   TEXT PRIMARY KEY,      -- symbol Yahoo, np. MSFT / CDR.WA
    name     TEXT DEFAULT '',
    type     TEXT DEFAULT '',       -- EQUITY / ETF / CRYPTOCURRENCY ...
    exchange TEXT DEFAULT '',
    currency TEXT DEFAULT '',
    note     TEXT DEFAULT '',
    added_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS price_meta (
    symbol     TEXT PRIMARY KEY,
    source     TEXT DEFAULT '',      -- 'stooq' | 'yahoo' | 'none'
    last_fetch TEXT DEFAULT '',      -- ISO UTC ostatniej udanej/nieudanej próby
    status     TEXT DEFAULT ''       -- 'ok' | 'empty' | 'error'
);
"""


def init() -> None:
    with _lock, _connect() as con:
        con.executescript(SCHEMA)
        # dokładane kolumny — baza mogła powstać przed ich wprowadzeniem
        have = {r[1] for r in con.execute("PRAGMA table_info(accounts)")}
        if "fees" not in have:
            con.execute("ALTER TABLE accounts ADD COLUMN fees TEXT DEFAULT ''")


def query(sql: str, params: tuple = ()) -> list:
    with _lock, _connect() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]


def execute(sql: str, params: tuple = ()) -> None:
    with _lock, _connect() as con:
        con.execute(sql, params)


def execute_script(sql: str) -> None:
    with _lock, _connect() as con:
        con.executescript(sql)


def executemany(sql: str, rows: list) -> None:
    if not rows:
        return
    with _lock, _connect() as con:
        con.executemany(sql, rows)


# ---------- pomocnicze zapisy ----------

def upsert_account(account: str, currency: str, date_from: str, date_to: str,
                   imported_at: str, broker: str = "") -> None:
    execute(
        """INSERT INTO accounts(account, currency, date_from, date_to, imported_at, broker)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(account) DO UPDATE SET
             currency=excluded.currency,
             date_from=MIN(accounts.date_from, excluded.date_from),
             date_to=MAX(accounts.date_to, excluded.date_to),
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
    execute("UPDATE accounts SET broker=?, fees=? WHERE account=?",
            ((broker or "").upper(), payload, account))


def insert_cash_ops(rows: list) -> int:
    """Wstawia operacje, ignoruje duplikaty (PRIMARY KEY account+op_id). Zwraca ile nowych."""
    before = query("SELECT COUNT(*) AS n FROM cash_ops")[0]["n"]
    executemany(
        """INSERT OR IGNORE INTO cash_ops(account, op_id, type, ticker, instrument, time, amount, comment, product)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    after = query("SELECT COUNT(*) AS n FROM cash_ops")[0]["n"]
    return after - before


def insert_closed_positions(rows: list) -> int:
    before = query("SELECT COUNT(*) AS n FROM closed_positions")[0]["n"]
    executemany(
        """INSERT OR IGNORE INTO closed_positions(key, account, instrument, category, ticker, type,
             volume, open_price, open_time, close_price, close_time, profit, gross_profit,
             purchase_value, sale_value, commission, swap, rollover, close_origin, position_id)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    after = query("SELECT COUNT(*) AS n FROM closed_positions")[0]["n"]
    return after - before


# ---------- obserwowane spółki ----------

def watch_add(symbol: str, name: str, typ: str, exchange: str, currency: str) -> None:
    import datetime
    execute(
        """INSERT INTO watchlist(symbol, name, type, exchange, currency, added_at)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(symbol) DO UPDATE SET
             name=excluded.name, type=excluded.type,
             exchange=excluded.exchange, currency=excluded.currency""",
        (symbol, name, typ, exchange, currency,
         datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")),
    )


def watch_remove(symbol: str) -> None:
    execute("DELETE FROM watchlist WHERE symbol=?", (symbol,))


def watch_symbols() -> set:
    return {r["symbol"] for r in query("SELECT symbol FROM watchlist")}


# ---------- cache cen ----------

def get_prices(symbol: str) -> dict:
    """Zwraca {data: close} dla symbolu z cache."""
    return {r["date"]: r["close"] for r in query(
        "SELECT date, close FROM price_cache WHERE symbol=? ORDER BY date", (symbol,))}


def put_prices(symbol: str, series: dict, source: str, status: str, fetched_at: str) -> None:
    executemany(
        "INSERT OR REPLACE INTO price_cache(symbol, date, close) VALUES(?,?,?)",
        [(symbol, d, c) for d, c in series.items()],
    )
    execute(
        """INSERT INTO price_meta(symbol, source, last_fetch, status) VALUES(?,?,?,?)
           ON CONFLICT(symbol) DO UPDATE SET source=excluded.source,
             last_fetch=excluded.last_fetch, status=excluded.status""",
        (symbol, source, fetched_at, status),
    )


def get_price_meta(symbol: str):
    rows = query("SELECT * FROM price_meta WHERE symbol=?", (symbol,))
    return rows[0] if rows else None


def set_meta(symbol: str, source: str, status: str, fetched_at: str) -> None:
    """Zapis samych metadanych (np. rozwiązany symbol Yahoo), bez cen."""
    execute(
        """INSERT INTO price_meta(symbol, source, last_fetch, status) VALUES(?,?,?,?)
           ON CONFLICT(symbol) DO UPDATE SET source=excluded.source,
             last_fetch=excluded.last_fetch, status=excluded.status""",
        (symbol, source, fetched_at, status),
    )


# ---------- kasowanie danych (zarządzanie raportami z UI) ----------

def delete_account(account: str) -> dict:
    """Usuwa konto wraz z operacjami i zamkniętymi pozycjami."""
    ops = query("SELECT COUNT(*) AS n FROM cash_ops WHERE account=?", (account,))[0]["n"]
    execute("DELETE FROM cash_ops WHERE account=?", (account,))
    execute("DELETE FROM closed_positions WHERE account=?", (account,))
    execute("DELETE FROM accounts WHERE account=?", (account,))
    return {"account": account, "ops_deleted": ops}


def wipe_all() -> None:
    """Czyści wszystkie dane portfela (konta, operacje, pozycje). Cache cen zostaje."""
    execute("DELETE FROM cash_ops")
    execute("DELETE FROM closed_positions")
    execute("DELETE FROM accounts")
