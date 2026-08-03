"""Wspólny stan bota i dashboardu: feed sygnałów + heartbeat (pliki na dysku)."""

import json
import os
import threading
import time

_DIR = os.path.dirname(__file__)
SIGNALS_FILE = os.path.join(_DIR, "signals.jsonl")
HEARTBEAT_FILE = os.path.join(_DIR, "heartbeat.json")
HOLDS_FILE = os.path.join(_DIR, "holds.json")

_state_lock = threading.Lock()


def get_holds() -> dict:
    """Pozycje oznaczone ręcznie 'trzymaj' — bot nie zamyka ich automatycznie
    (limit czasu / runaway take-profit); SL/TP u brokera dalej działają."""
    try:
        with open(HOLDS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def set_hold(position_id, hold: bool):
    with _state_lock:
        holds = get_holds()
        pid = str(position_id)
        if hold:
            holds[pid] = time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            holds.pop(pid, None)
        with open(HOLDS_FILE, "w", encoding="utf-8") as f:
            json.dump(holds, f)
        return holds


def log_signal(entry: dict):
    entry["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with _state_lock:
        with open(SIGNALS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def recent_signals(limit: int = 50) -> list[dict]:
    if not os.path.exists(SIGNALS_FILE):
        return []
    with open(SIGNALS_FILE, encoding="utf-8") as f:
        lines = f.readlines()[-limit:]
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def heartbeat(polls: dict = None):
    data = {"ts": time.time()}
    if polls:
        data["polls"] = polls
    with _state_lock:
        with open(HEARTBEAT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)


def bot_alive(max_age_seconds: int = 60) -> bool:
    try:
        with open(HEARTBEAT_FILE, encoding="utf-8") as f:
            return time.time() - json.load(f)["ts"] < max_age_seconds
    except (OSError, json.JSONDecodeError, KeyError):
        return False
