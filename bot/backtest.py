"""Backtest dnia: posty Trumpa z wybranej daty -> AI -> symulacja tradów
na prawdziwych świecach M5 z MT5 (XM) -> winrate i P&L.

Cała ocena postów idzie przez TEN SAM analyzer co na żywo, więc backtest
mierzy dokładnie to, co robiłby bot. Wyniki analizy AI są cache'owane na dysku
(backtests/<data>.json), żeby nie palić limitu darmowych zapytań przy
ponownym oglądaniu tego samego dnia.
"""

import json
import logging
import os
import re
import threading
import time as _time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import MetaTrader5 as mt5
import requests

import trader
import strategy
from analyzer import analyze_post
from config import load_params
from sources import sec_edgar
from sources.truth_social import _strip_html

log = logging.getLogger("backtest")

CACHE_DIR = os.path.join(os.path.dirname(__file__), "backtests")
os.makedirs(CACHE_DIR, exist_ok=True)

# stan bieżącego przebiegu (czytany przez dashboard)
state = {"running": False, "date": None, "progress": 0, "total": 0,
         "posts": [], "stats": {}, "error": None, "cancel": False}

TRADE_COST_PCT = 0.15  # szacunkowy koszt spreadu+prowizji na trade (odejmowany od wyniku)


# ---------- posty historyczne ----------

def fetch_posts_for_date(date_str: str) -> list[dict]:
    """Posty Trumpa z danego dnia z darmowego archiwum trumpstruth.org."""
    import xml.etree.ElementTree as ET
    try:
        r = requests.get(
            "https://www.trumpstruth.org/feed",
            params={"start_date": date_str, "end_date": date_str},
            headers={"User-Agent": "news-trader-backtest"},
            timeout=30,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning("Nie udało się pobrać postów dla %s: %s", date_str, e)
        return []
    posts = []
    for item in ET.fromstring(r.content).iter("item"):
        pub = item.findtext("pubDate")
        try:
            created = parsedate_to_datetime(pub).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        if created.date().isoformat() != date_str:
            continue
        posts.append({
            "id": (item.findtext("link") or "").rstrip("/").rsplit("/", 1)[-1],
            "text": _strip_html(item.findtext("description") or item.findtext("title") or ""),
            "created_at": created.isoformat(),
        })
    posts.sort(key=lambda p: p["created_at"])
    return posts


# ---------- historyczne raporty SEC 8-K ----------

_BIG_FALLBACK = set((
    "AAPL MSFT NVDA AMZN GOOGL GOOG META TSLA AMD INTC DELL MU AVGO ORCL CRM ADBE "
    "JPM BAC WFC GS MS C BA CAT GE HON F GM DIS NFLX PLTR COIN UBER PYPL SQ SHOP "
    "WMT COST TGT HD LOW PFE MRK LLY JNJ ABBV UNH KO PEP MCD SBUX NKE XOM CVX "
    "T VZ TMUS IBM QCOM CSCO TXN MRVL SMCI ARM CRWD SNOW NET DDOG PANW ").split())


def _tradable() -> set:
    """Tickery, którymi handlujemy (z brokera) albo szeroki fallback dużych spółek."""
    try:
        if trader.client.configured and hasattr(trader.client, "tradable_tickers"):
            t = trader.client.tradable_tickers()
            if t:
                return t
    except Exception:
        pass
    return _BIG_FALLBACK


def fetch_8k_for_date(date_str: str, tradable: set | None = None) -> list[dict]:
    """Raporty 8-K z danego dnia z dziennego indeksu SEC, tylko tradowalne spółki."""
    tradable = tradable or _tradable()
    sec_edgar._load_ticker_map()
    d = datetime.fromisoformat(date_str)
    q = (d.month - 1) // 3 + 1
    idx_url = (f"https://www.sec.gov/Archives/edgar/daily-index/{d.year}/"
               f"QTR{q}/form.{d.strftime('%Y%m%d')}.idx")
    try:
        r = requests.get(idx_url, headers=sec_edgar.UA, timeout=20)
    except requests.RequestException as e:
        log.warning("SEC daily index request failed for %s: %s", date_str, e)
        return []
    if r.status_code in (403, 404):
        return []  # weekend/święto/za nowa data — brak indeksu
    r.raise_for_status()

    events = []
    for line in r.text.splitlines():
        toks = line.split()
        if len(toks) < 4 or toks[0] != "8-K":
            continue
        cik, fname = toks[-3], toks[-1]
        ticker = sec_edgar._cik2ticker.get(cik.zfill(10))
        if not ticker or ticker not in tradable:
            continue
        ev = _load_8k_event(fname, ticker, date_str)
        if ev:
            events.append(ev)
    events.sort(key=lambda e: e["created_at"])
    return events


def _load_8k_event(fname: str, ticker: str, date_str: str) -> dict | None:
    """Pobiera pełny plik zgłoszenia: czas akceptacji (ET->UTC) + treść."""
    try:
        _time.sleep(0.12)  # etykieta SEC <10 req/s
        r = requests.get(f"https://www.sec.gov/Archives/{fname}", headers=sec_edgar.UA, timeout=20)
        if not r.ok:
            return None
        raw = r.text
        m = re.search(r"<ACCEPTANCE-DATETIME>(\d{14})", raw)
        if m:
            dt_et = datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(
                tzinfo=ZoneInfo("America/New_York"))
            created = dt_et.astimezone(timezone.utc).isoformat()
        else:
            created = datetime.fromisoformat(date_str).replace(
                hour=17, tzinfo=timezone.utc).isoformat()  # brak czasu -> po sesji

        # "ITEM INFORMATION" z nagłówka = typ zdarzenia (np. 5.02 zmiana CEO, 2.01 przejęcie)
        items = re.findall(r"ITEM INFORMATION:\s*(.+)", raw)
        # treść: body pierwszego dokumentu 8-K (z bloku <DOCUMENT>, nie nagłówek SGML)
        body_raw = ""
        for doc in re.split(r"<DOCUMENT>", raw)[1:]:
            typ = re.search(r"<TYPE>([^\r\n<]+)", doc)
            if typ and typ.group(1).strip().upper().startswith("8-K"):
                tx = re.search(r"<TEXT>(.*?)</TEXT>", doc, re.S)
                body_raw = tx.group(1) if tx else doc
                break
        if not body_raw:
            parts = re.split(r"</SEC-HEADER>", raw, maxsplit=1)
            body_raw = parts[1] if len(parts) > 1 else raw
        body = _strip_html(body_raw)[:5000]
        item_txt = ("Items: " + "; ".join(i.strip() for i in items) + ". ") if items else ""
        return {"id": fname, "ticker": ticker, "created_at": created,
                "text": f"[8-K] {ticker}. {item_txt}{body}", "source": "sec_edgar"}
    except Exception:
        return None


# ---------- rejestr źródeł (nowe źródła dodajesz TU i pojawią się w UI) ----------

SOURCES = {
    "truth_social": {"label": "Truth Social", "fetch": lambda date: fetch_posts_for_date(date)},
    "sec_edgar": {"label": "SEC 8-K", "fetch": lambda date: fetch_8k_for_date(date)},
}


# ---------- dane rynkowe / symulacja ----------

_offset_cache = None


def _server_offset_seconds() -> int:
    """Różnica czas-serwera-MT5 minus UTC (XM: zwykle +2/+3 h)."""
    global _offset_cache
    if _offset_cache is not None:
        return _offset_cache
    try:
        trader.client._ensure()
        for sym in ("Crypto_10#", "EURUSD#", "GOLD#"):
            if not mt5.symbol_select(sym, True):
                continue
            t = mt5.symbol_info_tick(sym)
            if t and abs(t.time - _time.time()) < 12 * 3600:
                _offset_cache = round((t.time - _time.time()) / 1800) * 1800
                return _offset_cache
    except Exception:
        pass
    _offset_cache = 3 * 3600
    return _offset_cache


def simulate_trade(ticker: str, direction: str, post_time_iso: str,
                   with_bars: bool = False) -> dict:
    """Symuluje trade wg aktualnych parametrów strategii na świecach M5."""
    params = load_params()
    trader.client._ensure()
    symbol = trader.client.find_epic(ticker)
    if not symbol:
        return {"error": f"brak instrumentu {ticker} na XM"}

    post_dt = datetime.fromisoformat(post_time_iso)
    entry_target = post_dt + timedelta(seconds=60)  # minuta na wykrycie+analizę+zlecenie
    offset = _server_offset_seconds()

    bars = mt5.copy_rates_range(
        symbol, mt5.TIMEFRAME_M5,
        entry_target - timedelta(hours=12),
        entry_target + timedelta(hours=params["max_hold_hours"] + 30),
    )
    if bars is None or len(bars) == 0:
        return {"error": "brak danych historycznych z XM dla tego dnia"}

    entry_srv = entry_target.timestamp() + offset
    future = [b for b in bars if b["time"] >= entry_srv]
    if not future:
        return {"error": "brak świec po czasie posta (za świeża data?)"}
    if future[0]["time"] - entry_srv > 30 * 60:
        return {"skipped": "rynek był zamknięty w momencie posta — bot by nie zagrał "
                           "(post starszy niż 10 min przy otwarciu)"}

    sign = 1 if direction == "long" else -1
    entry_price = float(future[0]["open"])
    tp = entry_price * (1 + sign * params["take_profit_pct"] / 100)
    sl = entry_price * (1 - sign * params["stop_loss_pct"] / 100)
    deadline = entry_srv + params["max_hold_hours"] * 3600

    exit_price, exit_time, exit_reason = None, None, None
    for b in future:
        if b["time"] > deadline:
            exit_price, exit_time, exit_reason = float(b["open"]), b["time"], "limit czasu"
            break
        lo, hi = float(b["low"]), float(b["high"])
        hit_sl = lo <= sl if sign == 1 else hi >= sl
        hit_tp = hi >= tp if sign == 1 else lo <= tp
        if hit_sl:  # konserwatywnie: w tej samej świecy najpierw SL
            exit_price, exit_time, exit_reason = sl, b["time"], "stop-loss"
            break
        if hit_tp:
            exit_price, exit_time, exit_reason = tp, b["time"], "take-profit"
            break
    if exit_price is None:
        last = future[-1]
        exit_price, exit_time, exit_reason = float(last["close"]), last["time"], "koniec danych"

    price_pct = sign * (exit_price - entry_price) / entry_price * 100 - TRADE_COST_PCT

    try:
        balance = trader.client.get_account().get("balance") or 1000
    except Exception:
        balance = 1000
    eff_lev = min(params["max_leverage"], 10)  # ~10x to sufit XM na akcjach
    pnl_eur = balance * params["position_pct_of_equity"] / 100 * eff_lev * price_pct / 100

    result = {
        "symbol": symbol, "direction": direction,
        "entry_price": round(entry_price, 2), "exit_price": round(exit_price, 2),
        "entry_time": int(future[0]["time"] - offset), "exit_time": int(exit_time - offset),
        "exit_reason": exit_reason,
        "price_pct": round(price_pct, 2), "pnl_eur": round(pnl_eur, 2),
        "win": price_pct > 0,
        "params_used": {k: params[k] for k in
                        ("take_profit_pct", "stop_loss_pct", "max_hold_hours",
                         "position_pct_of_equity", "max_leverage")},
    }
    if with_bars:
        lo_t = entry_srv - 3600
        hi_t = exit_time + 2 * 3600
        result["bars"] = [
            {"t": int(b["time"] - offset), "o": float(b["open"]), "h": float(b["high"]),
             "l": float(b["low"]), "c": float(b["close"])}
            for b in bars if lo_t <= b["time"] <= hi_t
        ]
        result["tp"] = round(float(tp), 2)
        result["sl"] = round(float(sl), 2)
    return result


# ---------- przebieg całego dnia ----------

def price_outcomes(ticker: str, time_iso: str) -> dict | None:
    """Jak REALNIE ruszył się kurs spółki po informacji: +1h, +3h, +6h (surowa zmiana %).
    Liczone niezależnie od decyzji bota — żeby ocenić, czy skip/trade był słuszny.
    Zwraca None gdy news nie dotyczy tradowalnej spółki (nic ważnego)."""
    try:
        trader.client._ensure()
        symbol = trader.client.find_epic(ticker)
        if not symbol:
            return None
        base_dt = datetime.fromisoformat(time_iso) + timedelta(seconds=60)
        offset = _server_offset_seconds()
        bars = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M5,
                                    base_dt - timedelta(minutes=30),
                                    base_dt + timedelta(hours=8))
        if bars is None or len(bars) == 0:
            return {"na": "brak danych M5"}
        ref_srv = base_dt.timestamp() + offset
        future = [b for b in bars if b["time"] >= ref_srv]
        if not future:
            return {"na": "brak świec po informacji"}
        ref = float(future[0]["open"])

        def at(hours):
            cand = [b for b in future if b["time"] >= ref_srv + hours * 3600]
            return round((float(cand[0]["open"]) - ref) / ref * 100, 2) if cand else None

        return {"ref": round(ref, 2), "h1": at(1), "h3": at(3), "h6": at(6),
                "after_hours": bool((future[0]["time"] - ref_srv) / 60 > 30)}
    except Exception:
        return None


def _cache_path(date_str: str, source: str) -> str:
    return os.path.join(CACHE_DIR, f"{date_str}__{source}.json")


def _migrate_old_cache():
    """Stare pliki {date}.json (tylko Truth Social) -> {date}__truth_social.json."""
    for fn in os.listdir(CACHE_DIR):
        if "__" in fn or not fn.endswith(".json"):
            continue
        date = fn[:-5]
        new = _cache_path(date, "truth_social")
        if os.path.exists(new):
            continue
        try:
            with open(os.path.join(CACHE_DIR, fn), encoding="utf-8") as f:
                old = json.load(f)
            events = old.get("posts", [])
            for e in events:
                e.setdefault("source", "truth_social")
            with open(new, "w", encoding="utf-8") as f:
                json.dump({"events": events, "stats": _compute_stats(events)}, f, ensure_ascii=False)
        except (OSError, json.JSONDecodeError):
            continue


def _compute_stats(results: list[dict]) -> dict:
    trades = [r["sim"] for r in results
              if r.get("would_trade") and r.get("sim") and "price_pct" in r["sim"]]
    wins = [t for t in trades if t["win"]]
    return {
        "posts": len(results),
        "signals": sum(1 for r in results if r.get("would_trade")),
        "trades": len(trades),
        "wins": len(wins),
        "winrate": round(len(wins) / len(trades) * 100, 1) if trades else None,
        "sum_price_pct": round(sum(t["price_pct"] for t in trades), 2),
        "sum_pnl_eur": round(sum(t["pnl_eur"] for t in trades), 2),
    }


def _analyze_one(ev: dict, source: str, params: dict) -> dict:
    entry = dict(ev)
    entry.setdefault("source", source)
    text = ev.get("text", "")
    try:
        if not text.strip():
            entry["signal"] = {"tradable": False, "strength": 0, "reason": "pusty wpis"}
        else:
            # Timeout 90s per post — prevents entire backtest from hanging on one AI call
            result = [None]
            err = [None]

            def _do_analysis():
                try:
                    result[0] = analyze_post(text, source=source)
                except Exception as e:
                    err[0] = e

            t = threading.Thread(target=_do_analysis, daemon=True)
            t.start()
            t.join(timeout=90)
            if t.is_alive():
                entry["signal"] = {"tradable": False, "strength": 0,
                                   "reason": "timeout analizy AI (90s) — post pominięty", "_error": True}
            elif err[0]:
                raise RuntimeError(str(err[0]))
            else:
                entry["signal"] = result[0]
    except (RuntimeError, Exception) as e:
        entry["signal"] = {"tradable": False, "strength": 0,
                           "reason": f"błąd analizy AI: {e}", "_error": True}
    sig = entry["signal"]
    would = (sig.get("tradable") and sig.get("ticker")
             and sig.get("strength", 0) >= params["min_signal_strength"])
    if would and "sim" not in entry:
        try:
            entry["sim"] = simulate_trade(sig["ticker"], sig.get("direction", "long"),
                                          entry["created_at"])
        except Exception as e:
            entry["sim"] = {"error": f"symulacja padła: {e}"}
    entry["would_trade"] = bool(would)
    return entry


def run_day(date_str: str, sources: list[str], force: bool = False):
    params = load_params()
    state.update(running=True, date=date_str, sources=sources, progress=0, total=0,
                 posts=[], stats={}, error=None, cancel=False)
    try:
        # 1) zbierz zdarzenia per źródło (z cache albo świeżo pobrane)
        buckets = {}
        for src in sources:
            if src not in SOURCES:
                continue
            cpath = _cache_path(date_str, src)
            if not force and os.path.exists(cpath):
                try:
                    with open(cpath, encoding="utf-8") as f:
                        buckets[src] = (json.load(f).get("events", []), True)
                except (json.JSONDecodeError, OSError) as e:
                    log.warning("Cache %s uszkodzony (%s) — pobieram od nowa", cpath, e)
                    buckets[src] = (SOURCES[src]["fetch"](date_str), False)
            else:
                try:
                    buckets[src] = (SOURCES[src]["fetch"](date_str), False)
                except Exception as e:
                    log.warning("Nie udało się pobrać danych z %s: %s", src, e)
                    state["error"] = f"Nie udało się pobrać danych z {SOURCES[src]['label']}: {e}"
                    buckets[src] = ([], False)
        state["total"] = sum(len(ev) for ev, _ in buckets.values())

        # 2) analiza (nowe źródła) lub reużycie (cache) + symulacja
        merged = []
        for src, (events, from_cache) in buckets.items():
            out = []
            # Filtrowanie zdarzeń poza godzinami sesji giełdowej (od razu do wyrzucenia)
            filtered_events = []
            for ev in events:
                try:
                    dt = datetime.fromisoformat(ev["created_at"].replace("Z", "+00:00"))
                    if strategy.market_open_now(dt):
                        filtered_events.append(ev)
                except Exception:
                    filtered_events.append(ev)  # w razie błędu parsowania sprawdzimy
            
            # Zaktualizuj całkowitą liczbę postów do przetworzenia w panelu
            state["total"] -= (len(events) - len(filtered_events))
            
            for ev in filtered_events:
                if state["cancel"]:
                    state["error"] = "analiza przerwana przez użytkownika"
                    break
                try:
                    if from_cache and not ev.get("signal", {}).get("_error"):
                        entry = ev  # już policzone
                    else:
                        entry = _analyze_one(ev, src, params)
                    # wskaźniki ruchu kursu 1h/3h/6h — dla KAŻDEGO newsa o konkretnej spółce
                    # (także pominiętego), żeby ocenić trafność decyzji. Tanie, bez AI.
                    tk = (entry.get("signal", {}).get("ticker") or entry.get("ticker"))
                    if tk and entry.get("outcomes") is None:
                        try:
                            entry["outcomes"] = price_outcomes(tk, entry["created_at"])
                        except Exception:
                            entry["outcomes"] = None
                except Exception as e:
                    entry = dict(ev)
                    entry["source"] = src
                    entry["signal"] = {"tradable": False, "strength": 0,
                                       "reason": f"krytyczny błąd: {e}", "_error": True}
                    entry["would_trade"] = False
                    log.warning("Pominięto event (błąd): %s", e)
                out.append(entry)
                merged.append(entry)
                state["posts"] = sorted(merged, key=lambda e: e.get("created_at", ""))
                state["progress"] += 1
            if not state["cancel"]:  # zapisz cache źródła (utrwala też naprawione błędy)
                with open(_cache_path(date_str, src), "w", encoding="utf-8") as f:
                    json.dump({"events": out, "stats": _compute_stats(out)}, f, ensure_ascii=False)
            if state["cancel"]:
                break

        merged.sort(key=lambda e: e.get("created_at", ""))
        state["posts"] = merged
        state["stats"] = _compute_stats(merged)
    except Exception as e:
        log.exception("Backtest %s padł", date_str)
        state["error"] = str(e)
    finally:
        state["running"] = False


def start(date_str: str, sources: list[str] | None = None, force: bool = False) -> bool:
    if state["running"]:
        return False
    sources = sources or ["truth_social"]
    threading.Thread(target=run_day, args=(date_str, sources, force), daemon=True).start()
    return True


def cancel() -> bool:
    if not state["running"]:
        return False
    state["cancel"] = True
    return True


def aggregate_stats() -> dict:
    """Łączny winrate ze wszystkich przetestowanych źródło-dni (per-source cache)."""
    total_trades, total_wins, total_pct, total_eur = 0, 0, 0.0, 0.0
    days = set()
    for fn in os.listdir(CACHE_DIR):
        if "__" not in fn or not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(CACHE_DIR, fn), encoding="utf-8") as f:
                s = json.load(f).get("stats", {})
            days.add(fn.split("__")[0])
            total_trades += s.get("trades", 0)
            total_wins += s.get("wins", 0)
            total_pct += s.get("sum_price_pct", 0) or 0
            total_eur += s.get("sum_pnl_eur", 0) or 0
        except (OSError, json.JSONDecodeError):
            continue
    return {
        "days": len(days), "trades": total_trades, "wins": total_wins,
        "winrate": round(total_wins / total_trades * 100, 1) if total_trades else None,
        "sum_price_pct": round(total_pct, 2), "sum_pnl_eur": round(total_eur, 2),
    }


def available_sources() -> list[dict]:
    """Lista źródeł do UI (nowe źródła w SOURCES pojawią się automatycznie)."""
    return [{"key": k, "label": v["label"]} for k, v in SOURCES.items()]


_migrate_old_cache()
