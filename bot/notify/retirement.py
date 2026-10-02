"""Przypomnienie o niewykorzystanym limicie IKE i IKZE — przed końcem roku.

Limit wpłat przepada 31 grudnia i nie da się go nadrobić w styczniu. To jedyne
powiadomienie w aplikacji, które przypomina o pieniądzach leżących na stole,
więc wysyłamy je rzadko i tylko wtedy, gdy jest o czym: cztery razy w roku,
do kont, którym coś z limitu zostało.

Terminy dobrane pod przelew: wpłata musi ZAKSIĘGOWAĆ się u brokera do końca
roku, więc ostatnie przypomnienie wychodzi 27 grudnia, a nie w sylwestra.
"""

from __future__ import annotations

import datetime as dt
import logging

from . import engine, store

log = logging.getLogger("notify.retirement")

#: (miesiąc, dzień) — kiedy przypominamy
TERMINY = ((11, 15), (12, 1), (12, 15), (12, 27))

#: poniżej tej kwoty nie zawracamy głowy — limit jest praktycznie wykorzystany
MINIMUM = 200.0


def czy_dzis(dzien: dt.date) -> bool:
    return (dzien.month, dzien.day) in TERMINY


def _konta_emerytalne() -> list[str]:
    """Konta, które mają cokolwiek oznaczone jako IKE albo IKZE."""
    import db
    rows = db.shared_query(
        "select distinct user_id from accounts where kind in ('ike', 'ikze') "
        "union select distinct user_id from retirement_accounts where kind in ('ike', 'ikze')")
    return [str(r["user_id"]) for r in rows]


def _wylaczyli(user_ids: list[str]) -> set[str]:
    import db
    if not user_ids:
        return set()
    try:
        rows = db.shared_query(
            "select user_id from notification_prefs "
            "where user_id = any(%s) and not retirement_limit", (user_ids,))
    except Exception as e:  # noqa: BLE001 — brak kolumny = nikt nie wyłączył
        log.info("retirement_limit niedostępne: %s", e)
        return set()
    return {str(r["user_id"]) for r in rows}


def _profil(uid: str) -> dict:
    """Stawka PIT i działalność z ustawień zsynchronizowanych z kontem."""
    import supabase_sync

    ust = supabase_sync.get_settings(uid) or {}

    def osoba(przedrostek: str) -> dict:
        try:
            stawka = int(str(ust.get(f"{przedrostek}stawka") or 12))
        except ValueError:
            stawka = 12
        return {"rok_ur": None, "jdg": str(ust.get(f"{przedrostek}jdg") or "0") == "1",
                "stawka": {12: 0.12, 19: 0.19, 32: 0.32}.get(stawka, 0.12)}

    p = osoba("emerytura.")
    p["m"] = osoba("emerytura.m.")
    return p


def _zl(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ")


def tresc(pozostale: list[dict], dni: int) -> tuple[str, str] | None:
    """(tytuł, treść) albo None, gdy nie ma o czym pisać."""
    zostalo = [p for p in pozostale if p["zostalo"] >= MINIMUM]
    if not zostalo:
        return None

    def nazwa(p: dict) -> str:
        return p["typ"].upper() + (" małżonka" if p["wlasciciel"] else "")

    czesci = [f"{nazwa(p)}: {_zl(p['zostalo'])} zł" for p in zostalo]
    ulga = sum(p["zostalo"] * p["stawka"] for p in zostalo if p["typ"] == "ikze")
    dni_txt = "1 dzień" if dni == 1 else f"{dni} dni"

    if len(zostalo) == 1:
        tytul = f"Zostało {_zl(zostalo[0]['zostalo'])} zł limitu {nazwa(zostalo[0])} i {dni_txt}"
    else:
        tytul = f"Limity emerytalne przepadają za {dni_txt}"
    body = ("Do wpłaty w tym roku — " + ", ".join(czesci) + ". "
            "Niewykorzystany limit nie przechodzi na kolejny rok.")
    if ulga >= 50:
        body += f" Dopłata do IKZE to około {_zl(ulga)} zł zwrotu w PIT."
    body += " Przelew musi zaksięgować się u brokera przed 31 grudnia."
    return tytul, body


def przypomnij(dzien: str = "", wymus: bool = False) -> int:
    """Rozsyła przypomnienia. `wymus` pomija kalendarz — do ręcznego testu."""
    import db
    import retirement as em

    dzis = dt.date.fromisoformat(dzien) if dzien else dt.date.today()
    if not wymus and not czy_dzis(dzis):
        return 0
    dni = (dt.date(dzis.year, 12, 31) - dzis).days

    konta = _konta_emerytalne()
    konta = sorted(store.tylko_premium(konta) - _wylaczyli(konta))
    wyslane = 0
    for uid in konta:
        # Dane portfela czytamy w imieniu tego konta — RLS przytnie resztę.
        db.set_current_user(uid)
        try:
            wynik = tresc(em.do_wplaty(_profil(uid)), dni)
        except Exception as e:  # noqa: BLE001
            log.warning("Limit konta %s: %s", uid, e)
            continue
        finally:
            db.set_current_user("")
        if not wynik:
            continue
        if engine.powiadom(uid, "retirement_limit", wynik[0], wynik[1],
                           dedup_key=f"emlimit:{dzis.isoformat()}",
                           meta={"date": dzis.isoformat(), "dni": dni},
                           link="/narzedzia"):
            wyslane += 1
    log.info("Przypomnienie o limicie IKE/IKZE (%s) — powiadomiono %s kont", dzis, wyslane)
    return wyslane
