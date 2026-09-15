"""Kody polecające twórców — przypisanie konta, darmowe premium z puli i raport prowizji.

Kampania z twórcami stoi na trzech obietnicach i każda ma tu swoje miejsce:

* **kod przypisuje konto do twórcy na zawsze** — `apply()`; jedno konto = jeden kod,
  bez przepisywania na innego (inaczej twórcy podbieraliby sobie widzów);
* **pierwsze osoby z kodem dostają premium za darmo** — pula w `referral_codes`,
  zajmowana atomowo w SQL (`apply_referral`, migracja 0006);
* **twórca dostaje procent od płatności poleconych kont** — `raport()`, liczony
  z `premium_events` (zakupy i odnowienia ze Stripe oraz z App Store).

Darmowe premium wydajemy WYŁĄCZNIE, gdy kod wpisano w przeglądarce. W aplikacji
z App Store kod tylko przypisuje konto: odblokowanie premium kodem wpisanym
w aplikacji to „własny mechanizm odblokowania" z wytycznej 3.1.1 i gotowe
odrzucenie wydania. To samo konto wpisuje potem ten sam kod na portevo.pl
i odbiera nagrodę — premium ze strony wolno używać w aplikacji (3.1.3(b)).

Twórca w raporcie dostaje same liczby. Żadnych adresów e-mail ani identyfikatorów
poleconych — to są dane naszych użytkowników, nie jego.
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import requests

import supabase_auth as sa

# ------------------------------------------------------------ od czego prowizja
#
# Prowizja liczy się od przychodu NETTO — od tego, co realnie do nas trafia.
# „50% ceny brutto" przy 5,99 zł to 3,00 zł, a z App Store po VAT i prowizji Apple
# dostajemy ok. 4,14 zł — zostałoby nam 1,14 zł na serwery, AI i podatek.
#
# VAT: Apple odprowadza go zawsze sam, więc po stronie App Store odejmujemy go
# zawsze. Przy Stripe zależy to od tego, czy jesteś płatnikiem VAT — bez
# rejestracji ustaw POLECENIA_VAT_STRIPE=0.
VAT_APPLE = 0.23
VAT_STRIPE = float(os.environ.get("POLECENIA_VAT_STRIPE", "0.23") or 0)
# Program dla małych firm (Small Business Program) — 15%. Bez niego 30%.
PROWIZJA_APPLE = float(os.environ.get("POLECENIA_PROWIZJA_APPLE", "0.15") or 0)
# Standardowa opłata Stripe za kartę z EOG: 1,5% + 1 zł (BLIK wychodzi podobnie).
STRIPE_PROCENT = 0.015
STRIPE_STALA_GROSZE = 100

_WZOR_KODU = re.compile(r"^[A-Z0-9_-]{3,24}$")

KOMUNIKATY = {
    "unknown": "Nie znamy takiego kodu. Sprawdź pisownię — wielkość liter nie ma znaczenia.",
    "other": "To konto ma już przypisany kod {code}. Jedno konto może wspierać jednego twórcę.",
    "own": "To Twój własny kod — nie da się polecić samego siebie.",
    "paid": "Kod polecający wpisuje się przed zakupem premium. To konto ma już aktywną subskrypcję.",
    "login": "Zaloguj się, żeby przypisać kod do konta.",
    "off": "Kody polecające jeszcze nie działają. Spróbuj za chwilę.",
}


def normalize(kod: str) -> str:
    """Wpis użytkownika → kod z bazy albo pusty ciąg, gdy to nie może być kod.

    Ludzie przepisują kody z filmu: „@kasia.inwestuje", „ Kasia ", „#KASIA".
    Zdejmujemy to, co na pewno nie jest częścią kodu, a polskie znaki zamieniamy
    na łacińskie — „ŁUKASZ" z napisów w filmie ma trafić w kod „LUKASZ".
    """
    t = (kod or "").strip().replace("ł", "l").replace("Ł", "L")
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[\s@#.]", "", t).upper()
    return t if _WZOR_KODU.match(t) else ""


# -------------------------------------------------------------------- baza


def _naglowki() -> dict:
    return {"apikey": sa.SERVICE, "Authorization": f"Bearer {sa.SERVICE}",
            "Content-Type": "application/json"}


def dziala() -> bool:
    return bool(sa.URL and sa.SERVICE)


def _get(tabela: str, params: dict) -> list | None:
    """Odczyt kluczem serwisowym. `None` = baza nie odpowiedziała albo brak tabeli
    (migracja 0006 jeszcze nie uruchomiona) — to co innego niż pusta lista."""
    if not dziala():
        return None
    try:
        r = requests.get(f"{sa.URL}/rest/v1/{tabela}", params=params,
                         headers=_naglowki(), timeout=10)
        return r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def _rpc(nazwa: str, dane: dict) -> dict | None:
    if not dziala():
        return None
    try:
        r = requests.post(f"{sa.URL}/rest/v1/rpc/{nazwa}", json=dane,
                          headers=_naglowki(), timeout=12)
        if r.status_code != 200:
            print(f"[polecenia] rpc {nazwa} -> {r.status_code}: {r.text[:200]}")
            return None
        return r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[polecenia] rpc {nazwa} nie doszło: {e}")
        return None


def _kod(kod: str) -> dict | None:
    rows = _get("referral_codes", {"code": f"eq.{kod}", "select": "*"})
    return rows[0] if rows else None


# ------------------------------------------------------------- użytkownik


def sprawdz(wpis: str) -> dict:
    """Czy taki kod istnieje — dla okna logowania, zanim ktokolwiek ma konto."""
    kod = normalize(wpis)
    # Puste zapytanie to próba „czy kody w ogóle działają" — okno logowania pyta
    # tak przy otwarciu i chowa pole, dopóki baza kodów nie jest gotowa.
    c = _kod(kod) if kod else None
    if c is None and _get("referral_codes", {"select": "code", "limit": "1"}) is None:
        return {"ok": False, "off": True, "message": KOMUNIKATY["off"]}
    if not c or not c.get("active"):
        return {"ok": False, "message": KOMUNIKATY["unknown"]}
    return {
        "ok": True, "code": kod,
        "creator": c.get("creator_name") or "", "handle": c.get("creator_handle") or "",
        "free_days": int(c.get("free_days") or 0),
        "slots_left": max(0, int(c.get("free_slots") or 0) - int(c.get("free_used") or 0)),
    }


def przypisz(user_id: str, wpis: str, zrodlo: str, platforma: str) -> dict:
    """Przypisuje konto do kodu; w przeglądarce odbiera też darmowe premium z puli."""
    kod = normalize(wpis)
    if not kod:
        return {"ok": False, "error": "unknown", "message": KOMUNIKATY["unknown"]}
    if not user_id:
        return {"ok": False, "error": "login", "message": KOMUNIKATY["login"]}

    platforma = platforma if platforma in ("web", "ios", "android") else "web"
    wynik = _rpc("apply_referral", {
        "p_user": user_id, "p_code": kod, "p_source": zrodlo,
        "p_platform": platforma, "p_reward": platforma == "web",
    })
    if not isinstance(wynik, dict):
        return {"ok": False, "error": "off", "message": KOMUNIKATY["off"]}

    if not wynik.get("ok"):
        blad = str(wynik.get("error") or "unknown")
        tekst = KOMUNIKATY.get(blad, KOMUNIKATY["unknown"]).format(code=wynik.get("code") or "")
        return {"ok": False, "error": blad, "message": tekst, "code": wynik.get("code")}

    if wynik.get("reward_days"):
        sa.forget(user_id)          # premium ma być widać od razu, nie po minucie cache
    try:
        import supabase_sync as sync
        sync.log_event(user_id, "referral_apply", feature=kod, platform=platforma,
                       meta={"zrodlo": zrodlo, "nagroda_dni": wynik.get("reward_days")})
    except Exception:
        pass
    return wynik


def moj(user_id: str) -> dict:
    """Kod przypisany do konta i to, czy da się jeszcze odebrać premium od twórcy."""
    if not user_id:
        return {"code": None}
    rows = _get("referrals", {"user_id": f"eq.{user_id}",
                              "select": "code,source,created_at,reward_days,reward_at"})
    if rows is None:
        return {"code": None, "available": False}
    if not rows:
        return {"code": None, "available": True}
    r = rows[0]
    c = _kod(r["code"]) or {}
    wolne = max(0, int(c.get("free_slots") or 0) - int(c.get("free_used") or 0))
    return {
        "available": True,
        "code": r["code"],
        "creator": c.get("creator_name") or "",
        "handle": c.get("creator_handle") or "",
        "source": r.get("source"),
        "created_at": r.get("created_at"),
        "reward_days": r.get("reward_days"),
        # Odebrać można tylko raz i tylko w przeglądarce — o tym drugim decyduje
        # klient (pokazuje przycisk wyłącznie na webie), serwer i tak to pilnuje.
        "can_claim": (not r.get("reward_at") and bool(c.get("active"))
                      and wolne > 0 and int(c.get("free_days") or 0) > 0),
        "free_days": int(c.get("free_days") or 0),
    }


# --------------------------------------------------------- panel właściciela


def zapisz_kod(dane: dict) -> dict:
    """Zakłada albo poprawia kod twórcy. Pola, których nie podano, zostają bez zmian."""
    kod = normalize(str(dane.get("code") or ""))
    if not kod:
        return {"ok": False, "message": "Kod: 3–24 znaki, litery, cyfry, „-” albo „_”."}
    wiersz: dict = {"code": kod}
    for pole in ("creator_name", "creator_handle", "contact_email", "note"):
        if pole in dane:
            wiersz[pole] = (str(dane.get(pole) or "").strip() or None)
    for pole in ("free_slots", "free_days"):
        if dane.get(pole) not in (None, ""):
            wiersz[pole] = max(0, int(dane[pole]))
    if dane.get("commission_pct") not in (None, ""):
        wiersz["commission_pct"] = min(100.0, max(0.0, float(dane["commission_pct"])))
    if "active" in dane:
        wiersz["active"] = bool(dane["active"])

    istnieje = _kod(kod)
    if not istnieje and not wiersz.get("creator_name"):
        return {"ok": False, "message": "Podaj nazwę twórcy."}
    try:
        r = requests.post(
            f"{sa.URL}/rest/v1/referral_codes", params={"on_conflict": "code"},
            headers={**_naglowki(), "Prefer": "resolution=merge-duplicates,return=representation"},
            json=wiersz, timeout=10)
    except requests.RequestException:
        return {"ok": False, "message": KOMUNIKATY["off"]}
    if r.status_code >= 300:
        return {"ok": False, "message": f"Baza odrzuciła zapis ({r.status_code}). "
                                        "Czy migracja 0006 jest uruchomiona?"}
    return {"ok": True, "code": kod}


def _miesiac(tekst: str) -> tuple[datetime, datetime]:
    """„2026-09" → [1 września, 1 października). Pusty = bieżący miesiąc."""
    teraz = datetime.now(timezone.utc)
    try:
        rok, mies = (int(x) for x in (tekst or "").split("-")[:2])
    except ValueError:
        rok, mies = teraz.year, teraz.month
    od = datetime(rok, mies, 1, tzinfo=timezone.utc)
    do = datetime(rok + (mies == 12), mies % 12 + 1, 1, tzinfo=timezone.utc)
    return od, do


def _czas(iso: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _netto(kwota: int, zrodlo: str) -> float:
    """Grosze brutto zapłacone przez klienta → grosze, które realnie do nas trafiają."""
    if zrodlo == "apple":
        return kwota / (1 + VAT_APPLE) * (1 - PROWIZJA_APPLE)
    oplata = kwota * STRIPE_PROCENT + STRIPE_STALA_GROSZE
    return max(0.0, kwota / (1 + VAT_STRIPE) - oplata)


def _zl(grosze: float) -> str:
    return f"{grosze / 100:,.2f} zł".replace(",", " ").replace(".", ",")


def raport(miesiac: str = "") -> dict:
    """Statystyki każdego kodu za miesiąc + gotowy tekst maila do twórcy."""
    od, do = _miesiac(miesiac)
    kody = _get("referral_codes", {"select": "*", "order": "created_at.asc"})
    if kody is None:
        return {"ok": False, "message": "Brak tabel kodów — uruchom migrację 0006 w Supabase."}
    polecenia = _get("referrals", {"select": "user_id,code,created_at,reward_at", "limit": "20000"}) or []

    przypisanie: dict[str, tuple[str, datetime]] = {}
    for p in polecenia:
        kiedy = _czas(p.get("created_at"))
        if p.get("user_id") and kiedy:
            przypisanie[p["user_id"]] = (p["code"], kiedy)

    zdarzenia = _get("premium_events", {
        "select": "user_id,event,platform,meta,created_at",
        "event": "in.(purchase,renewal,refund)",
        # dwa warunki na tej samej kolumnie = dwa parametry o tej samej nazwie
        "created_at": [f"gte.{od.isoformat()}", f"lt.{do.isoformat()}"],
        "limit": "20000",
    }) or []

    # Kto z poleconych płaci TERAZ (aktywna subskrypcja, nie darmowa z kodu).
    placacy: set[str] = set()
    if przypisanie:
        teraz = datetime.now(timezone.utc)
        for e in _get("entitlements", {"select": "user_id,expires_at",
                                       "source": "in.(stripe,apple)", "limit": "20000"}) or []:
            koniec = _czas(e.get("expires_at"))
            if e.get("user_id") in przypisanie and (koniec is None or koniec > teraz):
                placacy.add(e["user_id"])

    staty = {k["code"]: {
        "nowe": 0, "razem": 0, "platnosci": 0, "zwroty": 0,
        "brutto": 0, "netto": 0.0, "inne_waluty": 0, "placacy": 0,
    } for k in kody}

    for p in polecenia:
        s = staty.get(p.get("code"))
        kiedy = _czas(p.get("created_at"))
        if s is None or not kiedy or kiedy >= do:
            continue
        s["razem"] += 1
        if kiedy >= od:
            s["nowe"] += 1
    for uid in placacy:
        staty[przypisanie[uid][0]]["placacy"] += 1

    policzone: set[tuple] = set()
    for z in zdarzenia:
        uid = z.get("user_id")
        if uid not in przypisanie:
            continue
        kod, od_kiedy = przypisanie[uid]
        kiedy = _czas(z.get("created_at"))
        # prowizja należy się od płatności PO przypisaniu kodu, nigdy wstecz
        if not kiedy or kiedy < od_kiedy or kod not in staty:
            continue
        meta = z.get("meta") or {}
        klucz = (z.get("event"), meta.get("transakcja") or meta.get("sesja")
                 or meta.get("faktura") or meta.get("oplata") or z.get("created_at"))
        if klucz in policzone:
            continue                                  # to samo zdarzenie zapisane dwa razy
        policzone.add(klucz)

        s = staty[kod]
        if str(meta.get("waluta") or "pln").lower() != "pln":
            s["inne_waluty"] += 1
            continue
        kwota = int(meta.get("kwota") or 0)
        netto = _netto(kwota, "apple" if z.get("platform") == "apple" else "stripe")
        if z.get("event") == "refund":
            s["zwroty"] += 1
            s["brutto"] -= kwota
            s["netto"] -= netto
        else:
            s["platnosci"] += 1
            s["brutto"] += kwota
            s["netto"] += netto

    wynik = []
    nazwa_miesiaca = f"{od.month:02d}.{od.year}"
    for k in kody:
        s = staty[k["code"]]
        procent = float(k.get("commission_pct") or 0)
        prowizja = max(0.0, s["netto"] * procent / 100)
        wolne = max(0, int(k.get("free_slots") or 0) - int(k.get("free_used") or 0))
        wynik.append({
            "code": k["code"], "creator": k.get("creator_name"), "handle": k.get("creator_handle"),
            "email": k.get("contact_email"), "active": k.get("active"),
            "commission_pct": procent, "free_slots": k.get("free_slots"),
            "free_used": k.get("free_used"), "free_days": k.get("free_days"),
            **s, "netto": round(s["netto"]), "prowizja": round(prowizja),
            "mail": _mail(k, s, prowizja, wolne, nazwa_miesiaca),
        })
    return {"ok": True, "miesiac": f"{od.year}-{od.month:02d}", "od": od.isoformat(),
            "do": do.isoformat(), "kody": wynik}


def _mail(k: dict, s: dict, prowizja: float, wolne: int, miesiac: str) -> str:
    """Tekst comiesięcznego maila do twórcy — do skopiowania i wysłania."""
    imie = (k.get("creator_name") or "").split(" ")[0] or "Cześć"
    linie = [
        f"Temat: Portevo × {k.get('creator_name')} — podsumowanie kodu {k['code']} za {miesiac}",
        "",
        f"Cześć {imie}!",
        "",
        f"Poniżej statystyki Twojego kodu {k['code']} za {miesiac}:",
        "",
        f"• Nowe konta z Twoim kodem w tym miesiącu: {s['nowe']}",
        f"• Wszystkie konta z Twoim kodem: {s['razem']}",
        f"• Osoby z aktywną płatną subskrypcją: {s['placacy']}",
        f"• Darmowe premium dla widzów: wykorzystane {k.get('free_used') or 0} z {k.get('free_slots') or 0}"
        + (f" (zostało {wolne})" if wolne else ""),
        f"• Płatności od poleconych osób: {s['platnosci']}"
        + (f" (zwroty: {s['zwroty']})" if s["zwroty"] else ""),
        f"• Wartość tych płatności: {_zl(s['brutto'])} brutto / {_zl(s['netto'])} netto",
        f"• Twoja prowizja ({float(k.get('commission_pct') or 0):g}% netto): {_zl(prowizja)}",
    ]
    if s["inne_waluty"]:
        linie.append(f"• Płatności w innej walucie (doliczymy po przeliczeniu): {s['inne_waluty']}")
    linie += [
        "",
        "Przelew wyślemy w ciągu 7 dni od tego maila. Jeśli chcesz dostawać takie "
        "podsumowania częściej albo w innej formie — po prostu odpisz.",
        "",
        "Dzięki, że jesteś z nami!",
        "Zespół Portevo",
    ]
    return "\n".join(linie)


def zapisz_platnosc_apple(user_id: str, info: dict) -> None:
    """Płatność z App Store → ślad w `premium_events`, żeby liczyła się do prowizji.

    Stripe zapisuje zakupy i odnowienia sam (webhook), a z Apple dotąd nie zapisywało
    się nic — twórca, którego widz kupił na iPhonie, nie dostałby ani złotówki.
    Tę samą transakcję Apple pokazuje nam kilka razy (zakup, przywracanie,
    powiadomienie serwerowe), więc przed zapisem sprawdzamy, czy już jest.
    Piaskownicy nie liczymy: tam kupuje recenzent Apple i testy, nie klienci.
    """
    tid = str(info.get("transaction_id") or "")
    cena = int(info.get("price_milli") or 0)
    if not (user_id and tid and cena > 0) or info.get("environment") == "Sandbox":
        return
    zdarzenie = ("refund" if info.get("revoked")
                 else "purchase" if tid == str(info.get("original_transaction_id") or "")
                 else "renewal")
    juz = _get("premium_events", {"meta->>transakcja": f"eq.{tid}",
                                  "event": f"eq.{zdarzenie}", "select": "id", "limit": "1"})
    if juz is None or juz:
        return
    try:
        import premium
        import supabase_sync as sync
        sync.log_event(user_id, zdarzenie, feature="premium", platform="apple", meta={
            "plan": premium.plan_for_apple_product(str(info.get("product_id") or "")),
            "kwota": round(cena / 10),                   # Apple podaje tysięczne części
            "waluta": str(info.get("currency") or "").lower(),
            "transakcja": tid, "metoda": "apple",
        })
    except Exception as e:
        print(f"[polecenia] nie zapisałem płatności Apple {tid}: {e}")
