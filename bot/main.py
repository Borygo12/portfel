"""Samodzielne uruchomienie pętli bota (np. na VPS bez UI).

Uruchomienie:  python main.py
Panel:         python dashboard.py  (osobny proces, port 8500)

Ta sama pętla jest sterowana przyciskiem START w panelu — patrz runner.py.
"""

import logging
import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import runner  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log", encoding="utf-8")],
)

if __name__ == "__main__":
    import time
    runner.start()
    try:
        while runner.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        runner.stop()
