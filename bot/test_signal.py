"""Test pipeline'u bez czekania na prawdziwy post Trumpa.

Użycie:
  python test_signal.py                          # przykładowy post ("buy a Dell")
  python test_signal.py "Intel is doing GREAT"   # własny tekst posta

Jeśli w .env jest ANTHROPIC_API_KEY, post oceni prawdziwe AI.
Jeśli nie ma — użyta zostanie ocena przykładowa (mock), żeby zobaczyć feed w panelu.
Decyzja o tradzie przechodzi przez prawdziwy silnik (trader.open_trade),
więc przy podłączonym MT5 i włączonym tradingu otworzy PRAWDZIWĄ pozycję.
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

import state                    # noqa: E402
import trader                   # noqa: E402
from config import load_params  # noqa: E402

SAMPLE = "Michael Dell is a great guy building GREAT computers in AMERICA. Go out and buy a Dell!!!"


def mock_analyze(text: str) -> dict:
    return {
        "tradable": True, "ticker": "DELL", "direction": "long", "strength": 92,
        "reason": "[MOCK] Trump wprost zachwala Della i wzywa do kupna — silny sygnał long",
    }


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else SAMPLE
    params = load_params()

    if os.environ.get("ANTHROPIC_API_KEY"):
        from analyzer import analyze_post
        signal = analyze_post(text)
        print("Ocena AI (prawdziwa):", signal)
    else:
        signal = mock_analyze(text)
        print("Ocena AI (mock — brak ANTHROPIC_API_KEY):", signal)

    if not signal.get("tradable") or not signal.get("ticker"):
        result = {"action": "ignored", "why": "post nie dotyczy notowanej spółki"}
    elif signal["strength"] < params["min_signal_strength"]:
        result = {"action": "ignored",
                  "why": f"sygnał za słaby ({signal['strength']} < próg {params['min_signal_strength']})"}
    else:
        result = trader.open_trade(signal["ticker"], signal["direction"], signal["reason"])

    print("Decyzja:", result)
    state.log_signal({"post": "[TEST] " + text[:280], "signal": signal, "result": result})
    print("Zapisano do feedu — odśwież panel: http://localhost:8500")


if __name__ == "__main__":
    main()
