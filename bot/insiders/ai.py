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

Podsumowanie jest WSPÓLNE. Pisze się je tylko w dwóch sytuacjach (decyzja
ownera z 24.09.2026, żeby nie zjadać limitu darmowych modeli dzielonego
z nasłuchem newsów):
* w tle, raz na dobę, dla osób z rankingu — i tylko gdy od ostatniego tekstu
  przyszła nowa transakcja (`jobs.podsumowania_zawczasu`);
* gdy ktoś fizycznie kliknie przycisk w profilu — nie częściej niż raz na
  PONOWNIE_CO sekund na personę.
Samo wejście w profil NIGDY nie pyta modelu, tylko pokazuje zapisany tekst.
"""

from __future__ import annotations

import logging
import re
import time

from . import store

WAZNE_S = 24 * 3600
PONOWNIE_CO = 10 * 60

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
        lista = analyzer.free_models()
    except Exception:  # noqa: BLE001
        lista = []
    # Lista nasłuchu ma martwe pozycje (qwen3-next i llama-3.3 w wersji darmowej
    # zniknęły — 404, gpt-oss przestał być darmowy), więc dokładamy żywe z
    # katalogu OpenRoutera z 22.09.2026. Martwy model odpada w ułamku sekundy.
    zapas = ["google/gemma-4-31b-it:free", "qwen/qwen3.8-27b:free"]
    return (lista[:2] + [m for m in zapas if m not in lista[:2]])[:4]


_META = re.compile(r"\b(the user|constraints?|i need|i will|let me|let's|we need|"
                   r"the (task|request|prompt)|sentences?)\b", re.I)


def _po_polsku(tekst) -> bool:
    """Darmowe modele „myślące" potrafią oddać zamiast odpowiedzi własne rozważania
    po angielsku („The user wants a 2-3 sentence summary…"), ucięte na limicie
    tokenów. Takiego tekstu nie wolno pokazać — ani zapisać na dobę."""
    if not isinstance(tekst, str) or len(tekst.strip()) < 40:
        return False
    if _META.search(tekst[:400]):
        return False
    return sum(tekst.count(z) for z in "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ") >= 3


def model_platny() -> str:
    """Płatny model do narracji paska „Najciekawsze zagrania" — zmienna
    `INSIDERS_AI_MODEL` (np. `anthropic/claude-sonnet-5`). Pusta = same darmowe."""
    import os
    return (os.environ.get("INSIDERS_AI_MODEL") or "").strip()


def _zapytaj(rodzaj: str, system: str, tekst: str, max_tokens: int, json_: bool,
             sprawdz=None, modele: list[str] | None = None):
    """Pyta kolejne modele (domyślnie darmowe). Każda próba trafia do `ai_log` —
    panel dev liczy z niego rachunek i to, ile zjadamy ze wspólnego limitu darmowych."""
    import analyzer
    ostatni = None
    for model in (modele or _modele()):
        uzycie: dict = {}
        darmowy = model.endswith(":free")
        try:
            # Wszystkie dzisiejsze darmowe modele „myślą". Bez `reasoning.exclude`
            # część z nich wpisuje rozważania do odpowiedzi; z nim Nemotron Ultra
            # oddaje czysty tekst (sprawdzone 22.09.2026). Myślenie trwa: na 45
            # transakcjach Pelosi 70 s — przy limicie 50 s nie udawało się nigdy.
            # Płatnym modelom myślenie niepotrzebne — to prosty tekst z gotowych faktów.
            odp = analyzer._call(model, system, tekst, max_tokens=max_tokens,
                                 req_timeout=110 if darmowy else 60, parse_json=json_,
                                 usage_out=uzycie,
                                 extra={"reasoning": {"effort": "low", "exclude": True}}
                                 if darmowy else None)
        except Exception as e:  # noqa: BLE001 — następny model
            ostatni = e
            store.ai_log_add(rodzaj, model, ok=False, limit="429" in str(e) or "rate" in str(e).lower())
            continue
        dobra = sprawdz is None or sprawdz(odp)
        store.ai_log_add(rodzaj, model, ok=dobra, tok_in=uzycie.get("prompt_tokens") or 0,
                         tok_out=uzycie.get("completion_tokens") or 0,
                         usd=uzycie.get("cost") or 0)
        if not dobra:
            ostatni = RuntimeError(f"{model}: odpowiedź nie przeszła sprawdzenia")
            continue                                    # następny model
        return odp
    if ostatni:
        log.info("Darmowe modele nie odpowiedziały: %s", ostatni)
    return None


def _kw(t: dict) -> str:
    lo, hi = t.get("amt_lo"), t.get("amt_hi")
    if lo and hi and abs(hi - lo) > 1:
        return f"{int(lo):,}–{int(hi):,} $".replace(",", " ")
    v = lo or hi
    return f"{int(v):,} $".replace(",", " ") if v else "?"


def podpis(transakcje: list[dict]) -> str:
    """Odcisk listy transakcji — zmienia się, gdy dojdzie nowa. Po nim tło poznaje,
    że stary tekst dalej jest aktualny i nie ma po co pytać modelu."""
    if not transakcje:
        return ""
    t = transakcje[0]
    return f"{len(transakcje)}|{t.get('uid') or ''}|{t.get('date')}|{t.get('ticker')}"


def zapisane(pid: str) -> dict | None:
    """{text, at} ostatniego podsumowania persony, bez względu na wiek."""
    hit = store.kv_get(f"ai:{pid}")
    return hit if isinstance(hit, dict) and _po_polsku(hit.get("text")) else None


def podsumowanie(pid: str, nazwa: str, rola: str, transakcje: list[dict],
                 statystyki: dict, ponownie: bool = False) -> dict | None:
    """{text, at, fresh}. `ponownie` = prośba z przycisku o nowy tekst."""
    stare = zapisane(pid)
    teraz = time.time()
    if stare:
        wiek = teraz - float(stare.get("at") or 0)
        if wiek < WAZNE_S and not (ponownie and wiek >= PONOWNIE_CO):
            store.ai_log_add("podsumowanie", ok=True)          # z pamięci — bez modelu
            return {**stare, "fresh": False}
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
    # 2000 tokenów, choć odpowiedź ma 420 znaków: model „myślący" zużywa część
    # limitu na rozważania i przy 350 ucinało mu odpowiedź w połowie myśli
    odp = _zapytaj("podsumowanie", SYSTEM_PODSUMOWANIE, tekst, 2000, json_=False,
                   sprawdz=lambda o: _po_polsku(re.sub(r"\s+", " ", str(o))))
    if not isinstance(odp, str):
        return {**stare, "fresh": False} if stare else None   # stary tekst lepszy niż żaden
    czysty = re.sub(r"\s+", " ", odp.replace("*", "")).strip()[:600]
    # Model ucięty limitem tokenów kończy w pół zdania („Wyróżnia się") —
    # zostawiamy tylko pełne zdania.
    koniec = max(czysty.rfind(". "), czysty.rfind("! "), czysty.rfind("? "))
    if not czysty.endswith((".", "!", "?")) and koniec > 0:
        czysty = czysty[:koniec + 1]
    if len(czysty) < 40 or not czysty.endswith((".", "!", "?")):
        return {**stare, "fresh": False} if stare else None
    wpis = {"text": czysty, "at": teraz, "sig": podpis(transakcje)}
    store.kv_set(f"ai:{pid}", wpis)
    return {**wpis, "fresh": True}


def odczytaj_ptr(tekst: str) -> list[dict] | None:
    """Awaryjny odczyt raportu. Zwraca listę w formacie `house.czytaj`."""
    from .house import WLASCICIEL, _data_us

    odp = _zapytaj("ptr", SYSTEM_PTR, (tekst or "").replace("\x00", "")[:14000], 1800, json_=True)
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



SYSTEM_WYROZNIENIE = """Jesteś dziennikarzem rynku piszącym krótkie notki do polskiej aplikacji
inwestycyjnej. Dostajesz fakty o jednej transakcji ujawnionej w oficjalnym
zgłoszeniu (Kongres USA, rząd USA, prezes spółki, GPW) i powody, dla których
trafiła na listę najciekawszych.

Napisz 3–4 zdania po polsku:
1. kto (imię, nazwisko, funkcja) i co zrobił — spółka, kwota, data;
2. dlaczego to ciekawe — użyj podanych powodów (komisja, urząd, skala, inni insiderzy);
3. czym zajmuje się spółka, jednym zdaniem (jeśli wiesz na pewno; inaczej pomiń);
4. co od tego czasu zrobił kurs, jeśli podano.

Zasady:
- Tylko fakty z danych i powszechnie znane informacje o spółce. Bez domysłów.
- Konflikt interesów opisuj rzeczowo („zasiada w komisji, która nadzoruje…"),
  nigdy nie sugeruj przestępstwa ani wykorzystania informacji poufnych.
- Nie zgaduj płci z imienia. Unikaj form zależnych od płci: zamiast „kupił/kupiła",
  „członek/członkini" pisz „ujawnione kupno", „transakcja", „zasiada w komisji".
- Nazwy komisji i podkomisji podawaj po polsku.
- Daty pisz słownie („25 sierpnia"), kwoty jak w danych.
- Bez rad inwestycyjnych, bez markdownu, bez wstępów.
Odpowiedz samym tekstem, maksymalnie 600 znaków."""


def narracja_wyroznienia(p: dict, nazwa: str, rola: str) -> str | None:
    """Notka AI dla pozycji z paska. Zapisana na stałe pod `wyr:ai:{id}` —
    pozycja się nie zmienia, więc piszemy ją raz."""
    from . import wyroznione

    zapis = store.kv_get(f"wyr:ai:{p['id']}")
    if isinstance(zapis, dict) and zapis.get("sig") == wyroznione.podpis(p) and _po_polsku(zapis.get("text")):
        return zapis["text"]
    kw = (wyroznione._kwota_txt(p["lo"], p["hi"], p.get("cur") or "USD") if p.get("net") is None
          else f"saldo ok. {wyroznione._kwota_txt(abs(p['net']), abs(p['net']))}")
    fakty = "\n".join([
        f"Osoba: {nazwa}" + (f" — {rola}" if rola else ""),
        f"Transakcja: {'KUPNO' if p['side'] == 'buy' else 'SPRZEDAŻ'} {p['asset']} ({p['ticker']}), {kw}",
        f"Data transakcji: {p['date']}, data ujawnienia: {p['filed']}",
        f"Branża spółki: {p.get('sector') or 'nieznana'}",
        "Powody wyróżnienia:",
        *[f"- {z}" for z in (p.get("why") or [])],
    ])
    platny = model_platny()
    modele = ([platny] if platny else []) + _modele()
    odp = _zapytaj("wyroznienie", SYSTEM_WYROZNIENIE, fakty, 1500 if not platny else 500,
                   json_=False, modele=modele,
                   sprawdz=lambda o: _po_polsku(re.sub(r"\s+", " ", str(o))))
    if not isinstance(odp, str):
        return None
    czysty = re.sub(r"\s+", " ", odp.replace("*", "")).strip()[:800]
    koniec = max(czysty.rfind(". "), czysty.rfind("! "), czysty.rfind("? "))
    if not czysty.endswith((".", "!", "?")) and koniec > 0:
        czysty = czysty[:koniec + 1]
    if len(czysty) < 60:
        return None
    store.kv_set(f"wyr:ai:{p['id']}", {"text": czysty, "at": time.time(), "sig": wyroznione.podpis(p)})
    return czysty


def zapisana_narracja(pid: str) -> str | None:
    z = store.kv_get(f"wyr:ai:{pid}")
    return z["text"] if isinstance(z, dict) and _po_polsku(z.get("text")) else None
