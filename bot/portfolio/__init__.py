"""Moduł portfela — śledzenie kont maklerskich (XTB, w przyszłości inne).

Struktura:
  store.py      — SQLite (operacje, pozycje zamknięte, cache cen)
  importer.py   — parsowanie raportów XTB (xlsx / zip)
  prices.py     — ceny dzienne: Stooq (główne) + Yahoo (fallback) + FX
  engine.py     — rekonstrukcja pozycji, dzienna wycena w PLN, TWR/XIRR
  benchmarks.py — S&P500, WIG, WIG20, inflacja PL
"""
