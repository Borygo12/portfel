"""Reguły pomocnicze analizy newsów: pamięć wzmianek i godziny sesji.

Bot nie handluje, więc nie ma tu już liczenia wielkości pozycji ani TP/SL —
to wszystko odeszło razem z modułem egzekucji. Zostały dwie rzeczy, które
opisują KONTEKST wiadomości:

  record_mention / repeat_note  — która to już wzmianka o spółce w tym tygodniu
                                  (powtórki niosą mniej informacji niż pierwsza)
  market_open_*                 — czy sesja trwa; news po sesji ma mniejszą
                                  wartość informacyjną, bo rynek zdąży go wycenić

Mnożniki kategorii i autorytetu źródła żyją w prompts.py (panel /brain).
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

log = logging.getLogger("strategy")

MENTIONS_FILE = os.path.join(os.path.dirname(__file__), "mentions.json")
MENTION_WINDOW_DAYS = 7
_mentions_lock = threading.Lock()


# ---------- pamięć wzmianek ----------
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


def repeat_note(ticker: str) -> str | None:
    """Która to wzmianka o spółce w ostatnich 7 dniach (licząc PRZED tą)."""
    cutoff = time.time() - MENTION_WINDOW_DAYS * 86400
    prior = len([t for t in _load_mentions().get(ticker, []) if t > cutoff])
    if prior >= 1:
        return f"{prior + 1}. wzmianka o {ticker} w tym tygodniu"
    return None


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
