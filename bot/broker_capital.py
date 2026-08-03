"""Klient Capital.com REST API (https://open-api.capital.com/).

Sesja: POST /session z X-CAP-API-KEY + email/hasło zwraca tokeny CST i
X-SECURITY-TOKEN w nagłówkach; sesja wygasa po ~10 min bezczynności,
więc na 401 logujemy się ponownie i ponawiamy request.
"""

import logging
import os
import threading

import requests

log = logging.getLogger("capital")

LIVE_URL = "https://api-capital.backend-capital.com"
DEMO_URL = "https://demo-api-capital.backend-capital.com"


class CapitalClient:
    def __init__(self):
        self.api_key = os.environ.get("CAPITAL_API_KEY", "")
        self.identifier = os.environ.get("CAPITAL_IDENTIFIER", "")
        self.password = os.environ.get("CAPITAL_PASSWORD", "")
        demo = os.environ.get("CAPITAL_DEMO", "true").lower() != "false"
        self.base = DEMO_URL if demo else LIVE_URL
        self.demo = demo
        self._tokens = {}
        self._lock = threading.Lock()
        self._epic_cache: dict[str, str] = {}

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.identifier and self.password)

    def _login(self):
        resp = requests.post(
            f"{self.base}/api/v1/session",
            headers={"X-CAP-API-KEY": self.api_key},
            json={"identifier": self.identifier, "password": self.password},
            timeout=10,
        )
        resp.raise_for_status()
        self._tokens = {
            "CST": resp.headers["CST"],
            "X-SECURITY-TOKEN": resp.headers["X-SECURITY-TOKEN"],
        }
        log.info("Zalogowano do Capital.com (%s)", "DEMO" if self.demo else "LIVE")

    def _request(self, method: str, path: str, **kwargs) -> dict:
        with self._lock:
            if not self._tokens:
                self._login()
            headers = {"X-CAP-API-KEY": self.api_key, **self._tokens}
            resp = requests.request(method, f"{self.base}{path}", headers=headers, timeout=10, **kwargs)
            if resp.status_code == 401:
                self._login()
                headers = {"X-CAP-API-KEY": self.api_key, **self._tokens}
                resp = requests.request(method, f"{self.base}{path}", headers=headers, timeout=10, **kwargs)
            resp.raise_for_status()
            return resp.json() if resp.text else {}

    # --- rynki ---

    def find_epic(self, ticker: str) -> str | None:
        """Mapuje ticker (np. 'DELL') na epic instrumentu CFD na Capital.com."""
        if ticker in self._epic_cache:
            return self._epic_cache[ticker]
        data = self._request("GET", "/api/v1/markets", params={"searchTerm": ticker})
        for m in data.get("markets", []):
            if m.get("instrumentType") in ("SHARES", "OPT_SHARES") and m.get("epic"):
                self._epic_cache[ticker] = m["epic"]
                return m["epic"]
        return None

    def get_price(self, epic: str) -> float:
        data = self._request("GET", f"/api/v1/markets/{epic}")
        snap = data.get("snapshot", {})
        bid, offer = snap.get("bid"), snap.get("offer")
        return (bid + offer) / 2 if bid and offer else (offer or bid or 0.0)

    # --- konto / pozycje ---

    def get_account(self) -> dict:
        data = self._request("GET", "/api/v1/accounts")
        accounts = data.get("accounts", [])
        if not accounts:
            return {}
        b = accounts[0].get("balance", {})
        return {
            "balance": b.get("balance"),
            "available": b.get("available"),
            "pnl": b.get("profitLoss"),
            "currency": accounts[0].get("currency"),
            "demo": self.demo,
        }

    def get_positions(self) -> list[dict]:
        data = self._request("GET", "/api/v1/positions")
        out = []
        for p in data.get("positions", []):
            pos, market = p.get("position", {}), p.get("market", {})
            out.append({
                "dealId": pos.get("dealId"),
                "epic": market.get("epic"),
                "name": market.get("instrumentName"),
                "direction": pos.get("direction"),
                "size": pos.get("size"),
                "openLevel": pos.get("level"),
                "currentLevel": market.get("bid") if pos.get("direction") == "BUY" else market.get("offer"),
                "sl": pos.get("stopLevel"),
                "tp": pos.get("profitLevel"),
                "pnl": pos.get("upl"),
                "openTime": pos.get("createdDate"),  # Zazwyczaj zwracane w Capital API (ISO 8601 lub epoch)
            })
        return out

    def open_position(self, epic: str, direction: str, size: float,
                      stop_level: float, profit_level: float) -> dict:
        """direction: 'BUY' | 'SELL'. Zwraca potwierdzenie deala."""
        body = {
            "epic": epic,
            "direction": direction,
            "size": round(size, 2),
            "stopLevel": round(stop_level, 2),
            "profitLevel": round(profit_level, 2),
            "guaranteedStop": False,
        }
        data = self._request("POST", "/api/v1/positions", json=body)
        ref = data.get("dealReference")
        confirm = self._request("GET", f"/api/v1/confirms/{ref}") if ref else {}
        log.info("Zlecenie %s %s size=%.2f SL=%.2f TP=%.2f -> %s",
                 direction, epic, size, stop_level, profit_level,
                 confirm.get("dealStatus", "?"))
        return confirm

    def update_position(self, position_id, stop_level: float = None, profit_level: float = None) -> bool:
        """Aktualizacja Stop Loss / Take Profit otwartej pozycji."""
        body = {}
        if stop_level is not None:
            body["stopLevel"] = round(stop_level, 2)
        if profit_level is not None:
            body["profitLevel"] = round(profit_level, 2)
            
        if not body:
            return True
            
        try:
            data = self._request("PUT", f"/api/v1/positions/{position_id}", json=body)
            # Capital API zwraca dealReference podobnie jak przy otwieraniu
            ref = data.get("dealReference")
            if ref:
                log.info("Zaktualizowano SL/TP dla pozycji %s (ref: %s)", position_id, ref)
            return True
        except Exception as e:
            log.warning("Nie udało się zaktualizować pozycji %s: %s", position_id, e)
            return False

    def close_all(self):
        for p in self.get_positions():
            try:
                self._request("DELETE", f"/api/v1/positions/{p['dealId']}")
                log.warning("Zamknięto pozycję %s (%s)", p["epic"], p["dealId"])
            except requests.RequestException:
                log.exception("Nie udało się zamknąć %s", p["dealId"])
