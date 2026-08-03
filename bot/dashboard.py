"""Panel operacyjny ownera — serwer webowy (port 8500).

Uruchomienie:  python dashboard.py
Bot (main.py) i panel to osobne procesy; komunikują się przez params.json,
signals.jsonl i heartbeat.json, więc panel działa nawet gdy bot leży.
"""

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
import backtest as bt            # noqa: E402
import prompts                   # noqa: E402
import runner                     # noqa: E402
import state                     # noqa: E402
import trader                    # noqa: E402
from config import load_params, save_params  # noqa: E402
from live import calendar as live_cal       # noqa: E402
from live import manager as live_manager    # noqa: E402
from sources import sitemap_monitor         # noqa: E402

app = FastAPI(title="News Trader — panel")

_DIR = os.path.dirname(__file__)
_STARTED_AT = int(time.time())          # do rozpoznania, czy panel wstał po restarcie

# ---------------- dostęp z sieci (telefon) ----------------
# Panel steruje botem tradingowym, więc z LAN/VPN wpuszczamy TYLKO z tokenem.
# Z localhost (przeglądarka na tym komputerze) wszystko działa jak dotąd, bez zmian.

_TOKEN_FILE = os.path.join(_DIR, "portfolio_data", "api_token.txt")


def api_token() -> str:
    """Token dostępu z sieci — generowany raz i trzymany w pliku."""
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

# Ścieżki dostępne z sieci BEZ tokenu — inaczej nie dałoby się pokazać ekranu
# logowania ani strony sprzedażowej komuś, kto tokenu jeszcze nie ma.
_PUBLIC_PATHS = {"/premium", "/account", "/api/auth/config", "/api/premium/features",
                 "/api/premium/event", "/api/me", "/api/version", "/favicon.ico"}
_PUBLIC_PREFIXES = ("/static/",)


@app.middleware("http")
async def _require_token_from_network(request, call_next):
    from fastapi.responses import JSONResponse
    client = (request.client.host if request.client else "") or ""
    if client not in _LOCAL_HOSTS:
        path = request.url.path
        public = path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES)
        given = (request.headers.get("x-api-token")
                 or request.query_params.get("token") or "")
        # Wpuszczamy na dwa sposoby: tokenem panelu (telefon właściciela) albo
        # kontem Supabase (zalogowany użytkownik). Uprawnienia premium sprawdzają
        # już poszczególne endpointy — tu chodzi wyłącznie o „czy w ogóle wolno pukać”.
        ok = public or given == api_token()
        if not ok:
            import supabase_auth
            header = request.headers.get("authorization") or ""
            token = header[7:].strip() if header.lower().startswith("bearer ") else ""
            ok = bool(token and supabase_auth.verify_token(token))
        if not ok:
            return JSONResponse({"error": "Brak lub błędny token dostępu"}, status_code=401)
    return await call_next(request)


from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"], allow_credentials=False,
)


import account_api                            # noqa: E402
from account_api import require_premium        # noqa: E402
from fastapi import Depends                    # noqa: E402
from fastapi.staticfiles import StaticFiles    # noqa: E402

app.include_router(account_api.router)

# Wspólne skrypty i style paneli HTML (logowanie, kłódki premium).
app.mount("/static", StaticFiles(directory=os.path.join(_DIR, "static")), name="static")


def _page(name):
    # no-cache: przeglądarka MUSI zrewalidować HTML przy każdym wejściu (ETag i tak
    # sprawia, że to tanie). Bez tego po aktualizacji kodu ikona z pulpitu potrafiła
    # otwierać starą wersję strony z cache przeglądarki.
    return FileResponse(os.path.join(_DIR, name),
                        headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/")
def index():
    """Ekran wyboru: Portfel (tracker) albo Bot newsowy."""
    return _page("home.html")


@app.get("/bot")
def bot_panel():
    return _page("panel.html")


@app.get("/portfolio")
def portfolio_page():
    return _page("portfolio.html")


@app.get("/premium")
def premium_page():
    """Strona sprzedażowa — tu ląduje każde kliknięcie w kłódkę."""
    return _page("premium.html")


@app.get("/account")
def account_page():
    """Logowanie, stan subskrypcji i powrót z OAuth Google."""
    return _page("account.html")


@app.get("/vendor/lightweight-charts.js")
def vendor_lwc():
    return FileResponse(os.path.join(_DIR, "vendor", "lightweight-charts.js"),
                        media_type="application/javascript")


@app.get("/trades")
def trades_page():
    return _page("trades.html")


@app.get("/backtest")
def backtest_page():
    return _page("backtest.html")


@app.get("/settings")
def settings_page():
    return _page("settings.html")


@app.get("/ict")
def ict_page():
    return _page("ict.html")


@app.get("/position")
def position_page():
    return _page("position.html")


@app.get("/live")
def live_page():
    return _page("live.html")


@app.get("/brain")
def brain_page():
    return _page("brain.html")


@app.get("/earnings")
def earnings_page():
    return _page("earnings.html")


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


@app.post("/api/bot/start")
def bot_start(body: dict | None = None):
    # obserwacja = analizuj i pokazuj decyzje, ale nie składaj zleceń
    observe = bool((body or {}).get("observe"))
    save_params({"trading_enabled": not observe, "kill_switch": False})
    started = runner.start()
    return {"started": started, "observe": observe}


@app.post("/api/bot/stop")
def bot_stop():
    return {"stopped": runner.stop()}


@app.get("/api/position/{position_id}")
def position_get(position_id: str):
    details = trader.position_details(position_id, load_params())
    return details or {"error": "pozycja nie istnieje (mogła się już zamknąć)"}


@app.post("/api/position/{position_id}/close")
def position_close(position_id: str):
    ok = trader.close_position(position_id)
    state.set_hold(position_id, False)
    return {"closed": ok}


@app.post("/api/position/{position_id}/hold")
def position_hold(position_id: str, body: dict):
    state.set_hold(position_id, bool(body.get("hold")))
    return {"held": bool(body.get("hold"))}


@app.get("/api/backtest/sources")
def backtest_sources():
    return {"sources": bt.available_sources()}


@app.post("/api/backtest/start")
def backtest_start(body: dict):
    started = bt.start(body["date"], body.get("sources") or ["truth_social"],
                       bool(body.get("force")))
    return {"started": started}


@app.post("/api/backtest/cancel")
def backtest_cancel():
    return {"cancelled": bt.cancel()}


@app.get("/api/backtest/status")
def backtest_status():
    return {"state": bt.state, "aggregate": bt.aggregate_stats()}


@app.post("/api/backtest/chart")
def backtest_chart(body: dict):
    return bt.simulate_trade(body["ticker"], body.get("direction") or "long",
                             body["post_time"], with_bars=True)


@app.get("/api/state")
def get_state():
    broker = {"connected": False, "demo": trader.client.demo,
              "account": load_params().get("active_account", "saxo_live")}
    account, positions = {}, []
    if trader.client.configured:
        try:
            account = trader.client.get_account()
            positions = trader.client.get_positions()
            broker["connected"] = True
        except Exception as e:  # MT5 ConnectionError, requests, itp.
            broker["error"] = str(e)
    return {
        "server_time": time.time(),
        "params": load_params(),
        "bot_alive": runner.is_running(),  # źródło prawdy: pętla w tym procesie (START/STOP)
        "bot_status": runner.status(),
        "broker": broker,
        "account": account,
        "positions": positions,
        "signals": state.recent_signals(60),
    }


@app.get("/api/trades")
def trades_list():
    """Aktywne pozycje wzbogacone o wskaźniki (dla sekcji Tready)."""
    params = load_params()
    out = []
    if trader.client.configured:
        try:
            for p in trader.client.get_positions():
                d = trader.position_details(p.get("dealId"), params)
                out.append(d or p)
        except Exception as e:
            return {"error": str(e), "trades": []}
    return {"trades": out}


@app.post("/api/params")
def set_params(updates: dict):
    return save_params(updates)


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


@app.get("/api/accounts")
def accounts_list():
    return {"accounts": list(trader.ACCOUNTS.keys()),
            "active": load_params().get("active_account", "saxo_live")}


# stan logowania do Saxo (dla przycisku w panelu)
_saxo_login = {"active": False, "ok": False, "error": None, "started_at": 0, "env": None}


@app.post("/api/broker/login")
def broker_login():
    """Uruchamia logowanie OAuth do Saxo dla AKTYWNEGO konta — bez pliku .bat.
    Zwraca authorize_url (panel otworzy go w nowej karcie); w tle łapie kod z przekierowania,
    wymienia na token i przebudowuje klienta. Owner tylko loguje się w oknie Saxo."""
    import saxo_authorize as sa
    acct = load_params().get("active_account", "saxo_live")
    kind, env = trader.ACCOUNTS.get(acct, ("saxo", "live"))
    if kind != "saxo":
        return {"ok": False, "why": "Logowanie przez przeglądarkę dotyczy tylko kont Saxo."}
    cfg = sa.build_config(env)
    if not (cfg["key"] and cfg["secret"]):
        return {"ok": False, "why": f"Brak {cfg['pfx']}APP_KEY / {cfg['pfx']}APP_SECRET w .env."}
    if _saxo_login["active"]:
        return {"ok": True, "authorize_url": _saxo_login.get("authorize_url"), "env": env,
                "why": "Logowanie już w toku — dokończ w oknie Saxo."}

    _saxo_login.update(active=True, ok=False, error=None, started_at=time.time(),
                       env=env, authorize_url=cfg["authorize_url"])

    def _flow():
        try:
            code = sa.catch_code(cfg["redirect"], cfg["authorize_url"],
                                 open_browser=False, timeout=300)
            if not code:
                _saxo_login.update(active=False, error="Nie odebrano kodu (przekroczono czas logowania).")
                return
            tok = sa.exchange_code(cfg, code)
            with open(cfg["token_file"], "w", encoding="utf-8") as f:
                import json as _json
                _json.dump(tok, f)
            trader.reset_client()  # świeży token z pliku zamiast martwego w pamięci
            _saxo_login.update(active=False, ok=True, error=None)
        except Exception as e:
            _saxo_login.update(active=False, ok=False, error=str(e)[:200])

    threading.Thread(target=_flow, daemon=True).start()
    return {"ok": True, "authorize_url": cfg["authorize_url"], "env": env}


@app.get("/api/broker/login/status")
def broker_login_status():
    return dict(_saxo_login)


@app.post("/api/account")
def set_account(body: dict):
    """Przełącza aktywne konto brokera (saxo_demo/saxo_live/xm_demo/xm_live)."""
    acct = (body or {}).get("account")
    if acct not in trader.ACCOUNTS:
        return {"ok": False, "why": "nieznane konto"}
    # bezpieczeństwo: przy zmianie konta wracamy do obserwacji (nie handlujemy od razu na nowym)
    save_params({"active_account": acct, "trading_enabled": False})
    return {"ok": True, "active": acct}


@app.post("/api/kill")
def kill():
    save_params({"kill_switch": True, "trading_enabled": False})
    runner.stop()
    trader.close_everything()
    return {"ok": True}


@app.post("/api/resume")
def resume():
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
    """
    m = _re.search(r'boundary="?([^";]+)"?', content_type or "", _re.I)
    if not m:
        return None
    sep = b"--" + m.group(1).strip().encode()
    for part in body.split(sep):
        head, delim, payload = part.partition(b"\r\n\r\n")
        if not delim or b"filename" not in head.lower():
            continue
        name = _re.search(rb'filename\*?=(?:"([^"]*)"|([^;\r\n]+))', head, _re.I)
        fname = ""
        if name:
            fname = (name.group(1) or name.group(2) or b"").decode("utf-8", "replace").strip()
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        return payload, fname.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return None


@app.post("/api/portfolio/import")
async def portfolio_import(request: Request, filename: str = "report.xlsx",
                           encoding: str = ""):
    """Import raportu XTB — xlsx albo zip, dowolnym z trzech sposobów wysyłki.

    Telefon wysyła plik jako multipart (React Native robi to natywnie, bez
    przepakowywania bajtów), panel w przeglądarce wrzuca surowe bajty, a starsze
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
            return {"ok": False, "error": "Nie udało się odczytać przesłanego pliku"}
        data, part_name = part
        name = part_name or filename
    elif encoding == "base64" or (body[:2] != b"PK" and pf_importer.looks_base64(body)):
        # Base64 tylko wtedy, gdy to naprawdę base64 — plik zaczynający się od „PK"
        # jest już gotowymi bajtami i dekodowanie zrobiłoby z niego śmieć.
        try:
            data = pf_importer.decode_base64(body)
        except Exception:
            return {"ok": False, "error": "Nie udało się odkodować pliku (base64)"}

    if not data:
        return {"ok": False, "error": "Pusty plik — wybierz raport jeszcze raz"}
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
        "ORDER BY time DESC LIMIT ?", (min(limit, 5000),))


@app.get("/api/portfolio/closed")
def portfolio_closed(limit: int = 500):
    return pf_store.query(
        "SELECT * FROM closed_positions ORDER BY close_time DESC LIMIT ?", (min(limit, 5000),))


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
API_VERSION = 3


@app.get("/api/version")
def api_version():
    return {
        "api": API_VERSION,
        "features": ["premium", "accounts", "sync", "allocation_pro", "etf"],
        "started_at": _STARTED_AT,
    }


@app.get("/api/portfolio/ping")
def portfolio_ping():
    """Sprawdzenie połączenia przez apkę mobilną — jeśli odpowiada, token jest OK."""
    return {"ok": True, "app": "news-trader-portfolio", "api": 1}


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
PORT = int(os.environ.get("PANEL_PORT", "8500"))
URL = f"http://localhost:{PORT}/"


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
    # po START w panelu. Gdyby ktoś włączył flagę ręcznie — nadal tylko obserwacja.
    def _autostart():
        p = load_params()
        if p.get("autostart_monitoring", False) and not p.get("kill_switch"):
            save_params({"trading_enabled": False})
            runner.start()
    threading.Thread(target=_autostart, daemon=True).start()

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
