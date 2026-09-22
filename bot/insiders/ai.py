"""Dwie rzeczy, do których w insiderach przydaje się model językowy.

1. **Podsumowanie profilu** — trzy zdania po polsku o tym, co persona robiła
   ostatnio: w jakie spółki i branże szły pieniądze, czy przeważały zakupy,
   co było największe. Liczby w tabeli są dla kogoś, kto już wie, czego szuka;
   podsumowanie jest dla wszystkich pozostałych.
2. **Awaryjny odczyt raportu Kongresu** — gdy PDF ma tekst, ale parser nie
   znalazł w nim ani jednej transakcji (nietypowy układ).

Tylko DARMOWE modele (`analyzer.free_models`) i bez przejścia na płatne. To
dodatek: gdy limit darmowych zapytań na dobę się skończy, profil pokazuje się
bez podsumowania, a raport czeka do następnego przebiegu.

Podsumowanie trzymamy dobę per persona — liczba zapytań rośnie z liczbą
odwiedzanych profili, a nie z liczbą odwiedzin.
"""

from __future__ import annotations

import datetime as dt
import logging
import re

from . import store

log = logging.getLogger("insiders.ai")

SYSTEM_PODSUMOWANIE = """Jesteś analitykiem rynku piszącym do polskiej aplikacji inwestycyjnej.
Dostajesz listę transakcji jednej osoby (zakupy i sprzedaże akcji ujawnione
w oficjalnych zgłoszeniach) oraz kilka liczb.

Napisz 2–3 zdania po polsku, bezosobowo (np. „W ostatnich miesiącach przeważają…",
„Największa transakcja to…"). Wymień konkretne spółki (tickery) i branże,
powiedz, czy przeważały zakupy czy sprzedaże, i wskaż jedną rzecz, która
wyróżnia się na tle reszty. Kwoty podawaj w dolarach, zaokrąglone.

Zasady:
- Tylko fakty z danych. Nie oceniaj moralnie i nie sugeruj, że ktoś korzystał
  z informacji poufnych.
- Nie dawaj rad („warto kupić", „sygnał do zakupu" są zakazane).
- Bez wstępów i podsumowań w stylu „Podsumowując". Bez markdownu.
Odpowiedz samym tekstem, maksymalnie 420 znaków."""

SYSTEM_PTR = """Jesteś parserem raportu transakcji członka Kongresu USA (Periodic Transaction
Report). Dostajesz tekst wyciągnięty z PDF. Wypisz WYŁĄCZNIE transakcje akcji,
ETF-ów i opcji, które mają ticker w nawiasie, np. „(NVDA)".

Odpowiedz obiektem JSON:
{"transakcje": [{"ticker": "NVDA", "typ": "ST|OP|EF", "rodzaj": "P|S",
  "data": "MM/DD/RRRR", "kwota_od": 1001, "kwota_do": 15000,
  "wlasciciel": "SP|JT|DC|"}]}
Nie zgaduj brakujących pól — pomiń taką transakcję. Obligacji nie wypisuj."""


def _modele() -> list[str]:
    try:
        import analyzer
        return analyzer.free_models()[:3]
    except Exception:  # noqa: BLE001
        return []


def _zapytaj(system: str, tekst: str, max_tokens: int, json_: bool):
    import analyzer
    ostatni = None
    for model in _modele():
        try:
            return analyzer._call(model, system, tekst, max_tokens=max_tokens,
                                  req_timeout=25, parse_json=json_)
        except Exception as e:  # noqa: BLE001 — następny model
            ostatni = e
            continue
    if ostatni:
        log.info("Darmowe modele nie odpowiedziały: %s", ostatni)
    return None


def _kw(t: dict) -> str:
    lo, hi = t.get("amt_lo"), t.get("amt_hi")
    if lo and hi and abs(hi - lo) > 1:
        return f"{int(lo):,}–{int(hi):,} $".replace(",", " ")
    v = lo or hi
    return f"{int(v):,} $".replace(",", " ") if v else "?"


def podsumowanie(pid: str, nazwa: str, rola: str, transakcje: list[dict],
                 statystyki: dict) -> str | None:
    klucz = f"ai:{pid}:{dt.date.today().isoformat()}"
    hit = store.kv_get(klucz)
    if hit:
        return hit
    if not transakcje:
        return None
    wiersze = []
    for t in transakcje[:45]:
        wiersze.append(f"{t['date']} {'KUPNO' if t['side'] == 'buy' else 'SPRZEDAŻ'} "
                       f"{t['ticker']} {_kw(t)}"
                       + (" (opcje)" if t.get("options") else "")
                       + (f" [{t['asset'][:40]}]" if t.get("asset") else ""))
    tekst = (f"Osoba: {nazwa} — {rola}\n"
             f"Liczby z 12 miesięcy: zakupy {statystyki.get('buys', 0)} "
             f"(≈{int(statystyki.get('bought') or 0):,} $), sprzedaże {statystyki.get('sells', 0)} "
             f"(≈{int(statystyki.get('sold') or 0):,} $).\n"
             f"Transakcje (najnowsze najpierw):\n" + "\n".join(wiersze))
    odp = _zapytaj(SYSTEM_PODSUMOWANIE, tekst, 350, json_=False)
    if not isinstance(odp, str):
        return None
    czysty = re.sub(r"\s+", " ", odp.replace("*", "")).strip()
    if len(czysty) < 40:
        return None
    czysty = czysty[:600]
    store.kv_set(klucz, czysty)
    return czysty


def odczytaj_ptr(tekst: str) -> list[dict] | None:
    """Awaryjny odczyt raportu. Zwraca listę w formacie `house.czytaj`."""
    from .house import WLASCICIEL, _data_us

    odp = _zapytaj(SYSTEM_PTR, (tekst or "").replace("\x00", "")[:14000], 1800, json_=True)
    if not isinstance(odp, dict):
        return None
    out = []
    for t in odp.get("transakcje") or []:
        try:
            ticker = str(t.get("ticker") or "").upper().strip()
            rodzaj = str(t.get("rodzaj") or "").upper()[:1]
            data = _data_us(str(t.get("data") or ""))
            lo = float(t.get("kwota_od")) if t.get("kwota_od") else None
            hi = float(t.get("kwota_do")) if t.get("kwota_do") else lo
        except (TypeError, ValueError):
            continue
        typ = str(t.get("typ") or "ST").upper()
        # ticker musi rzeczywiście stać w tekście — model nie może go wymyślić
        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", ticker) or f"({ticker})" not in tekst:
            continue
        if rodzaj not in ("P", "S") or not data or typ not in ("ST", "OP", "EF"):
            continue
        out.append({"ticker": ticker, "typ": typ, "side": "buy" if rodzaj == "P" else "sell",
                    "partial": False, "date": data, "amt_lo": lo, "amt_hi": hi,
                    "owner": WLASCICIEL.get(str(t.get("wlasciciel") or "").upper(), ""),
                    "asset": "", "note": "odczyt AI" if typ != "OP" else "opcje · odczyt AI"})
    return out

