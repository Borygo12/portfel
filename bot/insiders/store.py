"""Baza transakcji insiderów — SQLite na trwałym dysku serwera.

Dlaczego SQLite, a nie Supabase: to dane publiczne, wspólne dla wszystkich
i w pełni odtwarzalne ze źródeł. Kilkaset tysięcy wierszy z SEC w Postgresie
na darmowym planie zjadłoby limit miejsca, a każde otwarcie wykresu spółki
kosztowałoby podróż do bazy w innym regionie. Plik obok serwera odpowiada
w milisekundach i nie wymaga migracji.

Plik leży w katalogu danych (`paths.data_path`), czyli na Railway na woluminie
`/data` — przeżywa wdrożenia. Gdyby wolumin zniknął, baza zbuduje się od nowa
w tle (patrz `jobs.py`); nic tu nie jest jedyną kopią czegokolwiek.

Wątki: każdy wątek dostaje własne połączenie (SQLite nie lubi dzielenia
połączeń), a zapisy idą przez jeden zamek — tryb WAL pozwala czytać w trakcie
zapisu, ale dwóch piszących naraz dostałoby „database is locked".
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time

import paths

_DB = paths.data_path("insiders.db")
_local = threading.local()
_write = threading.Lock()

SCHEMA = """
create table if not exists trades(
  uid     text primary key,          -- klucz przeciw duplikatom, stabilny między źródłami
  person  text not null,             -- identyfikator persony (people.py)
  source  text not null,             -- sec | house | oge
  ticker  text not null default '',
  asset   text not null default '',  -- nazwa waloru, jak w zgłoszeniu
  side    text not null,             -- buy | sell
  date    text not null,             -- dzień transakcji RRRR-MM-DD
  filed   text not null default '',  -- dzień zgłoszenia (ujawnienia)
  shares  real,
  price   real,
  amt_lo  real,                      -- kwota: dokładna (SEC) albo przedział (Kongres, OGE)
  amt_hi  real,
  options integer not null default 0,
  owner   text not null default '',  -- kto formalnie: małżonek, wspólnie, dziecko
  note    text not null default '',
  url     text not null default '',
  planned integer not null default 0, -- plan 10b5-1: sprzedaż ustalona z góry
  added   real not null default 0    -- kiedy MY to zobaczyliśmy (do powiadomień)
);
create index if not exists trades_ticker on trades(ticker, date);
create index if not exists trades_person on trades(person, date);
create index if not exists trades_filed on trades(filed);
create index if not exists trades_added on trades(added);

create table if not exists people(
  id      text primary key,
  name    text not null,
  cat     text not null,
  role    text not null default '',
  org     text not null default '',
  source  text not null default '',
  extra   text not null default '{}',
  updated real not null default 0
);

create table if not exists kv(key text primary key, value text not null, at real not null default 0);
create table if not exists seen(key text primary key, at real not null default 0);
create table if not exists stats(person text primary key, data text not null, at real not null);
-- każde pytanie do modelu z insiderów (także nieudane) — do rachunku w panelu dev
create table if not exists ai_log(
  t       real not null,
  rodzaj  text not null,            -- podsumowanie | ptr
  model   text not null default '', -- pusty = odpowiedź z pamięci, bez pytania modelu
  ok      integer not null default 0,
  limit_  integer not null default 0,
  tok_in  integer not null default 0,
  tok_out integer not null default 0,
  usd     real not null default 0
);
create index if not exists ai_log_t on ai_log(t);
"""


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(_DB, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("pragma journal_mode=wal")
        c.execute("pragma synchronous=normal")
        c.executescript(SCHEMA)
        # Kolumny dołożone po pierwszym wydaniu — baza na dysku serwera już
        # istnieje, więc `create table if not exists` ich nie doda.
        kolumny = {r[1] for r in c.execute("pragma table_info(trades)")}
        if "cur" not in kolumny:
            # waluta kwot i ceny: pusta = dolary (SEC, Kongres, OGE), „PLN" = GPW
            c.execute("alter table trades add column cur text not null default ''")
            c.commit()
        _local.c = c
    return c


def path() -> str:
    return _DB


# ------------------------------------------------------------------ zapis


TRADE_COLS = ("uid", "person", "source", "ticker", "asset", "side", "date", "filed",
              "shares", "price", "amt_lo", "amt_hi", "options", "owner", "note", "url",
              "planned", "added", "cur")


def add_trades(rows: list[dict]) -> list[str]:
    """Dopisuje transakcje. Zwraca identyfikatory tych, których wcześniej NIE było.

    Istniejących nie nadpisujemy: ta sama transakcja przychodzi dwiema drogami
    (dzienny indeks SEC i paczka kwartalna), a pierwsza wersja jest równie dobra
    jak druga. Lista nowych jest potrzebna powiadomieniom.
    """
    if not rows:
        return []
    now = time.time()
    fresh: list[str] = []
    with _write:
        c = conn()
        have = set()
        uids = [r["uid"] for r in rows]
        for i in range(0, len(uids), 800):
            part = uids[i:i + 800]
            q = "select uid from trades where uid in (%s)" % ",".join("?" * len(part))
            have.update(x[0] for x in c.execute(q, part))
        batch = []
        for r in rows:
            if r["uid"] in have:
                continue
            have.add(r["uid"])
            fresh.append(r["uid"])
            batch.append(tuple(
                now if k == "added" else r.get(k, _DEF.get(k)) for k in TRADE_COLS))
        if batch:
            c.executemany(
                f"insert or ignore into trades ({','.join(TRADE_COLS)}) "
                f"values ({','.join('?' * len(TRADE_COLS))})", batch)
            c.commit()
    return fresh


_DEF = {"ticker": "", "asset": "", "filed": "", "shares": None, "price": None,
        "amt_lo": None, "amt_hi": None, "options": 0, "owner": "", "note": "",
        "url": "", "planned": 0, "cur": ""}


def upsert_people(rows: list[dict]) -> None:
    """Zapisuje persony ze źródeł automatycznych. Nowsze dane wygrywają."""
    if not rows:
        return
    now = time.time()
    with _write:
        c = conn()
        c.executemany(
            "insert into people (id, name, cat, role, org, source, extra, updated) "
            "values (?,?,?,?,?,?,?,?) on conflict(id) do update set "
            "name=excluded.name, cat=excluded.cat, role=excluded.role, org=excluded.org, "
            "source=excluded.source, extra=excluded.extra, updated=excluded.updated",
            [(r["id"], r["name"], r["cat"], r.get("role", ""), r.get("org", ""),
              r.get("source", ""), json.dumps(r.get("extra") or {}, ensure_ascii=False), now)
             for r in rows])
        c.commit()


def kv_get(key: str, default=None):
    row = conn().execute("select value from kv where key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except ValueError:
        return default


def kv_set(key: str, value) -> None:
    with _write:
        c = conn()
        c.execute("insert into kv (key, value, at) values (?,?,?) on conflict(key) do update "
                  "set value=excluded.value, at=excluded.at",
                  (key, json.dumps(value, ensure_ascii=False), time.time()))
        c.commit()


def ai_log_add(rodzaj: str, model: str = "", ok: bool = False, limit: bool = False,
               tok_in: int = 0, tok_out: int = 0, usd: float = 0.0) -> None:
    try:
        with _write:
            c = conn()
            c.execute("insert into ai_log values (?,?,?,?,?,?,?,?)",
                      (time.time(), rodzaj, model, int(ok), int(limit), int(tok_in or 0),
                       int(tok_out or 0), float(usd or 0)))
            # rachunek potrzebuje tygodnia — starsze wpisy tylko puchną
            c.execute("delete from ai_log where t < ?", (time.time() - 35 * 86400,))
            c.commit()
    except Exception:  # noqa: BLE001 — rachunek nie może zepsuć odpowiedzi
        pass


def ai_log_od(t: float) -> list[dict]:
    return [dict(r) for r in conn().execute("select * from ai_log where t >= ?", (t,))]


def seen_filter(keys: list[str]) -> set[str]:
    """Które z tych kluczy już przerobiliśmy."""
    out: set[str] = set()
    c = conn()
    for i in range(0, len(keys), 800):
        part = keys[i:i + 800]
        q = "select key from seen where key in (%s)" % ",".join("?" * len(part))
        out.update(x[0] for x in c.execute(q, part))
    return out


def seen_add(keys: list[str]) -> None:
    if not keys:
        return
    now = time.time()
    with _write:
        c = conn()
        c.executemany("insert or ignore into seen (key, at) values (?,?)", [(k, now) for k in keys])
        c.commit()


def stats_get(person: str, max_age: float):
    row = conn().execute("select data, at from stats where person=?", (person,)).fetchone()
    if not row or time.time() - row["at"] > max_age:
        return None
    try:
        return json.loads(row["data"])
    except ValueError:
        return None


def stats_set(person: str, data: dict) -> None:
    with _write:
        c = conn()
        c.execute("insert into stats (person, data, at) values (?,?,?) on conflict(person) "
                  "do update set data=excluded.data, at=excluded.at",
                  (person, json.dumps(data, ensure_ascii=False), time.time()))
        c.commit()


# ------------------------------------------------------------------ odczyt


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn().execute(sql, params)]


def trades_for_tickers(tickers: list[str], since: str, limit: int = 1500) -> list[dict]:
    if not tickers:
        return []
    q = ("select * from trades where ticker in (%s) and date >= ? "
         "order by date desc limit ?") % ",".join("?" * len(tickers))
    return _rows(q, (*tickers, since, limit))


def trades_for_person(person: str, limit: int = 2000, since: str = "") -> list[dict]:
    return _rows("select * from trades where person=? and date >= ? "
                 "order by date desc, filed desc limit ?", (person, since, limit))


def trades_for_people(people: list[str], since: str) -> list[dict]:
    if not people:
        return []
    q = ("select * from trades where person in (%s) and date >= ? "
         "order by date desc") % ",".join("?" * len(people))
    return _rows(q, (*people, since))


def feed(since_filed: str, limit: int = 60, people: list[str] | None = None,
         sides: tuple = ("buy", "sell"), min_amt: float = 0,
         sources: tuple | None = None) -> list[dict]:
    """Najświeższe ZGŁOSZENIA — po dacie ujawnienia, nie transakcji.

    Kongres zgłasza z opóźnieniem do 45 dni, więc sortując po dniu transakcji
    wczorajsze ujawnienie zakupu sprzed miesiąca utonęłoby w środku listy —
    a dla człowieka to jest właśnie wiadomość dnia."""
    extra, params = "", [since_filed]
    if people is not None:
        if not people:
            return []
        extra = " and person in (%s)" % ",".join("?" * len(people))
        params += people
    extra += " and side in (%s)" % ",".join("?" * len(sides))
    params += list(sides)
    if min_amt:
        extra += " and coalesce(amt_hi, amt_lo, 0) >= ?"
        params.append(min_amt)
    if sources:
        extra += " and source in (%s)" % ",".join("?" * len(sources))
        params += list(sources)
    return _rows(f"select * from trades where filed >= ?{extra} and ticker != '' "
                 f"order by filed desc, date desc limit ?", (*params, limit))


def people_rows(ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    out: dict[str, dict] = {}
    for i in range(0, len(ids), 800):
        part = ids[i:i + 800]
        q = "select * from people where id in (%s)" % ",".join("?" * len(part))
        for r in conn().execute(q, part):
            d = dict(r)
            try:
                d["extra"] = json.loads(d.get("extra") or "{}")
            except ValueError:
                d["extra"] = {}
            out[d["id"]] = d
    return out


def activity(since: str, sources: tuple | None = None) -> list[dict]:
    """Aktywność każdej persony od danego dnia: liczby i sumy kupna/sprzedaży."""
    extra, params = "", [since]
    if sources:
        extra = " and source in (%s)" % ",".join("?" * len(sources))
        params += list(sources)
    return _rows(
        "select person, "
        " sum(case when side='buy' then 1 else 0 end) as buys, "
        " sum(case when side='sell' then 1 else 0 end) as sells, "
        " sum(case when side='buy' then (coalesce(amt_lo,0)+coalesce(amt_hi,amt_lo,0))/2 else 0 end) as bought, "
        " sum(case when side='sell' then (coalesce(amt_lo,0)+coalesce(amt_hi,amt_lo,0))/2 else 0 end) as sold, "
        " max(date) as last, max(filed) as last_filed, count(distinct ticker) as tickers "
        f"from trades where date >= ?{extra} and ticker != '' group by person", tuple(params))


def added_since(ts: float, limit: int = 5000) -> list[dict]:
    return _rows("select * from trades where added > ? order by added limit ?", (ts, limit))


def counts() -> dict:
    c = conn()
    out = {"trades": c.execute("select count(*) from trades").fetchone()[0],
           "people": c.execute("select count(*) from people").fetchone()[0]}
    for src, n in c.execute("select source, count(*) from trades group by source"):
        out[f"trades_{src}"] = n
    row = c.execute("select max(filed) from trades").fetchone()
    out["newest_filed"] = row[0] if row else None
    return out


def person_counts(ids: list[str]) -> dict[str, int]:
    if not ids:
        return {}
    q = ("select person, count(*) from trades where person in (%s) group by person"
         % ",".join("?" * len(ids)))
    return {r[0]: r[1] for r in conn().execute(q, ids)}


def trades_by_uids(uids: list[str]) -> list[dict]:
    out: list[dict] = []
    for i in range(0, len(uids), 800):
        part = uids[i:i + 800]
        out += _rows("select * from trades where uid in (%s)" % ",".join("?" * len(part)),
                     tuple(part))
    return out
