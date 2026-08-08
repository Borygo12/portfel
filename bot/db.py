"""Połączenie z bazą Supabase (Postgres) — z rozdziałem danych po stronie bazy.

Dlaczego nie zwykłe `WHERE user_id = ...` w każdym zapytaniu:
jedno zapomniane miejsce w 67 endpointach pokazuje komuś cudzy portfel. Zamiast
ufać, że nikt nigdy nie zapomni, łączymy się rolą `authenticated` i podajemy
tożsamość w `request.jwt.claims`. Od tego momentu polityki RLS z migracji 0002
odsiewają cudze wiersze **w silniku bazy**. `select * from cash_ops` zwraca
wyłącznie operacje pytającego, nawet gdy w kodzie nie ma żadnego filtra.

Dwa tryby połączenia:

* `user_scope(user_id)` — wszystko, co robi się „w imieniu" zalogowanego.
  Domyślny tryb dla żądań z aplikacji.
* `service_scope()` — zadania serwera bez użytkownika: pobieranie notowań do
  wspólnego cache, bot newsowy. Omija RLS, więc używamy go wyłącznie tam, gdzie
  naprawdę nie ma czyjegoś kontekstu, i nigdy do danych portfela.

Poza transakcją ustawienia znikają (`set_config(..., true)` działa lokalnie),
więc połączenie wracające do puli nie wynosi ze sobą cudzej tożsamości.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
import threading

log = logging.getLogger("db")

# Adres bazy: Supabase → Project Settings → Database → Connection string → "Transaction pooler".
# Pooler (port 6543) zamiast bezpośredniego 5432, bo darmowy plan ma mało slotów,
# a serwer w chmurze potrafi je zająć wszystkie po kilku restartach.
DB_URL = (os.environ.get("SUPABASE_DB_URL") or "").strip()

# Rola nadawana w transakcji użytkownika. `authenticated` to standardowa rola
# Supabase, na którą napisane są polityki RLS.
_USER_ROLE = "authenticated"

_pool = None
_pool_lock = threading.Lock()

# Kto jest „bieżącym użytkownikiem" w tym żądaniu. ContextVar, a nie zmienna
# globalna, bo uvicorn obsługuje żądania współbieżnie i globalna wyciekałaby
# tożsamość między nimi.
_current_user: contextvars.ContextVar[str] = contextvars.ContextVar("current_user", default="")


class NotConfigured(RuntimeError):
    """Brak SUPABASE_DB_URL — serwer nie ma gdzie trzymać danych."""


def configured() -> bool:
    return bool(DB_URL)


def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        if not DB_URL:
            raise NotConfigured(
                "Brak SUPABASE_DB_URL. Skopiuj adres z Supabase → Project Settings → "
                "Database → Connection string → Transaction pooler i wpisz go do .env "
                "(albo do zmiennych środowiskowych w Railway)."
            )
        from psycopg_pool import ConnectionPool
        from psycopg.rows import dict_row

        def _configure(con):
            """Wyłącza przygotowywanie zapytań — wymóg poolera Supabase.

            psycopg domyślnie po piątym wykonaniu tego samego zapytania zamienia
            je w „prepared statement" przypisany do konkretnego połączenia
            serwerowego. Pooler w trybie transakcyjnym przerzuca każdą transakcję
            na dowolne wolne połączenie, więc następne wywołanie trafia tam, gdzie
            tego zapytania nikt nie przygotował — i wywala się błędem
            `prepared statement "_pg3_N" does not exist`.
            """
            con.prepare_threshold = None

        _pool = ConnectionPool(
            DB_URL,
            min_size=1,
            # Darmowy plan Supabase ma ograniczoną liczbę połączeń, a przy 25
            # użytkownikach i tak nic tu nie stoi w kolejce dłużej niż chwilę.
            max_size=int(os.environ.get("DB_POOL_SIZE", "8")),
            kwargs={"row_factory": dict_row, "autocommit": False},
            configure=_configure,
            open=True,
            timeout=15,
        )
        log.info("Pula połączeń do Supabase gotowa (max %s)", _pool.max_size)
        return _pool


def set_current_user(user_id: str) -> None:
    """Ustawia tożsamość dla dalszych zapytań w tym żądaniu."""
    _current_user.set(user_id or "")


def current_user() -> str:
    return _current_user.get()


@contextlib.contextmanager
def user_scope(user_id: str = ""):
    """Transakcja w imieniu użytkownika — RLS przycina wyniki do jego wierszy."""
    uid = user_id or current_user()
    if not uid:
        raise PermissionError("Zapytanie o dane użytkownika bez ustalonej tożsamości.")
    pool = _get_pool()
    with pool.connection() as con:
        with con.transaction():
            with con.cursor() as cur:
                # Kolejność ma znaczenie: najpierw oświadczamy, kim jesteśmy,
                # potem schodzimy do roli, która podlega RLS. Odwrotnie nie
                # mielibyśmy już prawa ustawić claimów.
                cur.execute(
                    "select set_config('request.jwt.claims', %s, true)",
                    ('{"sub":"%s","role":"%s"}' % (uid, _USER_ROLE),),
                )
                cur.execute(f"set local role {_USER_ROLE}")
                yield cur


@contextlib.contextmanager
def service_scope():
    """Transakcja serwera — bez RLS. Tylko dane wspólne, nigdy cudzy portfel."""
    pool = _get_pool()
    with pool.connection() as con:
        with con.transaction():
            with con.cursor() as cur:
                yield cur


# ------------------------------------------------------------------ skróty

def query(sql: str, params: tuple = (), user_id: str = "") -> list:
    with user_scope(user_id) as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else []


def execute(sql: str, params: tuple = (), user_id: str = "") -> None:
    with user_scope(user_id) as cur:
        cur.execute(sql, params)


def executemany(sql: str, rows: list, user_id: str = "") -> None:
    if not rows:
        return
    with user_scope(user_id) as cur:
        cur.executemany(sql, rows)


def shared_query(sql: str, params: tuple = ()) -> list:
    """Odczyt wspólnego cache rynkowego — bez kontekstu użytkownika."""
    with service_scope() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else []


def shared_execute(sql: str, params: tuple = ()) -> None:
    with service_scope() as cur:
        cur.execute(sql, params)


def shared_executemany(sql: str, rows: list) -> None:
    if not rows:
        return
    with service_scope() as cur:
        cur.executemany(sql, rows)


def healthy() -> dict:
    """Czy baza odpowiada — używane przez /api/health i ekran diagnostyczny."""
    if not configured():
        return {"ok": False, "why": "brak SUPABASE_DB_URL"}
    try:
        with service_scope() as cur:
            cur.execute("select 1 as ok")
            cur.fetchone()
        return {"ok": True}
    except Exception as e:                      # noqa: BLE001 — raportujemy każdy błąd
        return {"ok": False, "why": str(e)[:200]}
