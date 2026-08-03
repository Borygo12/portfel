"""Klient Saxo Bank OpenAPI — broker z dostępem do CFD na akcje GPW (a także krypto,
akcje US/EU, forex, indeksy). Ten sam interfejs co MT5Client/CapitalClient, więc
trader.py i panel nie widzą różnicy.

Protokół: REST + OAuth2 (Bearer token). SIM: token 24h z developer.saxo (do testów).
PRODUKCJA: appka OAuth + refresh token (TODO — patrz _refresh_token).

Wszystkie wywołania zostały POTWIERDZONE na żywo na koncie SIM (open Market, StopIfTraded
jako SL, Limit jako TP, close przeciwnym Market, cancel przez DELETE). Ceny/SL/TP zaokrąglane
do tick size instrumentu (Saxo odrzuca nierówne — błąd PriceNotInTickSizeIncrements).

Dane rynkowe GPW przez API wymagają subskrypcji WSE. Bez niej get_price zwraca 0 —
wtedy bot i tak może grać w trybie "bracket" (SL/TP server-side liczone z ceny wejścia),
ale traci żywą wycenę w trakcie. Opcjonalne darmowe źródło ceny można wpiąć w _external_price.
"""

import json
import logging
import os
import threading
import time

import requests

import gpw_tickers

log = logging.getLogger("saxo")

_SIM = "https://gateway.saxobank.com/sim/openapi"
_LIVE = "https://gateway.saxobank.com/openapi"
# serwery logowania OAuth (osobne od bramki danych)
_AUTH = {"sim": "https://sim.logonvalidation.net", "live": "https://live.logonvalidation.net"}
_TOKEN_FILE = os.path.join(os.path.dirname(__file__), "saxo_token.json")

# tickery GPW: bot podaje "KGH", Saxo ma symbol "KGH:xwar" na giełdzie WSE
_GPW_EXCHANGE = "WSE"

# Tabela opłat (Classic) dla rynku kasowego (Stock/ETF) przekazana od użytkownika.
# Służy do weryfikacji opłacalności (np. by unikać kupna akcji GPW za 200 PLN, gdzie min. prowizja to 10 PLN).
SAXO_FEES_CLASSIC = {
    "GPW": {"pct": 0.0012, "min_fee": 10.0, "currency": "PLN"},
    "US": {"pct": 0.0008, "min_fee": 1.0, "currency": "USD"},
    "XETRA": {"pct": 0.0008, "min_fee": 3.0, "currency": "EUR"},
    "LSE": {"pct": 0.0008, "min_fee": 3.0, "currency": "GBP"},
    "Euronext Paris": {"pct": 0.0008, "min_fee": 2.0, "currency": "EUR"},
    "SIX Swiss": {"pct": 0.0008, "min_fee": 3.0, "currency": "CHF"},
}


class SaxoClient:
    def __init__(self, env: str | None = None):
        self.env = (env or os.environ.get("SAXO_ENV", "sim")).strip().lower()
        self.base = _LIVE if self.env == "live" else _SIM
        self.demo = self.env != "live"
        self.auth_base = _AUTH.get(self.env, _AUTH["sim"])
        # dane logowania per środowisko (SAXO_LIVE_* / SAXO_SIM_*), z fallbackiem do wspólnych
        if self.env == "live":
            self.app_key = (os.environ.get("SAXO_LIVE_APP_KEY") or os.environ.get("SAXO_APP_KEY", "")).strip()
            self.app_secret = (os.environ.get("SAXO_LIVE_APP_SECRET") or os.environ.get("SAXO_APP_SECRET", "")).strip()
            self.token = ""   # live zawsze przez OAuth
            self._token_file = os.path.join(os.path.dirname(__file__), "saxo_token_live.json")
            self._refresh_env = "SAXO_LIVE_REFRESH_TOKEN"
        else:
            self.app_key = os.environ.get("SAXO_SIM_APP_KEY", "").strip()
            self.app_secret = os.environ.get("SAXO_SIM_APP_SECRET", "").strip()
            self.token = (os.environ.get("SAXO_SIM_TOKEN") or os.environ.get("SAXO_TOKEN", "")).strip()  # token 24h SIM
            self._token_file = os.path.join(os.path.dirname(__file__), "saxo_token_sim.json")
            self._refresh_env = "SAXO_SIM_REFRESH_TOKEN"
        self._tok = self._load_tok()   # {access_token, refresh_token, expires_at}
        self._lock = threading.RLock()
        self._s = requests.Session()
        self._account_key = None
        self._account_id = None
        self._currency = None
        self._epic_cache: dict[str, str] = {}      # "KGH" -> "25285:CfdOnStock"
        self._uic_ticker: dict[int, str] = {}        # 25285 -> "KGH" (do darmowego źródła ceny)
        self._details: dict[int, dict] = {}          # uic -> szczegóły instrumentu
        self._ext_cache: dict[int, tuple] = {}        # uic -> (cena, ts) — cache darmowego źródła
        self._last_order = 0.0                        # throttle zleceń (Saxo limituje ~1/s)
        self._refresh_fail_until = 0.0                # backoff: gdy odświeżanie padnie, nie próbuj co cykl
        self._refresh_fail_msg = ""
        # darmowe źródło ceny GPW (Yahoo, ~15 min delay) gdy brak subskrypcji danych WSE
        self.free_price = os.environ.get("SAXO_FREE_PRICE", "1") != "0"

    @property
    def configured(self) -> bool:
        return bool(self.token or (self.app_key and self.app_secret and self._tok.get("refresh_token")))

    # ----------------------------------------------------------- OAuth / token

    def _load_tok(self) -> dict:
        try:
            with open(self._token_file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            # zgodność wstecz: stary wspólny plik saxo_token.json (był tylko live)
            if self.env == "live":
                try:
                    with open(_TOKEN_FILE, encoding="utf-8") as f:
                        return json.load(f)
                except (OSError, json.JSONDecodeError):
                    pass
            rt = os.environ.get(self._refresh_env, "").strip()
            return {"refresh_token": rt} if rt else {}

    def _save_tok(self):
        try:
            with open(self._token_file, "w", encoding="utf-8") as f:
                json.dump(self._tok, f)
        except OSError:
            log.warning("Nie udało się zapisać %s", self._token_file)

    def _refresh(self):
        """Wymiana refresh_token na świeży access_token (Saxo rotuje też refresh)."""
        # Backoff: jeśli odświeżanie właśnie padło, nie bombarduj Saxo co cykl —
        # zawiedź NATYCHMIAST (bez sieci), żeby nie spowalniać pętli bota. Panel i tak
        # pokaże jasny komunikat i owner ma minutę na ponowne logowanie.
        if time.time() < self._refresh_fail_until:
            raise ConnectionError(self._refresh_fail_msg)
        rt = self._tok.get("refresh_token")
        if not rt:
            msg = f"Brak tokenu Saxo {'LIVE' if self.env == 'live' else 'DEMO'} — zaloguj się (saxo_authorize.py {self.env})"
            self._refresh_fail_until = time.time() + 60
            self._refresh_fail_msg = msg
            raise ConnectionError(msg)
        try:
            r = self._s.post(f"{self.auth_base}/token",
                             data={"grant_type": "refresh_token", "refresh_token": rt},
                             auth=(self.app_key, self.app_secret), timeout=20)
        except requests.exceptions.RequestException as e:
            # błąd sieci — krótki backoff, ale nie tak długi jak wygasły token
            self._refresh_fail_until = time.time() + 15
            self._refresh_fail_msg = f"Saxo: brak połączenia z serwerem logowania ({e})"
            raise ConnectionError(self._refresh_fail_msg)
        if r.status_code >= 400:
            # 401/400/HTML z serwera OAuth = refresh token wygasł -> potrzebna ponowna autoryzacja.
            # Zwracamy krótki, zrozumiały komunikat zamiast surowej strony HTML + backoff 60s.
            body = (r.text or "").lstrip().lower()
            is_html = body.startswith(("<!doctype", "<html"))
            env_name = "LIVE" if self.env == "live" else "DEMO"
            if r.status_code in (400, 401) or is_html:
                msg = (f"Token Saxo {env_name} wygasł — potrzebne ponowne logowanie. "
                       f"Uruchom: python saxo_authorize.py {self.env}")
            else:
                msg = f"Saxo odświeżanie tokenu nieudane: {r.status_code} {r.text[:150]}"
            self._refresh_fail_until = time.time() + 60
            self._refresh_fail_msg = msg
            raise ConnectionError(msg)
        d = r.json()
        self._tok = {"access_token": d["access_token"],
                     "refresh_token": d.get("refresh_token", rt),
                     "expires_at": time.time() + d.get("expires_in", 1200)}
        self._refresh_fail_until = 0.0  # sukces — kasujemy backoff
        self._save_tok()
        log.info("Saxo: odświeżono token (ważny ~%ss)", d.get("expires_in", 1200))

    def _access_token(self) -> str:
        # tryb OAuth (produkcja) ma priorytet, gdy skonfigurowany
        if self.app_key and self.app_secret and self._tok.get("refresh_token"):
            if not self._tok.get("access_token") or time.time() > self._tok.get("expires_at", 0) - 30:
                self._refresh()
            return self._tok["access_token"]
        return self.token   # ręczny token 24h (SIM)

    # --------------------------------------------------------------- transport

    def _headers(self):
        return {"Authorization": f"Bearer {self._access_token()}", "Content-Type": "application/json"}

    def _req(self, method: str, path: str, _retry=True, **kw) -> dict:
        with self._lock:
            r = self._s.request(method, f"{self.base}{path}", headers=self._headers(),
                                timeout=20, **kw)
        if r.status_code == 401:
            # w trybie OAuth spróbuj odświeżyć token i ponów raz
            if _retry and self.app_key and self._tok.get("refresh_token"):
                try:
                    self._refresh()
                    return self._req(method, path, _retry=False, **kw)
                except Exception:
                    pass
            raise ConnectionError("Saxo token wygasł/nieważny — SIM: 24h z developer.saxo; "
                                  "LIVE: uruchom ponownie saxo_authorize.py")
        if r.status_code >= 400:
            raise RuntimeError(f"Saxo {method} {path}: {r.status_code} {r.text[:200]}")
        return r.json() if r.text else {}

    def _get(self, path, **params):
        return self._req("GET", path, params=params or None)

    # ----------------------------------------------------------- konto / rynki

    def _acct(self):
        if not self._account_key:
            d = self._get("/port/v1/accounts/me")["Data"][0]
            self._account_key = d["AccountKey"]
            self._account_id = d.get("AccountId")
            self._currency = d.get("Currency")
        return self._account_key

    def _instrument_details(self, uic: int, asset_type: str) -> dict:
        if uic not in self._details:
            self._details[uic] = self._get(
                f"/ref/v1/instruments/details/{uic}/{asset_type}")
        return self._details[uic]

    def _tick_for(self, details: dict, price: float) -> float:
        """Tick size dla danej ceny. Saxo daje TickSizeScheme z pasmami cenowymi
        (Elements: do jakiej ceny jaki tick) + DefaultTickSize dla najwyższych cen."""
        if details.get("TickSize"):
            return details["TickSize"]
        scheme = details.get("TickSizeScheme") or {}
        for el in sorted(scheme.get("Elements", []), key=lambda e: e["HighPrice"]):
            if price <= el["HighPrice"]:
                return el["TickSize"]
        return scheme.get("DefaultTickSize") or 0.01

    def _round_tick(self, uic: int, asset_type: str, price: float) -> float:
        """Zaokrągla cenę do tick size instrumentu (Saxo odrzuca nierówne)."""
        d = self._instrument_details(uic, asset_type)
        tick = self._tick_for(d, price)
        decimals = (d.get("Format") or {}).get("Decimals", 2)
        import math
        steps = math.floor(price / tick + 0.5)          # round-half-up, bez banker's rounding
        return round(steps * tick, max(decimals, len(str(tick).split(".")[-1])))

    # krypto: Saxo nie ma spot BTC/ETH — gramy przez CFD na ETF kryptowalutowy jako proxy.
    # AI podaje konkretny ticker (BTC/ETH/SOL), broker mapuje na odpowiedni ETF.
    # Krypto niedostępne u brokera → find_epic() zwróci None → trade pominięty.
    _CRYPTO_ETF = {
        # Bitcoin → iShares Bitcoin ETF
        "BTC": "IBIT", "BTCUSD": "IBIT", "XBT": "IBIT", "BITCOIN": "IBIT",
        # Ethereum → iShares Ethereum ETF
        "ETH": "ETHA", "ETHUSD": "ETHA", "ETHEREUM": "ETHA",
        # Solana ETF — jeśli dostępne na Saxo jako CfdOnEtf (np. SOLZ/SOLS)
        "SOL": "SOLZ", "SOLUSD": "SOLZ", "SOLANA": "SOLZ",
        # backward compat: stare sygnały z Crypto_10# trafiają na BTC (dominujący)
        "CRYPTO_10": "IBIT", "CRYPTO10": "IBIT", "CRYPTO_10#": "IBIT",
    }

    def find_epic(self, ticker: str) -> str | None:
        """Mapuje ticker na wewnętrzny epic 'uic:AssetType'.
        Obsługuje akcje GPW (CFD na WSE), akcje US (CFD na NASDAQ/NYSE) i krypto
        (przez CFD na ETF bitcoinowy/ethereum). Zapamiętuje symbol Yahoo do darmowej ceny."""
        key = (ticker or "").upper()
        if key in self._epic_cache:
            return self._epic_cache[key]
        crypto = key in self._CRYPTO_ETF
        search = self._CRYPTO_ETF.get(key, ticker)
        want = search.upper()
        types = "CfdOnEtf" if crypto else "CfdOnStock"
        try:
            data = self._get("/ref/v1/instruments", Keywords=search,
                             AssetTypes=types, **{"$top": 30}).get("Data", [])
        except Exception as e:
            log.warning("Saxo find_epic(%s): %s", ticker, e)
            return None
        # preferuj dokładne dopasowanie symbolu (TICKER:giełda), potem WSE, potem pierwszy CFD
        best = None
        for d in data:
            if d.get("AssetType") != types:
                continue
            sym = (d.get("Symbol") or "").upper()
            if sym.startswith(want + ":"):
                best = d
                break
            if best is None and (d.get("ExchangeId") == _GPW_EXCHANGE or crypto):
                best = d
        if not best:
            return None
        uic = int(best["Identifier"])
        epic = f"{uic}:{best['AssetType']}"
        self._epic_cache[key] = epic
        # symbol do Yahoo (darmowa cena): GPW -> 'KGH.WA', US/inne -> sam ticker ('AAPL','IBIT')
        base = (best.get("Symbol") or "").split(":")[0].upper() or want
        self._uic_ticker[uic] = f"{base}.WA" if best.get("ExchangeId") == _GPW_EXCHANGE else base
        return epic

    @staticmethod
    def _parse(epic: str):
        uic, atype = epic.split(":")
        return int(uic), atype

    def _external_price(self, uic: int) -> float:
        """Darmowe źródło ceny GPW (Yahoo Finance, ~15 min delay) — używane gdy konto
        nie ma subskrypcji danych WSE. Cena służy do policzenia wielkości pozycji;
        SL/TP i tak liczymy z realnej ceny wejścia (dokładnej, z Saxo)."""
        if not self.free_price:
            return 0.0
        cached = self._ext_cache.get(uic)
        if cached and time.time() - cached[1] < 30:   # cache 30 s, żeby nie zasypać Yahoo
            return cached[0]
        ysym = self._uic_ticker.get(uic)   # np. 'KGH.WA' (GPW) albo 'AAPL' (US) — ustawione w find_epic
        if not ysym:
            return 0.0
        try:
            r = self._s.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}",
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
            price = float(r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
            self._ext_cache[uic] = (price, time.time())
            return price
        except Exception as e:
            log.warning("Saxo darmowe źródło ceny (%s): %s", ysym, e)
            return 0.0

    def get_price(self, epic: str) -> float:
        uic, atype = self._parse(epic)
        try:
            q = self._get("/trade/v1/infoprices", Uic=uic, AssetType=atype,
                          AccountKey=self._acct(), Amount=1,
                          FieldGroups="Quote").get("Quote", {})
        except Exception:
            q = {}
        bid, ask = q.get("Bid"), q.get("Ask")
        if bid and ask:
            return (bid + ask) / 2
        if ask or bid:
            return ask or bid
        return self._external_price(uic)  # brak danych WSE -> ewentualne darmowe źródło

    def get_account(self) -> dict:
        self._acct()
        b = self._get("/port/v1/balances/me")
        return {
            "balance": b.get("CashBalance"),
            "available": b.get("MarginAvailableForTrading", b.get("CashBalance")),
            "pnl": b.get("UnrealizedMarginProfitLoss") or b.get("UnrealizedPositionsValue") or 0,
            "currency": b.get("Currency") or self._currency,
            "demo": self.demo,
        }

    def get_positions(self) -> list[dict]:
        data = self._get("/port/v1/positions/me",
                         FieldGroups="PositionBase,PositionView,DisplayAndFormat").get("Data", [])
        # zlecenia powiązane (SL/TP) do pokazania na pozycji
        orders = self._get("/port/v1/orders/me").get("Data", [])
        out = []
        for p in data:
            base, view = p.get("PositionBase", {}), p.get("PositionView", {})
            fmt = p.get("DisplayAndFormat", {})
            uic = base.get("Uic")
            amount = base.get("Amount", 0)
            rel = [o for o in orders if o.get("Uic") == uic]
            sl = next((o.get("Price") for o in rel if "Stop" in (o.get("OpenOrderType") or o.get("OrderType") or "")), None)
            tp = next((o.get("Price") for o in rel if (o.get("OpenOrderType") or o.get("OrderType")) == "Limit"), None)
            out.append({
                "dealId": p.get("PositionId"),
                "epic": f"{uic}:{base.get('AssetType')}",
                "name": fmt.get("Description") or fmt.get("Symbol") or str(uic),
                "direction": "BUY" if amount > 0 else "SELL",
                "size": abs(amount),
                "openLevel": base.get("OpenPrice"),
                "currentLevel": view.get("CurrentPrice") or None,
                "sl": sl, "tp": tp,
                "pnl": view.get("ProfitLossOnTrade"),
                "openTime": base.get("ExecutionTimeOpen"),
            })
        return out

    # ------------------------------------------------------------ egzekucja

    def _place(self, body: dict) -> dict:
        # Saxo limituje endpoint zleceń (~1/s) — odstęp między zleceniami, by nie dostać 429
        wait = 1.1 - (time.time() - self._last_order)
        if wait > 0:
            time.sleep(wait)
        try:
            return self._req("POST", "/trade/v2/orders", json=body)
        finally:
            self._last_order = time.time()

    def _market(self, uic, atype, amount, buy: bool):
        return {"AccountKey": self._acct(), "Uic": uic, "AssetType": atype,
                "Amount": abs(amount), "BuySell": "Buy" if buy else "Sell",
                "OrderType": "Market", "ManualOrder": False,
                "OrderDuration": {"DurationType": "DayOrder"}}

    def _limit(self, uic, atype, amount, buy: bool, price: float):
        return {"AccountKey": self._acct(), "Uic": uic, "AssetType": atype,
                "Amount": abs(amount), "BuySell": "Buy" if buy else "Sell",
                "OrderType": "Limit", "OrderPrice": self._round_tick(uic, atype, price),
                "ManualOrder": False,
                "OrderDuration": {"DurationType": "DayOrder"}}

    # spółki GPW spoza LIQUID_GPW (NewConnect/sWIG80, niska płynność) wchodzą Limitem
    # tuż nad Ask (long) / pod Bid (short) zamiast czystym Market — ogranicza poślizg
    # na szerokim spreadzie kosztem ryzyka niewypełnienia zlecenia.
    _SMALL_CAP_SLIPPAGE_BUFFER = 0.01  # 1%

    def _entry_order(self, uic, atype, amount, buy: bool, epic: str):
        ysym = self._uic_ticker.get(uic, "")
        is_small_gpw = ysym.endswith(".WA") and ysym[:-3] not in gpw_tickers.LIQUID_GPW
        if not is_small_gpw:
            return self._market(uic, atype, amount, buy)
        ref = self.get_price(epic)
        if not ref:
            log.warning("Saxo: brak ceny referencyjnej dla małej spółki %s — Market jako ostatnia deska ratunku", ysym)
            return self._market(uic, atype, amount, buy)
        buf = self._SMALL_CAP_SLIPPAGE_BUFFER
        price = ref * (1 + buf) if buy else ref * (1 - buf)
        log.info("Saxo: mała spółka GPW %s -> Limit @ %.2f (ref %.2f, bufor %.1f%%)", ysym, price, ref, buf * 100)
        return self._limit(uic, atype, amount, buy, price)

    def open_position(self, epic: str, direction: str, size: float,
                      stop_level: float, profit_level: float) -> dict:
        uic, atype = self._parse(epic)
        d = self._instrument_details(uic, atype)
        step = d.get("MinimumTradeSize") or 1
        amount = max(step, round(size / step) * step)
        buy = direction == "BUY"
        try:
            res = self._place(self._entry_order(uic, atype, amount, buy, epic))
        except Exception as e:
            return {"dealStatus": "REJECTED", "rejectReason": str(e)[:200]}
        order_id = res.get("OrderId")

        # odczytaj realną cenę wejścia i dołóż SL (StopIfTraded) + TP (Limit) po tej stronie
        time.sleep(1.2)
        pos = next((p for p in self.get_positions() if self._parse(p["epic"])[0] == uic), None)
        position_id = pos["dealId"] if pos else order_id
        for otype, level in (("StopIfTraded", stop_level), ("Limit", profit_level)):
            if not level:
                continue
            try:
                body = {"AccountKey": self._acct(), "Uic": uic, "AssetType": atype,
                        "Amount": abs(amount), "BuySell": "Sell" if buy else "Buy",
                        "OrderType": otype, "OrderPrice": self._round_tick(uic, atype, level),
                        "ManualOrder": False,
                        "OrderDuration": {"DurationType": "GoodTillCancel"}}
                self._place(body)
            except Exception as e:
                log.warning("Saxo %s dla %s nieudany: %s", otype, uic, e)
        log.info("Saxo TRADE %s uic=%s amount=%s SL=%.2f TP=%.2f", direction, uic,
                 amount, stop_level or 0, profit_level or 0)
        return {"dealStatus": "ACCEPTED", "rejectReason": None, "positionId": position_id}

    def _find_position(self, position_id):
        for p in self.get_positions():
            if str(p["dealId"]) == str(position_id):
                return p
        return None

    def _cancel_related(self, uic, kind: str | None = None):
        """Anuluje zlecenia zabezpieczające danego instrumentu.
        kind: 'stop' (tylko SL), 'limit' (tylko TP), None (wszystkie)."""
        for o in self._get("/port/v1/orders/me").get("Data", []):
            if o.get("Uic") != uic:
                continue
            ot = o.get("OpenOrderType") or o.get("OrderType") or ""
            if kind == "stop" and "Stop" not in ot:
                continue
            if kind == "limit" and ot != "Limit":
                continue
            try:
                self._req("DELETE", f"/trade/v2/orders/{o['OrderId']}",
                          params={"AccountKey": self._acct()})
            except Exception:
                pass

    def close_position(self, position_id) -> bool:
        p = self._find_position(position_id)
        if not p:
            log.warning("Saxo close: nie ma pozycji %s", position_id)
            return False
        uic, atype = self._parse(p["epic"])
        buy_was = p["direction"] == "BUY"
        try:
            self._place(self._market(uic, atype, p["size"], not buy_was))  # przeciwna strona
            self._cancel_related(uic)
            return True
        except Exception as e:
            log.warning("Saxo close_position %s: %s", position_id, e)
            return False

    def update_position(self, position_id, stop_level: float = None, profit_level: float = None) -> bool:
        """Zmiana SL/TP. Podmienia TYLKO to, co podano (trailing rusza sam stop,
        nie kasując take-profitu)."""
        p = self._find_position(position_id)
        if not p:
            return False
        uic, atype = self._parse(p["epic"])
        buy_was = p["direction"] == "BUY"
        ok = True
        for kind, otype, level in (("stop", "StopIfTraded", stop_level),
                                   ("limit", "Limit", profit_level)):
            if not level:
                continue
            self._cancel_related(uic, kind)  # tylko ten typ, drugi zostaje nietknięty
            try:
                self._place({"AccountKey": self._acct(), "Uic": uic, "AssetType": atype,
                             "Amount": p["size"], "BuySell": "Sell" if buy_was else "Buy",
                             "OrderType": otype, "OrderPrice": self._round_tick(uic, atype, level),
                             "ManualOrder": False,
                             "OrderDuration": {"DurationType": "GoodTillCancel"}})
            except Exception as e:
                log.warning("Saxo update %s: %s", otype, e)
                ok = False
        return ok

    def close_expired(self, max_hold_hours: float, skip: set | None = None):
        skip = skip or set()
        now = time.time()
        for p in self.get_positions():
            if str(p["dealId"]) in skip or not p.get("openTime"):
                continue
            try:
                from datetime import datetime
                opened = datetime.fromisoformat(p["openTime"].replace("Z", "+00:00")).timestamp()
            except (ValueError, AttributeError):
                continue
            if (now - opened) / 3600 >= max_hold_hours:
                self.close_position(p["dealId"])

    def close_all(self):
        for p in self.get_positions():
            self.close_position(p["dealId"])

    def tradable_tickers(self) -> set:
        return set()  # filtr EDGAR dotyczy akcji US; dla Saxo/GPW pomijamy
