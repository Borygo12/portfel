"""Kto ma dostać powiadomienie i czym ono do niego pojedzie.

Jedno wejście dla całej reszty serwera: `powiadom(...)`. Kolejność w środku jest
celowa i wygląda tak:

1. **skrzynka w bazie** — zapis jest pierwszy, bo to on decyduje o duplikacie.
   Gdy `dedup_key` już istnieje, `dopisz` zwraca 0 i NIE wysyłamy nic dalej.
   Dzięki temu ten sam news z dwóch źródeł dzwoni raz, a restart serwera
   w środku dnia nie powtarza przypomnienia o wynikach;
2. **kanały** — push i e-mail, każdy w swoim `try`. Awaria jednego nie zabiera
   drugiego, a żadna nie może wywrócić pętli bota.

Skrzynka jest zawsze. Kanały są dodatkiem — gdy Expo leży, a SMTP nie jest
skonfigurowany, powiadomienie po prostu czeka w aplikacji.
"""

from __future__ import annotations

import logging

from . import mail, push, store

log = logging.getLogger("notify.engine")


def powiadom(user_id: str, kind: str, title: str, body: str,
             dedup_key: str, symbol: str = "", meta: dict | None = None,
             link: str = "") -> bool:
    """Jedno powiadomienie dla jednego konta. False = duplikat, nic nie poszło."""
    if not user_id or not dedup_key:
        return False

    try:
        wpis = store.dopisz(user_id, kind, title, body, symbol, meta, dedup_key)
    except Exception as e:  # noqa: BLE001
        log.warning("Nie zapisano powiadomienia do skrzynki: %s", e)
        return False
    if not wpis:
        return False                      # już to wysyłaliśmy

    try:
        ust = store.ustawienia(user_id)
    except Exception as e:  # noqa: BLE001
        log.warning("Nie odczytano ustawień powiadomień: %s", e)
        return True                       # w skrzynce jest, i tyle

    dane = {"kind": kind, "symbol": symbol or "", "id": wpis}

    if ust["push_enabled"]:
        push.wyslij_do(user_id, title, body, dane)

    if ust["email_enabled"]:
        try:
            adres = store.adres_email(user_id)
            if adres:
                mail.wyslij(adres, title, body, link)
        except Exception as e:  # noqa: BLE001
            log.warning("Kanał e-mail zawiódł: %s", e)

    return True
