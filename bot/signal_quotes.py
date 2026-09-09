"""Notowanie spółki na karcie analizy: ile dziś zrobił kurs i czy rynek jest otwarty.

Po co osobny moduł, skoro `portfolio/prices.py` już pobiera kursy: tamte funkcje
odpowiadają na pytanie „ile jest wart mój portfel" i dopisują wyniki do historii
w bazie. Tutaj pytanie jest inne — „co się dzieje z tą spółką W TEJ CHWILI" —
i odpowiedź musi zawierać rzeczy, których wycena portfela nie potrzebuje: fazę
sesji, zmianę procentową i notowanie po zamknięciu.

Bez tego karta z analizą mówiła „wydźwięk pozytywny" i nic więcej. Człowiek nie
miał jak sprawdzić, czy kurs faktycznie poszedł w tę stronę, ani czy w ogóle
jest jeszcze sesja — a to pierwsza rzecz, o którą pyta, patrząc na news.

Jedno żądanie na spółkę (`v8/finance/chart`), wynik w pamięci na minutę. Karty
pokazują kilkanaście spółek naraz, więc bez cache każde odświeżenie listy
oznaczałoby kilkanaście zapytań do Yahoo.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

log = logging.getLogger("signal_quotes")

TTL = 60          # sekund — kurs na karcie nie musi być świeższy niż minuta
_cache: dict[str, dict] = {}
_lock = threading.Lock()

_session = requests.Session()
_session.headers.update({"User-Agent": "Mozilla/5.0 (portevo)"})

ADRES = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
         "?range=1d&interval=5m&includePrePost=true")


def _pobierz(ysym: str) -> dict | None:
    """Notowanie jednej spółki albo None. Nigdy nie rzuca."""
    try:
        r = _session.get(ADRES.format(sym=requests.utils.quote(ysym)), timeout=10)
        r.raise_for_status()
        wynik = ((r.json().get("chart") or {}).get("result") or [None])[0]
        if not wynik:
            return None
        meta = wynik.get("meta") or {}

        cena = meta.get("regularMarketPrice")
        odniesienie = meta.get("chartPreviousClose") or meta.get("previousClose")
        if cena is None or not odniesienie:
            return None

        # Czy trwa sesja: Yahoo podaje okna notowań ciągłych w czasie uniksowym.
        okresy = (meta.get("tradingPeriods") or {}).get("regular") or []
        okna = [(o["start"], o["end"]) for grupa in okresy for o in grupa] if okresy else []
        teraz = time.time()
        otwarty = any(a <= teraz < b for a, b in okna)

        dane = {
            "symbol": ysym,
            "price": round(float(cena), 4),
            "change_pct": round((float(cena) - float(odniesienie)) / float(odniesienie) * 100, 2),
            "currency": meta.get("currency") or "",
            "market_open": otwarty,
            "exchange": meta.get("fullExchangeName") or meta.get("exchangeName") or "",
            "fetched": teraz,
        }

        # Po zamknięciu (albo przed otwarciem) liczy się OSTATNI słupek spoza sesji
        # ciągłej — i to jego odchylenie od kursu zamknięcia, nie od wczorajszego.
        if not otwarty and okna:
            ts = wynik.get("timestamp") or []
            zamkniecia = ((wynik.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
            poza = [(t, c) for t, c in zip(ts, zamkniecia)
                    if c is not None and not any(a <= t < b for a, b in okna)]
            if poza:
                t, c = poza[-1]
                pierwszy_start = min((a for a, _ in okna), default=None)
                dane["extended"] = {
                    "price": round(float(c), 4),
                    "change_pct": round((float(c) - float(cena)) / float(cena) * 100, 2),
                    "phase": "pre" if pierwszy_start and t < pierwszy_start else "post",
                    "ts": t,
                }
        return dane
    except Exception as e:  # noqa: BLE001 — notowanie to dodatek, nie może psuć listy
        log.debug("Notowanie %s: %s", ysym, e)
        return None


def dla_symboli(symbole: list[str]) -> dict[str, dict]:
    """{symbol: notowanie} — z cache, brakujące dociągane równolegle."""
    czyste = [s.strip().upper() for s in dict.fromkeys(symbole) if s and s.strip()]
    if not czyste:
        return {}

    teraz = time.time()
    gotowe, brakuje = {}, []
    with _lock:
        for s in czyste:
            wpis = _cache.get(s)
            if wpis and teraz - wpis["fetched"] < TTL:
                gotowe[s] = wpis
            else:
                brakuje.append(s)

    if brakuje:
        # Ograniczamy równoległość: kilkanaście naraz to dla Yahoo norma,
        # kilkadziesiąt bywa odcinane.
        with ThreadPoolExecutor(max_workers=8) as ex:
            for s, wynik in zip(brakuje, ex.map(_pobierz, brakuje)):
                if wynik:
                    with _lock:
                        _cache[s] = wynik
                    gotowe[s] = wynik
    return gotowe
