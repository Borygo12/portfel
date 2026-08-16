"""Serwer danych (port 8500) — API aplikacji Portevo.

Uruchomienie:  python dashboard.py [--lan] [--no-browser]

Od sierpnia 2026 serwer nie ma własnego interfejsu: dawne panele HTML zostały
wycofane, a jedynym interfejsem jest aplikacja (telefon i przeglądarka z tego
samego kodu). Zostały tylko trzy strony, które MUSZĄ być otwierane w
przeglądarce: `/` (informacja, że serwer żyje), `/account` (powrót z logowania
Google) i `/premium` (strona sprzedażowa spod kłódek).

Bot (main.py) i serwer to osobne procesy; komunikują się przez params.json,
signals.jsonl i heartbeat.json, więc serwer działa nawet gdy bot leży.
"""

import mimetypes
import os

import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse

# ładuj .env z katalogu tego pliku — działa niezależnie od cwd (np. z ikony na pulpicie)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import threading                 # noqa: E402
import time                      # noqa: E402

import analyzer                  # noqa: E402
import outcomes                  # noqa: E402
import prompts                   # noqa: E402
import runner                     # noqa: E402
import state                     # noqa: E402
from config import load_params, save_params  # noqa: E402
from live import calendar as live_cal       # noqa: E402
from live import manager as live_manager    # noqa: E402
from sources import sitemap_monitor         # noqa: E402

app = FastAPI(title="Portevo — serwer danych")

_DIR = os.path.dirname(__file__)
_STARTED_AT = int(time.time())          # do rozpoznania, czy panel wstał po restarcie

# ---------------- dostęp z sieci (telefon) ----------------
# Panel steruje botem i pokazuje prywatny portfel, więc z LAN/VPN wpuszczamy TYLKO z tokenem.
# Z localhost (przeglądarka na tym komputerze) wszystko działa jak dotąd, bez zmian.

import paths                                   # noqa: E402

_TOKEN_FILE = paths.data_path("api_token.txt")


def api_token() -> str:
    """Token dostępu właściciela — ze zmiennej środowiskowej albo z pliku.

    W chmurze token musi być stały między wdrożeniami, inaczej po każdym deployu
    telefon traciłby połączenie. Dlatego pierwszeństwo ma PANEL_API_TOKEN.
    """
    from_env = (os.environ.get("PANEL_API_TOKEN") or "").strip()
    if from_env:
        return from_env
    try:
        with open(_TOKEN_FILE, encoding="utf-8") as f:
            tok = f.read().strip()
            if tok:
                return tok
    except OSError:
        pass
    import secrets
    tok = secrets.token_urlsafe(24)
    os.makedirs(os.path.dirname(_TOKEN_FILE), exist_ok=True)
    with open(_TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(tok)
    return tok


_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}

# Ścieżki dostępne BEZ logowania — inaczej nie dałoby się pokazać ekranu
# logowania ani strony sprzedażowej komuś, kto konta jeszcze nie ma.
# "/" musi tu być: po zalogowaniu przez Google Supabase odsyła na adres główny,
# a gdy ten wymaga logowania, użytkownik ląduje na surowym JSON-ie „login_required"
# tuż po tym, jak się zalogował. Sama strona niczego nie zdradza — dane do
# połączenia telefonu ma własną blokadę „tylko z tego komputera".
_PUBLIC_PATHS = {"/", "/premium", "/account", "/api/auth/config", "/api/premium/features",
                 "/api/premium/event", "/api/me", "/api/version", "/api/health",
                 "/favicon.ico",
                 # Wizytówka bota — warstwa sprzedażowa musi działać dla kogoś BEZ konta.
                 # Ktoś wchodzi z Google na /analiza-newsow-ai, klika „Otwórz analizy"
                 # i ląduje w zakładce bota: gdyby ten adres wymagał logowania,
                 # zobaczyłby ekran logowania zamiast produktu. Endpoint nie oddaje
                 # ani treści analiz, ani promptów — tylko to, co i tak jest reklamą.
                 "/api/bot/showcase"}
# Pliki samej aplikacji (skrypty, czcionki, grafika) muszą być dostępne dla każdego —
# inaczej bramka odsyła 401 na bundle i użytkownik widzi białą stronę zamiast apki.
_PUBLIC_PREFIXES = ("/static/", "/_expo/", "/assets/", "/api/legal/")

# Dokumenty prawne MUSZĄ być publiczne. Adresy polityki prywatności i wsparcia
# wpisuje się w formularzu App Store i Google Play, a recenzent otwiera je bez
# konta — strona za logowaniem to gotowe odrzucenie zgłoszenia.
import legal                                    # noqa: E402

_PUBLIC_PATHS |= set(legal.ROUTES)

# Strony pozycjonowane MUSZĄ być publiczne. Robot Google nie ma konta i nie
# zaloguje się — gdyby trafił na bramkę, dostałby przekierowanie na ekran
# logowania zamiast treści i cała warstwa SEO byłaby niewidoczna. Listę podaje
# sam moduł, żeby dołożenie nowej sekcji nie wymagało pamiętania o tym pliku.
from seo import routes as seo_routes             # noqa: E402
from seo import shell as seo_shell               # noqa: E402

_PUBLIC_PATHS |= seo_routes.PUBLICZNE_SCIEZKI
# Adresy zakładek aplikacji też muszą być publiczne — inaczej wejście wprost na
# „/earnings" kończyłoby się przekierowaniem na ekran logowania zamiast aplikacji,
# choć sama aplikacja jest dostępna dla gościa.
_PUBLIC_PATHS |= set(seo_shell.SCIEZKI_APLIKACJI)
_PUBLIC_PREFIXES += seo_routes.PUBLICZNE_PREFIKSY

# Ścieżki działające bez tożsamości w bazie: sterowanie botem i wspólny feed
# analiz. To są dane serwera, nie czyjeś prywatne — wymagają uprawnień właściciela
# albo zalogowania, ale nie potrzebują kontekstu użytkownika w Postgresie.
_NO_DB_USER_PREFIXES = ("/api/bot/", "/api/live/", "/api/signals", "/api/params",
                        "/api/prompts", "/api/status")


# --- konto pokazowe -----------------------------------------------------------
# Gość ma zobaczyć DZIAŁAJĄCĄ aplikację, a nie puste ramki — inaczej nie sposób
# ocenić, po co ona komu. Podstawiamy mu więc portfel konta pokazowego: te same
# endpointy, ta sama ścieżka kodu, tylko czyjeś inne dane. Wyłącznie do odczytu,
# bo dalej przepuszczamy sam GET.
_DEMO_UID = (os.environ.get("DEMO_USER_ID") or "").strip()
_DEMO_EMAIL = (os.environ.get("DEMO_EMAIL") or "").strip().lower()

# Odczyty, które gościowi pokazujemy z konta pokazowego.
#
# Są tu też `/api/market/` i `/api/earnings/`, choć podają dane publiczne (notowania,
# terminy publikacji wyników). Powód jest prozaiczny: oba doklejają do odpowiedzi
# „czy masz to w portfelu / obserwowanych", więc sięgają do bazy i bez tożsamości
# kończą się błędem. Bez tego gość, który dotknął pozycji w portfelu pokazowym albo
# wszedł w Earnings, dostawał zamiast ekranu napis „Zaloguj się, żeby korzystać
# z tej funkcji" — czyli dokładnie ślepą uliczkę, której konto pokazowe miało
# nie być. Przepuszczamy wyłącznie GET, więc niczego nie da się tu zmienić.
_DEMO_SCIEZKI = ("/api/portfolio/", "/api/market/", "/api/earnings/")


def demo_user_id() -> str:
    """Identyfikator konta pokazowego — z DEMO_USER_ID albo po adresie e-mail."""
    global _DEMO_UID
    if _DEMO_UID:
        return _DEMO_UID
    if _DEMO_EMAIL:
        import supabase_auth
        rows = supabase_auth._service_get("profiles", {"email": f"eq.{_DEMO_EMAIL}",
                                                       "select": "id"})
        _DEMO_UID = (rows[0].get("id") if rows else "") or ""
    return _DEMO_UID


def _sciezka_pokazowa(path: str) -> bool:
    return path.startswith(_DEMO_SCIEZKI)


@app.middleware("http")
async def _authenticate(request, call_next):
    """Ustala kto pyta, odsiewa niezalogowanych i podaje tożsamość bazie.

    Rozdział danych robi RLS w Postgresie (migracja 0002), ale baza musi wiedzieć,
    czyim imieniem pytamy — i to ustawiamy tutaj, raz na żądanie. Gdy tożsamości
    nie ma, `db.user_scope` rzuci wyjątkiem zamiast pokazać cudze wiersze.
    """
    from fastapi.responses import JSONResponse

    import db
    import supabase_auth

    path = request.url.path
    if path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES):
        db.set_current_user("")
        return await call_next(request)

    viewer = supabase_auth.viewer_from_request(request)
    client = (request.client.host if request.client else "") or ""
    local = client in _LOCAL_HOSTS and not supabase_auth.REQUIRE_AUTH_LOCAL
    panel_token = (request.headers.get("x-api-token")
                   or request.query_params.get("token") or "")
    owner_by_token = bool(panel_token) and panel_token == api_token()

    if not (viewer.logged_in or local or owner_by_token):
        # Gość ma się najpierw rozejrzeć — pokazujemy mu portfel konta pokazowego.
        # Przepuszczamy wyłącznie GET, więc niczego nie da się w nim zmienić.
        if request.method == "GET" and _sciezka_pokazowa(path):
            uid = demo_user_id()
            if uid:
                db.set_current_user(uid)
                request.state.demo = True
                odpowiedz = await call_next(request)
                # Nagłówek mówi aplikacji wprost: to nie są dane tej osoby.
                odpowiedz.headers["X-Portevo-Demo"] = "1"
                return odpowiedz
            return JSONResponse([] if path == "/api/market/watchlist"
                                else {"empty": True, "guest": True})

        # Człowiek w przeglądarce dostaje ekran logowania, a nie surowy JSON.
        # Aplikacja i telefon pytają o JSON (Accept: application/json), więc
        # dla nich nic się nie zmienia — dostają kod, który potrafią obsłużyć.
        if "text/html" in (request.headers.get("accept") or ""):
            from fastapi.responses import RedirectResponse
            return RedirectResponse("/account", status_code=303)
        return JSONResponse(
            {"error": "Zaloguj się, żeby korzystać z aplikacji", "code": "login_required"},
            status_code=401,
        )

    # Właściciel bywa rozpoznany tokenem panelu albo połączeniem lokalnym — wtedy
    # nie ma tokenu Supabase, ale jego dane leżą pod konkretnym identyfikatorem.
    uid = viewer.user_id
    if not uid and (owner_by_token or local or viewer.owner):
        uid = supabase_auth.owner_user_id()
    db.set_current_user(uid)

    if not uid and not path.startswith(_NO_DB_USER_PREFIXES):
        return JSONResponse(
            {"error": "Konto nie jest jeszcze połączone z bazą — zaloguj się w aplikacji",
             "code": "no_account"},
            status_code=401,
        )

    request.state.viewer = viewer
    return await call_next(request)


@app.middleware("http")
async def _kanoniczna_domena(request, call_next):
    """Przeglądarka spod adresu hostingu wraca na domenę.

    Supabase po zalogowaniu przez Google odsyła na `redirect_to` TYLKO wtedy, gdy
    ten adres jest na liście dozwolonych w panelu Supabase. Gdy go tam nie ma,
    cicho podstawia „Site URL" — i człowiek, który kliknął logowanie na
    `portevo.pl`, ląduje na `…up.railway.app`. To jest zapasowa bariera na ten
    przypadek: token logowania wraca w części adresu po `#`, a tę przeglądarka
    przenosi przez przekierowanie, więc sesja się nie gubi.

    Zawężenia, bez których to by szkodziło:
    - tylko GET/HEAD z `Accept: text/html`, czyli wejście człowieka w przeglądarce.
      Aplikacja i telefon proszą o JSON i mają rozmawiać z serwerem tam, gdzie się
      z nim połączyły;
    - tylko host hostingu. `localhost` i adres w LAN muszą działać dalej, bo na
      nich stoi panel na komputerze.

    Kod 302, a nie 301: przekierowanie stałe przeglądarka zapamiętuje na długo
    i gdyby domena kiedyś przestała działać, nie dałoby się wrócić pod adres
    Railway nawet ręcznie.
    """
    from seo import site as seo_site

    host = (request.headers.get("host") or "").split(":", 1)[0].lower()
    if (request.method in ("GET", "HEAD")
            and host.endswith("railway.app")
            and not seo_site.kanoniczny_host(host)
            and "text/html" in (request.headers.get("accept") or "")):
        from fastapi.responses import RedirectResponse
        cel = request.url.replace(scheme="https", netloc=seo_site.HOST)
        return RedirectResponse(str(cel), status_code=302)
    return await call_next(request)


@app.middleware("http")
async def _naglowki_bezpieczenstwa(request, call_next):
    """Nagłówki, których przeglądarka używa do ograniczenia szkód po cudzej stronie.

    Żaden z nich nie zmienia tego, co widzi użytkownik — zmieniają to, co wolno
    zrobić z naszą stroną komuś innemu. Przy serwisie o finansach to nie jest
    ozdoba: bez nich cudza witryna może osadzić Portevo w ramce i podstawić nad
    nim swoje przyciski, a adresy z naszymi parametrami wyciekają do obcych
    serwerów w nagłówku `Referer`.

    Czego tu NIE MA i dlaczego: `Content-Security-Policy`. Aplikacja to bundle
    z Expo, który korzysta z osadzonych stylów i skryptów, a zbyt ciasna polityka
    kończy się białym ekranem — czyli awarią gorszą niż problem, który miała
    rozwiązać. Do jej wprowadzenia trzeba osobnego przejścia z trybem
    raportowania, a nie dopisania jednej linijki.
    """
    odpowiedz = await call_next(request)

    # `nosniff` — przeglądarka ma wierzyć deklarowanemu typowi zawartości zamiast
    # zgadywać go z bajtów. Zgadywanie bywa drogą do wykonania cudzego skryptu.
    odpowiedz.headers.setdefault("X-Content-Type-Options", "nosniff")
    # Zakaz osadzania w ramce z obcej domeny (obrona przed clickjackingiem).
    odpowiedz.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    # Do obcych serwerów idzie sama domena, bez ścieżki i parametrów — inaczej
    # dostawca notowań widziałby w logach, jaką spółkę ktoś właśnie ogląda.
    odpowiedz.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # Aplikacja nie używa kamery, mikrofonu ani lokalizacji, więc odbieramy je
    # z góry: gdyby kiedyś wstrzyknięto tu obcy skrypt, nie ma o co prosić.
    odpowiedz.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")

    # HSTS ustawiamy WYŁĄCZNIE, gdy żądanie faktycznie przyszło po HTTPS.
    # Nagłówek jest bezterminowym zobowiązaniem: przeglądarka, która raz go
    # zobaczy dla danego hosta, przez rok odmówi połączenia po HTTP. Wysłany
    # przy pracy na komputerze zablokowałby `http://localhost:8500` i panel
    # przestałby się otwierać — bez oczywistego powodu i bez łatwego odwrotu.
    # Za TLS odpowiada proxy hostingu, więc protokół czytamy z jego nagłówka.
    if (request.headers.get("x-forwarded-proto") or request.url.scheme) == "https":
        odpowiedz.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return odpowiedz


@app.exception_handler(Exception)
async def _friendly_errors(request, exc):
    """Zamienia dwa typowe błędy konfiguracji na czytelną odpowiedź zamiast 500.

    Bez tego pierwsze uruchomienie na nowym serwerze kończy się „Internal Server
    Error" i zgadywaniem, czego brakuje.
    """
    from fastapi.responses import JSONResponse

    import db
    if isinstance(exc, db.NotConfigured):
        return JSONResponse({"error": str(exc), "code": "db_not_configured"}, status_code=503)
    if isinstance(exc, PermissionError):
        return JSONResponse({"error": "Zaloguj się, żeby zobaczyć swoje dane",
                             "code": "login_required"}, status_code=401)
    log.exception("Nieobsłużony błąd: %s %s", request.method, request.url.path)
    return JSONResponse({"error": "Błąd serwera", "code": "server_error"}, status_code=500)


from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

# Bez ALLOWED_ORIGINS wpuszczamy każdy adres — wygodne przy pracy lokalnej i
# bezpieczne o tyle, że tożsamość idzie nagłówkiem Authorization, a nie ciasteczkiem
# (więc obca strona nie „pożyczy" sesji przeglądarki). Na produkcji i tak warto
# wpisać własne domeny — wtedy cudza strona nie odpyta API w imieniu użytkownika.
_ORIGINS = [o.strip() for o in (os.environ.get("ALLOWED_ORIGINS") or "").split(",") if o.strip()]

# Adresy lokalne wpuszczamy ZAWSZE, obok listy z ALLOWED_ORIGINS. Bez tego
# ustawienie listy produkcyjnej odcina aplikację uruchomioną w trakcie pracy
# na komputerze (Expo web chodzi na losowym porcie localhost) — a to nie jest
# zagrożenie: „localhost" u kogoś obcego wskazuje jego własny komputer, nie nasz.
_LOCAL_ORIGIN_RE = r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?"

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGINS or ["*"],
    allow_origin_regex=_LOCAL_ORIGIN_RE if _ORIGINS else None,
    allow_methods=["*"], allow_headers=["*"], allow_credentials=False,
)


import account_api                            # noqa: E402
from account_api import require_owner, require_premium   # noqa: E402
from fastapi import Depends                    # noqa: E402
from fastapi.staticfiles import StaticFiles    # noqa: E402

app.include_router(account_api.router)

# Podstrony pozycjonowane: funkcje, wyniki spółek, poradniki, słownik, a także
# sitemap.xml, robots.txt, llms.txt i manifest aplikacji webowej.
app.include_router(seo_routes.router)

# Narzędzie „Inwestowanie dywidendowe" — skaner, kalendarz, kalkulator i analiza
# portfela pod kątem wypłat. Całość za bramką logowania (patrz `dividends_api`).
import dividends_api                             # noqa: E402
app.include_router(dividends_api.router)


@app.on_event("startup")
def _rozgrzej_seo():
    """Składa dane kalendarza zanim poprosi o nie pierwszy odwiedzający.

    Po restarcie pamięć procesu jest pusta i pierwsze wejście na `/sezon-wynikow`
    albo stronę branży płaci pełny koszt złożenia listy (zapytanie do Nasdaqa
    plus kilkaset plików cache): mierzone 9 sekund. Wdrożenie idzie w środku
    dnia, więc tym pierwszym wejściem bywa robot wyszukiwarki — a dla niego
    wolna odpowiedź to powód, żeby przy następnym obchodzie zajrzeć na mniej
    podstron. Rozgrzewka chodzi w wątku pobocznym, więc serwer startuje
    normalnie i zdąży odpowiedzieć na healthcheck.
    """
    from seo import dividends as seo_dividends
    from seo import pamiec as seo_pamiec
    from seo import reactions as seo_reactions
    from seo import upcoming as seo_upcoming
    try:
        seo_upcoming.rozgrzej()
        # Jeden wątek, po kolei — nie ma powodu, żeby dwa przebiegi pukały do
        # Yahoo równolegle.
        #
        # **Dywidendy IDĄ PIERWSZE i to nie jest obojętne.** Jedna spółka to tam
        # jedno lekkie zapytanie, więc cały katalog schodzi w kwadrans; przy
        # reakcjach każda spółka to pełny raport, czyli kilka zapytań i pół
        # godziny na sto czterdzieści spółek. Przy odwrotnej kolejności strony
        # dywidendowe stały puste przez pierwsze pół godziny po każdym wdrożeniu,
        # choć ich dane były do wzięcia od razu — sprawdzone na produkcji.
        seo_pamiec.rozgrzej(seo_dividends.rozgrzej_zadania()
                            + dividends_api.rozgrzej_zadania()
                            + seo_reactions.rozgrzej_zadania())
    except Exception:  # noqa: BLE001 — rozgrzewka nie może zatrzymać startu
        log.exception("Nie udało się uruchomić rozgrzewania warstwy SEO")

# Typy MIME obrazków wpisane na sztywno, bo na Windowsie `mimetypes` czyta je
# z rejestru — a tam potrafi ich po prostu nie być. Starlette bez trafienia
# podaje plik jako `text/plain` i przeglądarka pokazuje krzaki zamiast obrazka.
# Na Linuksie (produkcja) to nic nie zmienia, lokalnie ratuje podgląd.
for _rozsz, _typ in ((".png", "image/png"), (".webp", "image/webp"),
                     (".jpg", "image/jpeg"), (".svg", "image/svg+xml")):
    mimetypes.add_type(_typ, _rozsz)

# Skrypty i style stron logowania oraz strony sprzedażowej.
app.mount("/static", StaticFiles(directory=os.path.join(_DIR, "static")), name="static")


def _page(name):
    # no-cache: przeglądarka MUSI zrewalidować HTML przy każdym wejściu (ETag i tak
    # sprawia, że to tanie). Bez tego po aktualizacji kodu ikona z pulpitu potrafiła
    # otwierać starą wersję strony z cache przeglądarki.
    return FileResponse(os.path.join(_DIR, name),
                        headers={"Cache-Control": "no-cache, must-revalidate"})


# Zbudowana aplikacja webowa (Expo export). Serwer podaje ją pod adresem głównym,
# więc wejście na domenę = wejście do aplikacji, a nie na stronę o serwerze.
_WEB_DIR = os.path.join(os.path.dirname(_DIR), "web")
_WEB_INDEX = os.path.join(_WEB_DIR, "index.html")
_WEB_READY = os.path.isfile(_WEB_INDEX)

if _WEB_READY:
    # zasoby aplikacji (JS, czcionki, obrazki) — nazwy plików zawierają skrót
    # zawartości, więc mogą leżeć w cache przeglądarki dowolnie długo
    app.mount("/_expo", StaticFiles(directory=os.path.join(_WEB_DIR, "_expo")), name="expo")
    _assets = os.path.join(_WEB_DIR, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")


def _strona_publiczna(sciezka: str):
    """Rejestruje publiczny adres na GET **i HEAD** — patrz `seo.routes.strona`.

    `APIRouter` z FastAPI, w odróżnieniu od czystego Starlette, nie dokłada HEAD
    do tras zadeklarowanych jako GET. Adresy warstwy SEO mają to załatwione
    u siebie, ale strona główna, `/premium` i dokumenty prawne są rejestrowane
    tutaj — i one też siedzą w sitemapie, więc też muszą umieć odpowiedzieć na
    najtańsze pytanie, jakie zadaje robot i każdy sprawdzacz linków.
    """
    return app.api_route(sciezka, methods=["GET", "HEAD"], include_in_schema=False)


@_strona_publiczna("/favicon.ico")
def favicon():
    """Ikonka karty w przeglądarce.

    Plik leży w `web/` od zawsze, ale nic go nie podawało — przeglądarka pytała
    o niego przy każdym wejściu i dostawała 404, więc karta z Portevo była bez
    znaku firmowego. Kosztowało to jedną linijkę, której po prostu nie było.

    Pierwszy w kolejce jest ikonek z `static/seo/`: ten z `web/` pochodzi
    z szablonu Expo i pokazywał obcy znak, a nie Portevo. Generuje go
    `bot/seo/make_assets.py` z tego samego znaku firmowego co reszta grafiki.
    """
    for kandydat in (os.path.join(_DIR, "static", "seo", "favicon.ico"),
                     os.path.join(_WEB_DIR, "favicon.ico"),
                     os.path.join(_DIR, "icon.png")):
        if os.path.isfile(kandydat):
            return FileResponse(kandydat, headers={"Cache-Control": "public, max-age=86400"})
    from fastapi.responses import Response
    return Response(status_code=204)


def _aplikacja(adres: str = "/", noindex: bool = False):
    """Zbudowana aplikacja webowa jako odpowiedź HTTP.

    Plik nie idzie prosto z dysku: `seo.shell` dokleja do niego tytuł, opis, Open
    Graph, ikony i manifest, a dla przeglądarek bez JavaScriptu treść zapasową
    z linkami do podstron. Eksport z Expo nadpisuje `index.html` przy każdej
    przebudowie aplikacji, więc wpisanie tego do pliku i tak by nie przetrwało.
    """
    naglowki = {"Cache-Control": "no-cache, must-revalidate"}
    if noindex:
        naglowki["X-Robots-Tag"] = "noindex, follow"

    if not _WEB_READY:
        # Świadomie NIE pokazujemy tu żadnej strony zastępczej: strona „o serwerze"
        # z linkami donikąd była ślepą uliczką, w której lądował każdy po zalogowaniu.
        # Lepiej krzyczeć błędem niż udawać, że tak ma być.
        from fastapi.responses import JSONResponse
        return JSONResponse(
            {"error": "Brak zbudowanej aplikacji w obrazie (katalog web/). "
                      "Uruchom: npx expo export --platform web w mobile/ i skopiuj do web/.",
             "code": "web_build_missing"},
            status_code=503,
        )

    from fastapi.responses import HTMLResponse as _HTML
    try:
        return _HTML(seo_shell.index_html(_WEB_INDEX, adres), headers=naglowki)
    except Exception:  # noqa: BLE001
        # Aplikacja ma się otworzyć nawet wtedy, gdy wstrzykiwanie zawiedzie —
        # brak meta jest gorszy niż nic, ale biała strona jest gorsza od obu.
        log.exception("Wstrzykiwanie meta do index.html nie powiodło się")
        return FileResponse(_WEB_INDEX, headers=naglowki)


@_strona_publiczna("/")
def index():
    """Adres główny = aplikacja. Nic pośredniego, żadnej strony o serwerze."""
    return _aplikacja()


# Adresy zakładek aplikacji („/alokacja", „/earnings"…). Każdy podaje tę samą
# aplikację, a zakładkę do otwarcia wybiera ona sama na podstawie adresu.
#
# Ten kawałek istnieje po to, żeby ODŚWIEŻENIE strony pod takim adresem działało.
# Samo przełączanie zakładek dzieje się w przeglądarce bez pytania serwera, ale
# gdy ktoś wciśnie F5 albo otworzy link od znajomego, żądanie przychodzi tutaj —
# i bez tej pętli dostawałby czterysta czwórkę zamiast aplikacji.
# Domknięcie po `_sciezka` przez argument domyślny — bez tego wszystkie trasy
# podawałyby tytuł ostatniej zakładki z pętli.
for _sciezka in seo_shell.SCIEZKI_APLIKACJI:
    _strona_publiczna(_sciezka)(
        lambda _s=_sciezka: _aplikacja(_s, noindex=True))


@_strona_publiczna("/premium")
def premium_page():
    """Strona sprzedażowa — tu ląduje każde kliknięcie w kłódkę."""
    return _page("premium.html")


@_strona_publiczna("/account")
def account_page():
    """Logowanie, stan subskrypcji i powrót z OAuth Google."""
    return _page("account.html")


# ---------------- dokumenty prawne (strona + aplikacja) ----------------
#
# Apple i Google nie przyjmą aplikacji bez PUBLICZNEGO adresu polityki prywatności
# i wsparcia. Muszą działać bez logowania i bez JavaScriptu, więc podajemy je jako
# zwykły HTML z serwera, a nie jako ekran aplikacji webowej.

from fastapi import HTTPException                # noqa: E402
from fastapi.responses import HTMLResponse       # noqa: E402


def _legal_page(slug: str) -> HTMLResponse:
    html = legal.render_html(slug)
    if html is None:
        raise HTTPException(404, "Nie ma takiego dokumentu")
    # dokumenty zmieniają się rzadko, ale zmiana ma dojść szybko — godzina wystarczy
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=3600"})


for _path, _slug in legal.ROUTES.items():
    # domknięcie po `_slug` przez argument domyślny — bez tego wszystkie ścieżki
    # pokazywałyby ostatni dokument z pętli
    _strona_publiczna(_path)(
        (lambda slug=_slug: (lambda: _legal_page(slug)))()
    )


@app.get("/api/legal/{slug}")
def legal_doc(slug: str):
    """Ta sama treść dla aplikacji — telefon rysuje ją swoimi komponentami."""
    d = legal.doc(slug)
    if not d:
        raise HTTPException(404, "Nie ma takiego dokumentu")
    return d


# ---------------- Mózg AI (prompty, kategorie, autorytet) ----------------

@app.get("/api/brain")
def brain_get():
    """Cała konfiguracja mózgu + zbudowane prompty (podgląd tego, co idzie do OpenRoutera)."""
    cfg = prompts.load_config()
    return {
        "config": cfg,
        "defaults": {"sections": prompts.DEFAULT_SECTIONS,
                     "categories": prompts.DEFAULT_CATEGORIES,
                     "authority": prompts.DEFAULT_AUTHORITY},
        "section_meta": [{"key": k, "title": t, "desc": d} for k, t, d in prompts.SECTION_META],
        "built": {  # finalne prompty per źródło — dokładnie to trafia do AI
            "truth_social": prompts.build_system("truth_social"),
            "gpw_espi": prompts.build_system("gpw_espi"),
            "verify": prompts.verify_system(),
            "summary": prompts.summary_system(),
        },
        "models": {"free": analyzer.free_models(), "paid_fast": analyzer.paid_fast_model(),
                   "verify": analyzer.verify_model()},
        "params": load_params(),
    }


@app.post("/api/brain")
def brain_save(updates: dict):
    """Zapis zmian z panelu: {sections: {...}} / {categories: {...}} / {authority: {...}}."""
    prompts.save_config(updates or {})
    return brain_get()


@app.post("/api/brain/reset")
def brain_reset(body: dict):
    """Reset jednej sekcji/kategorii do domyślnej ({"name": "intro"}) lub całości ({"name": "ALL"})."""
    prompts.reset_section((body or {}).get("name", ""))
    return brain_get()


# ---------------- Wystąpienia na żywo ----------------

@app.get("/api/live/state")
def live_state(date: str | None = None):
    from live.capture import deps_status
    return {
        "server_time": time.time(),
        "date": date or time.strftime("%Y-%m-%d"),
        "deps": deps_status(),
        "monitor": live_manager.monitor_status(),
        "channels": live_cal.load_channels(),
        "events": live_cal.events_for_day(date),
        "sessions": live_manager.sessions_overview(),
        "params": {k: v for k, v in load_params().items() if k.startswith("live_")},
    }


@app.post("/api/live/monitor/start")
def live_monitor_start():
    return {"started": live_manager.monitor_start()}


@app.post("/api/live/monitor/stop")
def live_monitor_stop():
    return {"stopped": live_manager.monitor_stop()}


@app.post("/api/live/refresh")
def live_refresh():
    """Ręczne odświeżenie kalendarza: FDA + zaplanowane streamy + live-check kanałów."""
    out = {"fda_added": 0, "upcoming_added": 0, "fda_error": None, "channels": {}}
    try:
        out["fda_added"] = live_cal.refresh_fda()
    except Exception as e:
        out["fda_error"] = str(e)[:200]
    try:
        out["upcoming_added"] = live_cal.refresh_upcoming()
    except Exception as e:
        out["fda_error"] = (out["fda_error"] or "") + f" | upcoming: {str(e)[:120]}"
    checks = {}
    for ch in live_cal.load_channels():
        checks[ch["id"]] = live_cal.check_channel_live(ch.get("handle", ""))
    live_cal.sync_channel_events(checks)
    out["channels"] = checks
    return out


@app.post("/api/live/event")
def live_add_event(body: dict):
    ev = live_cal.add_manual_event(body.get("title", "Wydarzenie"),
                                   body.get("date") or time.strftime("%Y-%m-%d"),
                                   body.get("time"), body.get("stream_url", ""),
                                   body.get("category", "manual"))
    return {"event": ev}


@app.post("/api/live/event/{event_id}/track")
def live_track(event_id: str, body: dict):
    return {"ok": live_cal.set_tracked(event_id, bool(body.get("tracked")))}


@app.post("/api/live/event/{event_id}/priority")
def live_priority(event_id: str, body: dict):
    events = live_cal.load_events()
    if event_id not in events:
        return {"ok": False}
    events[event_id]["priority"] = "high" if body.get("high") else "normal"
    live_cal.save_events(events)
    return {"ok": True}


@app.post("/api/live/discover")
def live_discover(body: dict | None = None):
    """AI z web-searchem szuka wydarzeń na dziś + 2 dni i dopisuje do kalendarza."""
    try:
        return live_cal.ai_discover_events(int((body or {}).get("days_ahead", 2)))
    except Exception as e:
        return {"error": str(e)[:300]}


@app.post("/api/live/enrich")
def live_enrich(body: dict | None = None):
    """Etap 2: AI doprecyzowuje wydarzenia (godziny, URL-e streamów, kontekst, duplikaty)."""
    days = int((body or {}).get("days_ahead", 2))
    dates = [time.strftime("%Y-%m-%d", time.localtime(time.time() + d * 86400))
             for d in range(days + 1)]
    try:
        return live_cal.ai_enrich_events(dates)
    except Exception as e:
        return {"error": str(e)[:300]}


@app.post("/api/live/event/{event_id}/stream_url")
def live_set_stream_url(event_id: str, body: dict):
    events = live_cal.load_events()
    if event_id not in events:
        return {"ok": False}
    events[event_id]["stream_url"] = (body.get("stream_url") or "").strip()
    live_cal.save_events(events)
    return {"ok": True}


@app.post("/api/live/event/{event_id}/delete")
def live_delete_event(event_id: str):
    live_manager.stop_session(event_id)
    return {"ok": live_cal.delete_event(event_id)}


@app.post("/api/live/channel")
def live_add_channel(body: dict):
    channels = live_cal.load_channels()
    cid = "ch_" + str(len(channels) + 1) + "_" + str(int(time.time()))
    channels.append({"id": cid, "name": body.get("name", "Kanał"),
                     "handle": body.get("handle", ""),
                     "category": body.get("category", "manual"),
                     "lang": body.get("lang", "en"),
                     "watch": bool(body.get("watch", True))})
    live_cal.save_channels(channels)
    return {"channels": channels}


@app.post("/api/live/channel/{channel_id}")
def live_update_channel(channel_id: str, body: dict):
    channels = live_cal.load_channels()
    for ch in channels:
        if ch["id"] == channel_id:
            if "delete" in body:
                channels.remove(ch)
            else:
                for k in ("name", "handle", "category", "lang", "watch"):
                    if k in body:
                        ch[k] = body[k]
            break
    live_cal.save_channels(channels)
    return {"channels": channels}


@app.post("/api/live/session/{event_id}/start")
def live_session_start(event_id: str):
    return live_manager.start_session(event_id)


@app.post("/api/live/session/{event_id}/stop")
def live_session_stop(event_id: str):
    return {"stopped": live_manager.stop_session(event_id)}


@app.get("/api/live/session/{event_id}")
def live_session_get(event_id: str, transcript_after: int = 0, analyses_after: int = 0):
    sess = live_manager.get_session(event_id)
    if not sess:
        return {"error": "sesja nie istnieje"}
    return sess.to_dict(transcript_after, analyses_after)


# Włącznik nasłuchu jest jeden na cały serwer, więc trzyma go właściciel.
# Bez `require_owner` dowolne zalogowane konto mogło zgasić bota wszystkim
# (albo włączyć go i naliczać rachunek za AI komuś innemu).
@app.post("/api/bot/start")
def bot_start(body: dict | None = None, _v=Depends(require_owner)):
    save_params({"kill_switch": False})
    started = runner.start()
    return {"started": started}


@app.post("/api/bot/stop")
def bot_stop(_v=Depends(require_owner)):
    return {"stopped": runner.stop()}


@app.get("/api/outcomes")
def outcomes_list():
    """Jak zachował się kurs po wcześniejszych analizach — fakty, nie zalecenia."""
    return {"stats": outcomes.stats(), "recent": outcomes.recent(100)}


@app.get("/api/state")
def get_state():
    return {
        "server_time": time.time(),
        "params": load_params(),
        "bot_alive": runner.is_running(),  # źródło prawdy: pętla w tym procesie (START/STOP)
        "bot_status": runner.status(),
        "signals": state.recent_signals(60),
        "outcomes": outcomes.stats(),
    }


@app.post("/api/params")
def set_params(updates: dict):
    return save_params(updates)


# ---------------- Wizytówka bota (widok bez premium, także dla gościa) ----------------
#
# Osobny endpoint zamiast okrojonego `/api/state`, z dwóch powodów.
#
# 1. GRANICA. `/api/state` niesie treść analiz — czyli dokładnie ten towar, za który
#    płaci się w premium. Wizytówka nie może go dotykać nawet przypadkiem, więc nie
#    filtrujemy tamtej odpowiedzi, tylko budujemy nową z rzeczy jawnych: co bot
#    obserwuje, jak często, ile już przeanalizował i jak wygląda ścieżka decyzji.
#    Promptów też tu nie ma — oddajemy ich SPIS (tytuły sekcji), nie treść.
# 2. DOSTĘP. Ten adres jest publiczny, a `/api/state` wymaga konta.

_WIZYTOWKA = {"ts": 0.0, "dane": None}
_WIZYTOWKA_TTL = 20.0     # tyle sekund trzyma się odpowiedź; liczniki i tak tykają w apce

#: Klucz w `runner.status()["polls"]` -> przełącznik i rytm w params.json.
#: Nazwy i kolory źródeł mieszkają w aplikacji (`screens/bot/sources.ts`) — to
#: warstwa wyglądu. Tutaj są tylko dane, wspólne dla wizytówki i panelu dev.
_ZRODLA_BOTA = [
    ("truth", "truth_social_enabled", "truth_social_poll_seconds"),
    ("squawk", "squawk_enabled", "squawk_poll_seconds"),
    ("edgar", "sec_edgar_enabled", "sec_poll_seconds"),
    ("gov", "gov_rss_enabled", "gov_rss_poll_seconds"),
    ("gpw", "gpw_espi_enabled", "gpw_espi_poll_seconds"),
    ("knf", "knf_enabled", "knf_poll_seconds"),
    ("knf_ann", "knf_ann_enabled", "knf_ann_poll_seconds"),
    ("sitemap", "sitemap_enabled", "sitemap_poll_seconds"),
]


def _stan_zrodel(p: dict) -> list[dict]:
    """Stan każdego źródła: czy włączone, jak często pytane i kiedy ostatnio."""
    polls = runner.status().get("polls", {}) or {}
    out = []
    for klucz, flaga, rytm in _ZRODLA_BOTA:
        out.append({
            "key": klucz,
            "param": flaga,
            "enabled": bool(p.get(flaga)),
            "interval": int(polls.get(klucz, {}).get("interval") or p.get(rytm) or 0),
            "ts": float(polls.get(klucz, {}).get("ts") or 0),
        })
    return out


def _statystyka_analiz() -> tuple[int, dict | None]:
    """Ile analiz w ostatniej dobie i kiedy była ostatnia.

    Czytamy ogon pliku, nie całość: ten endpoint odpytuje każdy gość, a `signals.jsonl`
    rośnie w nieskończoność. Tysiąc wpisów to z zapasem doba nawet w sezonie wyników.
    """
    teraz = time.time()
    prog = teraz - 24 * 3600
    ile = 0
    ostatnia = None
    for wpis in state.recent_signals(1000):        # od najnowszego
        try:
            kiedy = time.mktime(time.strptime(str(wpis.get("ts", "")), "%Y-%m-%d %H:%M:%S"))
        except (ValueError, TypeError):
            continue
        if ostatnia is None:
            ostatnia = {"ago": max(0.0, teraz - kiedy), "source": wpis.get("source") or ""}
        if kiedy >= prog:
            ile += 1
    return ile, ostatnia


@app.get("/api/bot/showcase")
def bot_showcase():
    """Publiczna wizytówka bota: nasłuch na żywo + ścieżka decyzji, bez treści analiz."""
    if _WIZYTOWKA["dane"] and time.time() - _WIZYTOWKA["ts"] < _WIZYTOWKA_TTL:
        # server_time musi być świeży, inaczej odliczanie w apce skacze w tył
        return {**_WIZYTOWKA["dane"], "server_time": time.time()}

    p = load_params()
    zrodla = _stan_zrodel(p)
    sprawdzen_na_dobe = sum(round(86400 / z["interval"])
                            for z in zrodla if z["enabled"] and z["interval"] > 0)

    cfg = prompts.load_config()
    kategorie = [{"label": k.get("label", ""), "mult": float(k.get("mult", 1) or 1),
                  "desc": k.get("desc", "")}
                 for k in (cfg.get("categories") or {}).values() if k.get("enabled", True)]
    kategorie.sort(key=lambda k: -k["mult"])
    autorytet = [{"label": a.get("label", ""), "mult": float(a.get("mult", 1) or 1),
                  "desc": a.get("desc", "")}
                 for a in (cfg.get("authority") or {}).values()]
    autorytet.sort(key=lambda a: -a["mult"])

    # Objętość promptu zamiast promptu: pokazuje, że za analizą stoi kilka stron
    # instrukcji, a nie jedno zdanie — bez oddawania samych instrukcji.
    prompt_znakow = len(prompts.build_system("gpw_espi"))

    analiz_24h, ostatnia = _statystyka_analiz()

    dane = {
        "bot_alive": runner.is_running(),
        "paused": bool(p.get("kill_switch")),
        # publicznie oddajemy tylko cztery pola — nazwa przełącznika w params.json
        # nie ma czego szukać w odpowiedzi dla gościa
        "sources": [{k: z[k] for k in ("key", "enabled", "interval", "ts")} for z in zrodla],
        "counts": {
            "sources_on": sum(1 for z in zrodla if z["enabled"]),
            "sources_all": len(zrodla),
            "checks_per_day": sprawdzen_na_dobe,
            "analyses_24h": analiz_24h,
            "categories": len(kategorie),
            "authority": len(autorytet),
            "prompt_chars": prompt_znakow,
        },
        "last_analysis": ostatnia,
        "brain": {
            "sections": [{"key": k, "title": t, "desc": d} for k, t, d in prompts.SECTION_META],
            "categories": kategorie,
            "authority": autorytet,
            "models": {"free": analyzer.free_models(),
                       "paid_fast": analyzer.paid_fast_model(),
                       "verify": analyzer.verify_model()},
            "min_strength": int(p.get("min_signal_strength") or 0),
            "verify_enabled": bool(p.get("verify_enabled", True)),
            "thematic_enabled": bool(p.get("thematic_enabled", True)),
            "macro_enabled": bool(p.get("macro_enabled", True)),
            "max_post_age_minutes": p.get("max_post_age_minutes"),
            "max_filing_age_minutes": p.get("max_filing_age_minutes"),
            "max_gpw_age_minutes": p.get("max_gpw_age_minutes"),
        },
    }
    _WIZYTOWKA.update(ts=time.time(), dane=dane)
    return {**dane, "server_time": time.time()}


# ---------------- Panel dewelopera (tylko właściciel) ----------------
#
# Po co osobny ekran, skoro zakładka „Sterowanie" ma już START/STOP: tamta jest
# częścią produktu i mówi językiem użytkownika. Ta odpowiada na jedno pytanie
# właściciela — „ile mnie to dziś kosztuje i czy warto, żeby chodziło" — więc
# obok włącznika stoi rachunek, a nie opis funkcji.

# Stawki z cennika sprawdzonego 13.08.2026: `google/gemini-2.5-flash`
# $0,30/$2,50 za MTok, `anthropic/claude-sonnet-5` $3/$15. Przy ~3000 tokenów
# wejścia (sam prompt systemowy to 9–13 tys. znaków) i ~250 wyjścia wychodzi
# tyle za sztukę. Zmieni się cennik — poprawia się te dwie liczby i nic więcej.
STAWKA_ANALIZA_USD = 0.0015
STAWKA_WERYFIKACJA_USD = 0.0054

#: Wpisy, które nie są prawdziwym wywołaniem modelu i nie mogą wchodzić do rachunku.
_NIE_MODEL = {"regex_fast_track", "manual_test", "demo", ""}


def _analizy_do_rachunku(limit: int = 4000) -> list[dict]:
    """Ostatnie analizy sprowadzone do tego, co kosztuje: kiedy, skąd, jakim modelem."""
    out = []
    for wpis in state.recent_signals(limit):
        try:
            kiedy = time.mktime(time.strptime(str(wpis.get("ts", "")), "%Y-%m-%d %H:%M:%S"))
        except (ValueError, TypeError):
            continue
        sig = wpis.get("signal") or {}
        model = str(sig.get("_model") or "")
        if str(sig.get("reason", "")).startswith("[pre-filtr"):
            rodzaj = "prefiltr"                    # odsiane bez pytania AI — zero kosztu
        elif ":free" in model:
            rodzaj = "darmowy"
        elif model not in _NIE_MODEL:
            rodzaj = "platny"
        else:
            rodzaj = "inny"
        out.append({"t": kiedy, "src": wpis.get("source") or "?", "rodzaj": rodzaj,
                    "verify": bool(wpis.get("verify"))})
    return out


def _okno_kosztow(wpisy: list[dict], godziny: float, etykieta: str) -> dict:
    prog = time.time() - godziny * 3600
    w = [x for x in wpisy if x["t"] >= prog]
    platnych = sum(1 for x in w if x["rodzaj"] == "platny")
    weryfikacji = sum(1 for x in w if x["verify"])
    return {
        "label": etykieta,
        "hours": godziny,
        "analiz": len(w),
        "prefiltr": sum(1 for x in w if x["rodzaj"] == "prefiltr"),
        "darmowych": sum(1 for x in w if x["rodzaj"] == "darmowy"),
        "platnych": platnych,
        "weryfikacji": weryfikacji,
        "usd": round(platnych * STAWKA_ANALIZA_USD + weryfikacji * STAWKA_WERYFIKACJA_USD, 4),
    }


@app.get("/api/dev/status")
def dev_status(_v=Depends(require_owner)):
    """Stan serwera i rachunek za AI — jedno miejsce do decyzji „włączać czy nie"."""
    p = load_params()
    st = runner.status()
    wpisy = _analizy_do_rachunku()

    okna = [_okno_kosztow(wpisy, 24, "24 h"), _okno_kosztow(wpisy, 24 * 7, "7 dni")]
    # Prognozę liczymy z dłuższego okna, o ile w ogóle coś w nim jest — jedna
    # spokojna doba potrafi zaniżyć rachunek dziesięciokrotnie względem sezonu wyników.
    baza = okna[1] if okna[1]["analiz"] else okna[0]
    prognoza = round(baza["usd"] / max(1e-9, baza["hours"]) * 24 * 30, 2) if baza["analiz"] else 0.0

    # Gdzie idą pieniądze: liczba PŁATNYCH wywołań per źródło. To zwykle jedna
    # pozycja (SEC), więc wyłączenie jednego przełącznika potrafi ściąć rachunek.
    per_zrodlo: dict[str, int] = {}
    prog7 = time.time() - 7 * 24 * 3600
    for x in wpisy:
        if x["t"] >= prog7 and x["rodzaj"] == "platny":
            per_zrodlo[x["src"]] = per_zrodlo.get(x["src"], 0) + 1

    return {
        "server_time": time.time(),
        "panel": {
            "api": API_VERSION,
            "started_at": _STARTED_AT,
            "uptime_s": max(0.0, time.time() - _STARTED_AT),
        },
        "bot": {
            "alive": runner.is_running(),
            "paused": bool(p.get("kill_switch")),
            "cycles": st.get("cycles") or 0,
            "last_error": st.get("last_error"),
            "started_at": st.get("started_at"),
            "uptime_s": max(0.0, time.time() - st["started_at"]) if st.get("started_at") else 0.0,
            "last_poll": st.get("last_poll"),
        },
        "sources": _stan_zrodel(p),
        "koszty": {
            "okna": okna,
            "prognoza_30d_usd": prognoza,
            "platne_per_zrodlo": per_zrodlo,
            "stawki": {"analiza": STAWKA_ANALIZA_USD, "weryfikacja": STAWKA_WERYFIKACJA_USD},
        },
    }


# ---------------- Sitemap Monitor (panel /settings — podgląd watchlisty) ----------------

@app.get("/api/sitemap/status")
def sitemap_status():
    """Lista watchlisty + ostatnio znany stan z dysku (bez pytania sieci — szybkie)."""
    watchlist = sitemap_monitor._load_watchlist()
    saved_state = sitemap_monitor._load_state()
    items = [{
        "name": c.get("name"), "ticker": c.get("ticker"), "sitemap_url": c.get("sitemap_url"),
        "baseline_seeded": c.get("ticker") in saved_state,
        "known_url_count": len(saved_state.get(c.get("ticker"), []) or []),
    } for c in watchlist]
    return {"items": items, "poll": runner.status().get("polls", {}).get("sitemap", {})}


@app.post("/api/sitemap/check")
def sitemap_check():
    """Ręczne sprawdzenie na żądanie — realne zapytania sieciowe, ograniczone budżetem
    czasu w sitemap_monitor.check_connectivity() (nie zapisuje stanu, nie generuje sygnałów)."""
    return {"results": sitemap_monitor.check_connectivity()}


@app.post("/api/kill")
def kill(_v=Depends(require_owner)):
    """Awaryjne zatrzymanie nasłuchu — pętla staje i nic nie jest analizowane."""
    save_params({"kill_switch": True})
    runner.stop()
    return {"ok": True}


@app.post("/api/resume")
def resume(_v=Depends(require_owner)):
    return save_params({"kill_switch": False})


# ---------------- Portfel (tracker kont maklerskich) ----------------

import bisect                                    # noqa: E402
import datetime as _dt                           # noqa: E402
import logging                                   # noqa: E402
import re as _re                                 # noqa: E402

from earnings import calendar as earn_cal        # noqa: E402
from earnings import econ as earn_econ           # noqa: E402
from earnings import report as earn_report       # noqa: E402
from fastapi import Request                      # noqa: E402
from portfolio import benchmarks as pf_bench     # noqa: E402
from portfolio import classify as pf_classify    # noqa: E402
from portfolio import engine as pf_engine        # noqa: E402
from portfolio import fees as pf_fees            # noqa: E402
from portfolio import importer as pf_importer    # noqa: E402
from portfolio import intraday as pf_intraday    # noqa: E402
from portfolio import market as pf_market        # noqa: E402
from portfolio import prices as pf_prices        # noqa: E402
from portfolio import warm as pf_warm            # noqa: E402
from portfolio import store as pf_store          # noqa: E402

log = logging.getLogger("dashboard")


def _multipart_file(body: bytes, content_type: str):
    """Wyciąga pierwszy plik z ciała multipart/form-data. None, gdy to nie multipart.

    Parsujemy ręcznie zamiast przez `python-multipart` — to jedyne miejsce w panelu
    z uploadem, a jedna prosta funkcja jest tańsza niż kolejna zależność.

    Dwie rzeczy, na które jest tu miejsce celowo:

    * nagłówki oddzielone samym `\\n` zamiast `\\r\\n` (spotykane u pośredników,
      które „normalizują" ciało żądania);
    * część BEZ `filename=`. To nie jest teoria: klient, który dołączył plik
      niewłaściwie, przysyła część o nazwie `file` bez nazwy pliku, a odrzucenie
      całości kończyło się komunikatem „nie udało się odczytać pliku" przy
      zupełnie poprawnym raporcie. Skoro format i tak rozpoznajemy po zawartości,
      taką część bierzemy — nazwę weźmiemy z adresu żądania.
    """
    m = _re.search(r'boundary="?([^";]+)"?', content_type or "", _re.I)
    if not m:
        return None
    sep = b"--" + m.group(1).strip().encode()
    zapas = None
    for part in body.split(sep):
        head, delim, payload = part.partition(b"\r\n\r\n")
        if not delim:
            head, delim, payload = part.partition(b"\n\n")
        if not delim or b"content-disposition" not in head.lower():
            continue
        payload = payload[:-2] if payload.endswith(b"\r\n") else payload.rstrip(b"\n")
        name = _re.search(rb'filename\*?=(?:"([^"]*)"|([^;\r\n]+))', head, _re.I)
        if name:
            fname = (name.group(1) or name.group(2) or b"").decode("utf-8", "replace").strip()
            return payload, fname.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if zapas is None and payload:
            zapas = (payload, "")
    return zapas


@app.post("/api/portfolio/import")
async def portfolio_import(request: Request, filename: str = "report.xlsx",
                           encoding: str = ""):
    """Import raportu — xlsx, csv albo zip, dowolnym z trzech sposobów wysyłki.

    Telefon wysyła plik jako multipart (React Native robi to natywnie, bez
    przepakowywania bajtów), strona w przeglądarce wrzuca surowe bajty, a starsze
    wersje apki potrafią jeszcze przysłać base64. Rozpoznajemy wszystkie trzy po
    zawartości, bo pomyłka w wykrywaniu kończyła się mylącym „to nie jest zip".

    Import jest idempotentny: operacje mają klucz (konto, id operacji), więc wgranie
    tego samego raportu drugi raz niczego nie dubluje — dokładają się tylko nowe wiersze.
    """
    body = await request.body()
    ct = request.headers.get("content-type", "")
    data, name = body, filename

    if ct.lower().startswith("multipart/form-data"):
        part = _multipart_file(body, ct)
        if part is None:
            return {"ok": False,
                    "error": "Nie udało się odczytać przesłanego pliku — spróbuj "
                             "wybrać go jeszcze raz"}
        data, part_name = part
        name = part_name or filename
    elif encoding == "base64":
        # Klient sam mówi, czym to jest — wierzymy mu bez zgadywania.
        try:
            data = pf_importer.decode_base64(body)
        except Exception:
            return {"ok": False, "error": "Nie udało się odkodować pliku (base64)"}
    elif pf_importer.looks_base64(body):
        # Nikt nie zadeklarował base64, więc tylko ZGADUJEMY — i przyjmujemy zgadkę
        # dopiero, gdy z rozkodowania wyszedł plik. Sam wygląd nie wystarcza:
        # tekstowy raport złożony z samych liter i cyfr też przechodzi test
        # „wygląda na base64", a rozłożenie go na bajty zrobiłoby z niego śmieć.
        try:
            odkodowane = pf_importer.decode_base64(body)
        except Exception:
            odkodowane = b""
        if odkodowane[:2] in (b"PK", b"\xd0\xcf"):
            data = odkodowane

    if not data:
        return {"ok": False,
                "error": "Plik przyszedł pusty. Jeśli trzymasz raport w iCloud Drive "
                         "lub na Dysku Google, otwórz go najpierw w aplikacji Pliki, "
                         "poczekaj aż się ściągnie, i wybierz jeszcze raz."}
    try:
        results, warnings = pf_importer.import_report(data, name)
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    pf_engine.invalidate()
    return {"ok": True, "results": results, "warnings": warnings[:5]}


@app.get("/api/portfolio/summary")
def portfolio_summary():
    pf_warm.touch()
    d = pf_engine.compute()
    if d.get("empty"):
        return {"empty": True}
    return {k: d[k] for k in ("summary", "positions", "accounts", "flows",
                              "price_warnings", "computed_at", "quotes")} | {"empty": False}


def _range_start(rng: str, dates: list) -> int:
    """Indeks pierwszego dnia zakresu w siatce dat (dates są dzienne, ciągłe)."""
    if not dates or rng == "max":
        return 0
    today = _dt.date.fromisoformat(dates[-1])
    days = {"1d": 2, "1w": 7, "1m": 31, "3m": 92, "6m": 183,
            "1y": 366, "3y": 1096, "5y": 1827}.get(rng)
    if rng == "ytd":
        start = today.replace(month=1, day=1).isoformat()
    elif days:
        start = (today - _dt.timedelta(days=days)).isoformat()
    else:
        return 0
    return max(0, bisect.bisect_left(dates, start))


@app.get("/api/portfolio/series")
def portfolio_series(range: str = "max", bench: str = ""):
    """Seria wartości portfela + linia wpłat + znormalizowane benchmarki dla zakresu."""
    d = pf_engine.compute()
    if d.get("empty"):
        return {"empty": True}
    i0 = _range_start(range, d["dates"])
    dates = d["dates"][i0:]
    values = d["values"][i0:]
    values_net = d["values_net"][i0:]
    invested = d["invested"][i0:]
    twr = d["twr"][i0:]
    twr0 = twr[0] if twr and twr[0] else 1.0
    twr_norm = [t / twr0 for t in twr]

    out_bench = {}
    for name in [b for b in bench.split(",") if b]:
        ser = pf_bench.series(name, dates[0])
        if not ser:
            out_bench[name] = None
            continue
        step = pf_engine._Step(ser, default=None)
        vals, base = [], None
        for day in dates:
            v = step.at(day)
            if v is None:
                vals.append(None)
                continue
            if base is None:
                base = v
            vals.append(round(v / base, 6))
        out_bench[name] = vals

    flows = [f for f in d["flows"] if f["date"] >= dates[0]]
    change_pct = round((twr_norm[-1] - 1) * 100, 2) if twr_norm else 0.0
    # wartości są na koniec dnia, więc przepływy z PIERWSZEGO dnia zakresu siedzą
    # już w values[0] — do zysku liczymy tylko przepływy po tym dniu
    flows_after = sum(f["amount_pln"] for f in flows if f["date"] > dates[0])
    profit = round(values[-1] - values[0] - flows_after, 2) if values else 0.0
    profit_net = round(values_net[-1] - values_net[0] - flows_after, 2) if values_net else 0.0
    return {
        "empty": False, "range": range, "dates": dates, "values": values,
        "values_net": values_net,
        "invested": invested, "twr": twr_norm, "bench": out_bench, "flows": flows,
        "stats": {"change_pct": change_pct, "profit_pln": profit, "profit_net_pln": profit_net,
                  "value_start": values[0] if values else 0, "value_end": values[-1] if values else 0},
    }


@app.get("/api/portfolio/intraday")
def portfolio_intraday():
    """Przebieg wartości portfela w trakcie dzisiejszej sesji (zakres 1D)."""
    pf_warm.touch()
    return pf_intraday.session() | {"warm": pf_warm.status()}


@app.get("/api/portfolio/history")
def portfolio_history(range: str = "1w"):
    """Przebieg wartości portfela w rozdzielczości śróddziennej dla krótkich zakresów.

    Zakres tygodniowy z serii dziennej to kilka punktów (weekend to powtórka piątku),
    więc wykres wychodzi płaski. Tutaj ten sam tydzień składamy ze słupków
    15-minutowych — zakres zostaje ten sam, zmienia się tylko szczegółowość.
    """
    pf_warm.touch()
    return pf_intraday.history(range)


@app.get("/api/portfolio/costs")
def portfolio_costs():
    """Koszty: zapłacone (zmierzone z historii) i wyjścia (z profilu prowizji)."""
    d = pf_engine.compute()
    if d.get("empty"):
        return {"empty": True}
    return {
        "empty": False,
        "paid": d["costs"]["paid"],
        "exit": d["costs"]["exit"],
        "accounts": [
            {**a, "profile": d["costs"]["profiles"].get(a["account"], {})}
            for a in d["accounts"]
        ],
        "catalog": pf_fees.catalog(),
        "value": d["summary"]["value"],
        "value_net": d["summary"]["value_net"],
    }


@app.post("/api/portfolio/account/fees")
def portfolio_account_fees(body: dict):
    """Ręczne ustawienie brokera i stawek dla konta (formularz w aplikacji)."""
    account = str(body.get("account") or "").strip()
    if not account:
        return {"ok": False, "error": "Brak numeru konta"}
    overrides = body.get("fees") or {}
    clean = {}
    for k in pf_fees.FIELDS:
        v = overrides.get(k)
        if v is None or v == "":
            continue
        clean[k] = str(v) if k == "min_currency" else float(v)
    if overrides.get("label"):
        clean["label"] = str(overrides["label"])[:60]
    pf_store.set_account_fees(account, body.get("broker") or "", clean)
    pf_engine.invalidate()
    return {"ok": True, "account": account,
            "profile": pf_fees.profile(body.get("broker") or "", clean)}


@app.get("/api/market/search")
def market_search(q: str = "", limit: int = 15):
    """Wyszukiwarka spółek, ETF-ów i krypto z całego świata."""
    found = pf_market.search(q, limit)
    watched = pf_store.watch_symbols()
    return [{**it, "watched": it["symbol"] in watched} for it in found]


#  „OPEN BUY 0.1821 @ 57.38" / „CLOSE BUY 1 @ 13.30" — raport XTB trzyma wolumen
#  i cenę tylko w komentarzu operacji, osobnych kolumn na to nie ma
_TRADE_NOTE = _re.compile(r"(OPEN|CLOSE)\s+(BUY|SELL)\s+([\d.,]+)\s*@\s*([\d.,]+)", _re.I)


def _instrument_trades(symbol: str) -> list:
    """Twoje kupna i sprzedaże danego waloru — do znaczników na wykresie spółki."""
    sym = (symbol or "").upper()
    if not sym:
        return []
    resolved: dict = {}
    out = []
    for op in pf_store.query(
        "SELECT ticker, type, time, amount, comment FROM cash_ops "
        "WHERE type IN ('Stock purchase', 'Stock sell') ORDER BY time"
    ):
        t = (op["ticker"] or "").strip().upper()
        if not t:
            continue
        if t not in resolved:
            resolved[t] = pf_prices.resolved_symbol(t).upper()
        if resolved[t] != sym:
            continue
        m = _TRADE_NOTE.search(op["comment"] or "")
        out.append({
            "time": op["time"],
            "side": "buy" if op["type"] == "Stock purchase" else "sell",
            "amount": op["amount"],
            "volume": float(m.group(3).replace(",", ".")) if m else None,
            "price": float(m.group(4).replace(",", ".")) if m else None,
        })
    return out


@app.get("/api/market/company")
def market_company(symbol: str, peers: bool = True):
    """Profil spółki: notowanie, opis, wskaźniki i mediana podobnych spółek."""
    data = pf_market.company(symbol, with_peers=peers)
    data.setdefault("symbol", pf_market.resolve(symbol))
    data["watched"] = data["symbol"] in pf_store.watch_symbols()
    # gdy trzymamy ten walor w portfelu, dokładamy naszą pozycję
    d = pf_engine.compute()
    if not d.get("empty"):
        sym = (data.get("symbol") or "").upper()
        for p in d["positions"]:
            if pf_prices.resolved_symbol(p["ticker"]).upper() == sym:
                data["position"] = p
                break
    data["trades"] = _instrument_trades(data.get("symbol") or symbol)
    return data


@app.get("/api/market/chart")
def market_chart(symbol: str, range: str = "1y"):
    return pf_market.chart(symbol, range)


@app.get("/api/market/watchlist")
def market_watchlist():
    return pf_market.watchlist()


@app.post("/api/market/watchlist")
def market_watch_add(body: dict):
    return pf_market.watch_add(body.get("symbol", ""), body.get("name", ""), body)


@app.post("/api/market/watchlist/remove")
def market_watch_remove(body: dict):
    return pf_market.watch_remove(body.get("symbol", ""))


# ---------------- sekcja Earnings ----------------
#
# Kalendarz wyników i wydarzeń ekonomicznych. Dane składamy tutaj, bo tylko panel
# wie jednocześnie, co owner ma w portfelu i co obserwuje — moduły w earnings/
# są celowo bezstanowe i nic o portfelu nie wiedzą.


def _my_symbols() -> dict:
    """{positions, watchlist} w symbolach Yahoo — do wyróżniania kafli w kalendarzu."""
    positions, watch = set(), set()
    try:
        d = pf_engine.compute()
        if not d.get("empty"):
            for p in d["positions"]:
                sym = pf_prices.resolved_symbol(p["ticker"]).upper()
                if sym:
                    positions.add(sym)
    except Exception as e:  # noqa: BLE001
        log.debug("Pozycje do kalendarza: %s", e)
    try:
        for sym in pf_store.watch_symbols():
            watch.add(pf_prices.resolved_symbol(sym).upper())
    except Exception as e:  # noqa: BLE001
        log.debug("Obserwowane do kalendarza: %s", e)
    # spółka trzymana w portfelu nie jest jednocześnie „tylko obserwowana"
    return {"positions": positions, "watchlist": watch - positions}


_WEEKDAYS = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek",
             "Sobota", "Niedziela"]


@app.get("/api/earnings/meta")
def earnings_meta():
    """Słowniki dla interfejsu: filtry, sortowania, lista krajów makro."""
    return {
        "filters": [{"id": k, "label": v[0]} for k, v in earn_cal.FILTERS.items()],
        "sorts": [{"id": k, "label": v} for k, v in earn_cal.SORTS.items()],
        "countries": [{"code": c, "name": earn_econ._NAMES.get(c, c),
                       "flag": earn_econ._flag(c)}
                      for c in earn_econ.DEFAULT_COUNTRIES],
        "scopes": [{"id": k, "label": v} for k, v in earn_econ.SCOPES.items()],
        "importance": [{"id": 0, "label": "Wszystkie"}, {"id": 1, "label": "Od niskiej"},
                       {"id": 2, "label": "Średnie i wysokie"}, {"id": 3, "label": "Tylko wysokie"}],
    }


@app.get("/api/earnings/calendar")
def earnings_calendar(start: str, end: str, filter: str = "popular",
                      sort: str = "popular", limit: int = 40,
                      importance: int = 2, countries: str = "",
                      scope: str = "core", gpw: bool = True, events: bool = True,
                      budget: float = 25.0):
    """Kalendarz zakresu dat: spółki raportujące + wydarzenia ekonomiczne.

    `budget` to ile sekund wolno czekać na brakujące dni. Po jego upływie
    oddajemy to, co już mamy, a reszta dogrywa w tle — klient dostaje listę
    `pending_days` i wraca po uzupełnienie.
    """
    mine = _my_symbols()
    try:
        raw, pending = earn_cal.range_days(start, end,
                                           budget_sec=max(1.0, min(60.0, budget)))
    except ValueError:
        return {"error": "Zła data"}

    if gpw:
        try:
            universe = earn_cal.gpw_universe(list(mine["positions"] | mine["watchlist"]))
            for date, rows in earn_cal.gpw_days(universe).items():
                if date in raw:
                    raw[date].extend(rows)
        except Exception as e:  # noqa: BLE001
            # GPW to dodatek do kalendarza — jego awaria nie może zabrać reszty
            log.warning("Kalendarz GPW: %s", e)

    ev_days = {}
    if events:
        cc = [c.strip().upper() for c in countries.split(",") if c.strip()] or None
        try:
            ev_days = earn_econ.by_day(start, end, cc, max(0, min(3, importance)),
                                       scope if scope in earn_econ.SCOPES else "core")
        except Exception as e:  # noqa: BLE001
            log.warning("Kalendarz makro: %s", e)

    today = _dt.date.today().isoformat()
    waiting = set(pending)
    days = []
    for date in sorted(raw):
        day = _dt.date.fromisoformat(date)
        rows, total = earn_cal.prepare(raw[date], mine, filter, sort)
        shown = rows if limit <= 0 else rows[:limit]
        for r in shown:
            r.pop("_score", None)
            r["logo"] = earn_report.logo_url(r["symbol"])
        days.append({
            "date": date,
            "weekday": _WEEKDAYS[day.weekday()],
            "weekend": day.weekday() >= 5,
            "is_today": date == today,
            "is_past": date < today,
            "companies": shown,
            "total": total,
            "matched": len(rows),
            "hidden": max(0, len(rows) - len(shown)),
            "mine_count": sum(1 for r in rows if r["owned"] or r["watched"]),
            "events": ev_days.get(date, []),
            # dzień jeszcze się dociąga w tle — interfejs pokazuje to, co ma,
            # i sam wróci po resztę
            "pending": date in waiting,
        })

    return {
        "start": start, "end": end, "filter": filter, "sort": sort, "scope": scope,
        "days": days,
        "complete": not waiting,
        "pending_days": sorted(waiting),
        "mine": {"positions": sorted(mine["positions"]),
                 "watchlist": sorted(mine["watchlist"])},
        "server_now": int(time.time()),
    }


@app.get("/api/earnings/company")
def earnings_company(symbol: str):
    """Raport przed publikacją wyników: konsensus, zaskoczenia, marże, reakcje kursu."""
    data = earn_report.report(symbol)
    sym = (data.get("symbol") or pf_market.resolve(symbol) or "").upper()
    mine = _my_symbols()
    data["owned"] = sym in mine["positions"]
    data["watched"] = sym in mine["watchlist"]
    return data


@app.get("/api/earnings/event")
def earnings_event(event_id: str, country: str = "US", history: bool = True):
    """Szczegóły wydarzenia ekonomicznego wraz z poprzednimi odczytami."""
    out = earn_econ.detail(event_id)
    out["history"] = earn_econ.history(event_id, country) if history else []
    return out


@app.get("/api/portfolio/benchmarks")
def portfolio_benchmarks():
    return pf_bench.available()


@app.get("/api/portfolio/operations")
def portfolio_operations(limit: int = 500):
    return pf_store.query(
        "SELECT account, type, ticker, instrument, time, amount, comment FROM cash_ops "
        "ORDER BY time DESC LIMIT %s", (min(limit, 5000),))


@app.get("/api/portfolio/closed")
def portfolio_closed(limit: int = 500):
    return pf_store.query(
        "SELECT * FROM closed_positions ORDER BY close_time DESC LIMIT %s", (min(limit, 5000),))


@app.post("/api/portfolio/refresh")
def portfolio_refresh():
    pf_engine.invalidate()
    d = pf_engine.compute(force=True)
    return {"ok": True, "computed_at": d.get("computed_at")}


@app.get("/api/portfolio/allocation")
def portfolio_allocation(by: str = "asset_class"):
    """Podział portfela wg wybranego kryterium — do wykresów kołowych.

    by: asset_class | market | sector | currency | position | account
    """
    d = pf_engine.compute()
    if d.get("empty"):
        return {"empty": True}
    positions = [p for p in d["positions"] if not p.get("no_price")]

    groups: dict = {}
    for p in positions:
        if by == "currency":
            key = p["currency"]
        elif by == "position":
            key = p["ticker"]
        else:
            info = pf_classify.describe(p["ticker"], p.get("name", ""))
            key = info.get(by) or info.get("asset_class") or "Pozostałe"
        g = groups.setdefault(key, {"label": key, "value": 0.0, "pl": 0.0, "tickers": []})
        g["value"] += p["value_pln"]
        g["pl"] += p["pl_pln"]
        g["tickers"].append(p["ticker"])

    cash = sum(c for c in (
        a["cash"] * (1.0 if a["currency"] == "PLN" else _fx_now(a["currency"]))
        for a in d["accounts"]) if c > 0.01)
    if cash > 0.01 and by != "position":
        groups["Gotówka"] = {"label": "Gotówka", "value": cash, "pl": 0.0, "tickers": []}

    total = sum(g["value"] for g in groups.values()) or 1.0
    out = sorted(groups.values(), key=lambda g: -g["value"])
    for g in out:
        g["value"] = round(g["value"], 2)
        g["pl"] = round(g["pl"], 2)
        g["pct"] = round(g["value"] / total * 100, 2)
        g["count"] = len(g["tickers"])
    return {"empty": False, "by": by, "total": round(total, 2), "groups": out}


def _cash_pln(d: dict) -> float:
    """Wolne środki na wszystkich rachunkach, przeliczone na złotówki."""
    return sum(max(0.0, a["cash"] * (1.0 if a["currency"] == "PLN" else _fx_now(a["currency"])))
               for a in d.get("accounts", []))


@app.get("/api/portfolio/allocation/risk")
def portfolio_alloc_risk(_v=Depends(require_premium("alloc.risk"))):
    """Rentgen ryzyka — koncentracja, zmienność, wkład pozycji w wahania."""
    import allocation_pro
    d = pf_engine.compute()
    if d.get("empty"):
        return {"empty": True}
    return allocation_pro.risk(d, _cash_pln(d))


@app.get("/api/portfolio/allocation/correlation")
def portfolio_alloc_corr(limit: int = 14, _v=Depends(require_premium("alloc.correlation"))):
    """Macierz korelacji największych pozycji."""
    import allocation_pro
    d = pf_engine.compute()
    if d.get("empty"):
        return {"empty": True}
    return allocation_pro.correlation(d, limit)


# ---------------- skaner ETF ----------------
#
# Meta i lista są DARMOWE — bez tego zablokowana zakładka byłaby pustym prostokątem,
# a użytkownik ma zobaczyć, co dostanie. Płatne jest prześwietlenie pojedynczego
# funduszu i porównywarka, czyli to, po co się tu w ogóle przychodzi.


@app.get("/api/etf/meta")
def etf_meta():
    import etf
    return etf.meta()


@app.get("/api/etf/screen")
def etf_screen(region: str = "", sector: str = "", asset: str = "", currency: str = "",
               q: str = "", sort: str = "y1", limit: int = 24, offset: int = 0):
    import etf
    return etf.screen(region=region, sector=sector, asset=asset, currency=currency,
                      query=q, sort=sort, limit=limit, offset=offset)


@app.get("/api/etf/detail")
def etf_detail(symbol: str, _v=Depends(require_premium("tools.etf"))):
    import etf
    return etf.detail(symbol)


@app.get("/api/etf/compare")
def etf_compare(symbols: str = "", _v=Depends(require_premium("tools.etf"))):
    import etf
    return etf.compare([s for s in symbols.split(",") if s.strip()])


def _fx_now(currency: str) -> float:
    """Kurs waluty na dziś (do przeliczenia gotówki) — 1.0 gdy brak danych."""
    from portfolio import prices as pf_prices
    ser = pf_prices.fx_series(currency, _dt.date.today().isoformat())
    return ser[max(ser)] if ser else 1.0


@app.get("/api/portfolio/closed-summary")
def portfolio_closed_summary():
    """Statystyki zamkniętych transakcji z podziałem na akcje i CFD."""
    rows = pf_store.query("SELECT * FROM closed_positions")
    if not rows:
        return {"empty": True}

    def stats(items: list) -> dict:
        if not items:
            return {"count": 0}
        wins = [r for r in items if r["profit"] > 0]
        losses = [r for r in items if r["profit"] < 0]
        gross_win = sum(r["profit"] for r in wins)
        gross_loss = -sum(r["profit"] for r in losses)
        days = []
        for r in items:
            try:
                o = _dt.datetime.fromisoformat(r["open_time"])
                c = _dt.datetime.fromisoformat(r["close_time"])
                days.append((c - o).total_seconds() / 86400)
            except (ValueError, TypeError):
                pass
        best = max(items, key=lambda r: r["profit"])
        worst = min(items, key=lambda r: r["profit"])
        return {
            "count": len(items),
            "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins) / len(items) * 100, 1),
            "profit": round(sum(r["profit"] for r in items), 2),
            "gross_win": round(gross_win, 2), "gross_loss": round(gross_loss, 2),
            "avg_win": round(gross_win / len(wins), 2) if wins else 0.0,
            "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0.0,
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 1e-9 else None,
            "avg_days": round(sum(days) / len(days), 1) if days else None,
            "best": {"ticker": best["ticker"], "profit": round(best["profit"], 2),
                     "close": best["close_time"][:10]},
            "worst": {"ticker": worst["ticker"], "profit": round(worst["profit"], 2),
                      "close": worst["close_time"][:10]},
        }

    stocks = [r for r in rows if (r["category"] or "").upper() != "CFD"]
    cfds = [r for r in rows if (r["category"] or "").upper() == "CFD"]

    # najlepsze/najgorsze instrumenty łącznie (suma wyników per ticker)
    by_ticker: dict = {}
    for r in rows:
        t = by_ticker.setdefault(r["ticker"], {"ticker": r["ticker"], "instrument": r["instrument"],
                                               "profit": 0.0, "trades": 0})
        t["profit"] += r["profit"]
        t["trades"] += 1
    ranked = sorted(by_ticker.values(), key=lambda x: -x["profit"])
    for t in ranked:
        t["profit"] = round(t["profit"], 2)

    return {
        "empty": False,
        "all": stats(rows), "stocks": stats(stocks), "cfd": stats(cfds),
        "top": ranked[:5], "flop": ranked[-5:][::-1],
    }


# Numer podbijamy przy KAŻDYM dołożeniu endpointu, którego używa aplikacja.
# Telefon porównuje go z własnym wymaganiem i potrafi wtedy powiedzieć wprost
# „panel na komputerze jest starszy", zamiast pokazywać gołe 404 z serwera.
API_VERSION = 8


@app.get("/api/version")
def api_version():
    return {
        "api": API_VERSION,
        "features": ["premium", "accounts", "sync", "allocation_pro", "etf", "legal", "contact",
                     "apple_iap"],
        "started_at": _STARTED_AT,
    }


@app.get("/api/portfolio/ping")
def portfolio_ping():
    """Sprawdzenie połączenia przez apkę mobilną — jeśli odpowiada, token jest OK."""
    return {"ok": True, "app": "news-trader-portfolio", "api": 1}


@app.get("/api/health")
def api_health():
    """Stan serwera dla hostingu i ekranu diagnostycznego — bez logowania.

    Celowo nie zdradza szczegółów konfiguracji: hosting potrzebuje tylko wiedzieć,
    czy proces żyje i czy baza odpowiada.
    """
    import db
    dbs = db.healthy()
    return {
        "ok": bool(dbs.get("ok")),
        "db": "ok" if dbs.get("ok") else "błąd",
        "auth": "ok" if _sa_configured() else "brak konfiguracji Supabase",
        "started_at": _STARTED_AT,
        "api": API_VERSION,
    }


def _sa_configured() -> bool:
    import supabase_auth
    return supabase_auth.configured()


def _is_tailscale(ip: str) -> bool:
    """Adres z zakresu Tailscale (CGNAT 100.64.0.0/10) — działa też poza domem."""
    parts = ip.split(".")
    return (len(parts) == 4 and parts[0] == "100"
            and parts[1].isdigit() and 64 <= int(parts[1]) <= 127)


def _lan_ips() -> list:
    """Adresy IP tego komputera (LAN + ewentualnie Tailscale)."""
    import socket
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))       # nic nie wysyła, tylko wybiera interfejs
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    # dołóż adresy Tailscale z interfejsów systemowych (getaddrinfo bywa ich pozbawione)
    try:
        import subprocess
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-NetIPAddress -AddressFamily IPv4).IPAddress"],
            capture_output=True, text=True, timeout=8).stdout
        for line in out.splitlines():
            ip = line.strip()
            if _is_tailscale(ip) and ip not in ips:
                ips.append(ip)
    except Exception:  # noqa: BLE001 — brak PowerShella nie może wywalić panelu
        pass
    # Tailscale najpierw: to adres, który działa z każdej sieci
    return sorted(ips, key=lambda ip: (not _is_tailscale(ip), ip))


@app.get("/api/portfolio/connect-info")
def portfolio_connect_info(request: Request):
    """Dane do połączenia telefonu — dostępne TYLKO z tego komputera."""
    client = (request.client.host if request.client else "") or ""
    if client not in _LOCAL_HOSTS:
        return {"ok": False, "error": "dostępne tylko lokalnie"}
    ips = _lan_ips()
    return {
        "ok": True, "token": api_token(), "port": PORT, "ips": ips,
        "urls": [f"http://{ip}:{PORT}" for ip in ips],
        "endpoints": [
            {"url": f"http://{ip}:{PORT}", "ip": ip,
             "kind": "tailscale" if _is_tailscale(ip) else "lan",
             "label": "Tailscale — działa wszędzie" if _is_tailscale(ip) else "Sieć domowa (Wi-Fi)"}
            for ip in ips
        ],
        "tailscale": any(_is_tailscale(ip) for ip in ips),
    }


@app.get("/api/portfolio/accounts")
def portfolio_accounts():
    """Lista kont z liczbą operacji i zakresem dat — do zakładki Konta."""
    rows = pf_store.query(
        """SELECT a.account, a.currency, a.imported_at, a.broker, a.fees,
                  COUNT(o.op_id) AS ops, MIN(o.time) AS first_op, MAX(o.time) AS last_op
           FROM accounts a LEFT JOIN cash_ops o ON o.account = a.account
           GROUP BY a.account ORDER BY a.account""")
    for r in rows:
        prof = pf_fees.profile(r.get("broker"), r.pop("fees", None))
        r["broker_label"] = prof["label"]
    return rows


@app.post("/api/portfolio/account/delete")
def portfolio_account_delete(body: dict):
    acct = str((body or {}).get("account") or "")
    if not acct:
        return {"ok": False, "error": "brak numeru konta"}
    res = pf_store.delete_account(acct)
    pf_engine.invalidate()
    return {"ok": True, **res}


@app.post("/api/portfolio/wipe")
def portfolio_wipe():
    """Czyści wszystkie dane portfela — po tym wgrywasz raporty od zera."""
    pf_store.wipe_all()
    pf_engine.invalidate()
    return {"ok": True}


import sys as _sys  # noqa: E402

# Domyślnie localhost-only (brak monitu zapory Windows). `--lan` wystawia panel
# w sieci lokalnej/VPN dla telefonu — wtedy każdy request spoza tego komputera
# musi mieć token (middleware wyżej).
HOST = os.environ.get("PANEL_HOST", "0.0.0.0" if "--lan" in _sys.argv else "127.0.0.1")
# Railway (i większość hostingów) podaje port w zmiennej PORT i oczekuje, że
# aplikacja go użyje — inaczej ruch nie trafia do kontenera.
# Kolejność: port od hostingu (PORT) -> ustawiony ręcznie (PANEL_PORT) -> domyślny.
# W chmurze domyślny to 8080, czyli to samo, co EXPOSE w Dockerfile — dzięki temu
# port ogłaszany i faktyczny nie mogą się rozjechać. Lokalnie zostaje 8500.
PORT = int(os.environ.get("PORT") or os.environ.get("PANEL_PORT")
           or ("8080" if os.environ.get("PORTEVO_CLOUD") else "8500"))
URL = f"http://localhost:{PORT}/"


def _dual_stack_socket(host: str, port: int):
    """Gniazdo przyjmujące JEDNOCZEŚNIE IPv4 i IPv6. None = zostaw to uvicornowi.

    Sedno problemu z hostingiem: `0.0.0.0` przyjmuje wyłącznie IPv4, a `::`
    obsługuje obie rodziny tylko wtedy, gdy jądro ma `bindv6only=0`. Jeśli proxy
    hostingu puka inną rodziną adresów niż ta, którą otworzyliśmy, aplikacja
    działa, a healthcheck i tak raportuje „service unavailable" — objaw nie do
    odróżnienia od aplikacji, która w ogóle nie wstała.

    Zamiast polegać na domyślnym ustawieniu jądra, wyłączamy IPV6_V6ONLY jawnie.
    Gdy IPv6 jest w systemie niedostępny, wracamy do zwykłego nasłuchu uvicorna.
    """
    import socket
    if host not in ("::", "::0", "[::]"):
        return None
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        s.bind((host, port))
        s.listen(2048)
        s.set_inheritable(True)
        print(f"Portevo: gniazdo dwustosowe (IPv4 + IPv6) na porcie {port}", flush=True)
        return s
    except OSError as e:
        print(f"Portevo: brak dwustosu ({e}) — zwykly nasluch na {host}", flush=True)
        return None


def _open_browser_when_ready():
    """Otwórz panel w przeglądarce DOPIERO gdy serwer faktycznie odpowiada."""
    import time
    import urllib.request
    import webbrowser
    for _ in range(120):  # do ~60 s
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/state", timeout=1)
            # unikalny parametr omija stary wpis w cache przeglądarki — zawsze świeża strona
            webbrowser.open(f"{URL}?t={int(time.time())}")
            return
        except Exception:
            time.sleep(0.5)


if __name__ == "__main__":
    import sys
    import threading
    import time
    # Pod pythonw.exe (uruchomienie z ikony, bez konsoli) stdout/stderr = None,
    # przez co uvicorn/logging wywala się przy starcie. Przekieruj do pliku logu.
    if sys.stdout is None or sys.stderr is None:
        logf = open(os.path.join(_DIR, "dashboard.log"), "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stderr = logf
    # serwer sam otwiera przeglądarkę, gdy jest gotowy (chyba że --no-browser, np. VPS)
    if "--no-browser" not in sys.argv:
        threading.Thread(target=_open_browser_when_ready, daemon=True).start()

    # Autostart monitoringu jest DOMYŚLNIE WYŁĄCZONY (autostart_monitoring=False):
    # ikona pulpitu otwiera ekran wyboru Portfel/Bot, a nasłuch newsów rusza dopiero
    # po START w panelu.
    def _autostart():
        p = load_params()
        if p.get("autostart_monitoring", False) and not p.get("kill_switch"):
            runner.start()
    threading.Thread(target=_autostart, daemon=True).start()

    # Log dla hostingu. Najważniejsza jest informacja, SKĄD wziął się port:
    # gdy hosting go nie poda, a jego proxy puka pod własny zapamiętany numer,
    # healthcheck pada mimo działającego serwera — i bez tej linii wygląda to
    # identycznie jak aplikacja, która w ogóle nie wstała.
    skad = ("PORT od hostingu" if os.environ.get("PORT")
            else "PANEL_PORT" if os.environ.get("PANEL_PORT")
            else "domyslny, hosting nie podal portu")
    print(f"Portevo: nasluch na {HOST}:{PORT} ({skad}) | dane w {paths.DATA_DIR} | "
          f"baza {'skonfigurowana' if os.environ.get('SUPABASE_DB_URL') else 'BRAK URL'}",
          flush=True)
    if not os.environ.get("PORT") and os.environ.get("PORTEVO_CLOUD"):
        print("Portevo UWAGA: hosting nie podal zmiennej PORT. Jesli healthcheck "
              "pada mimo tego komunikatu, ustaw PORT=8080 w zmiennych serwisu "
              "albo popraw port docelowy w ustawieniach sieci.", flush=True)

    _log_level = "info" if os.environ.get("PORTEVO_CLOUD") else "warning"
    sock = _dual_stack_socket(HOST, PORT)
    if sock is None:
        uvicorn.run(app, host=HOST, port=PORT, log_level=_log_level)
    else:
        cfg = uvicorn.Config(app, log_level=_log_level)
        uvicorn.Server(cfg).run(sockets=[sock])
