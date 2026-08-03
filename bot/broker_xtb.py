"""Klient XTB xStation (xAPI) — broker z pełnym dostępem do akcji GPW, krypto,
akcji US/EU, forex i indeksów. Ten sam interfejs co MT5Client / CapitalClient,
więc trader.py i panel nie widzą różnicy.

Protokół: WebSocket JSON (wss://ws.xapi.pro/demo|real). Każde żądanie to
{"command": ..., "arguments": {...}}; odpowiedź {"status": true, "returnData": ...}
albo {"status": false, "errorCode": ..., "errorDescr": ...}. Jedna komenda naraz
na gnieździe — serializujemy RLockiem i dokładamy lekki throttle (limit XTB).

Zamykanie/modyfikacja pozycji: tradeTransInfo.order = NUMER POZYCJI (z getTrades),
przy otwieraniu order=0. Wolumen w LOTACH (contractSize = wielkość 1 lota).
Ceny/SL/TP zaokrąglane do 'precision' instrumentu.

Wymaga: pip install websocket-client. Dane logowania w .env:
XTB_USER_ID, XTB_PASSWORD, XTB_DEMO (true/false), opcjonalnie XTB_WS_HOST.
"""

import json
import logging
import os
import threading
import time

import websocket  # websocket-client

log = logging.getLogger("xtb")

# XTB wyłączył ws.xtb.com 14.03.2025 — aktualny host to ws.xapi.pro
_DEFAULT_HOST = "ws.xapi.pro"

# enumy protokołu (potwierdzone z dokumentacji xAPI)
_CMD_BUY, _CMD_SELL = 0, 1
_TYPE_OPEN, _TYPE_CLOSE, _TYPE_MODIFY = 0, 2, 3
_STATUS_ACCEPTED = 3
_PERIOD_D1 = 1440

# krypto: XTB ma realne instrumenty krypto — mapujemy popularne tickery na symbole XTB
_CRYPTO_ALIASES = {
    "BTC": "BITCOIN", "BTCUSD": "BITCOIN", "XBT": "BITCOIN", "BITCOIN": "BITCOIN",
    "ETH": "ETHEREUM", "ETHUSD": "ETHEREUM", "ETHEREUM": "ETHEREUM",
    "LTC": "LITECOIN", "LTCUSD": "LITECOIN",
    "XRP": "RIPPLE", "SOL": "SOLANA", "ADA": "CARDANO", "DOGE": "DOGECOIN",
    "BNB": "BINANCECOIN", "DOT": "POLKADOT",
}


class XTBClient:
    def __init__(self):
        self.demo = os.environ.get("XTB_DEMO", "true").lower() != "false"
        # dane wybierane przełącznikiem XTB_DEMO: osobne sloty demo/realne, z fallbackiem
        # do wspólnych XTB_USER_ID/XTB_PASSWORD (żeby oba konta były w jednym .env)
        if self.demo:
            self.user_id = os.environ.get("XTB_DEMO_USER_ID") or os.environ.get("XTB_USER_ID", "")
            self.password = os.environ.get("XTB_DEMO_PASSWORD") or os.environ.get("XTB_PASSWORD", "")
        else:
            self.user_id = os.environ.get("XTB_REAL_USER_ID") or os.environ.get("XTB_USER_ID", "")
            self.password = os.environ.get("XTB_REAL_PASSWORD") or os.environ.get("XTB_PASSWORD", "")
        # odporność na literówki: numer konta to same cyfry (usuń ew. '#', spacje)
        self.user_id = (self.user_id or "").strip().lstrip("#").strip()
        self.password = (self.password or "").strip()
        host = os.environ.get("XTB_WS_HOST", _DEFAULT_HOST)
        self.url = f"wss://{host}/{'demo' if self.demo else 'real'}"
        self._ws: websocket.WebSocket | None = None
        self._lock = threading.RLock()
        self._logged_in = False
        self._last_cmd = 0.0
        self._symbol_cache: dict[str, str] = {}      # base ticker -> symbol XTB
        self._symbol_info: dict[str, dict] = {}       # symbol -> pełny rekord
        self._symbols_at = 0.0
        self._currency = None

    @property
    def configured(self) -> bool:
        return bool(self.user_id and self.password)

    # ------------------------------------------------------------- transport

    def _connect(self):
        self._ws = websocket.create_connection(self.url, timeout=20,
                                               enable_multithread=True)
        resp = self._raw("login", {"userId": self.user_id, "password": self.password})
        if not resp.get("status"):
            raise ConnectionError(f"XTB login nieudany: {resp.get('errorDescr') or resp}")
        self._logged_in = True
        log.info("Zalogowano do XTB (%s)", "DEMO" if self.demo else "LIVE")

    def _ensure(self):
        if self._ws and self._logged_in and self._ws.connected:
            # XTB rozłącza po ~15 min bezczynności — pinguj po dłuższej przerwie
            if time.time() - self._last_cmd > 300:
                try:
                    self._raw("ping", None)
                except Exception:
                    self._reset()
            if self._ws and self._ws.connected:
                return
        self._reset()
        self._connect()

    def _reset(self):
        self._logged_in = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        self._ws = None

    def _raw(self, command: str, arguments: dict | None) -> dict:
        """Wyślij jedną komendę i odbierz odpowiedź (bez auto-reconnectu)."""
        # throttle: XTB odcina przy zbyt gęstych żądaniach (~<200 ms)
        wait = 0.22 - (time.time() - self._last_cmd)
        if wait > 0:
            time.sleep(wait)
        payload = {"command": command}
        if arguments is not None:
            payload["arguments"] = arguments
        tag = f"{command}{int(time.time() * 1000)}"
        payload["customTag"] = tag
        self._ws.send(json.dumps(payload))
        # czytaj aż trafi odpowiedź z naszym tagiem (pomiń ewentualne inne ramki)
        for _ in range(5):
            resp = json.loads(self._ws.recv())
            if resp.get("customTag") in (tag, None) or "status" in resp:
                self._last_cmd = time.time()
                return resp
        self._last_cmd = time.time()
        return {"status": False, "errorDescr": "brak dopasowanej odpowiedzi"}

    def _call(self, command: str, arguments: dict | None = None) -> dict:
        """Komenda z auto-reconnectem i jednym ponowieniem. Zwraca returnData."""
        with self._lock:
            for attempt in (1, 2):
                try:
                    self._ensure()
                    resp = self._raw(command, arguments)
                    if not resp.get("status"):
                        code = resp.get("errorCode", "")
                        # sesja wygasła/nieautoryzowana -> zaloguj ponownie i ponów
                        if code in ("BE005", "BE118", "EX009", "SExxx") and attempt == 1:
                            self._reset()
                            continue
                        raise RuntimeError(
                            f"XTB {command}: {resp.get('errorDescr') or resp.get('errorCode')}")
                    return resp.get("returnData", {})
                except (websocket.WebSocketException, ConnectionError, OSError) as e:
                    log.warning("XTB %s: błąd transportu (%s), próba %d", command, e, attempt)
                    self._reset()
                    if attempt == 2:
                        raise
        return {}

    # --------------------------------------------------------------- rynki

    def _load_symbols(self):
        data = self._call("getAllSymbols")
        recs = data if isinstance(data, list) else data.get("symbolRecords", [])
        self._symbol_cache, self._symbol_info = {}, {}
        for s in recs:
            sym = s.get("symbol")
            if not sym:
                continue
            self._symbol_info[sym] = s
            base = sym.split(".")[0].upper()            # 'PKN.PL' -> 'PKN', 'AAPL.US' -> 'AAPL'
            self._symbol_cache.setdefault(base, sym)
            self._symbol_cache.setdefault(sym.upper(), sym)
        self._symbols_at = time.time()
        log.info("XTB: załadowano %d symboli", len(self._symbol_info))

    def _ensure_symbols(self):
        if not self._symbol_info or time.time() - self._symbols_at > 3600:
            self._load_symbols()

    def find_epic(self, ticker: str) -> str | None:
        """Mapuje ticker (np. 'PKN', 'KGH', 'DELL', 'BTC') na symbol XTB."""
        self._ensure_symbols()
        key = (ticker or "").upper()
        # krypto: BTC -> BITCOIN itd. (jeśli broker taki symbol ma)
        alias = _CRYPTO_ALIASES.get(key)
        if alias and alias in self._symbol_info:
            return alias
        sym = self._symbol_cache.get(key)
        if sym:
            return sym
        # akcje GPW bez podanego sufiksu: spróbuj TICKER.PL
        pl = self._symbol_cache.get(f"{key}.PL")
        return pl

    def _info(self, symbol: str) -> dict:
        self._ensure_symbols()
        return self._symbol_info.get(symbol) or self._call("getSymbol", {"symbol": symbol})

    def get_price(self, symbol: str) -> float:
        d = self._call("getSymbol", {"symbol": symbol})
        bid, ask = d.get("bid"), d.get("ask")
        if bid and ask:
            return (bid + ask) / 2
        return ask or bid or 0.0

    def _chart_d1(self, symbol: str, days: int):
        """Świece dzienne (getChartLastRequest). XTB zwraca ceny skalowane 10^digits,
        a high/low/close jako DELTY od open — normalizujemy do realnych cen."""
        start_ms = int((time.time() - (days + 3) * 86400) * 1000)
        d = self._call("getChartLastRequest",
                       {"info": {"symbol": symbol, "period": _PERIOD_D1, "start": start_ms}})
        digits = d.get("digits", 2)
        scale = 10 ** digits
        out = []
        for r in d.get("rateInfos", []):
            o = r["open"] / scale
            out.append({"open": o,
                        "high": (r["open"] + r["high"]) / scale,
                        "low": (r["open"] + r["low"]) / scale,
                        "close": (r["open"] + r["close"]) / scale})
        return out

    def get_daily_change_pct(self, symbol: str) -> float | None:
        bars = self._chart_d1(symbol, 2)
        if not bars:
            return None
        day_open = bars[-1]["open"]
        price = self.get_price(symbol)
        if not day_open or not price:
            return None
        return (price - day_open) / day_open * 100

    def get_atr_pct(self, symbol: str, days: int = 14) -> float | None:
        bars = self._chart_d1(symbol, days)
        if len(bars) < 5:
            return None
        vals = [(b["high"] - b["low"]) / b["close"] * 100 for b in bars if b["close"]]
        return sum(vals) / len(vals) if vals else None

    # ------------------------------------------------------- konto / pozycje

    def _get_currency(self) -> str:
        if self._currency is None:
            try:
                self._currency = self._call("getCurrentUserData").get("currency") or ""
            except Exception:
                self._currency = ""
        return self._currency

    def get_account(self) -> dict:
        m = self._call("getMarginLevel")
        balance = m.get("balance") or 0
        equity = m.get("equity") or balance
        return {
            "balance": balance,
            "available": m.get("margin_free"),
            "pnl": round(equity - balance, 2),
            "currency": m.get("currency") or self._get_currency(),
            "demo": self.demo,
        }

    def get_positions(self) -> list[dict]:
        trades = self._call("getTrades", {"openedOnly": True}) or []
        out = []
        for t in trades:
            if t.get("closed"):
                continue
            sym = t.get("symbol")
            buy = t.get("cmd") == _CMD_BUY
            out.append({
                "dealId": t.get("position"),          # id pozycji (do zamykania)
                "epic": sym,
                "name": self._symbol_info.get(sym, {}).get("description") or sym,
                "direction": "BUY" if buy else "SELL",
                "size": t.get("volume"),
                "openLevel": t.get("open_price"),
                "currentLevel": self.get_price(sym) if sym else None,
                "sl": t.get("sl"),
                "tp": t.get("tp"),
                "pnl": t.get("profit"),
                "openTime": (t.get("open_time") or 0) / 1000,  # ms -> epoch s
                "_order": t.get("order"),
                "_cmd": t.get("cmd"),
            })
        return out

    # ------------------------------------------------------------ egzekucja

    def _round_lots(self, info: dict, size: float) -> float:
        """Przelicza wielkość (jednostki) na loty i dopasowuje do lotMin/lotStep."""
        contract = info.get("contractSize") or 1
        lot_min = info.get("lotMin") or 0.01
        lot_step = info.get("lotStep") or lot_min
        lots = size / contract
        lots = round(lots / lot_step) * lot_step
        if lots < lot_min:
            lots = lot_min
        return round(lots, 4)

    def _cap_to_margin(self, symbol: str, lots: float, info: dict) -> float:
        """Przycina wolumen, jeśli wymagany depozyt > wolne środki (bufor 10%)."""
        try:
            need = self._call("getMarginTrade", {"symbol": symbol, "volume": lots}).get("margin")
            free = (self._call("getMarginLevel").get("margin_free") or 0) * 0.9
        except Exception:
            return lots
        if not need or need <= free:
            return lots
        lot_min = info.get("lotMin") or 0.01
        lot_step = info.get("lotStep") or lot_min
        capped = lots * free / need
        capped = int(capped / lot_step) * lot_step
        log.info("XTB depozyt przycina %s: %.4f -> %.4f (margin %.2f > wolne %.2f)",
                 symbol, lots, capped, need, free)
        return capped if capped >= lot_min else 0.0

    def _trade(self, info: dict) -> dict:
        """Wysyła tradeTransaction i czeka na status wykonania."""
        res = self._call("tradeTransaction", {"tradeTransInfo": info})
        order = res.get("order")
        if not order:
            return {"ok": False, "reason": "brak numeru zlecenia", "order": None}
        for _ in range(15):   # do ~4.5 s na wykonanie
            st = self._call("tradeTransactionStatus", {"order": order})
            status = st.get("requestStatus")
            if status == _STATUS_ACCEPTED:
                return {"ok": True, "order": order}
            if status in (0, 4):  # ERROR / REJECTED
                return {"ok": False, "reason": st.get("message") or "odrzucone", "order": order}
            time.sleep(0.3)
        return {"ok": False, "reason": "timeout statusu zlecenia", "order": order}

    def open_position(self, symbol: str, direction: str, size: float,
                      stop_level: float, profit_level: float) -> dict:
        info = self._info(symbol)
        if not info:
            return {"dealStatus": "REJECTED", "rejectReason": f"brak symbolu {symbol}"}
        prec = info.get("precision", 2)
        lots = self._round_lots(info, size)
        lots = self._cap_to_margin(symbol, lots, info)
        if lots <= 0:
            return {"dealStatus": "REJECTED", "rejectReason": "za mało wolnego depozytu"}
        buy = direction == "BUY"
        price = self.get_price(symbol)
        tt = self._trade({
            "cmd": _CMD_BUY if buy else _CMD_SELL,
            "type": _TYPE_OPEN,
            "symbol": symbol,
            "volume": lots,
            "price": round(price, prec),
            "sl": round(stop_level, prec),
            "tp": round(profit_level, prec),
            "order": 0,
            "customComment": "news-trader",
        })
        log.info("XTB zlecenie %s %s vol=%.4f SL=%.2f TP=%.2f -> %s",
                 direction, symbol, lots, stop_level, profit_level,
                 "OK" if tt["ok"] else tt.get("reason"))
        if not tt["ok"]:
            return {"dealStatus": "REJECTED", "rejectReason": tt.get("reason")}
        # numer pozycji do późniejszego zamknięcia = najświeższa pozycja na tym symbolu
        position_id = tt["order"]
        try:
            for t in self.get_positions():
                if t["epic"] == symbol:
                    position_id = t["dealId"]
                    break
        except Exception:
            pass
        return {"dealStatus": "ACCEPTED", "rejectReason": None, "positionId": position_id}

    def _find_trade(self, position_id) -> dict | None:
        for t in self._call("getTrades", {"openedOnly": True}) or []:
            if str(t.get("position")) == str(position_id) or str(t.get("order")) == str(position_id):
                return t
        return None

    def update_position(self, position_id, stop_level: float = None,
                        profit_level: float = None) -> bool:
        t = self._find_trade(position_id)
        if not t:
            return False
        info = self._info(t["symbol"])
        prec = info.get("precision", 2)
        res = self._trade({
            "cmd": t.get("cmd", _CMD_BUY),
            "type": _TYPE_MODIFY,
            "symbol": t["symbol"],
            "volume": t.get("volume"),
            "price": round(self.get_price(t["symbol"]), prec),
            "sl": round(stop_level, prec) if stop_level is not None else (t.get("sl") or 0),
            "tp": round(profit_level, prec) if profit_level is not None else (t.get("tp") or 0),
            "order": t.get("position"),
        })
        return res["ok"]

    def close_position(self, position_id) -> bool:
        t = self._find_trade(position_id)
        if not t:
            log.warning("XTB close: nie znaleziono pozycji %s", position_id)
            return False
        info = self._info(t["symbol"])
        prec = info.get("precision", 2)
        buy = t.get("cmd") == _CMD_BUY
        # zamknięcie: przeciwna strona rynku, order = NUMER POZYCJI
        price = self.get_price(t["symbol"])
        res = self._trade({
            "cmd": t.get("cmd", _CMD_BUY),
            "type": _TYPE_CLOSE,
            "symbol": t["symbol"],
            "volume": t.get("volume"),
            "price": round(price, prec),
            "order": t.get("position"),
        })
        log.info("XTB zamknięcie pozycji %s (%s): %s", position_id, t["symbol"],
                 "OK" if res["ok"] else res.get("reason"))
        return res["ok"]

    def close_expired(self, max_hold_hours: float, skip: set | None = None):
        skip = skip or set()
        now = time.time()
        for t in self._call("getTrades", {"openedOnly": True}) or []:
            pid = t.get("position")
            if str(pid) in skip:
                continue
            age_h = (now - (t.get("open_time") or 0) / 1000) / 3600
            if age_h >= max_hold_hours:
                self.close_position(pid)

    def close_all(self):
        for t in self._call("getTrades", {"openedOnly": True}) or []:
            self.close_position(t.get("position"))

    def tradable_tickers(self) -> set:
        self._ensure_symbols()
        return set(self._symbol_cache.keys())
