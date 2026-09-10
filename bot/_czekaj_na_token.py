"""Czeka, aż telefon właściciela zarejestruje token, i wysyła test powiadomienia.

Plik roboczy — do ręcznego odpalenia przy testach, nie część serwera.
Powód istnienia: token pojawia się dopiero, gdy aplikacja wstanie na telefonie,
a wtedy nie ma sensu prosić kogokolwiek o klikanie „wyślij test". Ten skrypt
pilnuje bazy i wysyła w chwili, gdy jest do czego wysłać.
"""

from __future__ import annotations

import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _linia in io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
                      encoding="utf-8"):
    _linia = _linia.strip()
    if _linia and not _linia.startswith("#") and "=" in _linia:
        _k, _v = _linia.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

import db                      # noqa: E402
import supabase_auth           # noqa: E402
from notify import engine, push, store   # noqa: E402

CZEKAJ_MAX = float(os.environ.get("CZEKAJ_MAX_S", "1500"))


def main() -> int:
    uid = supabase_auth.owner_user_id()
    if not uid:
        print("BRAK konta wlasciciela")
        return 1

    koniec = time.time() + CZEKAJ_MAX
    tokeny: list[str] = []
    while time.time() < koniec:
        tokeny = store.tokeny(uid)
        if tokeny:
            break
        time.sleep(15)

    if not tokeny:
        print("TIMEOUT: telefon nie zarejestrowal zadnego urzadzenia")
        return 2

    print(f"URZADZENIE ZAREJESTROWANE ({len(tokeny)}): {tokeny[0][:26]}...")

    # Test idzie tą samą drogą, co prawdziwy news o spółce z portfela.
    poszlo = engine.powiadom(
        uid, "news",
        "NVDA — pozytywny news",
        "Spółka podniosła prognozę przychodów na kolejny kwartał o 12% względem "
        "konsensusu analityków (SEC EDGAR · siła 91/100)",
        dedup_key=f"test-push:{int(time.time())}",
        symbol="NVDA",
        meta={"test": True, "strength": 91, "source": "sec_edgar"},
    )
    print("zapisane w skrzynce:", poszlo)

    # Osobno, żeby zobaczyć ILE urządzeń realnie przyjęło wysyłkę.
    przyjete = push.wyslij(tokeny, "NVDA — pozytywny news",
                           "To jest test. Tak wygląda powiadomienie o newsie "
                           "dotyczącym spółki z Twojego portfela.",
                           {"kind": "news", "symbol": "NVDA", "test": True})
    print("Expo przyjelo wysylek:", przyjete)
    return 0 if przyjete else 3


if __name__ == "__main__":
    db.set_current_user(supabase_auth.owner_user_id())
    sys.exit(main())
