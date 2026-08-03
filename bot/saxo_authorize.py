"""Autoryzacja OAuth dla Saxo (SIM lub LIVE) — logowanie przez przeglądarkę.

Uruchom, gdy panel pokaże "Token Saxo wygasł — potrzebne ponowne logowanie":
    python saxo_authorize.py            (DEMO/SIM — domyślnie)
    python saxo_authorize.py live       (LIVE)

Skrypt:
1. otwiera link logowania w przeglądarce (zaloguj się do Saxo i zatwierdź dostęp),
2. SAM przechwytuje kod z przekierowania na localhost (nie musisz nic kopiować),
3. wymienia go na refresh token i zapisuje do saxo_token_sim.json / _live.json.

Gdy automatyczne przechwycenie się nie uda (np. port zajęty), skrypt przełącza się
w tryb ręczny: wkleisz cały adres z paska przeglądarki. Potem bot loguje się już sam
(odświeża token) — do następnego wygaśnięcia refresh tokenu.
"""
import json
import os
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from dotenv import load_dotenv

_DIR = os.path.dirname(os.path.abspath(__file__))


def build_config(env: str) -> dict:
    """Zbiera wszystko potrzebne do autoryzacji danego środowiska (sim/live)."""
    load_dotenv(os.path.join(_DIR, ".env"))
    env = (env or "sim").strip().lower()
    auth = "https://live.logonvalidation.net" if env == "live" else "https://sim.logonvalidation.net"
    pfx = "SAXO_LIVE_" if env == "live" else "SAXO_SIM_"
    key = (os.environ.get(pfx + "APP_KEY") or os.environ.get("SAXO_APP_KEY", "")).strip()
    secret = (os.environ.get(pfx + "APP_SECRET") or os.environ.get("SAXO_APP_SECRET", "")).strip()
    redirect = os.environ.get("SAXO_REDIRECT_URI", "http://localhost/callback").strip()
    token_file = os.path.join(_DIR, f"saxo_token_{'live' if env == 'live' else 'sim'}.json")
    authorize_url = (f"{auth}/authorize?response_type=code&client_id={key}"
                     f"&redirect_uri={urllib.parse.quote(redirect, safe='')}&state=newstrader")
    return {"env": env, "auth": auth, "pfx": pfx, "key": key, "secret": secret,
            "redirect": redirect, "token_file": token_file, "authorize_url": authorize_url}


def catch_code(redirect: str, authorize_url: str, open_browser: bool = True,
               timeout: int = 180) -> str | None:
    """Lokalny serwer na adresie redirectu łapie ?code=... automatycznie.
    Zwraca code albo None, gdy nie uda się wystartować serwera (port zajęty/uprawnienia)
    lub upłynie czas. Serwuje w wątku i czeka na Event — odporne na równoległe żądania
    (np. /favicon.ico), bo kończy DOPIERO gdy przyjdzie prawdziwy kod."""
    parsed = urllib.parse.urlparse(redirect)
    host = parsed.hostname or "localhost"
    port = parsed.port or 80
    caught: dict[str, str] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code = (qs.get("code") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if code:
                caught["code"] = code
                msg = "Zalogowano do Saxo. Mozesz zamknac te karte i wrocic do panelu."
            else:
                # np. /favicon.ico przed przekierowaniem — NIE kończymy czekania
                msg = "Czekam na kod autoryzacji z Saxo..."
            self.wfile.write(f"<html><body style='font:16px sans-serif;padding:40px'>{msg}</body></html>"
                             .encode("utf-8"))
            if code:
                done.set()

        def log_message(self, *a):
            pass  # cisza

    try:
        srv = HTTPServer((host, port), Handler)
    except OSError as e:
        print(f"(automatyczne przechwycenie niedostępne: {e} — przechodzę w tryb ręczny)")
        return None

    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    print("\n1) Otwieram przeglądarkę — zaloguj się do Saxo i zatwierdź dostęp.")
    print("   Jeśli okno się nie otworzyło, wklej ten link ręcznie:\n")
    print("   " + authorize_url + "\n")
    if open_browser:
        try:
            webbrowser.open(authorize_url)
        except Exception:
            pass
    print(f"2) Czekam na powrót z logowania (do {timeout // 60} min)...")
    done.wait(timeout)
    srv.shutdown()
    srv.server_close()
    return caught.get("code")


def catch_code_manual(cfg: dict) -> str:
    print(f"\nŚRODOWISKO: {cfg['env'].upper()}  (redirect: {cfg['redirect']})")
    print("\n1) Otwórz ten link w przeglądarce, zaloguj się do Saxo i zatwierdź dostęp:\n")
    print(cfg["authorize_url"])
    print("\n2) Po zatwierdzeniu przeglądarka przejdzie na adres z ?code=... (strona może się"
          " nie załadować — to normalne, liczy się adres w pasku).")
    raw = input("\n3) Wklej tu CAŁY adres z paska (albo sam code) i Enter:\n> ").strip()
    if "code=" in raw:
        return urllib.parse.parse_qs(urllib.parse.urlparse(raw).query).get("code", [raw])[0]
    return raw


def exchange_code(cfg: dict, code: str) -> dict:
    """Wymienia authorization_code na tokeny. Rzuca RuntimeError z czytelnym powodem."""
    r = requests.post(f"{cfg['auth']}/token",
                      data={"grant_type": "authorization_code", "code": code,
                            "redirect_uri": cfg["redirect"]},
                      auth=(cfg["key"], cfg["secret"]), timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"{r.status_code} {r.text[:300]}")
    d = r.json()
    return {"access_token": d["access_token"], "refresh_token": d["refresh_token"],
            "expires_at": time.time() + d.get("expires_in", 1200)}


def main(env: str) -> int:
    cfg = build_config(env)
    print(f"\n=== Autoryzacja Saxo {cfg['env'].upper()} ===")
    if not (cfg["key"] and cfg["secret"]):
        print(f"Uzupełnij najpierw {cfg['pfx']}APP_KEY i {cfg['pfx']}APP_SECRET w .env "
              "(z developer.saxo -> App Management).")
        return 1

    code = catch_code(cfg["redirect"], cfg["authorize_url"])
    if not code:
        code = catch_code_manual(cfg)
    if not code:
        print("\nNie udało się pobrać kodu autoryzacji. Spróbuj jeszcze raz.")
        return 1

    try:
        tok = exchange_code(cfg, code)
    except RuntimeError as e:
        print(f"\nBŁĄD wymiany code na token: {e}")
        print("Sprawdź, czy redirect_uri w .env jest DOKŁADNIE taki sam jak w aplikacji na developer.saxo.")
        return 1

    with open(cfg["token_file"], "w", encoding="utf-8") as f:
        json.dump(tok, f)
    print(f"\n✓ Gotowe. Token zapisany do {os.path.basename(cfg['token_file'])}.")
    print("Panel połączy się z kontem w ciągu kilku sekund (odśwież stronę). Bot loguje się teraz sam.")
    return 0


if __name__ == "__main__":
    env_arg = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SAXO_ENV", "sim")
    sys.exit(main(env_arg))
