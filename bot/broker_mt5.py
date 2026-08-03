"""Klient MetaTrader 5 — działa z KAŻDYM brokerem oferującym MT5 (XM, Admirals,
Pepperstone itd.). Wymaga zainstalowanego terminala MT5 na Windowsie; biblioteka
sama go uruchomi i zaloguje danymi z .env.

Ten sam interfejs co broker_capital.CapitalClient, więc trader.py i panel
nie widzą różnicy.
"""

import logging
import os
import re
import threading
import time

import MetaTrader5 as mt5

log = logging.getLogger("mt5")

# --- Krypto ---------------------------------------------------------------
# To konto (XM) nie ma osobnych par BTC/ETH/itd. — jedyny instrument krypto to
# indeks "Crypto 10" (Crypto_10#). Każdy sygnał krypto (BTC, ETH, ...) gramy więc
# na nim: kierunek przenosi się 1:1 (indeks jest zdominowany przez BTC/ETH, więc
# news dobry/zły dla BTC jest dobry/zły dla Crypto 10). Hard-code — do czasu, aż
# broker udostępni pojedyncze pary.
CRYPTO_INDEX_SYMBOL = "Crypto_10#"
_CRYPTO_TICKERS = {
    "BTC", "BTCUSD", "BTCUSDT", "XBT", "XBTUSD", "BITCOIN",
    "ETH", "ETHUSD", "ETHUSDT", "ETHEREUM",
    "SOL", "SOLUSD", "SOLANA",
    "CRYPTO", "CRYPTO10", "CRYPTO_10",
}


def _norm_ticker(t: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (t or "").upper())


_CRYPTO_NORM = {_norm_ticker(t) for t in _CRYPTO_TICKERS}


def is_crypto_ticker(ticker: str) -> bool:
    """Czy ticker to kryptowaluta (BTC/ETH/...), którą na tym koncie gramy indeksem."""
    return _norm_ticker(ticker) in _CRYPTO_NORM


def _locked(fn):
    """MT5 API nie jest thread-safe. Pętla bota i requesty panelu wołają klienta
    z różnych wątków — serializujemy każdą operację jednym RLockiem."""
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)
    return wrapper


class MT5Client:
    def __init__(self, live: bool | None = None):
        # dane per środowisko (MT5_DEMO_* / MT5_LIVE_*), z fallbackiem do wspólnych MT5_*
        pfx = "MT5_LIVE_" if live else "MT5_DEMO_"
        self.login = int(os.environ.get(pfx + "LOGIN") or os.environ.get("MT5_LOGIN") or 0)
        self.password = os.environ.get(pfx + "PASSWORD") or os.environ.get("MT5_PASSWORD", "")
        self.server = (os.environ.get(pfx + "SERVER") or os.environ.get("MT5_SERVER", "")).strip()
        self.path = os.environ.get("MT5_PATH") or None  # opcjonalna ścieżka do terminal64.exe
        self._initialized = False
        self._symbol_cache: dict[str, str] = {}
        self._lock = threading.RLock()
        self.demo = True  # doprecyzowane po połączeniu

    @property
    def configured(self) -> bool:
        return bool(self.login and self.password and self.server)

    def _ensure(self):
        if self._initialized and mt5.terminal_info():
            return
        kwargs = {"login": self.login, "password": self.password, "server": self.server}
        if self.path:
            kwargs["path"] = self.path
        if not mt5.initialize(**kwargs):
            raise ConnectionError(f"MT5 initialize failed: {mt5.last_error()}")
        acct = mt5.account_info()
        if acct is None:
            raise ConnectionError(f"MT5 login failed: {mt5.last_error()}")
        self.demo = acct.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
        self._initialized = True
        log.info("Połączono z MT5: %s @ %s (%s)", acct.login, self.server,
                 "DEMO" if self.demo else "LIVE")

    # --- rynki ---

    def _build_ticker_map(self):
        """XM nazywa symbole nazwami firm ('Dell'), ale ticker jest w opisie:
        'Dell Technologies Inc (DELL.N)' — parsujemy to raz dla wszystkich symboli."""
        self._symbol_cache = {}
        for s in mt5.symbols_get() or []:
            m = re.search(r"\(([A-Z][A-Z0-9.]*)\.[A-Z]+\)\s*$", s.description or "")
            if m:
                self._symbol_cache.setdefault(m.group(1).upper(), s.name)
            # zapasowo: brokerzy używający tickera wprost w nazwie (np. 'DELL.US')
            base = s.name.lstrip("#").rstrip("#").split(".")[0].upper()
            self._symbol_cache.setdefault(base, s.name)
            # aliasy indeksów/surowców: 'US100Cash#' -> 'US100', 'GOLD#' -> 'GOLD'
            if base.endswith("CASH"):
                self._symbol_cache.setdefault(base[:-4], s.name)

    @_locked
    def tradable_tickers(self) -> set:
        """Zbiór tickerów, które broker potrafi handlować (do filtra EDGAR przed AI)."""
        self._ensure()
        if not self._symbol_cache:
            self._build_ticker_map()
        return set(self._symbol_cache.keys())

    @_locked
    def find_epic(self, ticker: str) -> str | None:
        """Mapuje ticker (np. 'DELL') na symbol brokera (np. 'Dell' na XM).
        Tickery krypto (BTC, ETH, ...) automatycznie mapowane na Crypto_10#."""
        self._ensure()
        # --- Krypto: zawsze gramy na indeksie ---
        if is_crypto_ticker(ticker):
            mt5.symbol_select(CRYPTO_INDEX_SYMBOL, True)
            info = mt5.symbol_info(CRYPTO_INDEX_SYMBOL)
            if info:
                log.info("Krypto ticker '%s' → mapuję na %s", ticker, CRYPTO_INDEX_SYMBOL)
                return CRYPTO_INDEX_SYMBOL
            log.warning("Krypto ticker '%s' → brak %s u brokera!", ticker, CRYPTO_INDEX_SYMBOL)
            return None
        # --- Standardowe akcje ---
        if not self._symbol_cache:
            self._build_ticker_map()
        name = self._symbol_cache.get(ticker.upper())
        if name:
            mt5.symbol_select(name, True)
        return name

    @_locked
    def get_price(self, symbol: str) -> float:
        self._ensure()
        # świeżo dodany symbol potrzebuje chwili na synchronizację ticków z serwerem
        for _ in range(10):
            tick = mt5.symbol_info_tick(symbol)
            if tick and (tick.bid or tick.ask):
                return (tick.bid + tick.ask) / 2 if tick.bid and tick.ask else (tick.ask or tick.bid)
            time.sleep(0.3)
        return 0.0

    @_locked
    def get_daily_change_pct(self, symbol: str) -> float | None:
        """Dzisiejsza zmiana % od otwarcia dnia (do reguły 'news już wyceniony')."""
        self._ensure()
        mt5.symbol_select(symbol, True)
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 1)
        if rates is None or len(rates) == 0:
            return None
        day_open = float(rates[0]["open"])
        price = self.get_price(symbol)
        if not day_open or not price:
            return None
        return (price - day_open) / day_open * 100

    @_locked
    def get_atr_pct(self, symbol: str, days: int = 14) -> float | None:
        """Średnia dzienna rozpiętość % z ostatnich N dni (uproszczony ATR) — miara zmienności."""
        self._ensure()
        mt5.symbol_select(symbol, True)
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 1, days)
        if rates is None or len(rates) < 5:
            return None
        vals = [(float(r["high"]) - float(r["low"])) / float(r["close"]) * 100
                for r in rates if r["close"]]
        return sum(vals) / len(vals) if vals else None

    # --- konto / pozycje ---

    @_locked
    def get_account(self) -> dict:
        self._ensure()
        a = mt5.account_info()
        return {
            "balance": a.balance,
            "available": a.margin_free,
            "pnl": a.profit,
            "currency": a.currency,
            "demo": self.demo,
        }

    @_locked
    def get_positions(self) -> list[dict]:
        self._ensure()
        out = []
        for p in mt5.positions_get() or []:
            out.append({
                "dealId": p.ticket,
                "epic": p.symbol,
                "name": p.symbol,
                "direction": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                "size": p.volume,
                "openLevel": p.price_open,
                "currentLevel": p.price_current,
                "sl": p.sl,
                "tp": p.tp,
                "pnl": p.profit,
                "openTime": p.time,  # epoch czasu serwera
            })
        return out

    def _cap_size_to_margin(self, symbol: str, direction: str, size: float, info) -> float:
        """Skaluje wolumen w dół, jeśli wymagany depozyt przekracza wolne środki.
        Zostawiamy 10% bufora, żeby nie wejść od razu w margin call."""
        order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        tick = mt5.symbol_info_tick(symbol)
        price = tick.ask if direction == "BUY" else tick.bid
        margin = mt5.order_calc_margin(order_type, symbol, size, price)
        free = (mt5.account_info().margin_free or 0) * 0.9
        if margin is None or margin <= 0 or margin <= free:
            return size
        capped = size * free / margin
        step = info.volume_step or 0.01
        capped = int(capped / step) * step  # w dół, do kroku wolumenu
        log.info("Depozyt przycina pozycję %s: %.2f -> %.2f (wymagany margin %.2f > wolne %.2f)",
                 symbol, size, capped, margin, free)
        return capped

    @_locked
    def open_position(self, symbol: str, direction: str, size: float,
                      stop_level: float, profit_level: float) -> dict:
        self._ensure()
        info = mt5.symbol_info(symbol)
        if not info:
            return {"dealStatus": "REJECTED", "rejectReason": f"brak symbolu {symbol}"}

        # dopasuj wolumen do wymogów brokera (min/step)
        step = info.volume_step or 0.01
        size = max(info.volume_min, round(size / step) * step)

        # przytnij do najwyższej wielkości, na jaką pozwala depozyt brokera:
        # gdy owner ustawi dźwignię wyższą niż limit instrumentu, gramy maksimum
        size = self._cap_size_to_margin(symbol, direction, size, info)
        if size < info.volume_min:
            return {"dealStatus": "REJECTED",
                    "rejectReason": "za mało wolnego depozytu nawet na minimalną pozycję"}

        tick = mt5.symbol_info_tick(symbol)
        buy = direction == "BUY"
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": size,
            "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
            "price": tick.ask if buy else tick.bid,
            "sl": round(stop_level, info.digits),
            "tp": round(profit_level, info.digits),
            "deviation": 30,  # dopuszczalny poślizg w punktach
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        ok = result and result.retcode == mt5.TRADE_RETCODE_DONE
        log.info("Zlecenie %s %s vol=%.2f SL=%.2f TP=%.2f -> %s",
                 direction, symbol, size, stop_level, profit_level,
                 result.retcode if result else "brak odpowiedzi")
        return {
            "dealStatus": "ACCEPTED" if ok else "REJECTED",
            "rejectReason": None if ok else (result.comment if result else str(mt5.last_error())),
            "positionId": result.order if ok else None,  # ticket pozycji (do zamknięcia przez weryfikator)
        }

    @_locked
    def update_position(self, position_id, stop_level: float = None, profit_level: float = None) -> bool:
        self._ensure()
        try:
            ticket = int(position_id)
        except (TypeError, ValueError):
            return False
        
        positions = mt5.positions_get(ticket=ticket) or ()
        if not positions:
            positions = tuple(p for p in (mt5.positions_get() or ()) if p.ticket == ticket)
        if not positions:
            return False
            
        p = positions[0]
        info = mt5.symbol_info(p.symbol)
        
        sl = round(stop_level, info.digits) if stop_level is not None else p.sl
        tp = round(profit_level, info.digits) if profit_level is not None else p.tp
        
        if sl == p.sl and tp == p.tp:
            return True
            
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": p.ticket,
            "symbol": p.symbol,
            "sl": sl,
            "tp": tp,
        }
        result = mt5.order_send(request)
        ok = result and result.retcode == mt5.TRADE_RETCODE_DONE
        if ok:
            log.info("Zaktualizowano pozycję %s (%s): nowy SL=%.2f TP=%.2f", p.symbol, p.ticket, sl, tp)
        else:
            log.warning("Błąd aktualizacji pozycji %s (%s): %s", p.symbol, p.ticket, 
                        result.comment if result else mt5.last_error())
        return bool(ok)

    @_locked
    def close_position(self, position_id) -> bool:
        """Zamyka jedną konkretną pozycję po jej tickecie (panel / weryfikator)."""
        self._ensure()
        try:
            ticket = int(position_id)  # z URL/JSON przychodzi string, MT5 wymaga int
        except (TypeError, ValueError):
            log.warning("close_position: zły identyfikator %r", position_id)
            return False
        positions = mt5.positions_get(ticket=ticket) or ()
        if not positions:  # fallback: dopasuj po tickecie w pełnej liście
            positions = tuple(p for p in (mt5.positions_get() or ()) if p.ticket == ticket)
        if not positions:
            log.warning("close_position: nie znaleziono pozycji %s (może już zamknięta)", ticket)
            return False
        p = positions[0]
        buy = p.type == mt5.POSITION_TYPE_BUY
        tick = mt5.symbol_info_tick(p.symbol)
        result = mt5.order_send({
            "action": mt5.TRADE_ACTION_DEAL,
            "position": p.ticket,
            "symbol": p.symbol,
            "volume": p.volume,
            "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
            "price": tick.bid if buy else tick.ask,
            "deviation": 30,
            "type_filling": mt5.ORDER_FILLING_IOC,
        })
        ok = result and result.retcode == mt5.TRADE_RETCODE_DONE
        log.info("Weryfikator zamyka pozycję %s (%s): %s", p.symbol, p.ticket,
                 "OK" if ok else (result.comment if result else mt5.last_error()))
        return bool(ok)

    @_locked
    def close_expired(self, max_hold_hours: float, skip: set | None = None):
        """Zamyka pozycje starsze niż max_hold_hours (krótkie trady — nie trzymamy).
        Pozycje z ręczną flagą 'trzymaj' (skip) są pomijane."""
        self._ensure()
        skip = skip or set()
        now_srv = None
        for p in mt5.positions_get() or []:
            if str(p.ticket) in skip:
                continue
            tick = mt5.symbol_info_tick(p.symbol)
            if not tick:
                continue
            now_srv = tick.time
            if now_srv - p.time < max_hold_hours * 3600:
                continue
            buy = p.type == mt5.POSITION_TYPE_BUY
            result = mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL,
                "position": p.ticket,
                "symbol": p.symbol,
                "volume": p.volume,
                "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
                "price": tick.bid if buy else tick.ask,
                "deviation": 30,
                "type_filling": mt5.ORDER_FILLING_IOC,
            })
            log.info("Limit czasu %.1f h — zamykam %s (%s): %s", max_hold_hours,
                     p.symbol, p.ticket, result.retcode if result else mt5.last_error())

    @_locked
    def close_all(self):
        self._ensure()
        for p in mt5.positions_get() or []:
            buy = p.type == mt5.POSITION_TYPE_BUY
            tick = mt5.symbol_info_tick(p.symbol)
            result = mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL,
                "position": p.ticket,
                "symbol": p.symbol,
                "volume": p.volume,
                "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
                "price": tick.bid if buy else tick.ask,
                "deviation": 30,
                "type_filling": mt5.ORDER_FILLING_IOC,
            })
            log.warning("Zamknięcie %s (%s): %s", p.symbol, p.ticket,
                        result.retcode if result else mt5.last_error())
