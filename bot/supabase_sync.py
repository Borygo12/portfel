"""Synchronizacja ustawień między telefonem a panelem web (tabela `user_settings`).

Serwer pośredniczy zamiast puszczać klientów prosto do Supabase z dwóch powodów:
telefon i tak rozmawia z tym serwerem (jeden adres do skonfigurowania), a panel
HTML nie musi wtedy wozić ze sobą klucza i logiki ponawiania.

Zapis idzie kluczem serwerowym, ale zawsze na `user_id` wyciągnięty z tokenu —
klient nie ma jak podać cudzego identyfikatora.
"""

from __future__ import annotations

import requests

from supabase_auth import SERVICE, URL


def _headers() -> dict:
    return {
        "apikey": SERVICE,
        "Authorization": f"Bearer {SERVICE}",
        "Content-Type": "application/json",
    }


def enabled() -> bool:
    return bool(URL and SERVICE)


def get_settings(user_id: str) -> dict:
    """Wszystkie preferencje konta jako {klucz: wartość}."""
    if not (enabled() and user_id):
        return {}
    try:
        r = requests.get(
            f"{URL}/rest/v1/user_settings",
            params={"user_id": f"eq.{user_id}", "select": "key,value,updated_at"},
            headers=_headers(), timeout=8)
        if r.status_code != 200:
            return {}
        return {row["key"]: row["value"] for row in r.json()}
    except (requests.RequestException, ValueError, KeyError):
        return {}


def put_settings(user_id: str, values: dict, device: str = "") -> bool:
    """Nadpisuje podane klucze. Reszty nie rusza — synchronizacja jest przyrostowa."""
    if not (enabled() and user_id and values):
        return False
    rows = [{"user_id": user_id, "key": k, "value": v, "device": device or None}
            for k, v in values.items()]
    try:
        r = requests.post(
            f"{URL}/rest/v1/user_settings",
            params={"on_conflict": "user_id,key"},
            headers={**_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"},
            json=rows, timeout=8)
        return r.status_code in (200, 201, 204)
    except requests.RequestException:
        return False


def log_event(user_id: str | None, event: str, feature: str = "",
              platform: str = "", meta: dict | None = None) -> None:
    """Ślad w lejku sprzedażowym. Cicho — analityka nie ma prawa psuć ekranu."""
    if not enabled():
        return
    try:
        requests.post(
            f"{URL}/rest/v1/premium_events",
            headers={**_headers(), "Prefer": "return=minimal"},
            json={"user_id": user_id or None, "event": event,
                  "feature": feature or None, "platform": platform or None,
                  "meta": meta or None},
            timeout=5)
    except requests.RequestException:
        pass
