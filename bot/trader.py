"""Silnik decyzyjny: bezpieczniki + wielkość pozycji wg strategii + egzekucja."""

import json
import logging
import os
import time
from datetime import date

import state
import strategy
from config import load_params

log = logging.getLogger("trader")


# Konta wybieralne z panelu (suwak). Każde = (typ brokera, środowisko).
ACCOUNTS = {
    "saxo_demo":  ("saxo", "sim"),
    "saxo_live":  ("saxo", "live"),
    "xm_demo":    ("mt5", "demo"),
    "xm_live":    ("mt5", "live"),
    "gtrade":     ("gtrade", "live"),   # dźwignia on-chain (Arbitrum) — krypto 24/7 + akcje US w RTH
}


def _build_client(account: str):
    kind, env = ACCOUNTS.get(account, ("saxo", "live"))
    if kind == "saxo":
        from broker_saxo import SaxoClient
        return SaxoClient(env=env)
    if kind == "mt5":
        from broker_mt5 import MT5Client
        return MT5Client(live=(env == "live"))
    if kind == "gtrade":
        from broker_gtrade import GTradeClient
        return GTradeClient(env=env)
    from broker_capital import CapitalClient
    return CapitalClient()


_client = None
_client_account = None


def get_client():
    """Zwraca klienta aktywnego konta; przebudowuje, gdy owner przełączył konto w panelu."""
    global _client, _client_account
    acct = load_params().get("active_account") or "saxo_live"
    if _client is None or _client_account != acct:
        _client = _build_client(acct)
        _client_account = acct
        log.info("Aktywne konto brokera: %s (%s)", acct, type(_client).__name__)
    return _client


def reset_client():
    """Wymusza przebudowę klienta (np. po ponownym zalogowaniu do Saxo — świeży token
    z pliku zamiast starego, martwego w pamięci)."""
    global _client, _client_account
    _client = None
    _client_account = None


class _ClientProxy:
    """Pozwala pisać `trader.client.cokolwiek` — zawsze trafia do aktywnego konta."""
    def __getattr__(self, name):
        return getattr(get_client(), name)


client = _ClientProxy()

_DAY_FILE = os.path.join(os.path.dirname(__file__), "day_start.json")


def _day_start_balance(current: float) -> float:
    """Kapitał z początku dnia — baza do dziennego limitu straty."""
    today = date.today().isoformat()
    try:
        with open(_DAY_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        if saved.get("date") == today:
            return saved["balance"]
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    with open(_DAY_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": today, "balance": current}, f)
    return current


def daily_loss_exceeded(params: dict) -> bool:
    acct = client.get_account()
    balance = acct.get("balance") or 0
    equity = balance + (acct.get("pnl") or 0)
    start = _day_start_balance(balance)
    if start <= 0:
        return False
    loss_pct = (start - equity) / start * 100
    return loss_pct >= params["daily_loss_limit_pct"]


def open_trade(ticker: str, direction: str, reason: str, signal: dict | None = None,
               target: dict | None = None) -> dict:
    """Otwiera pozycję. signal/target (od AI) włączają mnożniki strategii;
    bez nich (stare wywołania/testy) gra bazową wielkością."""
    params = load_params()
    signal = signal or {"strength": 75, "signal_type": "direct"}
    target = target or {"ticker": ticker, "direction": direction, "weight": 1.0}

    if params["kill_switch"]:
        return {"action": "skipped", "why": "kill_switch aktywny"}
    if not params["trading_enabled"]:
        return {"action": "skipped", "why": "tryb obserwacji (trading wyłączony)"}
    if not client.configured:
        return {"action": "skipped", "why": "brak kluczy brokera w .env"}
    if daily_loss_exceeded(params):
        client.close_all()
        return {"action": "halted", "why": "przekroczony dzienny limit straty — pozycje zamknięte"}
    if len(client.get_positions()) >= params["max_open_positions"]:
        return {"action": "skipped", "why": "osiągnięty limit otwartych pozycji"}

    epic = client.find_epic(ticker)
    if not epic:
        return {"action": "skipped", "why": f"nie znaleziono instrumentu {ticker} u brokera"}

    # Zabezpieczenie przed dublowaniem pozycji
    open_positions = client.get_positions()
    if any(p["epic"] == epic for p in open_positions):
        if int(signal.get("strength", 0)) < 95:
            return {"action": "skipped", "why": f"pozycja na {epic} już istnieje (siła < 95)"}

    price = client.get_price(epic)
    if price <= 0:
        return {"action": "skipped", "why": f"brak ceny dla {epic}"}

    # --- mnożniki strategii (agresywność, siła, typ, wycenienie, powtórki, waga) ---
    daily_change = client.get_daily_change_pct(epic) if hasattr(client, "get_daily_change_pct") else None
    mult, notes = strategy.position_multiplier(signal, target, daily_change, params)

    acct = client.get_account()
    base_cap = acct.get("balance") or acct.get("available") or 0
    notional = base_cap * params["position_pct_of_equity"] / 100 \
        * params["max_leverage"] * mult
    size = notional / price
    if size <= 0:
        return {"action": "skipped", "why": f"za mały kapitał na pozycję (baza: {base_cap})"}

    # --- TP/SL: baza skalowana zmiennością spółki ---
    atr = client.get_atr_pct(epic) if hasattr(client, "get_atr_pct") else None
    tp_pct, sl_pct, vol_note = strategy.volatility_tp_sl(atr, params)
    if vol_note:
        notes.append(vol_note)

    sign = 1 if direction == "long" else -1
    tp = price * (1 + sign * tp_pct / 100)
    sl = price * (1 - sign * sl_pct / 100)

    confirm = client.open_position(
        epic, "BUY" if direction == "long" else "SELL", size, sl, tp,
    )
    status = confirm.get("dealStatus", "UNKNOWN")
    log.info("TRADE %s %s size=%.2f (x%.2f) @ ~%.2f — %s (%s)",
             direction, ticker, size, mult, price, reason, status)
    return {
        "action": "opened" if status == "ACCEPTED" else "rejected",
        "why": reason if status == "ACCEPTED" else str(confirm.get("rejectReason", status)),
        "ticker": ticker, "direction": direction,
        "size": round(size, 2), "price": price,
        "positionId": confirm.get("positionId"),
        "sizing": f"mnożnik x{mult:.2f}: " + ", ".join(notes),
        "tp_pct": tp_pct, "sl_pct": sl_pct,
    }


# Tokeny rozpoznawane jako krypto w nazwie/epic pozycji (obejmuje zarówno
# bezpośrednie symbole krypto jak i ETF-y proxy używane przez Saxo)
_CRYPTO_TOKENS = {"BTC", "ETH", "SOL", "CRYPTO", "IBIT", "ETHA", "SOLZ"}


def _is_crypto_position(pos: dict) -> bool:
    """Czy pozycja to krypto? Sprawdza epic i nazwę instrumentu (Saxo epic to
    'uic:AssetType', więc szukamy też w polu name, które ma czytelny symbol)."""
    epic = (pos.get("epic") or "").upper()
    name = (pos.get("name") or "").upper()
    for token in _CRYPTO_TOKENS:
        if token in epic or token in name:
            return True
    return False


def manage_positions(params: dict):
    """Wygaszanie pozycji: limit czasu + runaway take-profit (ruch >= runaway_tp_pct).
    Pozycje z ręczną flagą 'trzymaj' są nietykalne (SL/TP brokera dalej działają)."""
    if not client.configured:
        return
    held = set(state.get_holds().keys())

    if hasattr(client, "close_expired"):
        client.close_expired(params["max_hold_hours"], skip=held)

    for p in client.get_positions():
        pid = str(p.get("dealId"))
        if pid in held:
            continue
        entry, cur = p.get("openLevel"), p.get("currentLevel")
        if not entry or not cur:
            continue
        sign = 1 if p.get("direction") == "BUY" else -1
        move = sign * (cur - entry) / entry * 100
        
        # --- Specjalna logika dla Kryptowalut (BTC/ETH/SOL — IBIT/ETHA/SOLZ na Saxo) ---
        is_crypto = _is_crypto_position(p)
        if is_crypto and p.get("openTime"):
            if isinstance(p["openTime"], str):
                import dateutil.parser
                age_minutes = (time.time() - dateutil.parser.isoparse(p["openTime"]).timestamp()) / 60.0
            else:
                age_minutes = (time.time() + 3 * 3600 - p["openTime"]) / 60.0
                
            if age_minutes >= 5.0:
                # Zamykamy po 15 minutach (5 min okno + 10 min bonusu z podciąganym SL)
                if age_minutes >= 15.0:
                    log.info("Krypto max hold (15m): %s +%.2f%% — zamykam", p.get("epic"), move)
                    close_position(pid)
                    state.log_signal({"post": f"[AUTO] Krypto 15-min TP na {p.get('epic')}", "signal": {"strength": None, "reason": f"zamknięcie po 15m na {move:.2f}%"}, "result": {"action": "auto_tp", "why": "Koniec 15-min okna"}})
                    continue
                    
                # Po pierwszych 5 min: brak wybicia (mniej niż 0.8%) -> zamykamy
                # Dajemy mały zapas czasowy (age < 6), by nie spamować logów, chociaż close_position wyrzuci go z listy
                if move < 0.8 and age_minutes < 6.0:
                    log.info("Krypto 5-min checkout: %s ruch %.2f%% < 0.8%% — zamykam", p.get("epic"), move)
                    close_position(pid)
                    state.log_signal({"post": f"[AUTO] Krypto 5-min ucięcie na {p.get('epic')}", "signal": {"strength": None, "reason": f"ruch tylko {move:.2f}%"}, "result": {"action": "auto_tp", "why": "Brak siły ( < 0.8% ) po 5 min"}})
                    continue
                    
                # Powyżej 0.8%: Płynny Trailing Stop 0.8% (utrzymujemy gwarantowany profit)
                if move >= 0.8 and hasattr(client, "update_position"):
                    new_sl = entry * (1 + sign * (move - 0.8) / 100)
                    cur_sl = p.get("sl")
                    needs_update = cur_sl is None or (sign == 1 and new_sl > cur_sl) or (sign == -1 and new_sl < cur_sl)
                    if needs_update:
                        client.update_position(pid, stop_level=new_sl)

        # --- Zwykły Runaway Take-Profit ---
        if move >= params["runaway_tp_pct"]:
            log.info("Runaway take-profit: %s +%.1f%% >= %s%% — zamykam",
                     p.get("epic"), move, params["runaway_tp_pct"])
            close_position(pid)
            state.log_signal({
                "post": f"[AUTO] Runaway take-profit na {p.get('epic')}",
                "signal": {"strength": None, "reason": f"pozycja osiągnęła +{move:.1f}%"},
                "result": {"action": "auto_tp", "why": f"zamknięta z zyskiem +{move:.1f}% "
                           f"(próg {params['runaway_tp_pct']}%)"},
            })


def position_details(position_id, params: dict) -> dict | None:
    """Szczegóły jednej pozycji dla podstrony kontroli (P&L, wiek, % wycenienia)."""
    for p in client.get_positions():
        if str(p.get("dealId")) == str(position_id):
            hours_open = None
            if p.get("openTime"):
                # openTime to epoch czasu serwera; wiek liczymy z różnicy do "teraz" serwera,
                # które przybliżamy tickiem — wystarczające dla wskaźnika
                hours_open = max(0.0, (time.time() + 3 * 3600 - p["openTime"]) / 3600)
            entry, cur = p.get("openLevel"), p.get("currentLevel")
            move = None
            if entry and cur:
                sign = 1 if p.get("direction") == "BUY" else -1
                move = sign * (cur - entry) / entry * 100
            p = dict(p)
            p["hours_open"] = round(hours_open, 2) if hours_open is not None else None
            p["move_pct"] = round(move, 2) if move is not None else None
            p["priced_in"] = strategy.priced_in_pct(hours_open, move, params)
            p["held"] = str(position_id) in state.get_holds()
            p["max_hold_hours"] = params["max_hold_hours"]
            p["runaway_tp_pct"] = params["runaway_tp_pct"]
            p["priced_in_hours"] = params["priced_in_hours"]
            return p
    return None


def close_position(position_id) -> bool:
    """Zamyka jedną pozycję (weryfikator etapu 2 / strona pozycji / runaway TP)."""
    if position_id is None or not hasattr(client, "close_position"):
        return False
    try:
        return client.close_position(position_id)
    except Exception:
        log.exception("Nie udało się zamknąć pozycji %s", position_id)
        return False


def close_everything():
    log.warning("Zamykam wszystkie pozycje (kill-switch)")
    if client.configured:
        client.close_all()
