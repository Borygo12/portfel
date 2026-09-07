"""Płatności przez Stripe — sprzedaż na stronie, nie na iPhonie.

Podział jest wymuszony przez Apple: w aplikacji z App Store treści cyfrowe
sprzedaje wyłącznie StoreKit (wytyczna 3.1.1) i tym zajmuje się `apple_iap`.
Ten moduł obsługuje **drugą drogę** — zakup w przeglądarce na portevo.pl, gdzie
Apple nie ma nic do rzeczy, a prowizja jest kilkukrotnie niższa.

Zasada ta sama, co przy Apple: **klient nigdy nie decyduje o swoim premium**.
Przeglądarka dostaje wyłącznie adres kasy Stripe; o tym, że pieniądze wpłynęły,
dowiadujemy się z podpisanego powiadomienia (webhook), a nie z powrotu
użytkownika na stronę sukcesu — ten adres da się przecież wpisać ręcznie.

Dlaczego bez biblioteki `stripe`, na gołym `requests`:

* API Stripe to zwykłe formularze POST — cały nasz kontakt z nim to trzy wywołania.
* Weryfikacja podpisu webhooka to dziesięć linijek HMAC-a, a nie powód na kolejną
  zależność w obrazie kontenera.
* `apple_iap` rozmawia z Apple dokładnie tak samo. Jeden wzorzec, nie dwa.

Konfiguracja w `keys/stripe.env` (plik nie idzie do repozytorium), a na hostingu
w tablicy zmiennych — wczytuje go `supabase_auth._load_env_file` przy starcie.

    STRIPE_SECRET_KEY=sk_live_...      # Developers -> API keys
    STRIPE_WEBHOOK_SECRET=whsec_...    # Developers -> Webhooks -> Signing secret
    STRIPE_PRICE_MONTHLY=price_...     # Product catalog -> cena planu miesięcznego
    STRIPE_PRICE_YEARLY=price_...      # ... i rocznego

Dopóki tych wartości nie ma, `configured()` zwraca False, a endpoint zakupu mówi
o tym wprost zamiast udawać kasę.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from datetime import datetime, timedelta, timezone

import requests

import premium
import supabase_auth as sa

API = "https://api.stripe.com/v1"

# Ile sekund tolerujemy między znacznikiem czasu w podpisie a naszym zegarem.
# Pięć minut to wartość z dokumentacji Stripe: dość na ponowienie i rozjazd
# zegarów, za mało, żeby ktoś odtworzył podsłuchane żądanie następnego dnia.
PODPIS_TOLERANCJA = 300

# Stany subskrypcji, przy których dostęp ZOSTAJE. `past_due` i `unpaid` to jeszcze
# nie koniec — Stripe przez kilka dni ponawia obciążenie karty, a odcinanie
# premium w środku takiej wymiany to najgorszy możliwy moment (jak u Apple).
STANY_AKTYWNE = {"trialing", "active", "past_due", "unpaid"}


def _klucz() -> str:
    return (os.environ.get("STRIPE_SECRET_KEY") or "").strip()


def configured() -> bool:
    """Czy da się w ogóle utworzyć kasę. Bez klucza nie udajemy płatności."""
    return bool(_klucz() and premium.stripe_price_id("monthly"))


def _api(path: str, dane: dict | None = None, metoda: str = "POST") -> dict | None:
    """Jedno wywołanie API Stripe. `None` = nie udało się; wołający mówi to po polsku."""
    klucz = _klucz()
    if not klucz:
        return None
    try:
        r = requests.request(
            metoda, f"{API}/{path}",
            auth=(klucz, ""),
            data=dane if metoda == "POST" else None,
            params=dane if metoda != "POST" else None,
            timeout=20,
        )
        if r.status_code >= 400:
            print(f"[stripe] {metoda} {path} -> {r.status_code}: {r.text[:300]}")
            return None
        return r.json()
    except Exception as e:                              # sieć, timeout, śmieci w JSON
        print(f"[stripe] {metoda} {path} nie doszło: {e}")
        return None


# ------------------------------------------------------------------- adresy


def _adres_zwrotny(sufiks: str) -> str:
    """Dokąd Stripe odsyła klienta. Domyślnie na naszą domenę kanoniczną.

    Adres wolno nadpisać (`STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL`) — przy pracy
    na komputerze kasa musi wracać na `127.0.0.1`, a nie na produkcję.
    """
    nadpisany = (os.environ.get(
        "STRIPE_SUCCESS_URL" if sufiks == "ok" else "STRIPE_CANCEL_URL") or "").strip()
    if nadpisany:
        return nadpisany
    try:
        from seo import site
        baza = site.URL
    except Exception:
        baza = "https://www.portevo.pl"
    return f"{baza}/?zakup={sufiks}"


# ------------------------------------------------------------------- zakup


def checkout_url(user_id: str, email: str, plan_id: str, metoda: str = "card") -> tuple[str, str]:
    """Adres kasy Stripe dla tego konta i planu. Zwraca `(url, komunikat_błędu)`.

    Dwie drogi, bo BLIK **nie umie płatności cyklicznych** — Stripe pozwala nim
    zapłacić raz i tyle. Zamiast więc chować w Polsce najpopularniejszy sposób
    płatności, sprzedajemy przez BLIK ten sam okres jako pojedynczą płatność:
    klient dostaje miesiąc albo rok, a przed końcem po prostu kupuje ponownie.
    Kartą idzie zwykła subskrypcja, która odnawia się sama.
    """
    plan = premium.PLAN_BY_ID.get(plan_id)
    if not plan:
        return "", "Nieznany plan."
    if not _klucz():
        return "", "Bramka płatności nie jest jeszcze skonfigurowana."

    wspolne = {
        "success_url": _adres_zwrotny("ok"),
        "cancel_url": _adres_zwrotny("anulowany"),
        "client_reference_id": user_id,
        "locale": "pl",
        "metadata[user_id]": user_id,
        "metadata[plan]": plan_id,
        "line_items[0][quantity]": "1",
    }
    if email:
        wspolne["customer_email"] = email

    if metoda == "blik":
        # Cena wprost w żądaniu (`price_data`), a nie osobny cennik w panelu:
        # kwota i tak pochodzi z `premium.PLANS`, więc dublowanie jej w Stripe
        # tworzyłoby drugie miejsce, w którym promocja może się rozjechać.
        dane = {
            **wspolne,
            "mode": "payment",
            "payment_method_types[0]": "blik",
            "line_items[0][price_data][currency]": str(plan["currency"]).lower(),
            "line_items[0][price_data][unit_amount]": str(round(float(plan["price"]) * 100)),
            "line_items[0][price_data][product_data][name]":
                f"Portevo Premium — {str(plan['label']).lower()}",
            "payment_intent_data[metadata][user_id]": user_id,
            "payment_intent_data[metadata][plan]": plan_id,
        }
    else:
        price_id = premium.stripe_price_id(plan_id)
        if not price_id:
            return "", "Ten plan nie ma jeszcze ceny w Stripe."
        dane = {
            **wspolne,
            "mode": "subscription",
            "line_items[0][price]": price_id,
            "allow_promotion_codes": "true",
            # Metadane na subskrypcji, nie tylko na sesji: odnowienia po roku
            # przychodzą już bez sesji, a muszą wiedzieć, czyje są.
            "subscription_data[metadata][user_id]": user_id,
            "subscription_data[metadata][plan]": plan_id,
        }

    sesja = _api("checkout/sessions", dane)
    if not sesja or not sesja.get("url"):
        return "", "Nie udało się otworzyć płatności. Spróbuj za chwilę."
    return sesja["url"], ""


def portal_url(email: str) -> tuple[str, str]:
    """Adres panelu Stripe, w którym klient sam anuluje albo zmienia kartę.

    Na paywallu obiecujemy „rezygnujesz jednym kliknięciem" — to jest to
    kliknięcie. Klienta szukamy po adresie e-mail, bo tym samym adresem założone
    jest konto Portevo i to on trafia do kasy jako `customer_email`.
    """
    if not (_klucz() and email):
        return "", "Zarządzanie subskrypcją nie jest jeszcze dostępne."
    lista = _api("customers", {"email": email, "limit": "1"}, metoda="GET")
    dane = (lista or {}).get("data") or []
    if not dane:
        return "", "Na tym koncie nie ma subskrypcji kupionej na stronie."
    sesja = _api("billing_portal/sessions", {
        "customer": dane[0]["id"],
        "return_url": _adres_zwrotny("ok"),
    })
    if not sesja or not sesja.get("url"):
        return "", "Nie udało się otworzyć panelu subskrypcji. Spróbuj za chwilę."
    return sesja["url"], ""


# --------------------------------------------------------------- powiadomienia


def verify_signature(payload: bytes, naglowek: str) -> bool:
    """Czy to powiadomienie naprawdę przyszło ze Stripe.

    Adres webhooka jest publiczny, więc bez tego sprawdzenia każdy mógłby wysłać
    nam „opłacono" na cudze konto. Podpisu nie da się podrobić znajomością samej
    treści — liczy go klucz `whsec_…`, którego nie ma nikt poza nami i Stripe.
    """
    sekret = (os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip()
    if not (sekret and naglowek):
        return False

    czas, podpisy = "", []
    for czesc in naglowek.split(","):
        k, _, v = czesc.strip().partition("=")
        if k == "t":
            czas = v
        elif k == "v1":
            podpisy.append(v)
    if not (czas and podpisy):
        return False
    try:
        if abs(time.time() - int(czas)) > PODPIS_TOLERANCJA:
            return False
    except ValueError:
        return False

    oczekiwany = hmac.new(
        sekret.encode(), f"{czas}.".encode() + payload, hashlib.sha256,
    ).hexdigest()
    return any(hmac.compare_digest(oczekiwany, p) for p in podpisy)


def _iso(unix: float) -> str:
    return datetime.fromtimestamp(float(unix), timezone.utc).isoformat()


def _plan_po_cenie(price_id: str) -> str:
    """Cena ze Stripe → nasz plan. Pusty ciąg = to nie nasza cena.

    Dzięki temu subskrypcja czegoś innego (choćby z drugiej marki na tym samym
    koncie Stripe) nie nada nikomu premium w Portevo.
    """
    for p in premium.PLANS:
        if price_id and premium.stripe_price_id(p["id"]) == price_id:
            return p["id"]
    return ""


def _zastosuj_subskrypcje(sub: dict) -> bool:
    """Subskrypcja ze Stripe → wiersz nadania premium.

    Jeden wiersz na subskrypcję: kluczem jest jej identyfikator, stały przez
    wszystkie odnowienia, więc dwunaste odnowienie aktualizuje ten sam wiersz,
    zamiast dokładać dwunasty.
    """
    sub_id = str((sub or {}).get("id") or "")
    if not sub_id:
        return False

    pozycje = (sub.get("items") or {}).get("data") or []
    price_id = ((pozycje[0].get("price") or {}).get("id") or "") if pozycje else ""
    plan = _plan_po_cenie(price_id) or str((sub.get("metadata") or {}).get("plan") or "")
    if plan not in premium.PLAN_BY_ID:
        return False                                # nie nasz produkt — nie nasza sprawa

    user_id = str((sub.get("metadata") or {}).get("user_id") or "")
    if not user_id:
        user_id = sa.user_for_provider_ref("stripe", sub_id)
    if not user_id:
        print(f"[stripe] subskrypcja {sub_id} bez konta — pomijam")
        return False

    # Jedna subskrypcja = jedno konto. Bez tego dwie osoby dzieliłyby się jednym
    # zakupem, gdyby ktoś podmienił metadane w drodze powrotnej.
    wlasciciel = sa.user_for_provider_ref("stripe", sub_id)
    if wlasciciel and wlasciciel != user_id:
        print(f"[stripe] subskrypcja {sub_id} należy już do innego konta")
        return False

    status = str(sub.get("status") or "")
    koniec = sub.get("current_period_end")
    # Nieaktywna subskrypcja (anulowana, po zwrocie, po nieudanych płatnościach)
    # zapisuje się tak samo jak aktywna, tylko z datą końca w przeszłości. Wiersz
    # zostaje, więc historia nadań jest kompletna, a `entitlement()` i tak liczy
    # wyłącznie te z datą w przyszłości.
    expires = _iso(koniec) if (koniec and status in STANY_AKTYWNE) else sa._now_iso()

    return sa.set_entitlement(
        user_id=user_id, plan=plan, source="stripe", expires_at=expires,
        provider_ref=sub_id,
        # rezygnacja nie odcina dostępu od razu — to znacznik, dzięki któremu
        # ekran konta umie napisać „premium wygaśnie 12 marca"
        cancelled_at=(sa._now_iso() if sub.get("cancel_at_period_end") else None),
        note=f"Stripe · {status}",
    )


def _zastosuj_jednorazowa(sesja: dict) -> bool:
    """Zakup BLIK-iem — jeden okres z góry, bez odnowienia."""
    if str(sesja.get("payment_status") or "") != "paid":
        return False
    meta = sesja.get("metadata") or {}
    user_id = str(meta.get("user_id") or "") or str(sesja.get("client_reference_id") or "")
    plan = str(meta.get("plan") or "")
    if not (user_id and plan in premium.PLAN_BY_ID):
        return False

    dni = 366 if plan == "yearly" else 31
    expires = (datetime.now(timezone.utc) + timedelta(days=dni)).isoformat()
    return sa.set_entitlement(
        user_id=user_id, plan=plan, source="stripe", expires_at=expires,
        provider_ref=str(sesja.get("id") or ""),
        # płatność jednorazowa z definicji się nie odnawia — od razu wiadomo, że
        # dostęp ma termin, i ekran konta może o tym uprzedzić
        cancelled_at=sa._now_iso(),
        note="Stripe · BLIK (jednorazowo)",
    )


def handle_event(event: dict) -> bool:
    """Powiadomienie ze Stripe → zmiana w nadaniach. `True` = coś zapisaliśmy.

    Nasłuchujemy trzech rzeczy, bo tyle wystarczy: dopięcia kasy (zakup), zmiany
    stanu subskrypcji (odnowienie, rezygnacja, nieudana płatność) i jej końca.
    Reszty zdarzeń Stripe nie musimy nawet czytać.
    """
    typ = str(event.get("type") or "")
    obiekt = ((event.get("data") or {}).get("object")) or {}

    if typ == "checkout.session.completed":
        if str(obiekt.get("mode") or "") == "payment":
            return _zastosuj_jednorazowa(obiekt)
        sub_id = obiekt.get("subscription")
        if not sub_id:
            return False
        # Sesja niesie tylko identyfikator subskrypcji. O jej stan pytamy Stripe,
        # zamiast składać go z tego, co akurat było w ładunku — tak samo jak przy
        # Apple pytamy o transakcję, a nie ufamy paragonowi z telefonu.
        sub = _api(f"subscriptions/{sub_id}", metoda="GET")
        return _zastosuj_subskrypcje(sub) if sub else False

    if typ in ("customer.subscription.created", "customer.subscription.updated",
               "customer.subscription.deleted"):
        return _zastosuj_subskrypcje(obiekt)

    return False
