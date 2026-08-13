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
_load_env_file(os.path.join(_ROOT, "keys", "email.env"))

URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
ANON = os.environ.get("SUPABASE_ANON_KEY") or ""
SERVICE = os.environ.get("SUPABASE_SERVICE_KEY") or ""
OWNER_EMAIL = (os.environ.get("OWNER_EMAIL") or "").strip().lower()

# W chmurze zaufanie do „localhost" jest niebezpieczne: żądanie przychodzi przez
# proxy hostingu, a gdyby kiedykolwiek trafiło do nas z adresem pętli zwrotnej,
# każdy dostałby uprawnienia właściciela. Dlatego na serwerze wymagamy logowania
# zawsze, a wyłączyć to można tylko świadomie, ustawiając REQUIRE_AUTH_LOCAL=0.
_CLOUD = bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("PORTEVO_CLOUD"))
REQUIRE_AUTH_LOCAL = (
    os.environ.get("REQUIRE_AUTH_LOCAL") or ("1" if _CLOUD else "0")
).strip() in ("1", "true", "yes")


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


def _service_write(path: str, method: str, payload, params: dict | None = None) -> bool:
    """Zapis kluczem serwerowym. Uprawnienia nadaje wyłącznie serwer, nigdy klient."""
    if not (URL and SERVICE):
        return False
    try:
        r = requests.request(
            method,
            f"{URL}/rest/v1/{path}",
            params=params or {},
            json=payload,
            headers={
                "apikey": SERVICE, "Authorization": f"Bearer {SERVICE}",
                "Content-Type": "application/json", "Prefer": "return=minimal",
            },
            timeout=10,
        )
        return r.status_code < 300
    except requests.RequestException:
        return False


def set_entitlement(user_id: str, plan: str, source: str, expires_at: str | None,
                    provider_ref: str, cancelled_at: str | None = None,
                    note: str = "") -> bool:
    """Zapisuje nadanie premium od dostawcy płatności — jeden wiersz na subskrypcję.

    Kluczem tożsamości jest `provider_ref` (u Apple: `originalTransactionId`, stały
    przez wszystkie odnowienia). Dlatego odnowienie AKTUALIZUJE wiersz zamiast
    dokładać nowy — inaczej po roku konto miałoby dwanaście nadań i nie dałoby się
    powiedzieć, które obowiązuje.

    Świadomie bez `on_conflict`: unikalny indeks `entitlements_provider_idx` jest
    częściowy (`where provider_ref is not null`), a takiego PostgREST nie potrafi
    wskazać jako arbitra konfliktu. Czytamy więc wprost i wybieramy PATCH albo POST.
    """
    if not (user_id and provider_ref):
        return False

    row = {
        "user_id": user_id, "product": "premium", "plan": plan, "source": source,
        "expires_at": expires_at, "cancelled_at": cancelled_at,
        "provider_ref": provider_ref, "updated_at": _now_iso(),
    }
    if note:
        row["note"] = note

    found = _service_get("entitlements", {
        "source": f"eq.{source}", "provider_ref": f"eq.{provider_ref}", "select": "id",
    })
    if found:
        ok = _service_write("entitlements", "PATCH", row,
                            {"id": f"eq.{found[0].get('id')}"})
    else:
        ok = _service_write("entitlements", "POST", row)

    if ok:
        forget(user_id)          # cache uprawnień ma minutę życia — po zakupie za długo
    return ok


def user_for_provider_ref(source: str, provider_ref: str) -> str:
    """Czyje to nadanie — po identyfikatorze u dostawcy płatności.

    Powiadomienia od Apple nie niosą naszego użytkownika, tylko swoją transakcję.
    Wiązanie powstaje przy zakupie i to ono pozwala później odnowić albo odebrać
    premium właściwemu kontu.
    """
    if not (source and provider_ref):
        return ""
    rows = _service_get("entitlements", {
        "source": f"eq.{source}", "provider_ref": f"eq.{provider_ref}",
        "select": "user_id", "limit": "1",
    })
    return (rows[0].get("user_id") if rows else "") or ""


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


_owner_uid: list = [0.0, ""]


def owner_user_id() -> str:
    """Identyfikator konta właściciela w Supabase — po e-mailu z OWNER_EMAIL.

    Potrzebny, bo telefon właściciela loguje się tokenem panelu, a nie kontem.
    Dane portfela żyją pod identyfikatorem użytkownika, więc token trzeba na ten
    identyfikator przetłumaczyć — inaczej właściciel widziałby pustą bazę.
    """
    if not OWNER_EMAIL:
        return ""
    now = time.time()
    if _owner_uid[0] > now and _owner_uid[1]:
        return _owner_uid[1]
    rows = _service_get("profiles", {"email": f"eq.{OWNER_EMAIL}", "select": "id"})
    uid = (rows[0].get("id") if rows else "") or ""
    if uid:
        _owner_uid[0], _owner_uid[1] = now + 600.0, uid
    return uid


def forget(user_id: str) -> None:
    """Kasuje cache uprawnień — po zakupie chcemy zobaczyć zmianę natychmiast."""
    with _lock:
        _ent_cache.pop(user_id, None)
        _role_cache.pop(user_id, None)


def delete_user(user_id: str) -> bool:
    """Kasuje konto w Supabase — nieodwracalnie, razem z danymi.

    Wymóg App Store: aplikacja z rejestracją MUSI umieć skasować konto z własnego
    wnętrza. Jedno wywołanie wystarcza, bo wszystkie tabele użytkownika mają
    `references auth.users (id) on delete cascade` (migracje 0001 i 0002) —
    portfel, operacje, ustawienia i obserwowane znikają razem z kontem.

    Robi to KLUCZ SERWEROWY, nie token użytkownika: GoTrue nie pozwala kasować
    samego siebie zwykłym tokenem.
    """
    if not (URL and SERVICE and user_id):
        return False
    try:
        r = requests.delete(
            f"{URL}/auth/v1/admin/users/{user_id}",
            headers={"apikey": SERVICE, "Authorization": f"Bearer {SERVICE}"},
            timeout=15,
        )
    except requests.RequestException:
        return False
    if r.status_code not in (200, 204, 404):     # 404 = konta już nie ma, cel osiągnięty
        return False

    # token skasowanego konta nie może przez minutę dalej działać z cache
    with _lock:
        _ent_cache.pop(user_id, None)
        _role_cache.pop(user_id, None)
        for k, v in list(_token_cache.items()):
            if (v[1] or {}).get("id") == user_id:
                _token_cache.pop(k, None)
    return True


# ------------------------------------------------------------ role (konta dev)

_role_cache: dict[str, tuple[float, str]] = {}
ROLE_TTL = 300.0


def role_of(user_id: str, email: str = "") -> str:
    """'owner' | 'dev' | 'user'. Rola siedzi w profiles.role (migracja 0002)."""
    if email and OWNER_EMAIL and email.lower() == OWNER_EMAIL:
        return "owner"
    if not user_id:
        return "user"

    now = time.time()
    with _lock:
        hit = _role_cache.get(user_id)
        if hit and hit[0] > now:
            return hit[1]

    rows = _service_get("profiles", {"id": f"eq.{user_id}", "select": "role"})
    out = (rows[0].get("role") if rows else "") or "user"
    with _lock:
        _role_cache[user_id] = (now + ROLE_TTL, out)
    return out


# ------------------------------------------------------- rozpoznanie żądania


class Viewer:
    """Kto pyta. Jeden obiekt dla wszystkich wariantów: właściciel, konto, gość."""

    def __init__(self, user: dict | None = None, owner: bool = False, premium: dict | None = None,
                 role: str = "user", premium_view: str = ""):
        self.user = user or {}
        self.owner = owner
        self._ent = premium or {"premium": False, "plan": None, "source": None, "expires_at": None}
        self.role = "owner" if owner else (role or "user")
        # Podgląd wybrany przez konto testowe: "off" = pokaż wersję bez premium.
        # Honorujemy to WYŁĄCZNIE dla dev/owner — inaczej byłby to przełącznik,
        # którym każdy nadałby sobie premium jednym nagłówkiem.
        self.premium_view = premium_view if self.role in ("dev", "owner") else ""

    @property
    def logged_in(self) -> bool:
        return bool(self.user.get("id")) or self.owner

    @property
    def is_dev(self) -> bool:
        return self.role in ("dev", "owner")

    @property
    def premium(self) -> bool:
        """Czy TERAZ pokazujemy zawartość premium (uwzględnia podgląd konta dev)."""
        if self.premium_view == "off":
            return False
        return self.owner or self.role == "dev" or bool(self._ent.get("premium"))

    @property
    def user_id(self) -> str:
        return self.user.get("id") or ""

    @property
    def email(self) -> str:
        return self.user.get("email") or ""

    def to_json(self) -> dict:
        return {
            "logged_in": self.logged_in,
            "owner": self.owner,
            "premium": self.premium,
            "role": self.role,
            # aplikacja pokazuje przełącznik podglądu tylko kontom testowym
            "can_preview_free": self.is_dev,
            "premium_view": self.premium_view or "on",
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
    role = role_of(user.get("id", ""), user.get("email", "")) if user else ("owner" if owner else "user")
    view = (request.headers.get("x-premium-view") or "").strip().lower()
    return Viewer(user=user, owner=owner, premium=ent, role=role,
                  premium_view=view if view in ("on", "off") else "")


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
