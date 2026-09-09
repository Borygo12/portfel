"""Endpointy powiadomień — ustawienia, urządzenia, skrzynka.

Router wpinany w `dashboard.py`, tak samo jak `account_api`.

Dlaczego ODCZYT ustawień jest otwarty dla każdego zalogowanego, a ZAPIS trybu
newsów wymaga premium: ekran ma pokazać trzy przyciski od razu, również komuś
bez subskrypcji — inaczej nie wiadomo, co się kupuje. Klikniecie „tak" bez
premium kończy się odpowiedzią 402 z identyfikatorem funkcji, więc aplikacja
otwiera stronę sprzedażową zamiast udawać, że zapisała.

Wyjątkiem są przełączniki kalendarza wyników i wybór kanału — te zapisujemy
każdemu. Nie kosztują nic, a ktoś, kto dopiero kupi premium, nie musi wtedy
ustawiać wszystkiego od nowa.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

import supabase_auth as sa
from account_api import require_login
from notify import earnings as notify_earnings
from notify import engine as notify_engine
from notify import store as notify_store

log = logging.getLogger("notify.api")

router = APIRouter()

FUNKCJA = "bot.alerts"          # identyfikator w katalogu premium


def _premium(v: sa.Viewer) -> bool:
    return bool(v.premium)


@router.get("/api/notify/prefs")
def prefs(v: sa.Viewer = Depends(require_login)):
    """Ustawienia + informacja, które kanały serwer w ogóle potrafi obsłużyć."""
    from notify import mail as notify_mail

    ust = notify_store.ustawienia_moje()
    return {
        **ust,
        "premium": _premium(v),
        # Aplikacja nie ma jak zgadnąć, czy skrzynka nadawcza jest skonfigurowana.
        # Bez tego pokazywałaby przełącznik e-maila, który nic nie robi.
        "email_available": notify_mail.skonfigurowany(),
        "email_address": (v.email or ""),
    }


@router.post("/api/notify/prefs")
async def prefs_save(request: Request, v: sa.Viewer = Depends(require_login)):
    body = await request.json() if await request.body() else {}
    if not isinstance(body, dict):
        raise HTTPException(400, "Oczekiwano obiektu z ustawieniami")

    tryb = body.get("news_mode")
    if tryb is not None and tryb not in notify_store.TRYBY:
        raise HTTPException(400, f"news_mode musi być jednym z {notify_store.TRYBY}")

    # Włączenie newsów to funkcja płatna. Wyłączenie — nigdy: nikt nie ma
    # płacić za to, żeby telefon przestał dzwonić.
    if tryb in ("all", "strong") and not _premium(v):
        raise HTTPException(
            402,
            {"error": "premium_required", "feature": FUNKCJA,
             "message": "Powiadomienia o newsach są częścią wersji premium"},
        )

    return notify_store.zapisz_moje(body)


# ------------------------------------------------------------------- urządzenia


@router.post("/api/notify/device")
async def device_register(request: Request, v: sa.Viewer = Depends(require_login)):
    """Rejestruje token urządzenia z Expo. Aplikacja woła to po każdym starcie."""
    body = await request.json() if await request.body() else {}
    token = str((body or {}).get("token") or "").strip()
    if not token.startswith("Expo"):
        raise HTTPException(400, "To nie wygląda na token powiadomień Expo")
    notify_store.zapisz_token_moj(token, str((body or {}).get("platform") or ""))
    return {"registered": True}


@router.post("/api/notify/device/remove")
async def device_remove(request: Request, v: sa.Viewer = Depends(require_login)):
    body = await request.json() if await request.body() else {}
    token = str((body or {}).get("token") or "").strip()
    if token:
        notify_store.usun_token_moj(token)
    return {"removed": True}


# --------------------------------------------------------------------- skrzynka


@router.get("/api/notify/inbox")
def inbox(limit: int = 50, v: sa.Viewer = Depends(require_login)):
    return notify_store.skrzynka_moja(limit)


@router.post("/api/notify/read")
async def inbox_read(request: Request, v: sa.Viewer = Depends(require_login)):
    body = await request.json() if await request.body() else {}
    ids = (body or {}).get("ids")
    notify_store.oznacz_przeczytane_moje(
        [int(i) for i in ids] if isinstance(ids, list) else None)
    return {"ok": True}


# ------------------------------------------------- co mnie obchodzi (cache symboli)


@router.post("/api/notify/symbols")
def symbols_refresh(v: sa.Viewer = Depends(require_login)):
    """Odświeża listę „moich spółek", z której korzysta silnik powiadomień.

    Woła to aplikacja przy wejściu na ekran bota i po zmianie portfela. Bez tego
    świeżo dokupiona spółka byłaby dla powiadomień niewidoczna do następnego
    nocnego odświeżenia.
    """
    import dashboard

    mine = dashboard._my_symbols()
    notify_store.zapisz_symbole_moje(mine["positions"], mine["watchlist"])
    return {"positions": sorted(mine["positions"]),
            "watchlist": sorted(mine["watchlist"])}


# ------------------------------------------------------------------------- test


@router.post("/api/notify/test")
def test_send(v: sa.Viewer = Depends(require_login)):
    """Wysyła testowe powiadomienie do samego siebie.

    Bez tego jedynym sposobem sprawdzenia, czy zgody systemowe i token działają,
    byłoby czekanie na prawdziwy news — czyli nie da się tego sprawdzić wtedy,
    gdy się chce.

    `dedup_key` ma w sobie znacznik czasu, więc test da się powtórzyć; wszystkie
    pozostałe powiadomienia celowo dedupują się na treści.
    """
    import time
    if not v.user_id:
        raise HTTPException(400, "To konto nie jest połączone z bazą")
    poszlo = notify_engine.powiadom(
        v.user_id, "news", "Powiadomienia działają",
        "Tak będzie wyglądać wiadomość o newsie dotyczącym Twojej spółki.",
        dedup_key=f"test:{int(time.time())}",
        meta={"test": True},
    )
    return {"sent": bool(poszlo)}


# ------------------------------------------------- ręczne odpalenie zadań (owner)


@router.post("/api/notify/jobs/{job}")
def run_job_owner(job: str, request: Request):
    """Ręczne odpalenie zadania o wynikach. Tylko właściciel.

    Sprawdzenie uprawnień robimy tutaj, a nie zależnością, bo zadanie potrafi
    chodzić kilkadziesiąt sekund (kalendarz na zimnym cache) i chcemy mieć
    pewność, że nikt postronny go nie uruchomi seryjnie.
    """
    v = sa.viewer_from_request(request)
    if not (v.owner or v.role == "owner"):
        raise HTTPException(403, "Tylko konto właściciela")
    if job == "dzien":
        return {"sent": notify_earnings.dzisiejsze()}
    if job == "tydzien":
        return {"sent": notify_earnings.tydzien()}
    raise HTTPException(400, "Nieznane zadanie — 'dzien' albo 'tydzien'")
