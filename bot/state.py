"""Wspólny stan bota i serwera: feed analiz + heartbeat (pliki na dysku)."""

import json
import os
import threading
import time

import paths

SIGNALS_FILE = paths.data_path("signals.jsonl")
HEARTBEAT_FILE = paths.data_path("heartbeat.json")

_state_lock = threading.Lock()


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
