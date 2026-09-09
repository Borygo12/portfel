"""Z analizy newsa robi powiadomienia dla tych, których ta spółka obchodzi.

Wpinane w `runner.handle_post` — jedno wywołanie po zapisaniu analizy do feedu.

Trzy rzeczy, które ten moduł musi zrobić dobrze, bo inaczej powiadomienia albo
nie docierają, albo docierają za często:

* **dopasowanie symbolu.** AI oddaje ticker w postaci, w jakiej padł w newsie
  („CDR", „NVDA"), a w `user_symbols` leżą symbole Yahoo („CDR.WA"). Szukamy
  więc obu naraz — surowego i rozwiązanego;
* **próg „tylko mocne".** Kto wybrał trzeci przycisk, dostaje wyłącznie analizy
  od `notify_strong_strength` w górę. Próg jest w parametrach serwera, nie
  w kodzie, więc da się go podkręcić bez wydawania nowej wersji aplikacji;
* **jedno powiadomienie na news, nie na spółkę.** Gdy komunikat dotyczy trzech
  spółek z czyjegoś portfela, ta osoba dostaje jedną wiadomość o trzech, a nie
  trzy osobne. Telefon dzwoniący trzy razy pod rząd to powód do wyłączenia
  powiadomień, a nie do wejścia do aplikacji.
"""

from __future__ import annotations

import hashlib
import logging

from . import engine, store

log = logging.getLogger("notify.news")

ZRODLA = {
    "gpw_espi": "ESPI (GPW)", "sec_edgar": "SEC EDGAR", "squawk": "Terminal",
    "truth_social": "Truth Social", "rss": "komunikat rządowy", "knf": "KNF",
    "knf_ann": "KNF", "live_event": "wystąpienie na żywo", "direct": "źródło bezpośrednie",
}


def _symbole_celu(ticker: str) -> set[str]:
    """Warianty symbolu, pod którymi ta spółka może siedzieć w `user_symbols`."""
    t = (ticker or "").strip().upper()
    if not t:
        return set()
    warianty = {t}
    try:
        from portfolio import prices as pf_prices
        rozwiazany = (pf_prices.resolved_symbol(t) or "").upper()
        if rozwiazany:
            warianty.add(rozwiazany)
    except Exception as e:  # noqa: BLE001 — brak mapowania nie może zablokować wysyłki
        log.debug("Nie rozwiązano symbolu %s: %s", t, e)
    return warianty


def _tresc(cele: list[dict], zrodlo: str, sila: int) -> tuple[str, str]:
    """Tytuł i treść powiadomienia. Krótko — to ma zmieścić się na ekranie blokady."""
    symbole = [c["etykieta"] for c in cele]
    wydzwiek = "negatywny" if cele[0]["kierunek"] == "short" else "pozytywny"

    if len(symbole) == 1:
        tytul = f"{symbole[0]} — {wydzwiek} news"
    else:
        tytul = f"{', '.join(symbole[:3])} — {wydzwiek} news"

    powod = (cele[0].get("why") or "").strip()
    skad = ZRODLA.get(zrodlo, zrodlo or "źródło")
    tresc = f"{powod} " if powod else ""
    tresc += f"({skad} · siła {sila}/100)"
    return tytul[:100], tresc.strip()[:240]


def rozeslij(signal: dict, zrodlo: str, params: dict) -> int:
    """Rozsyła powiadomienia o jednej analizie. Zwraca liczbę powiadomionych kont."""
    if not signal.get("tradable") or not signal.get("targets"):
        return 0

    sila = int(signal.get("strength") or 0)
    prog_mocnych = int(params.get("notify_strong_strength", 85))

    # symbol (dowolny wariant) -> dane celu z analizy
    cele: dict[str, dict] = {}
    for target in signal["targets"]:
        ticker = (target.get("ticker") or "").strip().upper()
        for wariant in _symbole_celu(ticker):
            cele[wariant] = {
                "etykieta": ticker or wariant,
                "kierunek": target.get("direction") or "long",
                "why": target.get("why") or "",
            }
    if not cele:
        return 0

    try:
        trafienia = store.kogo_obchodzi(set(cele))
    except Exception as e:  # noqa: BLE001
        log.warning("Nie sprawdzono, kogo obchodzi ten news: %s", e)
        return 0
    if not trafienia:
        return 0

    # Powiadomienia to funkcja płatna — sprawdzamy uprawnienia jednym zapytaniem,
    # zanim zaczniemy cokolwiek wysyłać.
    uprawnieni = store.tylko_premium([str(t["user_id"]) for t in trafienia])
    if not uprawnieni:
        return 0

    # Jedna osoba może mieć w portfelu kilka spółek z tego samego komunikatu —
    # zbieramy je razem, żeby wysłać JEDNO powiadomienie.
    per_konto: dict[str, list[dict]] = {}
    for t in trafienia:
        uid = str(t["user_id"])
        if uid not in uprawnieni:
            continue
        cel = cele.get((t["symbol"] or "").upper())
        if not cel:
            continue
        lista = per_konto.setdefault(uid, [])
        if all(c["etykieta"] != cel["etykieta"] for c in lista):
            lista.append(cel)

    # Klucz przeciw duplikatom: ta sama treść analizy = ten sam news, nawet gdy
    # przyszedł dwoma źródłami albo pętla zobaczyła go drugi raz po restarcie.
    odcisk = hashlib.sha1(
        f"{sorted(cele)}|{sila}|{(signal.get('summary') or '')[:200]}".encode()
    ).hexdigest()[:16]

    wyslane = 0
    for uid, lista in per_konto.items():
        try:
            ust = store.ustawienia(uid)
        except Exception as e:  # noqa: BLE001
            log.warning("Nie odczytano ustawień konta: %s", e)
            continue

        tryb = ust["news_mode"]
        if tryb == "off":
            continue
        if tryb == "strong" and sila < prog_mocnych:
            continue

        tytul, tresc = _tresc(lista, zrodlo, sila)
        if engine.powiadom(
            uid, "news", tytul, tresc,
            dedup_key=f"news:{odcisk}",
            symbol=lista[0]["etykieta"],
            meta={"strength": sila, "source": zrodlo,
                  "symbols": [c["etykieta"] for c in lista]},
        ):
            wyslane += 1

    if wyslane:
        log.info("News o %s — powiadomiono %s kont", sorted(cele), wyslane)
    return wyslane
