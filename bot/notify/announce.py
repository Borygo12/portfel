"""Ogłoszenie do wszystkich, którzy mają włączone powiadomienia.

Jednorazowa wiadomość „co nowego w aplikacji": trafia do skrzynki w aplikacji
i na telefon. Celowo BEZ e-maila — zgoda na e-mail dotyczyła powiadomień
o własnych spółkach, a nie nowości produktowych.

Odbiorcy to konta, które mają zarejestrowane urządzenie i nie wyłączyły
powiadomień na telefon. Kto ich nie chce, ten ogłoszenia nie dostanie —
również w skrzynce.

Uruchamiane ręcznie, z komputera właściciela:

    python -m notify.announce "Tytuł" "Treść" klucz-ogloszenia [--wyslij]

Bez `--wyslij` tylko liczy odbiorców. `klucz-ogloszenia` chroni przed
podwójną wysyłką: drugie uruchomienie z tym samym kluczem nikogo nie zaczepi.
"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger("notify.announce")


def odbiorcy() -> list[str]:
    import db
    rows = db.shared_query(
        "select distinct t.user_id from push_tokens t "
        "left join notification_prefs p on p.user_id = t.user_id "
        "where coalesce(p.push_enabled, true)")
    return [str(r["user_id"]) for r in rows]


def oglos(tytul: str, tresc: str, klucz: str, dane: dict | None = None,
          wyslij: bool = False) -> dict:
    """Rozsyła ogłoszenie. Zwraca {odbiorcy, w_skrzynce, urzadzenia}."""
    from . import push, store

    konta = odbiorcy()
    wynik = {"odbiorcy": len(konta), "w_skrzynce": 0, "urzadzenia": 0}
    if not wyslij:
        return wynik
    for uid in konta:
        try:
            wpis = store.dopisz(uid, "announce", tytul, tresc, meta=dane or {},
                                dedup_key=f"announce:{klucz}")
        except Exception as e:  # noqa: BLE001
            log.warning("Ogłoszenie dla %s nie zapisało się: %s", uid, e)
            continue
        if not wpis:
            continue                      # to konto już je dostało
        wynik["w_skrzynce"] += 1
        wynik["urzadzenia"] += push.wyslij_do(
            uid, tytul, tresc, {"kind": "announce", "id": wpis, **(dane or {})})
    return wynik


if __name__ == "__main__":
    import os

    # te same klucze co serwer — adres bazy leży w bot/.env
    tu = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        for linia in open(os.path.join(tu, ".env"), encoding="utf-8"):
            if "=" in linia and not linia.lstrip().startswith("#"):
                k, v = linia.strip().split("=", 1)
                os.environ.setdefault(k, v.strip().strip('"'))
    except OSError:
        pass
    # `db` czyta adres bazy przy imporcie, a pakiet `notify` zdążył go już
    # zaimportować — zanim wczytaliśmy plik z kluczami
    import db
    db.DB_URL = db.DB_URL or (os.environ.get("SUPABASE_DB_URL") or "").strip()

    arg = [a for a in sys.argv[1:] if a != "--wyslij"]
    if len(arg) != 3:
        sys.exit(__doc__)
    print(oglos(arg[0], arg[1], arg[2], {"open": "emerytura"}, wyslij="--wyslij" in sys.argv))
