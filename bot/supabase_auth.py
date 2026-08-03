"""Konta i uprawnienia premium oparte o Supabase.

Podział ról, żeby nie było wątpliwości kto czemu ufa:

* **Supabase** trzyma tożsamość (Google / e-mail) i nadania premium.
* **Ten serwer** trzyma dane portfela i steruje botem. Nie zna haseł — dostaje
  wyłącznie token dostępowy wystawiony przez Supabase i pyta go, czyj to token.
* **Klient** (telefon, panel web) nigdy nie decyduje o swoim premium. Wysyła token,
  resztę ustala serwer.

Weryfikacja tokenu idzie przez `GET /auth/v1/user` w Supabase zamiast lokalnego
sprawdzania podpisu. Kosztuje jedno zapytanie na 5 minut (wynik jest w cache), za to
nie wymaga PyJWT ani `cryptography`, obsługuje oba warianty podpisu (HS256 i nowe
klucze asymetryczne) i od razu widzi tokeny unieważnione — czego samo sprawdzenie
podpisu nie potrafi.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time

import requests

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)

# ---------------------------------------------------------------- konfiguracja


def _load_env_file(path: str) -> None:
    """Doczytuje KLUCZ=wartość, nie nadpisując tego, co już jest w środowisku."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and v and not os.environ.get(k):
                    os.environ[k] = v
    except OSError:
        pass


_load_env_file(os.path.join(_ROOT, "keys", "supabase.env"))
_load_env_file(os.path.join(_ROOT, "keys", "stripe.env"))

URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
ANON = os.environ.get("SUPABASE_ANON_KEY") or ""
SERVICE = os.environ.get("SUPABASE_SERVICE_KEY") or ""
OWNER_EMAIL = (os.environ.get("OWNER_EMAIL") or "").strip().lower()
REQUIRE_AUTH_LOCAL = (os.environ.get("REQUIRE_AUTH_LOCAL") or "0").strip() in ("1", "true", "yes")


def configured() -> bool:
    """Czy w ogóle podpięto Supabase. Bez tego panel działa jak dotąd — na tokenie."""
    return bool(URL and ANON)


def public_config() -> dict:
    """To, co wolno oddać przeglądarce: adres projektu i klucz publiczny."""
    return {
        "configured": configured(),
        "url": URL,
        "anon_key": ANON,
        "require_auth_local": REQUIRE_AUTH_LOCAL,
    }


# ------------------------------------------------------------- cache tokenów

_lock = threading.Lock()
_token_cache: dict[str, tuple[float, dict | None]] = {}
_ent_cache: dict[str, tuple[float, dict]] = {}

TOKEN_TTL = 300.0      # 5 min — tyle ufamy odpowiedzi Supabase o tożsamości
ENT_TTL = 60.0         # 1 min — po zakupie premium ma się pojawić szybko


def _peek(token: str) -> dict:
    """Zawartość tokenu BEZ weryfikacji — tylko do wstępnego odsiania i cache.

    Nic z tego nie może samo w sobie o niczym decydować.
    """
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def verify_token(token: str) -> dict | None:
    """Zwraca dane użytkownika albo None, gdy token jest nieważny."""
    if not token or not configured():
        return None

    claims = _peek(token)
    exp = claims.get("exp")
    # token po terminie odrzucamy od razu, bez ruszania sieci
    if isinstance(exp, (int, float)) and exp < time.time():
        return None

    now = time.time()
    with _lock:
        hit = _token_cache.get(token)
        if hit and hit[0] > now:
            return hit[1]

    user = None
    try:
        r = requests.get(
            f"{URL}/auth/v1/user",
            headers={"apikey": ANON, "Authorization": f"Bearer {token}"},
            timeout=8,
        )
        if r.status_code == 200:
            js = r.json() or {}
            meta = js.get("user_metadata") or {}
            user = {
                "id": js.get("id"),
                "email": (js.get("email") or "").lower(),
                "name": meta.get("full_name") or meta.get("name") or "",
                "avatar": meta.get("avatar_url") or "",
                "provider": (js.get("app_metadata") or {}).get("provider") or "email",
            }
    except requests.RequestException:
        # Brak sieci nie może wyrzucić zalogowanego z aplikacji — jeśli mamy jeszcze
        # świeży wpis w cache, zostaje przy nim; jeśli nie, traktujemy jak niezalogowanego.
        with _lock:
            hit = _token_cache.get(token)
        return hit[1] if hit else None

    ttl = TOKEN_TTL
    if isinstance(exp, (int, float)):
        ttl = max(5.0, min(TOKEN_TTL, exp - now))
    with _lock:
        _token_cache[token] = (now + ttl, user)
        if len(_token_cache) > 200:                       # sprzątanie przeterminowanych
            for k, (t, _) in list(_token_cache.items()):
                if t <= now:
                    _token_cache.pop(k, None)
    return user


# --------------------------------------------------------------- uprawnienia


def _service_get(path: str, params: dict) -> list:
    """Odczyt z bazy kluczem serwerowym — omija RLS, więc widzi cudze wiersze."""
    if not (URL and SERVICE):
        return []
    try:
        r = requests.get(
            f"{URL}/rest/v1/{path}",
            params=params,
            headers={"apikey": SERVICE, "Authorization": f"Bearer {SERVICE}"},
            timeout=8,
        )
        return r.json() if r.status_code == 200 else []
    except (requests.RequestException, ValueError):
        return []


def entitlement(user_id: str, email: str = "") -> dict:
    """Aktualny status premium konta. Właściciel ma go zawsze."""
    if email and OWNER_EMAIL and email.lower() == OWNER_EMAIL:
        return {"premium": True, "plan": "lifetime", "source": "owner", "expires_at": None}

    now = time.time()
    with _lock:
        hit = _ent_cache.get(user_id)
        if hit and hit[0] > now:
            return hit[1]

    rows = _service_get("entitlements", {
        "user_id": f"eq.{user_id}",
        "product": "eq.premium",
        "select": "plan,source,expires_at,cancelled_at",
    })

    out = {"premium": False, "plan": None, "source": None, "expires_at": None}
    for row in rows:
        exp = row.get("expires_at")
        if exp:
            try:
                # Postgres oddaje ISO z offsetem; „Z" nie przechodzi przez fromisoformat
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                if dt.timestamp() <= now:
                    continue
            except ValueError:
                continue
        out = {"premium": True, "plan": row.get("plan"), "source": row.get("source"),
               "expires_at": exp}
        break

    with _lock:
        _ent_cache[user_id] = (now + ENT_TTL, out)
    return out


def forget(user_id: str) -> None:
    """Kasuje cache uprawnień — po zakupie chcemy zobaczyć zmianę natychmiast."""
    with _lock:
        _ent_cache.pop(user_id, None)


# ------------------------------------------------------- rozpoznanie żądania


class Viewer:
    """Kto pyta. Jeden obiekt dla wszystkich wariantów: właściciel, konto, gość."""

    def __init__(self, user: dict | None = None, owner: bool = False, premium: dict | None = None):
        self.user = user or {}
        self.owner = owner
        self._ent = premium or {"premium": False, "plan": None, "source": None, "expires_at": None}

    @property
    def logged_in(self) -> bool:
        return bool(self.user.get("id")) or self.owner

    @property
    def premium(self) -> bool:
        return self.owner or bool(self._ent.get("premium"))

    @property
    def user_id(self) -> str:
        return self.user.get("id") or ""

    def to_json(self) -> dict:
        return {
            "logged_in": self.logged_in,
            "owner": self.owner,
            "premium": self.premium,
            "plan": "owner" if self.owner else self._ent.get("plan"),
            "source": "owner" if self.owner else self._ent.get("source"),
            "expires_at": None if self.owner else self._ent.get("expires_at"),
            "user": {
                "id": self.user.get("id", ""),
                "email": self.user.get("email", ""),
                "name": self.user.get("name", ""),
                "avatar": self.user.get("avatar", ""),
                "provider": self.user.get("provider", ""),
            } if self.user else None,
            "auth_configured": configured(),
        }


def viewer_from_request(request) -> Viewer:
    """Ustala tożsamość na podstawie nagłówków — bez rzucania wyjątków.

    Kolejność ma znaczenie: token dostępu do panelu (ten z pliku, wpisywany raz
    w telefonie) oznacza właściciela, więc sterowanie botem działa nawet gdy
    Supabase leży albo w ogóle nie jest podpięty.
    """
    header = request.headers.get("authorization") or ""
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not token:
        token = request.headers.get("x-supabase-token") or ""

    user = verify_token(token) if token else None
    ent = entitlement(user["id"], user.get("email", "")) if user and user.get("id") else None

    owner = _is_owner_request(request, user)
    return Viewer(user=user, owner=owner, premium=ent)


def _is_owner_request(request, user: dict | None) -> bool:
    if user and OWNER_EMAIL and (user.get("email") or "").lower() == OWNER_EMAIL:
        return True
    # połączenie z tego komputera przy wyłączonym wymogu logowania
    client = (request.client.host if request.client else "") or ""
    if not REQUIRE_AUTH_LOCAL and client in ("127.0.0.1", "::1", "localhost"):
        return True
    # telefon właściciela: token panelu z pliku api_token.txt
    try:
        import dashboard  # noqa: PLC0415  (import późny — dashboard importuje ten moduł)
        given = request.headers.get("x-api-token") or request.query_params.get("token") or ""
        if given and given == dashboard.api_token():
            return True
    except Exception:
        pass
    return False
