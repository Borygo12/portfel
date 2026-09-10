"""App Store Connect API — czytanie stanu buildów i zgłaszanie wersji do recenzji.

Narzędzie do wydawania aplikacji, NIE część serwera. Powstało, bo dwie rzeczy
wymagały dotąd klikania w panelu Apple i przez to blokowały wydanie:

1. **stan paczki po wgraniu.** EAS pokazuje wyłącznie „czy wysłaliśmy", a nie
   „czy Apple przyjęło". Odrzucenie widać dopiero w App Store Connect —
   raz kosztowało to trzy kwadranse czekania na status, który nigdy nie miał
   się zmienić (paczka 1.0.1 wylądowała w zamkniętym pociągu wersji);
2. **zgłoszenie wersji do recenzji.** `eas submit` kończy pracę na wgraniu
   buildu do TestFlight — dalej trzeba było wejść i kliknąć „Submit for Review".

UWAGA na klucze: `keys/apple_iap.p8` (APPLE_IAP_*) obsługuje WYŁĄCZNIE App Store
Server API, czyli zakupy. Na endpointach App Store Connect oddaje 401 i nie jest
to do naprawienia — potrzebny jest osobny klucz z rolą App Manager (ASC_*).
"""

from __future__ import annotations

import io
import os
import time

import jwt
import requests

BAZA = "https://api.appstoreconnect.apple.com/v1"
_KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _wczytaj_env() -> None:
    """Dociąga ASC_* z keys/apple.env, gdy nie ma ich w środowisku."""
    if os.environ.get("ASC_KEY_ID") and os.environ.get("ASC_ISSUER_ID"):
        return
    sciezka = os.path.join(_KORZEN, "keys", "apple.env")
    if not os.path.exists(sciezka):
        return
    for linia in io.open(sciezka, encoding="utf-8"):
        linia = linia.strip()
        if linia and not linia.startswith("#") and "=" in linia:
            k, v = linia.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def skonfigurowane() -> bool:
    _wczytaj_env()
    return bool(os.environ.get("ASC_KEY_ID") and os.environ.get("ASC_ISSUER_ID")
                and os.path.exists(_plik_klucza()))


def _plik_klucza() -> str:
    _wczytaj_env()
    sciezka = os.environ.get("ASC_KEY_FILE") or "keys/apple_asc.p8"
    return sciezka if os.path.isabs(sciezka) else os.path.join(_KORZEN, sciezka)


def _token() -> str:
    """Token ES256 ważny 15 minut. Apple odrzuca dłuższe."""
    _wczytaj_env()
    pem = io.open(_plik_klucza(), encoding="utf-8").read()
    teraz = int(time.time())
    return jwt.encode(
        {"iss": os.environ["ASC_ISSUER_ID"], "iat": teraz, "exp": teraz + 15 * 60,
         "aud": "appstoreconnect-v1"},
        pem, algorithm="ES256",
        headers={"kid": os.environ["ASC_KEY_ID"], "typ": "JWT"},
    )


def _zapytaj(metoda: str, sciezka: str, **kw) -> dict:
    r = requests.request(
        metoda, f"{BAZA}{sciezka}", timeout=30,
        headers={"Authorization": f"Bearer {_token()}",
                 "Content-Type": "application/json"},
        **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"{metoda} {sciezka} -> {r.status_code}: {r.text[:600]}")
    return r.json() if r.content else {}


# ----------------------------------------------------------------- odczyty


def buildy(app_id: str, limit: int = 10) -> list[dict]:
    """Ostatnio wgrane paczki wraz ze stanem przetwarzania po stronie Apple."""
    dane = _zapytaj("GET", "/builds", params={
        "filter[app]": app_id, "limit": limit, "sort": "-uploadedDate",
        "fields[builds]": "version,processingState,uploadedDate,expired",
    })
    return [{"id": b["id"], **b["attributes"]} for b in dane.get("data", [])]


def wersje(app_id: str, limit: int = 5) -> list[dict]:
    """Wersje w App Store wraz ze stanem (PREPARE_FOR_SUBMISSION, IN_REVIEW…)."""
    dane = _zapytaj("GET", f"/apps/{app_id}/appStoreVersions", params={
        "limit": limit,
        "fields[appStoreVersions]": "versionString,appStoreState,platform,createdDate",
    })
    return [{"id": w["id"], **w["attributes"]} for w in dane.get("data", [])]


def lokalizacje(wersja_id: str) -> list[dict]:
    """Języki opisu danej wersji — do nich wpisuje się „co nowego"."""
    dane = _zapytaj("GET", f"/appStoreVersions/{wersja_id}/appStoreVersionLocalizations",
                    params={"limit": 50,
                            "fields[appStoreVersionLocalizations]": "locale,whatsNew"})
    return [{"id": l["id"], **l["attributes"]} for l in dane.get("data", [])]


# ------------------------------------------------------------------ zapisy


def utworz_wersje(app_id: str, numer: str, platforma: str = "IOS") -> dict:
    """Zakłada nową wersję w App Store. Metadane dziedziczy po poprzedniej."""
    dane = _zapytaj("POST", "/appStoreVersions", json={"data": {
        "type": "appStoreVersions",
        "attributes": {"platform": platforma, "versionString": numer},
        "relationships": {"app": {"data": {"type": "apps", "id": app_id}}},
    }})
    w = dane["data"]
    return {"id": w["id"], **w["attributes"]}


def przypnij_build(wersja_id: str, build_id: str) -> None:
    """Wskazuje, KTÓRA paczka ma pójść do recenzji."""
    _zapytaj("PATCH", f"/appStoreVersions/{wersja_id}/relationships/build",
             json={"data": {"type": "builds", "id": build_id}})


def ustaw_co_nowego(lokalizacja_id: str, tekst: str) -> None:
    """„Co nowego w tej wersji" — przy aktualizacji Apple tego wymaga."""
    _zapytaj("PATCH", f"/appStoreVersionLocalizations/{lokalizacja_id}",
             json={"data": {"type": "appStoreVersionLocalizations",
                            "id": lokalizacja_id,
                            "attributes": {"whatsNew": tekst[:4000]}}})


def zglos_do_recenzji(app_id: str, wersja_id: str, platforma: str = "IOS") -> dict:
    """Wysyła wersję do recenzji Apple.

    Trzy kroki, bo tak działa nowszy mechanizm zgłoszeń: zakładamy zgłoszenie,
    wkładamy do niego wersję, dopiero potem je zatwierdzamy. Rozdzielenie ma
    sens po stronie Apple — jedno zgłoszenie potrafi objąć kilka rzeczy naraz
    (wersję, zakupy w aplikacji, wydarzenia).

    Gdy zgłoszenie dla tej platformy już istnieje i czeka niewysłane, bierzemy
    je zamiast zakładać drugie — Apple na dwa naraz nie pozwala.
    """
    istniejace = _zapytaj("GET", "/reviewSubmissions", params={
        "filter[app]": app_id, "filter[platform]": platforma, "limit": 10,
        "fields[reviewSubmissions]": "state,platform",
    }).get("data", [])
    zgloszenie = next((z for z in istniejace
                       if z["attributes"].get("state") in ("READY_FOR_REVIEW", None)), None)

    if zgloszenie:
        zid = zgloszenie["id"]
    else:
        zid = _zapytaj("POST", "/reviewSubmissions", json={"data": {
            "type": "reviewSubmissions",
            "attributes": {"platform": platforma},
            "relationships": {"app": {"data": {"type": "apps", "id": app_id}}},
        }})["data"]["id"]

    # Wersja do zgłoszenia. Gdy już tam jest, Apple odpowie błędem — ignorujemy go,
    # bo znaczy tylko tyle, że poprzednie podejście doszło do tego miejsca.
    try:
        _zapytaj("POST", "/reviewSubmissionItems", json={"data": {
            "type": "reviewSubmissionItems",
            "relationships": {
                "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": zid}},
                "appStoreVersion": {"data": {"type": "appStoreVersions", "id": wersja_id}},
            },
        }})
    except RuntimeError as e:
        if "already" not in str(e).lower() and "duplicate" not in str(e).lower():
            raise

    wynik = _zapytaj("PATCH", f"/reviewSubmissions/{zid}", json={"data": {
        "type": "reviewSubmissions", "id": zid, "attributes": {"submitted": True},
    }})
    return {"id": zid, **(wynik.get("data", {}).get("attributes") or {})}
