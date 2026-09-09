"""Baza powiadomień: ustawienia, tokeny urządzeń, skrzynka, symbole użytkownika.

Dwa tryby dostępu i to nie jest przypadek:

* funkcje z końcówką `_moje` działają W IMIENIU zalogowanego (RLS przycina
  wiersze w bazie — patrz `db.user_scope`). Tak chodzą endpointy z aplikacji;
* reszta łączy się rolą serwisową, bo silnik powiadomień odpala się w reakcji na
  newsa, kiedy NIKT nie jest zalogowany. Takie funkcje zawsze biorą `user_id`
  jawnym argumentem — nie ma tu „bieżącego użytkownika", którego można pomylić.
"""

from __future__ import annotations

import json
import logging

import db

log = logging.getLogger("notify.store")

# Domyślne ustawienia — te same, co w migracji 0005. Powtórzone tutaj, bo ktoś,
# kto nigdy nie dotknął ekranu powiadomień, NIE MA wiersza w bazie, a i tak musi
# dostać sensowną odpowiedź z API.
DOMYSLNE = {
    "news_mode": "off",
    "earnings_daily": True,
    "earnings_weekly": True,
    "push_enabled": True,
    "email_enabled": False,
    "email_asked": False,
}

TRYBY = ("off", "all", "strong")


def _wiersz_na_ustawienia(r: dict | None) -> dict:
    if not r:
        return dict(DOMYSLNE)
    return {
        "news_mode": r.get("news_mode") or "off",
        "earnings_daily": bool(r.get("earnings_daily")),
        "earnings_weekly": bool(r.get("earnings_weekly")),
        "push_enabled": bool(r.get("push_enabled")),
        "email_enabled": bool(r.get("email_enabled")),
        "email_asked": r.get("email_asked_at") is not None,
    }


# ------------------------------------------------------------------ ustawienia


def ustawienia(user_id: str) -> dict:
    """Ustawienia konkretnego konta — czytane rolą serwisową (silnik w tle)."""
    rows = db.shared_query(
        "select * from notification_prefs where user_id = %s", (user_id,))
    return _wiersz_na_ustawienia(rows[0] if rows else None)


def ustawienia_moje() -> dict:
    rows = db.query("select * from notification_prefs")
    return _wiersz_na_ustawienia(rows[0] if rows else None)


def zapisz_moje(zmiany: dict) -> dict:
    """Zapisuje zmienione pola zalogowanego. Nieznane klucze pomijamy."""
    pola, wartosci = [], []
    for klucz in ("news_mode", "earnings_daily", "earnings_weekly",
                  "push_enabled", "email_enabled"):
        if klucz in zmiany:
            pola.append(klucz)
            wartosci.append(zmiany[klucz])
    # „Pytaliśmy o e-mail" to nie preferencja, tylko ślad rozmowy — ustawia się
    # znacznikiem czasu, żeby pytanie nie wracało przy każdym uruchomieniu.
    pytano = bool(zmiany.get("email_asked"))

    if not pola and not pytano:
        return ustawienia_moje()

    kolumny = ", ".join(pola)
    znaki = ", ".join(["%s"] * len(pola))
    aktualizacja = ", ".join(f"{k} = excluded.{k}" for k in pola)
    if pytano:
        kolumny += (", " if kolumny else "") + "email_asked_at"
        znaki += (", " if znaki else "") + "now()"
        aktualizacja += (", " if aktualizacja else "") + "email_asked_at = now()"

    db.execute(
        f"insert into notification_prefs (user_id, {kolumny}, updated_at) "
        f"values (auth.uid(), {znaki}, now()) "
        f"on conflict (user_id) do update set {aktualizacja}, updated_at = now()",
        tuple(wartosci),
    )
    return ustawienia_moje()


# --------------------------------------------------------------- tokeny urządzeń


def zapisz_token_moj(token: str, platforma: str = "") -> None:
    """Rejestruje urządzenie zalogowanego.

    `on conflict (token)` przepisuje token na NOWE konto: gdy ktoś wyloguje się
    i zaloguje jako ktoś inny na tym samym telefonie, powiadomienia mają iść do
    tego, kto jest zalogowany teraz — a nie do poprzednika.
    """
    db.execute(
        "insert into push_tokens (token, user_id, platform, last_seen_at) "
        "values (%s, auth.uid(), %s, now()) "
        "on conflict (token) do update set user_id = excluded.user_id, "
        "platform = excluded.platform, last_seen_at = now()",
        (token, platforma or ""),
    )


def usun_token_moj(token: str) -> None:
    db.execute("delete from push_tokens where token = %s", (token,))


def tokeny(user_id: str) -> list[str]:
    rows = db.shared_query(
        "select token from push_tokens where user_id = %s", (user_id,))
    return [r["token"] for r in rows]


def wyrzuc_token(token: str) -> None:
    """Expo powiedziało, że urządzenia już nie ma (odinstalowana aplikacja)."""
    db.shared_execute("delete from push_tokens where token = %s", (token,))


# ------------------------------------------------------------------- skrzynka


def dopisz(user_id: str, kind: str, title: str, body: str,
           symbol: str = "", meta: dict | None = None, dedup_key: str = "") -> int:
    """Wkłada powiadomienie do skrzynki. Zwraca id albo 0, gdy to duplikat.

    Zero to normalna odpowiedź, a nie błąd: ten sam news wpada czasem dwoma
    źródłami naraz. `on conflict do nothing` sprawia, że telefon dzwoni raz.
    """
    # `%s::jsonb` zamiast gołego `%s`: sterownik wysyła słownik jako TEKST, a bez
    # jawnego rzutowania Postgres nie wie, że ma z niego zrobić jsonb, i odmawia
    # wstawienia. Rzutowanie w zapytaniu jest tu pewniejsze niż poleganie na tym,
    # którą wersję adaptera akurat zainstalowano.
    rows = db.shared_query(
        "insert into notifications (user_id, kind, title, body, symbol, meta, dedup_key) "
        "values (%s, %s, %s, %s, %s, %s::jsonb, %s) "
        "on conflict (user_id, dedup_key) do nothing returning id",
        (user_id, kind, title[:200], body[:1000], (symbol or "")[:40],
         json.dumps(meta or {}, ensure_ascii=False), dedup_key[:200]),
    )
    return int(rows[0]["id"]) if rows else 0


def skrzynka_moja(limit: int = 50) -> dict:
    rows = db.query(
        "select id, kind, title, body, symbol, meta, read_at, created_at "
        "from notifications order by created_at desc limit %s",
        (min(200, max(1, limit)),))
    nieprzeczytane = db.query(
        "select count(*) as n from notifications where read_at is null")
    return {
        "items": [{
            "id": r["id"], "kind": r["kind"], "title": r["title"], "body": r["body"],
            "symbol": r["symbol"] or "", "meta": r["meta"] or {},
            "read": r["read_at"] is not None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else "",
        } for r in rows],
        "unread": int(nieprzeczytane[0]["n"]) if nieprzeczytane else 0,
    }


def oznacz_przeczytane_moje(ids: list[int] | None = None) -> None:
    if ids:
        db.execute("update notifications set read_at = now() "
                   "where read_at is null and id = any(%s)", (list(ids),))
    else:
        db.execute("update notifications set read_at = now() where read_at is null")


# ------------------------------------------------- symbole, które kogoś obchodzą


def zapisz_symbole_moje(pozycje: set[str], obserwowane: set[str]) -> None:
    """Odświeża cache „co mnie obchodzi" dla zalogowanego.

    Kasujemy i wstawiamy od nowa zamiast dopisywać różnicę: lista ma kilkanaście
    pozycji, a sprzedaną spółkę trzeba usunąć równie pewnie, jak dopisać nową.
    """
    wiersze = [(s, "position") for s in sorted(pozycje) if s]
    wiersze += [(s, "watch") for s in sorted(obserwowane) if s and s not in pozycje]
    db.execute("delete from user_symbols")
    if wiersze:
        db.executemany(
            "insert into user_symbols (user_id, symbol, relation) "
            "values (auth.uid(), %s, %s) "
            "on conflict (user_id, symbol) do update set relation = excluded.relation, "
            "updated_at = now()",
            wiersze,
        )


def kogo_obchodzi(symbole: set[str]) -> list[dict]:
    """Kto ma albo obserwuje którykolwiek z tych symboli. Rolą serwisową."""
    czyste = sorted({(s or "").upper() for s in symbole if s})
    if not czyste:
        return []
    return db.shared_query(
        "select user_id, symbol, relation from user_symbols where symbol = any(%s)",
        (czyste,),
    )


def symbole_uzytkownika(user_id: str) -> list[dict]:
    return db.shared_query(
        "select symbol, relation from user_symbols where user_id = %s order by symbol",
        (user_id,))


def konta_z_powiadomieniami(pole: str) -> list[str]:
    """Konta, które mają włączony dany rodzaj powiadomień o wynikach.

    Uwaga na domyślne wartości: kto nigdy nie dotknął ustawień, NIE MA wiersza,
    a mimo to `earnings_daily` jest domyślnie włączone. Dlatego bierzemy też
    konta bez wiersza — ale tylko takie, które mają jakiekolwiek spółki, więc
    nie zaczepiamy ludzi, dla których i tak nie byłoby o czym pisać.
    """
    if pole not in ("earnings_daily", "earnings_weekly"):
        raise ValueError(f"nieznany rodzaj powiadomień: {pole}")
    rows = db.shared_query(
        "select distinct s.user_id from user_symbols s "
        "left join notification_prefs p on p.user_id = s.user_id "
        f"where coalesce(p.{pole}, true)"
    )
    return [str(r["user_id"]) for r in rows]


def adres_email(user_id: str) -> str:
    rows = db.shared_query("select email from profiles where id = %s", (user_id,))
    return (rows[0]["email"] or "").strip() if rows else ""


def tylko_premium(user_ids: list[str]) -> set[str]:
    """Odsiewa konta bez ważnego premium — jednym zapytaniem, nie po jednym.

    Powiadomienia są funkcją płatną, a rozsyłka leci w reakcji na newsa, więc
    pytanie o uprawnienia raz na konto (`supabase_auth.entitlement`) oznaczałoby
    kilkadziesiąt wywołań HTTP na jeden komunikat. Tu wystarczy jeden `select`.

    Właściciel przechodzi zawsze — jego premium bierze się z adresu e-mail,
    a nie z wiersza w `entitlements`, więc bez tego wyjątku sam nie dostałby
    ani jednego powiadomienia z własnej usługi.
    """
    czyste = [u for u in {str(u) for u in user_ids} if u]
    if not czyste:
        return set()

    rows = db.shared_query(
        "select distinct user_id from entitlements "
        "where user_id = any(%s) and product = 'premium' "
        "and (expires_at is null or expires_at > now())",
        (czyste,),
    )
    uprawnieni = {str(r["user_id"]) for r in rows}

    import supabase_auth
    if supabase_auth.OWNER_EMAIL:
        wlasciciel = db.shared_query(
            "select id from profiles where lower(email) = %s and id = any(%s)",
            (supabase_auth.OWNER_EMAIL, czyste))
        uprawnieni |= {str(r["id"]) for r in wlasciciel}
    return uprawnieni
