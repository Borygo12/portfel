"""API kont emerytalnych — `/api/retirement/…`.

Podział na darmowe i płatne jest tu inny niż w reszcie aplikacji i warto go
mieć w głowie:

* **Zasady i limity są darmowe i publiczne** (`/meta`). To wiedza, nie funkcja —
  ktoś, kto dopiero rozważa IKE, ma się tu dowiedzieć, jak ono działa, zanim
  założy konto u nas czy u brokera.
* **Porządkowanie danych jest darmowe** (wymaga tylko konta): oznaczenie
  rachunku jako IKE/IKZE, przypisanie go małżonkowi, dopisanie konta ręcznie.
  To ten sam rodzaj czynności co nazwanie portfela.
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
from account_api import require_login

log = logging.getLogger("retirement_api")

router = APIRouter()

FEATURE = "tools.retirement"

_BRAK_MIGRACJI = ("Baza nie jest jeszcze gotowa na tę zmianę (migracja kont emerytalnych). "
                  "Spróbuj za chwilę.")


def _osoba(rok_ur: int, stawka: int, jdg: int) -> dict:
    rok = int(rok_ur or 0)
    return {
        "rok_ur": rok if 1920 <= rok <= 2015 else None,
        "stawka": {12: 0.12, 19: 0.19, 32: 0.32}.get(int(stawka or 12), 0.12),
        "jdg": bool(jdg),
    }


def _profil(rok_ur: int = 0, stawka: int = 12, jdg: int = 0, malzonek: int = 0,
            m_rok_ur: int = 0, m_stawka: int = 12, m_jdg: int = 0) -> dict:
    """Ustawienia z aplikacji: rok urodzenia, stawka PIT, działalność — swoje i małżonka.

    Przychodzą w adresie, a nie z bazy — to kilka liczb trzymanych w ustawieniach
    aplikacji (i synchronizowanych z kontem razem z resztą preferencji), więc
    osobna tabela byłaby tylko drugim miejscem, w którym mogą się rozjechać.
    """
    p = _osoba(rok_ur, stawka, jdg)
    p["malzonek"] = bool(malzonek)
    p["m"] = _osoba(m_rok_ur, m_stawka, m_jdg)
    return p


@router.get("/api/retirement/meta")
def meta(rok_ur: int = 0, stawka: int = 12, jdg: int = 0):
    """Zasady, limity i przykładowe konto — dla każdego, także bez logowania."""
    p = _profil(rok_ur, stawka, jdg)
    return {**retirement.meta(p), "przyklad": retirement.demo(p)}


@router.get("/api/retirement/overview")
def overview(rok_ur: int = 0, stawka: int = 12, jdg: int = 0, malzonek: int = 0,
             m_rok_ur: int = 0, m_stawka: int = 12, m_jdg: int = 0,
             v: sa.Viewer = Depends(require_login)):
    """Konta emerytalne zalogowanego. Bez premium: przykład + to, co rozpoznaliśmy."""
    p = _profil(rok_ur, stawka, jdg, malzonek, m_rok_ur, m_stawka, m_jdg)
    wykryte = retirement.wykryte()
    if not v.premium:
        # Lista rachunków i kont wpisanych ręcznie jest prawdziwa także tutaj:
        # porządkowanie jest darmowe, a to, co człowiek sam wpisał, nie jest
        # liczbą pod kłódką. Płatne jest to, co z tego wyliczamy.
        try:
            rachunki, wpisane = retirement.konta(), retirement.reczne()
        except Exception:  # noqa: BLE001
            rachunki, wpisane = [], []
        return {**retirement.demo(p), "konta": rachunki, "reczne": wpisane,
                "premium": False, "wykryte": wykryte}
    try:
        dane = retirement.przeglad(p)
    except Exception as e:  # noqa: BLE001
        log.exception("Przegląd kont emerytalnych")
        raise HTTPException(503, f"Nie udało się policzyć kont emerytalnych: {str(e)[:160]}")
    return {**dane, "premium": True, "wykryte": wykryte}


@router.post("/api/retirement/account")
async def set_account(request: Request, _v: sa.Viewer = Depends(require_login)):
    """Ręczne oznaczenie rachunku maklerskiego.

    {"account": "…", "kind": "ike" | "ikze" | "oki" | ""} zmienia rodzaj,
    {"account": "…", "owner": "" | "malzonek"} — czyj to rachunek. Oba pola
    są opcjonalne, zmieniamy tylko to, co przyszło.
    """
    from portfolio import engine as pf_engine
    from portfolio import store as pf_store

    body = (await request.json()) or {}
    konto = str(body.get("account") or "").strip()
    if not konto:
        raise HTTPException(400, "Brak numeru rachunku")
    if "kind" in body:
        kind = str(body.get("kind") or "").strip().lower()
        if kind not in ("", *retirement.KINDS):
            raise HTTPException(400, "Nieznany rodzaj konta")
        if not pf_store.set_account_kind(konto, kind, "user"):
            raise HTTPException(503, _BRAK_MIGRACJI)
    if "owner" in body:
        owner = str(body.get("owner") or "").strip().lower()
        if owner not in retirement.OSOBY:
            raise HTTPException(400, "Nieznany właściciel")
        if not retirement.ustaw_wlasciciela(konto, owner):
            raise HTTPException(503, _BRAK_MIGRACJI)
    pf_engine.invalidate()
    return {"ok": True, "account": konto}


@router.post("/api/retirement/asset")
async def set_asset(request: Request, _v: sa.Viewer = Depends(require_login)):
    """To samo dla majątku dopisanego ręcznie albo z odczytu AI: {"id", "kind"}."""
    body = (await request.json()) or {}
    aid = str(body.get("id") or "").strip()
    kind = str(body.get("kind") or "").strip().lower()
    if not aid:
        raise HTTPException(400, "Brak identyfikatora aktywa")
    if not retirement.ustaw_typ_aktywa(aid, kind):
        raise HTTPException(503, _BRAK_MIGRACJI)
    return {"ok": True, "id": aid, "kind": kind if kind in retirement.KINDS else ""}


@router.post("/api/retirement/manual")
async def save_manual(request: Request, _v: sa.Viewer = Depends(require_login)):
    """Konto wpisywane ręcznie — IKE-Obligacje, konto w TFI, PPK, PPE.

    Z `id` poprawia istniejące, bez — dodaje nowe. Wpłaty przychodzą w komplecie:
    [{"rok": 2025, "kwota": 12000, "zrodlo": "wlasne" | "pracodawca" | "panstwo"}].
    """
    body = (await request.json()) or {}
    try:
        aid = retirement.zapisz_reczne(body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        log.warning("Zapis konta ręcznego: %s", e)
        raise HTTPException(503, _BRAK_MIGRACJI)
    return {"ok": True, "id": aid}


@router.delete("/api/retirement/manual/{aid}")
def delete_manual(aid: str, _v: sa.Viewer = Depends(require_login)):
    try:
        retirement.usun_reczne(aid)
    except Exception as e:  # noqa: BLE001
        log.warning("Usunięcie konta ręcznego: %s", e)
        raise HTTPException(503, _BRAK_MIGRACJI)
    return {"ok": True}
