"""Konto, premium i synchronizacja — endpointy wspólne dla telefonu i panelu web.

Router wpinany w `dashboard.py`. Trzymamy to osobno, bo dashboard i tak jest długi,
a ta część ma zupełnie inne zależności niż reszta panelu.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

import apple_iap
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


def require_owner(v: sa.Viewer = Depends(viewer)) -> sa.Viewer:
    """Zależność dla akcji, które zmieniają CAŁY serwer, a nie dane jednego konta.

    Nasłuch newsów jest jeden i wspólny dla wszystkich, więc jego włącznik nie może
    stać otworem dla każdego zalogowanego. A stał: `/api/bot/stop` wymagało wcześniej
    tylko zalogowania, czyli dowolne konto mogło zgasić bota całej usłudze — albo
    włączyć go i naliczać rachunek za AI właścicielowi.

    403, nie 402: to nie jest funkcja, którą da się dokupić.

    Kim jest właściciel, ustala `supabase_auth._is_owner_request`: konto o adresie
    z `OWNER_EMAIL`, połączenie z tego komputera albo token panelu z pliku. Dzięki
    temu sterowanie działa także wtedy, gdy Supabase akurat nie odpowiada.
    """
    if not (v.owner or v.role == "owner"):
        raise HTTPException(403, "Ta operacja jest dostępna tylko dla konta właściciela")
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


@router.post("/api/premium/checkout")
async def premium_checkout(request: Request, v: sa.Viewer = Depends(require_login)):
    """Rozpoczęcie płatności — GOTOWE POD STRIPE, ale jeszcze nieuzbrojone.

    Aplikacja woła tu z wybranym planem. Gdy w `keys/stripe.env` pojawią się
    identyfikatory cen (`STRIPE_PRICE_MONTHLY`, `STRIPE_PRICE_YEARLY`),
    w miejscu oznaczonym niżej tworzy się sesję Stripe Checkout i zwraca `url`.
    Dopóki ich nie ma, zwracamy `ready: false` — apka pokazuje uprzejmy komunikat
    zamiast prowadzić donikąd.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    plan_id = str(body.get("plan") or "")
    if plan_id not in premium.PLAN_BY_ID:
        raise HTTPException(400, "Nieznany plan")

    price_id = premium.stripe_price_id(plan_id)
    if not price_id:
        return {
            "ready": False,
            "message": (
                "Płatności online uruchamiamy razem z wydaniem w sklepie. "
                "Do tego czasu premium nadajemy ręcznie na koncie "
                + (v.email or "") + "."
            ),
        }

    # TODO(owner): tu wpina się Stripe Checkout — utworzyć sesję dla `price_id`
    # przypisaną do `v.user_id` i zwrócić `{"ready": True, "url": session.url}`.
    return {"ready": False, "message": "Bramka płatności jest w trakcie konfiguracji."}


# ------------------------------------------------------- zakupy w App Store
#
# Na iPhonie sprzedaje Apple, nie Stripe — wytyczna 3.1.1 nie zostawia wyboru
# przy treściach cyfrowych. Telefon przeprowadza zakup przez StoreKit i przysyła
# tu SAM IDENTYFIKATOR transakcji; czym ta transakcja jest, ustala serwer u Apple
# (`apple_iap`). Ten sam kod obsługuje zakup, przywracanie zakupów i odnowienia.


def _apple_apply(user_id: str, transaction_id: str) -> dict:
    """Pyta Apple o transakcję i zapisuje z niej nadanie premium.

    Wspólny trzon trzech dróg (zakup, przywracanie, powiadomienie serwerowe), bo
    w każdej z nich mamy dokładnie jedno: identyfikator transakcji.
    """
    info = apple_iap.subscription(transaction_id)
    if not info:
        return {"ok": False, "message": "Apple nie potwierdził tego zakupu."}

    # Powiadomienie serwerowe nie wie, czyje jest konto. Wie to za to sama
    # transakcja: przy zakupie wpisujemy w nią identyfikator konta Portevo.
    if not user_id:
        user_id = info["app_account_token"]
    if not user_id:
        return {"ok": False, "message": "Nie wiadomo, do którego konta przypisać zakup."}

    plan = premium.plan_for_apple_product(info["product_id"])
    if not plan:
        return {"ok": False, "message": "Ten zakup nie dotyczy Portevo Premium."}

    # Zwrot pieniędzy i wygaśnięcie zapisujemy tak samo jak zakup — z datą końca
    # w przeszłości. Wiersz zostaje, więc historia nadań jest kompletna, a
    # `entitlement()` i tak liczy tylko te z datą w przyszłości.
    expires = info["expires_at"]
    if info["revoked"]:
        expires = sa._now_iso()

    # Jedna subskrypcja = jedno konto. Bez tego dwie osoby dzieliłyby się jednym
    # zakupem, podając ten sam identyfikator transakcji z dwóch telefonów.
    ref = info["original_transaction_id"] or transaction_id
    owner_of_ref = sa.user_for_provider_ref("apple", ref)
    if owner_of_ref and owner_of_ref != user_id:
        return {"ok": False, "message": (
            "Ta subskrypcja jest już przypisana do innego konta Portevo. "
            "Zaloguj się na nie albo napisz do nas przez zakładkę Kontakt."
        )}

    sa.set_entitlement(
        user_id=user_id, plan=plan, source="apple", expires_at=expires,
        provider_ref=ref,
        # brak zgody na odnowienie to jeszcze nie koniec dostępu — to znacznik,
        # dzięki któremu ekran konta może napisać „premium wygaśnie 12 marca"
        cancelled_at=(None if info["auto_renew"] else sa._now_iso()),
        note=f"App Store · {info['environment']}",
    )
    return {"ok": True, "premium": info["active"], "plan": plan,
            "expires_at": info["expires_at"], "status": info["status_label"]}


@router.post("/api/premium/apple/verify")
async def premium_apple_verify(request: Request, v: sa.Viewer = Depends(require_login)):
    """Potwierdzenie zakupu z telefonu. Apka woła to zaraz po udanej płatności.

    Zwraca `ok: false` z komunikatem zamiast błędu HTTP — użytkownik ma wtedy na
    ekranie zdanie po polsku, a nie „500". Pieniądze i tak są u Apple, więc
    najgorsze, co się może stać, to przywrócenie zakupu za chwilę.
    """
    if not apple_iap.configured():
        return {"ok": False, "message": "Weryfikacja zakupów nie jest jeszcze skonfigurowana."}
    if not v.user_id:
        # właściciel na tokenie panelu — premium ma z urzędu, nie ma czego kupować
        return {"ok": False, "message": "Zaloguj się kontem Portevo, żeby przypisać zakup."}
    try:
        body = await request.json()
    except Exception:
        body = {}
    transaction_id = str(body.get("transaction_id") or "").strip()
    if not transaction_id:
        raise HTTPException(400, "Brak identyfikatora transakcji")
    return _apple_apply(v.user_id, transaction_id)


@router.post("/api/apple/notifications")
async def apple_notifications(request: Request):
    """App Store Server Notifications V2 — odnowienia, rezygnacje, zwroty.

    Bez tego premium wygasłoby dopiero przy następnym uruchomieniu aplikacji, a po
    zwrocie pieniędzy działałoby do końca opłaconego okresu.

    Ładunku Apple NIE ufamy na słowo i nie sprawdzamy jego podpisu certyfikatami
    root — wyciągamy z niego wyłącznie identyfikator transakcji i pytamy o niego
    App Store Server API. Podszycie się pod to żądanie daje więc tyle, co
    poproszenie nas o odświeżenie cudzego stanu prawdziwymi danymi od Apple.

    Adres do wpisania w App Store Connect (Monetization → App Store Server
    Notifications, wariant V2): https://www.portevo.pl/api/apple/notifications
    """
    if not apple_iap.configured():
        return {"ok": False}
    try:
        body = await request.json()
    except Exception:
        body = {}

    payload = apple_iap.peek_notification(str(body.get("signedPayload") or ""))
    transaction_id = payload.get("transaction_id") or ""
    original_id = payload.get("original_transaction_id") or ""
    if not (transaction_id or original_id):
        return {"ok": False}

    # Kogo dotyczy: wiersz nadania pamięta `originalTransactionId` z zakupu.
    # Gdy go jeszcze nie ma (powiadomienie wyprzedziło telefon), konto ustali
    # `_apple_apply` z `appAccountToken` w transakcji potwierdzonej przez Apple.
    user_id = sa.user_for_provider_ref("apple", original_id or transaction_id)
    res = _apple_apply(user_id, transaction_id or original_id)
    return {"ok": bool(res.get("ok"))}


@router.post("/api/contact")
async def contact(request: Request, v: sa.Viewer = Depends(require_login)):
    """Wiadomość od użytkownika prosto do twórców — perk wersji premium.

    Przepuszcza treść na skrzynkę z `mailer.CONTACT_TO` (Reply-To = adres autora
    wiadomości) i zawsze zapisuje kopię lokalnie, żeby nic nie zginęło, nawet
    zanim SMTP zostanie uzbrojony. Bez premium zwraca `need_premium`, a apka
    kieruje do strony premium.
    """
    import mailer

    try:
        body = await request.json()
    except Exception:
        body = {}
    message = str(body.get("message") or "").strip()
    topic = str(body.get("topic") or "").strip()[:120]
    if not message:
        raise HTTPException(400, "Napisz treść wiadomości")
    message = message[:4000]

    if not v.premium:
        return {
            "ok": False, "need_premium": True,
            "message": "Bezpośredni kontakt z twórcami jest częścią wersji premium.",
        }

    mailer.store_feedback(v.user_id, v.email, topic, message)
    delivered = mailer.send_contact(v.email, topic, message)
    sync.log_event(v.user_id or None, "contact_message", topic or "", "mobile",
                   {"delivered": delivered, "len": len(message)})
    return {"ok": True, "delivered": delivered}


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
