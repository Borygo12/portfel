"""Mapa najpłynniejszych spółek GPW (WIG20/mWIG40 blue chips) — nazwa -> ticker.

Jedno źródło prawdy używane w dwóch miejscach:
  - prompts.py: generuje z tego listę tickerów w sekcji "polish" (prompt dla AI)
  - analyzer.py: fast_regex_filter() szuka tu nazwy spółki, żeby ominąć LLM

Zbiór wyznacza też granicę płynności: spółka spoza niego to mikrospółka
(NewConnect/sWIG80), przy której pojedynczy komunikat rusza kursem inaczej niż
przy blue chipie — AI dostaje o tym informację w prompcie.

Rozszerzaj śmiało — to zwykły dict, żadna z powyższych ścieżek nie wymaga
dodatkowych zmian kodu przy dopisaniu kolejnej spółki.
"""

LIQUID_GPW = {
    "PKN": "Orlen",
    "PKO": "PKO BP",
    "PEO": "Pekao",
    "KGH": "KGHM",
    "PZU": "PZU",
    "CDR": "CD Projekt",
    "ALE": "Allegro",
    "DNP": "Dino",
    "PGE": "PGE",
    "LPP": "LPP",
    "JSW": "JSW",
    "MBK": "mBank",
    "SPL": "Santander",
    "OPL": "Orange",
    "KRU": "Kruk",
    "CCC": "CCC",
    "BDX": "Budimex",
    "CPS": "Cyfrowy Polsat",
    "ACP": "Asseco",
    "KTY": "Kęty",
}


def tickers_prompt_line() -> str:
    """Fragment zdania do promptu: 'Orlen=PKN, PKO BP=PKO, ...'."""
    return ", ".join(f"{name}={ticker}" for ticker, name in LIQUID_GPW.items())


def find_ticker(company_text: str) -> str | None:
    """Szuka znanej spółki w dowolnym tekście (np. części tytułu ESPI przed ':').
    Dopasowanie częściowe, case-insensitive. Zwraca ticker albo None."""
    low = (company_text or "").lower()
    for ticker, name in LIQUID_GPW.items():
        if name.lower() in low:
            return ticker
    return None
