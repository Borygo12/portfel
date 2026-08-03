"""Strategia — wszystkie reguły i mnożniki wielkości pozycji w JEDNYM miejscu.

Wielkość pozycji = baza (kapitał% x dźwignia) x iloczyn mnożników:

  aggressiveness_mult  0.4-1.6   główny suwak ownera (0-100)
  strength_mult        0.5-1.4   siła sygnału AI (siła 95 -> gramy grubiej niż 72)
  type_mult            wg typu   direct=1.0, thematic=0.35, macro=0.5 (parametry)
  category_mult        0.1-2.0   mnożnik kategorii newsa (news_type, panel /brain)
  authority_mult       0.1-2.0   kto mówi: prezydent USA vs anonimowe konto (/brain)
  already_priced_mult  1.0/0.5   spółka już dziś ruszyła >=10% w kierunku sygnału
  repeat_mult          1.0-0.6   która to wzmianka o spółce w ostatnich 7 dniach
  target_weight        0.3-1.0   waga celu od AI (tematyczne dostają mniejsze)

Do tego: godziny sesji US (posty po sesji odpuszczamy, żółte w panelu),
TP/SL skalowane zmiennością (ATR), wskaźnik "% wycenienia informacji".
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import prompts

log = logging.getLogger("strategy")

MENTIONS_FILE = os.path.join(os.path.dirname(__file__), "mentions.json")
MENTION_WINDOW_DAYS = 7
_mentions_lock = threading.Lock()


# ---------- mnożniki wielkości pozycji ----------

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def aggressiveness_mult(params: dict) -> float:
    """0 -> x0.4 (gramy z wyczuciem), 50 -> x1.0, 100 -> x1.6 (gramy grubo)."""
    return 0.4 + params["aggressiveness"] / 100 * 1.2


def strength_mult(strength: int) -> float:
    """Progi ownera: siła 98+ -> x1.5, 90+ -> x1.25; poniżej liniowo (70 -> x0.86)."""
    if strength >= 98:
        return 1.5
    if strength >= 90:
        return 1.25
    return _clamp(0.5 + (strength - 50) * 0.018, 0.5, 1.2)


def type_mult(signal_type: str, params: dict) -> float:
    if signal_type == "thematic":
        return params["thematic_size_factor"]
    if signal_type == "macro":
        return params["macro_size_factor"]
    return 1.0  # direct


def already_priced_mult(daily_change_pct: float | None, direction: str, params: dict,
                        company_size: str = "large") -> tuple[float, str | None]:
    """Spółka już dziś mocno ruszyła w kierunku sygnału -> news może być wyceniony,
    ryzyko korekty -> gramy, ale mniejszym rozmiarem.
    Próg zależy od wielkości spółki: duża 10% (Apple nie robi +10% ot tak),
    bardzo mała 25% (małe spółki normalnie ruszają się mocniej)."""
    if daily_change_pct is None:
        return 1.0, None
    threshold = (params.get("already_priced_move_pct_small", 25)
                 if company_size == "small" else params["already_priced_move_pct"])
    sign = 1 if direction == "long" else -1
    favorable = sign * daily_change_pct
    if favorable >= threshold:
        return params["already_priced_weight"], (
            f"spółka ({company_size}) już dziś {daily_change_pct:+.1f}% >= próg {threshold}% "
            f"— news częściowo wyceniony, waga x{params['already_priced_weight']}")
    return 1.0, None


# ---------- pamięć wzmianek (powtórki są słabsze) ----------

def _load_mentions() -> dict:
    try:
        with open(MENTIONS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def record_mention(ticker: str):
    with _mentions_lock:
        data = _load_mentions()
        cutoff = time.time() - MENTION_WINDOW_DAYS * 86400
        lst = [t for t in data.get(ticker, []) if t > cutoff]
        lst.append(time.time())
        data[ticker] = lst
        with open(MENTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)


def repeat_mult(ticker: str, params: dict) -> tuple[float, str | None]:
    """Ile razy spółka była już grana w ostatnich 7 dniach (PRZED tą wzmianką)."""
    if not params.get("repeat_mention_decay", True):
        return 1.0, None
    cutoff = time.time() - MENTION_WINDOW_DAYS * 86400
    prior = len([t for t in _load_mentions().get(ticker, []) if t > cutoff])
    if prior >= 3:
        return 0.6, f"{prior + 1}. wzmianka o {ticker} w tym tygodniu — rynek przyzwyczajony, waga x0.6"
    if prior == 2:
        return 0.8, f"3. wzmianka o {ticker} w tym tygodniu — waga x0.8"
    return 1.0, None


# ---------- godziny sesji (USA / GPW) ----------

def market_open_now(now: datetime | None = None, market: str = "us") -> bool:
    """Czy dana sesja akcji jest otwarta (pn-pt).

    market="us": regularna sesja USA 13:30-20:00 UTC (15:30-22:00 czasu PL latem).
    market="pl": notowania ciągłe GPW 09:00-17:00 czasu warszawskiego — dzięki temu
                 polskie sygnały gramy rano, gdy rynek USA jeszcze śpi."""
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    if market == "pl":
        try:
            from zoneinfo import ZoneInfo
            local = now.astimezone(ZoneInfo("Europe/Warsaw"))
        except Exception:
            # brak bazy stref (rzadkie) — PL to UTC+1/+2, przyjmij bezpieczne 08:00-15:00 UTC
            minutes = now.hour * 60 + now.minute
            return 8 * 60 <= minutes < 15 * 60
        minutes = local.hour * 60 + local.minute
        return 9 * 60 <= minutes < 17 * 60
    minutes = now.hour * 60 + now.minute
    return 13 * 60 + 30 <= minutes < 20 * 60


# źródła powiązane z GPW grają wg godzin warszawskich, reszta wg sesji USA
_PL_SOURCES = {"gpw_espi"}


def market_for_source(source: str) -> str:
    return "pl" if source in _PL_SOURCES else "us"


def market_open_for_source(source: str, now: datetime | None = None) -> bool:
    return market_open_now(now, market=market_for_source(source))


# ---------- TP/SL wg zmienności ----------

def volatility_tp_sl(atr_pct: float | None, params: dict) -> tuple[float, float, str | None]:
    """Skaluje bazowe TP/SL zmiennością spółki. ATR% ~2% = spółka 'normalna' (x1.0).
    Apple (ATR ~1.2%) dostanie ciaśniejsze progi, rozchwiana mała spółka (ATR 5%) szersze."""
    tp, sl = params["take_profit_pct"], params["stop_loss_pct"]
    if not params.get("volatility_scaling", True) or not atr_pct:
        return tp, sl, None
    factor = _clamp(atr_pct / 2.0, 0.6, 2.2)
    if abs(factor - 1.0) < 0.15:
        return tp, sl, None
    return round(tp * factor, 2), round(sl * factor, 2), (
        f"zmienność ATR {atr_pct:.1f}% -> TP/SL x{factor:.2f}")


# ---------- wskaźnik "% wycenienia informacji" (dla pozycji w UI) ----------

def priced_in_pct(hours_open: float | None, favorable_move_pct: float | None, params: dict) -> int:
    """Rośnie z czasem (100% po priced_in_hours) i z ruchem ceny (100% przy runaway_tp)."""
    time_pct = min(100, (hours_open or 0) / max(params["priced_in_hours"], 0.1) * 100)
    move_pct = min(100, max(0.0, favorable_move_pct or 0) / max(params["runaway_tp_pct"], 0.1) * 100)
    return int(max(time_pct, move_pct))


# ---------- złożenie wszystkich mnożników ----------

def position_multiplier(signal: dict, target: dict, daily_change_pct: float | None,
                        params: dict) -> tuple[float, list[str]]:
    """Zwraca (łączny mnożnik, lista notatek do panelu — skąd taka wielkość)."""
    notes = []
    m_agg = aggressiveness_mult(params)
    notes.append(f"agresywność x{m_agg:.2f}")

    m_str = strength_mult(int(signal.get("strength", 70)))
    notes.append(f"siła {signal.get('strength')} x{m_str:.2f}")

    m_type = type_mult(signal.get("signal_type", "direct"), params)
    if m_type != 1.0:
        notes.append(f"typ {signal.get('signal_type')} x{m_type:.2f}")

    m_cat = prompts.category_mult(signal.get("news_type"))
    if m_cat != 1.0:
        notes.append(f"kategoria {signal.get('news_type')} x{m_cat:.2f}")

    m_auth = prompts.authority_mult(signal.get("authority"))
    if m_auth != 1.0:
        notes.append(f"autorytet {signal.get('authority')} x{m_auth:.2f}")

    m_priced, note = already_priced_mult(daily_change_pct, target.get("direction", "long"),
                                         params, target.get("size", "large"))
    if note:
        notes.append(note)

    m_repeat, note = repeat_mult(target["ticker"], params)
    if note:
        notes.append(note)

    w = float(target.get("weight", 1.0))
    if w != 1.0:
        notes.append(f"waga celu x{w:.2f}")

    total = m_agg * m_str * m_type * m_cat * m_auth * m_priced * m_repeat * w
    return total, notes
