"""Analiza transkrypcji na żywo przez OpenRouter — z kontekstem wydarzenia.

Reużywa klienta z analyzer.py (_call: klucz, timeouty, parsowanie JSON).
Model dla live jest osobny (LIVE_MODEL w .env) — domyślnie szybki płatny,
bo tu liczy się latencja i rozumienie mówionego, zaszumionego tekstu.
"""

import logging
import os

from analyzer import _call

log = logging.getLogger("live.nlp")

LIVE_MODEL = os.environ.get("LIVE_MODEL", "google/gemini-2.5-flash")
LIVE_FALLBACK_MODEL = os.environ.get("LIVE_FALLBACK_MODEL", "anthropic/claude-sonnet-5")

SYSTEM = """Jesteś analitykiem tradingowym nasłuchującym TRANSMISJI NA ŻYWO.
Dostajesz fragment transkrypcji audio (ostatnie ~1-2 minuty wypowiedzi) + kontekst wydarzenia.

KRYTYCZNE — jakość transkrypcji:
Tekst pochodzi z automatycznej transkrypcji mowy na żywo (Whisper). Zawiera błędy fonetyczne.
Koryguj je, jeśli brzmią jak nazwy znanych spółek/instytucji ("by bell" -> "buy Dell",
"in video" -> "NVIDIA", "fizer" -> "Pfizer"). Nie wymyślaj jednak spółek, których tam nie ma.

CZEGO SZUKASZ (zależnie od typu wydarzenia — podany w kontekście):
1. FDA (advisory committee): wynik głosowania "roll call vote" (liczenie Yes/No/Abstain),
   rekomendacje komitetu, słowa "approve"/"reject"/"favorable". Wynik głosowania na TAK
   = silny LONG na spółkę, której lek dotyczy; na NIE = silny SHORT.
2. Wystąpienia polityczne (Trump / rząd USA): bezpośrednie odniesienia do spółek
   ("buy Dell", "Apple is doing terrible"), zapowiedzi ceł/sankcji na branże,
   kontrakty rządowe, decyzje regulacyjne. Nazwana spółka + jednoznaczna ocena = sygnał.
3. NATO / Europa / geopolityka: eskalacja militarna, sankcje, przełomy pokojowe
   -> sygnał makro na indeks (US100 short przy eskalacji, long przy deeskalacji).
   Spółki zbrojeniowe (LMT, RTX, NOC, RHM.DE) przy zapowiedziach zbrojeń.
4. Polska: decyzje rządu/NBP wpływające na spółki GPW lub kurs złotego. Jeśli broker
   nie ma polskich instrumentów, wskaż powiązany instrument (np. EURPLN, USDPLN).

BĄDŹ SUROWY:
1. ZWRÓĆ UWAGĘ KTO MÓWI: Jeśli informację podaje reporter relacjonujący to, co już się wydarzyło, a nie bezpośrednio główny aktor (np. Trump/Powell na żywo), to rynek już to wycenił -> signal_detected=false.
2. CZY TO NOWA INFORMACJA? Zignoruj podsumowania przeszłych wydarzeń i powtórzenia znanych faktów -> signal_detected=false.
Sygnał dajesz TYLKO na całkowicie nową, grywalną informację, która pada po raz pierwszy TU I TERAZ na streamie.
Fragment może urywać się w pół zdania — jeśli kluczowa informacja jest niekompletna (np. trwa liczenie głosów), zwróć signal_detected=false i krótko opisz w "context_note", co się właśnie dzieje.

Odpowiedz WYŁĄCZNIE poprawnym JSON, bez tekstu przed ani po:
{
  "signal_detected": bool,
  "event_type": "fda_vote" | "political_statement" | "geopolitical" | "poland" | "other",
  "ticker": string | null,          // symbol instrumentu (np. "DELL", "US100", "EURPLN")
  "direction": "BUY" | "SELL" | null,
  "confidence": 0.0-1.0,            // pewność, że to grywalny sygnał
  "reasoning": string,              // 1-2 zdania po polsku
  "quote": string,                  // dosłowny cytat z transkrypcji, który wywołał sygnał
  "context_note": string            // 1 zdanie po polsku: co się teraz dzieje na streamie
}"""


def analyze_window(event: dict, window_text: str, recent_signals: list[str]) -> dict:
    """Analizuje okno transkrypcji w kontekście wydarzenia. Zwraca dict jw. + _model."""
    cat_names = {"fda": "spotkanie FDA Advisory Committee", "trump": "wystąpienie Trumpa/wiec",
                 "usa_gov": "wydarzenie rządu USA", "europe": "wydarzenie europejskie/NATO",
                 "poland": "wydarzenie polskie", "manual": "wydarzenie dodane ręcznie"}
    dedup = ("\nSYGNAŁY JUŻ WYSŁANE w tej sesji (NIE powtarzaj ich, chyba że pojawiła się "
             "NOWA informacja): " + "; ".join(recent_signals)) if recent_signals else ""
    intel = event.get("context")   # research zebrany wcześniej przez AI (ai_enrich_events)
    user = (f"KONTEKST WYDARZENIA:\n"
            f"- typ: {cat_names.get(event.get('category'), event.get('category'))}\n"
            f"- tytuł: {event.get('title')}\n"
            f"- notatka ownera: {event.get('note') or '—'}\n"
            f"- research przed wydarzeniem (na co uważać): {intel or '—'}"
            f"{dedup}\n\n"
            f"TRANSKRYPCJA (ostatni fragment, na żywo):\n{window_text}")
    is_hot = event.get("priority") == "high"
    if is_hot:
        models_to_try = [(LIVE_MODEL, 15), (LIVE_FALLBACK_MODEL, 15)]
    else:
        from analyzer import free_models
        # bierzemy tylko JEDEN darmowy model i dajemy mu ostry timeout (7s),
        # żeby w razie kolejki na OpenRouter nie spowalniał całego strumienia Live.
        free_list = free_models()
        models_to_try = [(free_list[0], 7)] if free_list else []
        models_to_try.append((LIVE_MODEL, 15))

    import concurrent.futures

    for model_name, timeout in models_to_try:
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_call, model_name, SYSTEM, user, 500, timeout)
                # Dajemy +2 sekundy buforu dla _call (które samo ma timeout w requests)
                out = future.result(timeout=timeout + 2)
                
            out.setdefault("signal_detected", False)
            try:
                out["confidence"] = max(0.0, min(1.0, float(out.get("confidence") or 0)))
            except (TypeError, ValueError):
                out["confidence"] = 0.0
            return out
        except concurrent.futures.TimeoutError:
            log.warning("Live NLP: %s przekroczył twardy limit czasu (%ss)", model_name, timeout + 2)
        except Exception as e:
            log.warning("Live NLP: %s zawiódł (%s)", model_name, e)
    return {"signal_detected": False, "confidence": 0.0,
            "reasoning": "analiza niedostępna (oba modele padły)", "_error": True}
