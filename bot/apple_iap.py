"""Subskrypcje z App Store — pytamy Apple o stan i sami nadajemy premium.

Zasada jest ta sama, co przy logowaniu (`supabase_auth`): **klient nigdy nie
decyduje o swoim premium**. Telefon przysyła wyłącznie identyfikator transakcji,
a prawdę o niej ustala serwer, pytając App Store Server API.

Dlaczego akurat tak, a nie przez sprawdzanie podpisu paragonu:

* Odpowiedź przychodzi od Apple po TLS-ie, więc jest wiarygodna z tego samego
  powodu, co każde inne zapytanie HTTPS — nie musimy wozić ze sobą certyfikatów
  root Apple ani ich rotować, gdy wygasną.
* Widzimy stan AKTUALNY, a nie ten z chwili zakupu: zwrot pieniędzy, rezygnację,
  wygaśnięcie i zmianę planu. Paragon z telefonu tego nie wie.
* Ten sam kod obsługuje zakup i powiadomienie serwerowe — w obu wypadkach mamy
  identyfikator transakcji i pytamy o niego Apple.

Konfiguracja w `keys/apple.env` (plik nie idzie do repozytorium):

    APPLE_IAP_KEY_ID=XXXXXXXXXX          # z App Store Connect, klucz In-App Purchase
    APPLE_IAP_ISSUER_ID=xxxxxxxx-....    # z tej samej strony
    APPLE_IAP_KEY_FILE=keys/apple_iap.p8 # pobrany raz, nie do odzyskania
    APPLE_BUNDLE_ID=pl.borygo.portevo

Na hostingu, gdzie katalogu `keys/` nie ma, zamiast pliku wystarczy zmienna
`APPLE_IAP_KEY_PEM` z całą treścią `.p8` (razem z liniami BEGIN/END).

Dopóki tych wartości nie ma, `configured()` zwraca False, a endpoint zakupu mówi
o tym wprost zamiast udawać, że coś sprawdził.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from datetime import datetime, timezone

import requests

import supabase_auth as sa

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)

sa._load_env_file(os.path.join(_ROOT, "keys", "apple.env"))

KEY_ID = (os.environ.get("APPLE_IAP_KEY_ID") or "").strip()
ISSUER_ID = (os.environ.get("APPLE_IAP_ISSUER_ID") or "").strip()
BUNDLE_ID = (os.environ.get("APPLE_BUNDLE_ID") or "pl.borygo.portevo").strip()
KEY_FILE = (os.environ.get("APPLE_IAP_KEY_FILE") or "keys/apple_iap.p8").strip()
# Na hostingu nie ma katalogu `keys/` (nie idzie do repozytorium), a plików się tam
# nie wgrywa — jest tylko tablica zmiennych. Dlatego treść `.p8` wolno podać wprost
# w `APPLE_IAP_KEY_PEM`. Railway zjada wieloliniowe wartości, ale gdyby ktoś wkleił
# klucz z „\n" zamiast złamań wiersza, i tak go rozwiniemy.
KEY_PEM = (os.environ.get("APPLE_IAP_KEY_PEM") or "").strip().replace("\\n", "\n")

# Produkcja i piaskownica to OSOBNE serwery z osobnymi transakcjami. Apple każe
# pytać najpierw produkcję, a dopiero po odpowiedzi „nie znam takiej" — piaskownicę.
# Dzięki temu ta sama wersja aplikacji działa u recenzenta (sandbox) i u klienta.
API_PROD = "https://api.storekit.itunes.apple.com"
API_SANDBOX = "https://api.storekit-sandbox.itunes.apple.com"

# kod błędu App Store Server API: „nie ma takiej transakcji w tym środowisku"
ERR_NOT_FOUND = 4040010

# Stany subskrypcji z odpowiedzi Apple. 3 (ponawianie płatności) i 4 (okres
# łaski) zostawiają dostęp — karta mogła po prostu wygasnąć, a wyłączanie
# premium w środku takiej wymiany to najgorszy możliwy moment.
STATUS_ACTIVE = {1, 3, 4, 5}
STATUS_NAMES = {
    1: "aktywna", 2: "wygasła", 3: "ponawianie płatności",
    4: "okres łaski", 5: "cofnięta zgoda na odnowienie",
}


def configured() -> bool:
    """Czy da się w ogóle zapytać Apple. Bez klucza nie udajemy weryfikacji."""
    return bool(KEY_ID and ISSUER_ID and (KEY_PEM or _key_path()))


def _key_path() -> str:
    p = KEY_FILE if os.path.isabs(KEY_FILE) else os.path.join(_ROOT, KEY_FILE)
    return p if os.path.exists(p) else ""


def _private_key() -> str:
    """Klucz ES256: z pliku na komputerze, ze zmiennej na hostingu."""
    if KEY_PEM:
        return KEY_PEM
    with open(_key_path(), encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------- token dostępu

_lock = threading.Lock()
_token: list = [0.0, ""]        # [ważny do, token]


def _bearer() -> str:
    """Podpisany ES256 token do App Store Server API, trzymany do wygaśnięcia.

    Apple pozwala na maksymalnie godzinę; bierzemy 50 minut i odnawiamy z zapasem,
    żeby żądanie nie trafiło w moment przeterminowania.
    """
    now = time.time()
    with _lock:
        if _token[0] > now and _token[1]:
            return _token[1]

    import jwt                                    # PyJWT[crypto] — tylko tutaj

    private_key = _private_key()

    token = jwt.encode(
        {
            "iss": ISSUER_ID,
            "iat": int(now),
            "exp": int(now) + 3000,
            "aud": "appstoreconnect-v1",
            "bid": BUNDLE_ID,
        },
        private_key,
        algorithm="ES256",
        headers={"kid": KEY_ID, "typ": "JWT"},
    )
    with _lock:
        _token[0], _token[1] = now + 2700, token
    return token


# ----------------------------------------------------------------- zapytania


def _decode(signed: str) -> dict:
    """Ładunek JWS bez sprawdzania podpisu.

    Wolno tak, bo ten JWS przyszedł do nas prosto od Apple po TLS-ie — podpis
    potwierdzałby to, co już potwierdził certyfikat serwera. Tej funkcji NIE
    używamy do danych przysłanych przez telefon ani przez webhooka.
    """
    try:
        payload = signed.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError, TypeError):
        return {}


def _get(path: str) -> tuple[dict, str]:
    """Pyta produkcję, a gdy transakcji tam nie ma — piaskownicę.

    Zwraca (odpowiedź, środowisko). Pusty słownik = nie znaleziono nigdzie.
    """
    headers = {"Authorization": f"Bearer {_bearer()}"}
    for base, env in ((API_PROD, "Production"), (API_SANDBOX, "Sandbox")):
        try:
            r = requests.get(base + path, headers=headers, timeout=12)
        except requests.RequestException:
            continue
        if r.status_code == 200:
            try:
                return r.json() or {}, env
            except ValueError:
                return {}, env
        if r.status_code == 404:
            try:
                if (r.json() or {}).get("errorCode") == ERR_NOT_FOUND:
                    continue          # spróbuj w drugim środowisku
            except ValueError:
                pass
        # 401 (zły klucz) albo 5xx — dalsze pytanie o to samo nic nie da
        break
    return {}, ""


def subscription(transaction_id: str) -> dict | None:
    """Aktualny stan subskrypcji u Apple albo None, gdy nie da się jej potwierdzić.

    Zwraca: product_id, original_transaction_id, expires_at (ISO), status,
    active, revoked, environment.
    """
    if not (configured() and transaction_id):
        return None

    data, env = _get(f"/inApps/v1/subscriptions/{transaction_id}")
    groups = data.get("data") or []
    for group in groups:
        for last in group.get("lastTransactions") or []:
            info = _decode(last.get("signedTransactionInfo") or "")
            if not info:
                continue
            # Cudzy paragon albo paragon z innej aplikacji nie nadaje niczego.
            if info.get("bundleId") and info["bundleId"] != BUNDLE_ID:
                continue
            status = int(last.get("status") or 0)
            revoked = bool(info.get("revocationDate"))
            expires = info.get("expiresDate")
            renewal = _decode(last.get("signedRenewalInfo") or "")
            return {
                "product_id": info.get("productId") or "",
                "original_transaction_id": (
                    last.get("originalTransactionId")
                    or info.get("originalTransactionId") or ""
                ),
                "transaction_id": info.get("transactionId") or transaction_id,
                # nasz identyfikator konta wpisany przy zakupie (StoreKit
                # `appAccountToken`) — dzięki niemu powiadomienie o odnowieniu
                # trafia do właściwego konta nawet zanim telefon zdąży zgłosić zakup
                "app_account_token": str(info.get("appAccountToken") or ""),
                "expires_at": _iso(expires),
                "expires_ms": expires,
                "status": status,
                "status_label": STATUS_NAMES.get(status, "nieznany"),
                "active": status in STATUS_ACTIVE and not revoked,
                "revoked": revoked,
                # użytkownik wyłączył odnawianie — dostęp trwa do końca okresu
                "auto_renew": bool(renewal.get("autoRenewStatus")),
                "environment": info.get("environment") or env,
            }
    return None


def peek_notification(signed_payload: str) -> dict:
    """Z powiadomienia serwerowego wyjmuje TYLKO identyfikatory transakcji.

    Świadomie nie czytamy stąd ani produktu, ani daty końca, ani typu zdarzenia:
    to dane z internetu, a nie od Apple po TLS-ie. Identyfikator służy wyłącznie
    do zadania pytania `subscription()`, które sprowadzi prawdę wprost od Apple.
    Gdyby ktoś podszył się pod ten adres, najwyżej zmusi nas do odświeżenia
    cudzego stanu prawdziwymi danymi.
    """
    outer = _decode(signed_payload)
    data = outer.get("data") or {}
    info = _decode(data.get("signedTransactionInfo") or "")
    return {
        "notification_type": str(outer.get("notificationType") or ""),
        "transaction_id": str(info.get("transactionId") or ""),
        "original_transaction_id": str(
            info.get("originalTransactionId")
            or data.get("originalTransactionId") or ""
        ),
    }


def _iso(ms) -> str | None:
    """Milisekundy Apple → ISO 8601. Brak daty = nadanie bezterminowe."""
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None
