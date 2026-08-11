"""Konto, premium i synchronizacja — endpointy wspólne dla telefonu i panelu web.

Router wpinany w `dashboard.py`. Trzymamy to osobno, bo dashboard i tak jest długi,
a ta część ma zupełnie inne zależności niż reszta panelu.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

import premium
import supabase_auth as sa
import supabase_sync as sync

router = APIRouter()


def viewer(request: Request) -> sa.Viewer:
    """Zależność FastAPI: kto pyta. Nigdy nie rzuca — brak konta to też odpowiedź."""
    return sa.viewer_from_request(request)


def require_login(v: sa.Viewer = Depends(viewer)) -> sa.Viewer:
    if not v.logged_in:
        raise HTTPException(401, "Zaloguj się, żeby użyć tej funkcji")
    return v


def require_premium(feature_id: str):
    """Fabryka zależności dla endpointów płatnych.

    Odpowiedź 402 niesie identyfikator funkcji, więc klient wie, którą stronę
    sprzedażową otworzyć — nie musi tego zgadywać z adresu.
    """
    def dep(v: sa.Viewer = Depends(viewer)) -> sa.Viewer:
        if not v.premium:
            raise HTTPException(
                402,
                {"error": "premium_required", "feature": feature_id,
                 "message": "Ta funkcja jest częścią wersji premium"},
            )
        return v
    return dep


# --------------------------------------------------------------------- konto


@router.get("/api/auth/config")
def auth_config():
    """Adres projektu i klucz publiczny — panel web pobiera to zamiast mieć wklejone."""
    return sa.public_config()


@router.get("/api/me")
def me(v: sa.Viewer = Depends(viewer)):
    return v.to_json()


@router.post("/api/me/refresh")
def me_refresh(request: Request, v: sa.Viewer = Depends(viewer)):
    """Wymusza ponowny odczyt uprawnień — po zakupie nie chcemy czekać minuty."""
    if v.user_id:
        sa.forget(v.user_id)
        v = sa.viewer_from_request(request)     # drugie przejście trafia już do bazy
    return v.to_json()


@router.delete("/api/me")
def me_delete(v: sa.Viewer = Depends(require_login)):
    """Kasuje konto razem z całym portfelem. Nieodwracalnie.

    Wymóg App Store („Account Deletion"): apka, w której da się założyć konto,
    musi umieć je skasować bez pisania maili i bez wychodzenia do przeglądarki.
    Kasujemy naprawdę wszystko — kaskada w bazie zabiera operacje, pozycje,
    ustawienia i obserwowane; nie zostawiamy „konta zawieszonego".

    Konta właściciela świadomie nie da się skasować tym przyciskiem: to samo
    konto trzyma dane panelu, a jedno przypadkowe kliknięcie wyczyściłoby
    produkcję bez możliwości cofnięcia.
    """
    if not v.user_id:
        raise HTTPException(400, "To konto nie jest kontem Supabase — nie ma czego kasować")
    if v.owner or v.role == "owner":
        raise HTTPException(403, "Konta właściciela nie kasujemy z aplikacji")
    if not sa.delete_user(v.user_id):
        raise HTTPException(502, "Nie udało się skasować konta. Spróbuj później albo napisz do nas.")
    return {"deleted": True}


# ------------------------------------------------------------------- premium


@router.get("/api/premium/features")
def premium_features(v: sa.Viewer = Depends(viewer)):
    return premium.catalog(v)


@router.post("/api/premium/event")
async def premium_event(request: Request, v: sa.Viewer = Depends(viewer)):
    """Ślad kliknięcia w kłódkę. Zawsze zwraca ok — analityka nie blokuje interfejsu."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    sync.log_event(
        v.user_id or None,
        str(body.get("event") or "lock_click"),
        str(body.get("feature") or ""),
        str(body.get("platform") or ""),
        body.get("meta") if isinstance(body.get("meta"), dict) else None,
    )
    return {"ok": True}


# ------------------------------------------------------------ synchronizacja


@router.get("/api/sync/settings")
def sync_get(v: sa.Viewer = Depends(viewer)):
    """Preferencje konta. Niezalogowany dostaje pustkę i trzyma wszystko lokalnie."""
    if not v.user_id:
        return {"synced": False, "settings": {}}
    return {"synced": True, "settings": sync.get_settings(v.user_id)}


@router.post("/api/sync/settings")
async def sync_put(request: Request, v: sa.Viewer = Depends(require_login)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Oczekiwano obiektu JSON")
    values = body.get("settings")
    if not isinstance(values, dict) or not values:
        raise HTTPException(400, "Brak ustawień do zapisania")
    if not v.user_id:
        # właściciel na localhost bez konta Supabase — nie ma gdzie synchronizować
        return {"synced": False, "settings": {}}
    ok = sync.put_settings(v.user_id, values, str(body.get("device") or ""))
    return {"synced": ok, "settings": sync.get_settings(v.user_id) if ok else {}}
