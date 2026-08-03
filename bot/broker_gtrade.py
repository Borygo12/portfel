"""Klient gTrade (Gains Network) — dźwignia on-chain na Arbitrum (krypto 24/7 + akcje US w RTH).
Ten sam interfejs co SaxoClient/MT5Client, więc trader.py i panel nie widzą różnicy.

ARCHITEKTURA: Python nie gada z blockchainem bezpośrednio. Oficjalny stack gTrade jest
w TypeScript (@gainsnetwork/sdk + ethers), więc egzekucję robi lokalny SIDECAR Node.js
(katalog gtrade_sidecar/). Ten adapter woła sidecar przez HTTP na 127.0.0.1.

  Python (broker_gtrade.py)  --HTTP/JSON-->  Node sidecar (server.js)  --ethers-->  Arbitrum

STATUS (2026-07-13):
  Faza 0 GOTOWA: preflight.js potwierdził sieć + że collateral to kanoniczne USDC
    (0xaf88…5831, 6 dec), a adresy z docs to gToken-vaulty (gUSDC/gDAI/gETH) — NIE do wpłaty.
  Faza 1 DO ZROBIENIA: server.js (endpointy poniżej) + rozwiązanie pairIndex i ceny z SDK
    + kodowanie openTrade/closeTradeMarket. Do czasu jego uruchomienia `configured` = False,
    więc trader.py grzecznie pomija egzekucję ("skipped"), nic się nie psuje.

KONTRAKT SIDECARA (server.js ma wystawić te endpointy, JSON in/out):
  GET  /health                      -> {ok, wallet, chainId}
  GET  /account                     -> {balance, available, pnl}   (USDC saldo + PnL otwartych)
  GET  /positions                   -> [{index, pair, long, leverage, collateral, openPrice, currentPrice, tp, sl, openTime}]
  POST /find_pair   {ticker}        -> {pair, pairIndex} | {pair:null}
  POST /price       {pair}          -> {price}
  POST /open        {pair, long, collateralUsdc, leverage, tp, sl, maxSlippageP} -> {ok, index, txHash} | {ok:false, error}
  POST /close       {index}         -> {ok, txHash} | {ok:false, error}
  POST /update_sl   {index, sl}     -> {ok, txHash}

Wielkość pozycji: trader.py liczy `size` w jednostkach aktywa przy danej `price` (notional
z wbudowaną dźwignią). gTrade działa na modelu collateral+leverage, więc tu rozkładamy:
  notional = size * price ;  collateral = notional / leverage_gtrade.
Dźwignię gTrade bierzemy z env GTRADE_LEVERAGE (domyślnie 5) — świadomie osobno od Saxo.
"""

import logging
import os

import requests

log = logging.getLogger("gtrade")

_PORT = os.environ.get("GTRADE_SIDECAR_PORT", "8787")
_BASE = f"http://127.0.0.1:{_PORT}"
_TIMEOUT = 15


class GTradeClient:
    def __init__(self, env: str | None = None):
        # env "live" = mainnet Arbitrum (jedyny sensowny; gTrade nie ma pełnego testnetu z akcjami).
        self.env = (env or os.environ.get("GTRADE_ENV", "live")).strip().lower()
        self.demo = False
        self.default_collateral = os.environ.get("GTRADE_COLLATERAL", "USDC").upper()
        self.leverage = float(os.environ.get("GTRADE_LEVERAGE", "5"))
        self.max_slippage_pct = float(os.environ.get("GTRADE_MAX_SLIPPAGE_PCT", "1.0"))
        self._s = requests.Session()
        self._pair_cache: dict[str, str] = {}   # "ETH" -> "ETH/USD"

    # ------------------------------------------------------------- HTTP helpers
    def _get(self, path: str):
        r = self._s.get(_BASE + path, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict):
        r = self._s.post(_BASE + path, json=body, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()

    @property
    def configured(self) -> bool:
        """True tylko gdy sidecar żyje i ma odblokowany portfel (klucz w env sidecara)."""
        try:
            h = self._get("/health")
            return bool(h.get("ok") and h.get("wallet"))
        except Exception:
            return False

    # ------------------------------------------------------------- instrumenty / cena
    def find_epic(self, ticker: str) -> str | None:
        """Mapuje ticker bota (np. 'ETH', 'AAPL') na parę gTrade (np. 'ETH/USD')."""
        t = (ticker or "").upper().strip()
        if not t:
            return None
        if t in self._pair_cache:
            return self._pair_cache[t]
        try:
            res = self._post("/find_pair", {"ticker": t})
        except Exception:
            log.exception("find_pair padło dla %s", t)
            return None
        pair = res.get("pair")
        if pair:
            self._pair_cache[t] = pair
        return pair

    def get_price(self, epic: str) -> float:
        try:
            return float(self._post("/price", {"pair": epic}).get("price") or 0.0)
        except Exception:
            log.exception("price padło dla %s", epic)
            return 0.0

    # ------------------------------------------------------------- konto / pozycje
    def get_account(self) -> dict:
        try:
            a = self._get("/account")
            return {
                "balance": float(a.get("balance") or 0.0),
                "available": float(a.get("available") or 0.0),
                "pnl": float(a.get("pnl") or 0.0),
            }
        except Exception:
            return {"balance": 0.0, "available": 0.0, "pnl": 0.0}

    def get_positions(self) -> list[dict]:
        """Zwraca pozycje w kształcie oczekiwanym przez trader.py (epic/direction/openLevel...)."""
        try:
            raw = self._get("/positions")
        except Exception:
            return []
        out = []
        for p in raw:
            idx = p.get("index")
            out.append({
                "epic": p.get("pair"),
                "name": p.get("pair"),
                "dealId": idx,
                "positionId": idx,
                "direction": "BUY" if p.get("long") else "SELL",
                "openLevel": p.get("openPrice"),
                "currentLevel": p.get("currentPrice"),
                "sl": p.get("sl"),
                "tp": p.get("tp"),
                "openTime": p.get("openTime"),
            })
        return out

    # ------------------------------------------------------------- egzekucja
    def open_position(self, epic: str, side: str, size: float, sl: float, tp: float) -> dict:
        """side='BUY'/'SELL'. size = jednostki aktywa (z trader.py). Rozkładamy na collateral+leverage."""
        price = self.get_price(epic)
        if price <= 0:
            return {"dealStatus": "REJECTED", "rejectReason": f"brak ceny dla {epic}"}
        notional = size * price
        collateral = notional / self.leverage if self.leverage > 0 else notional
        try:
            res = self._post("/open", {
                "pair": epic,
                "long": side == "BUY",
                "collateralUsdc": round(collateral, 2),
                "leverage": self.leverage,
                "tp": tp,
                "sl": sl,
                "maxSlippageP": self.max_slippage_pct,
            })
        except Exception as e:
            return {"dealStatus": "REJECTED", "rejectReason": str(e)}
        if res.get("ok"):
            return {"dealStatus": "ACCEPTED", "positionId": res.get("index"), "txHash": res.get("txHash")}
        return {"dealStatus": "REJECTED", "rejectReason": res.get("error", "unknown")}

    def close_position(self, position_id) -> bool:
        try:
            return bool(self._post("/close", {"index": position_id}).get("ok"))
        except Exception:
            log.exception("close padło dla %s", position_id)
            return False

    def update_position(self, position_id, stop_level: float | None = None):
        if stop_level is None:
            return
        try:
            self._post("/update_sl", {"index": position_id, "sl": stop_level})
        except Exception:
            log.exception("update_sl padło dla %s", position_id)

    def close_all(self):
        for p in self.get_positions():
            self.close_position(p["dealId"])
