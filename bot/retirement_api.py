"""API kont emerytalnych — `/api/retirement/…`.

Podział na darmowe i płatne jest tu inny niż w reszcie aplikacji i warto go
mieć w głowie:

* **Zasady i limity są darmowe i publiczne** (`/meta`). To wiedza, nie funkcja —
  ktoś, kto dopiero rozważa IKE, ma się tu dowiedzieć, jak ono działa, zanim
  założy konto u nas czy u brokera.
* **Oznaczenie rachunku jako IKE/IKZE jest darmowe** (wymaga tylko konta). To
  porządek w danych, tak samo jak nazwanie portfela.
* **Liczby na Twoich rachunkach są płatne** (`/overview`). Konto bez premium
  dostaje w ich miejsce dane przykładowe z flagą `demo` — ekran rysuje je
  zamglone. Prawdziwe kwoty w ogóle nie opuszczają serwera, więc rozmycia nie
  da się „zdjąć" w przeglądarce.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

import retirement
import supabase_auth as sa
from account_api import require_login, viewer

log = logging.getLogger("retirement_api")

router = APIRouter()

FEATURE = "tools.retirement"


def _profil(rok_ur: int = 0, stawka: int = 12, jdg: int = 0) -> dict:
    """Ustawienia z aplikacji: rok urodzenia, stawka PIT w procentach, działalność.

    Przychodzą w adresie, a nie z bazy — to trzy liczby trzymane w ustawieniach
    aplikacji (i synchronizowane z kontem razem z resztą preferencji), więc
    osobna tabela byłaby tylko drugim miejscem, w którym mogą się rozjechać.
    """
    rok = int(rok_ur or 0)
    return {
        "rok_ur": rok if 1920 <= rok <= 2015 else None,
        "stawka": {12: 0.12, 19: 0.19, 32: 0.32}.get(int(stawka or 12), 0.12),
        "jdg": bool(jdg),
    }


@router.get("/api/retirement/meta")
def meta(rok_ur: int = 0, stawka: int = 12, jdg: int = 0):
    """Zasady, limity i przykładowe konto — dla każdego, także bez logowania."""
    p = _profil(rok_ur, stawka, jdg)
    return {**retirement.meta(p), "przyklad": retirement.demo(p)}


@router.get("/api/retirement/overview")
def overview(rok_ur: int = 0, stawka: int = 12, jdg: int = 0,
             v: sa.Viewer = Depends(require_login)):
    """Konta emerytalne zalogowanego. Bez premium: przykład + to, co rozpoznaliśmy."""
    p = _profil(rok_ur, stawka, jdg)
    wykryte = retirement.wykryte()
    if not v.premium:
        # Lista rachunków jest prawdziwa także tutaj: oznaczanie IKE/IKZE jest
        # darmowe, a numery własnych rachunków to nie są liczby pod kłódką.
        try:
            rachunki = retirement.konta()
        except Exception:  # noqa: BLE001
            rachunki = []
        return {**retirement.demo(p), "konta": rachunki, "premium": False, "wykryte": wykryte}
    try:
        dane = retirement.przeglad(p)
    except Exception as e:  # noqa: BLE001
        log.exception("Przegląd kont emerytalnych")
        raise HTTPException(503, f"Nie udało się policzyć kont emerytalnych: {str(e)[:160]}")
    return {**dane, "premium": True, "wykryte": wykryte}


@router.post("/api/retirement/account")
async def set_account(request: Request, _v: sa.Viewer = Depends(require_login)):
    """Ręczne oznaczenie rachunku: {"account": "…", "kind": "ike" | "ikze" | "oki" | ""}."""
    from portfolio import engine as pf_engine
    from portfolio import store as pf_store

    body = (await request.json()) or {}
    konto = str(body.get("account") or "").strip()
    kind = str(body.get("kind") or "").strip().lower()
    if not konto:
        raise HTTPException(400, "Brak numeru rachunku")
    if kind not in ("", *retirement.KINDS):
        raise HTTPException(400, "Nieznany rodzaj konta")
    if not pf_store.set_account_kind(konto, kind, "user"):
        raise HTTPException(503, "Baza nie jest jeszcze gotowa na konta emerytalne "
                                 "(migracja 0011). Spróbuj za chwilę.")
    pf_engine.invalidate()
    return {"ok": True, "account": konto, "kind": kind}


@router.post("/api/retirement/asset")
async def set_asset(request: Request, _v: sa.Viewer = Depends(require_login)):
    """To samo dla majątku dopisanego ręcznie albo z odczytu AI: {"id", "kind"}."""
    body = (await request.json()) or {}
    aid = str(body.get("id") or "").strip()
    kind = str(body.get("kind") or "").strip().lower()
    if not aid:
        raise HTTPException(400, "Brak identyfikatora aktywa")
    if not retirement.ustaw_typ_aktywa(aid, kind):
        raise HTTPException(503, "Baza nie jest jeszcze gotowa na konta emerytalne "
                                 "(migracja 0011). Spróbuj za chwilę.")
    return {"ok": True, "id": aid, "kind": kind if kind in retirement.KINDS else ""}
