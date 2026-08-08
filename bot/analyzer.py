"""Analiza postów przez AI (OpenRouter) — dwustopniowa.

ETAP 1 (SZYBKI, decyzja): analyze_post()
  Liczy się czas. Kolejność prób:
    1. darmowe modele :free (2 rundy, fallback po 429/przeciążeniu)
    2. gdy wszystkie darmowe padną -> szybki PŁATNY model (kredyty) — żeby nigdy
       nie przegapić sygnału tylko dlatego, że darmowy provider był zajęty.

ETAP 2 (WERYFIKACJA, jakość): verify_signal()
  Uruchamiany PO otwarciu pozycji (nie blokuje wejścia). Mocny płatny model
  sprawdza, czy trade ma sens. Nastawienie: portfel świadomie podejmuje ryzyko,
  więc trzymanie pozycji jest domyślne — zamykamy tylko przy WYRAŹNYM błędzie.
"""

import json
import logging
import os
import re
import time

import requests

import gpw_tickers
import prompts

log = logging.getLogger("analyzer")

OR_URL = "https://openrouter.ai/api/v1/chat/completions"

# Ścieżka modeli mieszka w prompts.py (edytowalna w /brain). Zmienne środowiskowe
# (OPENROUTER_MODEL / PAID_FAST_MODEL / VERIFY_MODEL) mają pierwszeństwo, gdy ustawione.

def free_models() -> list[str]:
    """Darmowe modele etapu 1 (kolejność = priorytet). ENV OPENROUTER_MODEL idzie na początek."""
    lst = list(prompts.models().get("free") or [])
    env = os.environ.get("OPENROUTER_MODEL")
    if env:
        lst = [env] + [m for m in lst if m != env]
    return lst or ["nvidia/nemotron-3-super-120b-a12b:free"]


def paid_fast_model() -> str:
    return os.environ.get("PAID_FAST_MODEL") or prompts.models().get("paid_fast") or "google/gemini-2.5-flash"


def verify_model() -> str:
    return os.environ.get("VERIFY_MODEL") or prompts.models().get("verify") or "anthropic/claude-sonnet-5"

# Prompty (etap 1, weryfikator, streszczanie) mieszkają w prompts.py i są
# edytowalne na żywo z panelu /brain — tutaj tylko je składamy per źródło.


def pre_filter(text: str) -> str | None:
    """Tani filtr PRZED zapytaniem do AI — odsiewa oczywiste śmieci."""
    stripped = text.strip()
    if len(stripped) < 15:
        return "post za krótki (mem/emotka/pusty retruth)"
    if re.fullmatch(r"(https?://\S+[\s.!]*)+", stripped):
        return "post to sam link, bez treści"
    return None


# ------------------------------------------------------- Squawk: filtr szumu
# Squawk (TreeNews) to w większości "chatter" — komentarze rynkowe bez nowego faktu.
# Zanim w ogóle wyślemy zapytanie do AI, wymagamy przynajmniej jednego rdzenia słowa
# wysokiego sygnału w nagłówku. Rdzenie zamiast pełnych fraz ("ACQUI" zamiast
# "ACQUISITION"), bo Squawk pisze skrótowo ("XYZ TO ACQUIRE ABC", "FDA APPROVES...").
SQUAWK_KEYWORDS = ("BREAKING", "ACQUI", "MERG", "BANKRUPT", "OPEC", "FDA")


def _squawk_noise_filter(text: str) -> bool:
    """True = nagłówek wygląda na coś istotnego, wysyłamy do AI."""
    up = text.upper()
    return any(k in up for k in SQUAWK_KEYWORDS)


# --------------------------------------------- GPW: regex fast-track (Tier 1)
# Absolutne katalizatory z komunikatów ESPI — omijają AI, trafiają prosto do brokera.
# Każdy wzorzec ma strażnika negacji: jeśli tuż przed dopasowaniem stoi "nie"/"brak"/
# "oddalono"/itp., NIE bypassujemy (bezpieczny fallback do LLM, który rozumie kontekst).
_NEGATION_RE = re.compile(r"(?i)\b(nie|brak|bez|wycofa\w*|oddal\w*|odrzuc\w*|zaprzecz\w*|uniewa[żz]ni\w*)\b")

_GPW_HARD_PATTERNS = [
    # Odmiana polska (nabycie/nabycia/nabyciu, wyższa/wyższej) — dopasowujemy rdzenie,
    # nie dosłowne frazy, bo tytuły ESPI/EBI używają różnych przypadków gramatycznych.
    (re.compile(r"(?i)(nabyci\w*\s+akcji\s+własnych|program\w*\s+skupu\s+akcji).{0,100}wyższ\w*\s+niż\s+(rynkow\w*|kurs\w*)"),
     "strong_buy", "skup akcji własnych po cenie z premią"),
    (re.compile(r"(?i)rekomendacj\w*\s+zarządu.{0,60}wypłat\w*\s+dywidend\w*"),
     "buy", "rekomendacja wypłaty dywidendy"),
    (re.compile(r"(?i)wniosk\w*\s+o\s+ogłoszeni\w*\s+upadłości|niewykupien\w*\s+obligacji"),
     "strong_short", "wniosek o upadłość / niewykupione obligacje"),
]

_GPW_HARD_STRENGTH = {"strong_buy": 95, "buy": 78, "strong_short": 95}


def _has_negation_before(text: str, start: int, window: int = 60) -> bool:
    """Szuka słowa negującego jako CAŁEGO słowa (\\b), nie podciągu — polskie rzeczowniki
    odczasownikowe ('złożenie', 'ogłoszenie', 'wykupienie'...) kończą się na '-nie' i
    naiwne dopasowanie podciągu 'nie ' fałszywie wyzwalałoby negację niemal wszędzie."""
    before = text[max(0, start - window):start]
    return bool(_NEGATION_RE.search(before))


def fast_regex_filter(text: str) -> dict | None:
    """Bypass LLM dla twardych, jednoznacznych komunikatów ESPI (Tier 1). Zwraca
    None gdy nic nie pasuje LUB gdy pasuje, ale nie da się bezpiecznie ustalić tickera
    (bez pewnego tickera nie ma czego przypisać -> lecimy normalną ścieżką AI)."""
    for pattern, kind, label in _GPW_HARD_PATTERNS:
        m = pattern.search(text)
        if not m or _has_negation_before(text, m.start()):
            continue
        ticker = gpw_tickers.find_ticker(text.split(":", 1)[0])
        if not ticker:
            continue
        direction = "short" if kind == "strong_short" else "long"
        strength = _GPW_HARD_STRENGTH[kind]
        return {
            "tradable": True, "ticker": ticker, "direction": direction,
            "targets": [{"ticker": ticker, "direction": direction, "weight": 1.0,
                        "size": "large", "why": label}],
            "signal_type": "direct", "news_type": "gpw_hard_signal",
            "authority": "ceo_insider", "strength": strength,
            "reason": f"[REGEX FAST-TRACK] {label}",
            "_model": "regex_fast_track",
        }
    return None


def _parse_json(raw: str) -> dict:
    """Modele lubią owijać JSON w ```json```, dopisywać komentarz albo psuć klucze spacjami."""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"brak JSON w odpowiedzi: {raw[:200]}")
    data = json.loads(m.group(0))
    return {str(k).strip(): v for k, v in data.items()}


def _call(model: str, system: str, user: str, max_tokens: int = 900, req_timeout: int = 18, parse_json: bool = True) -> dict | str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("brak klucza OPENROUTER_API_KEY w .env")
    try:
        resp = requests.post(
            OR_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model, "max_tokens": max_tokens, "temperature": 0,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
            },
            timeout=req_timeout,
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(f"{model}: timeout ({req_timeout}s)")
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"{model}: connection error: {e}")
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        raise RuntimeError(f"{model}: pusta odpowiedź AI")
    if not parse_json:
        return content
    out = _parse_json(content)
    out["_model"] = model
    return out


def _normalize(out: dict) -> dict:
    """Ujednolica odpowiedź AI: zawsze lista targets (max 3) + zgodność wstecz
    (top-level ticker/direction = pierwszy cel, używane przez backtest i panel)."""
    targets = out.get("targets") or []
    if not targets and out.get("ticker"):
        targets = [{"ticker": out["ticker"], "direction": out.get("direction") or "long", "weight": 1.0}]
    clean = []
    for t in targets[:3]:
        if not isinstance(t, dict) or not t.get("ticker"):
            continue
        t.setdefault("direction", "long")
        t.setdefault("size", "large")
        try:
            t["weight"] = max(0.2, min(1.0, float(t.get("weight", 1.0))))
        except (TypeError, ValueError):
            t["weight"] = 1.0
        clean.append(t)
    out["targets"] = clean
    out["ticker"] = clean[0]["ticker"] if clean else None
    out["direction"] = clean[0]["direction"] if clean else None
    out.setdefault("signal_type", "direct")
    out.setdefault("news_type", "other")
    # brak pola authority (starszy prompt / model pominął) = neutralnie, NIE karzemy jak anonima
    if not clean:
        out["tradable"] = False
    return out


def _summarize_long_text(text: str) -> str:
    """Tylko darmowe AI. Agresywny timeout (8s), zwraca czysty tekst."""
    user = f"RAPORT DO STRESZCZENIA:\n{text}"
    for model in free_models():
        try:
            return _call(model, prompts.summary_system(), user, max_tokens=250, req_timeout=8, parse_json=False)
        except Exception as e:
            log.debug("Summary failed on %s: %s", model, e)
    raise RuntimeError("Wszystkie darmowe modele zawiodły przy streszczaniu.")


def analyze_post(post_text: str, source: str = "truth_social") -> dict:
    """ETAP 1 — szybka decyzja. Optymalizacje pod długie teksty."""
    reject = pre_filter(post_text)
    if reject:
        return {"tradable": False, "ticker": None, "direction": None, "targets": [],
                "strength": 0, "reason": f"[pre-filtr] {reject}"}

    if source == "squawk" and not _squawk_noise_filter(post_text):
        return {"tradable": False, "ticker": None, "direction": None, "targets": [],
                "strength": 0, "reason": "[pre-filtr squawk] brak słowa-klucza, pomijam AI"}

    if source == "gpw_espi":
        fast = fast_regex_filter(post_text)
        if fast:
            log.info("GPW regex fast-track (bez AI): %s", fast["reason"])
            return fast

    # prompt składany na żywo z prompts.py (sekcje + kategorie + autorytet, edytowalne w /brain);
    # źródło polskie (GPW/ESPI) dostaje dodatkowy kontekst: tickery GPW, polskie realia
    system = prompts.build_system(source)

    # ZABEZPIECZENIE: Jeśli tekst jest bardzo długi (np. SEC) -> kompresujemy
    is_long = len(post_text) > 1500 or source == "sec_edgar"
    if is_long:
        try:
            log.info("Tekst długi (%d znaków). Próba streszczenia darmowym AI...", len(post_text))
            summary = _summarize_long_text(post_text)
            log.info("Udało się streścić tekst.")
            # Przekazujemy streszczony tekst bezpośrednio do szybkiego PŁATNEGO modelu, żeby nie męczyć znowu darmowych JSON-em
            user = f"ŹRÓDŁO: {source}\n\nSTRESZCZENIE RAPORTU (oryginał miał {len(post_text)} znaków):\n{summary}"
            out = _normalize(_call(paid_fast_model(), system, user, req_timeout=18))
            out["_paid_fallback"] = True
            out["_summarized"] = True
            return out
        except Exception as e:
            log.warning("Streszczanie przerwane (%s). Wysyłam pełny raport od razu do mocnego AI.", e)
            # Fallback bez streszczania prosto do Paid (bo free wyraźnie wisi/ma limity)
            user = f"ŹRÓDŁO: {source}\n\nNEWS:\n{post_text}"
            try:
                out = _normalize(_call(paid_fast_model(), system, user, req_timeout=25))
                out["_paid_fallback"] = True
                return out
            except Exception as e2:
                raise RuntimeError(f"Analiza długiego tekstu całkowicie padła (Paid error: {e2})")

    # Klasyczna ścieżka dla krótkich tekstów (Truth Social)
    user = f"ŹRÓDŁO: {source}\n\nNEWS:\n{post_text}"
    last_err = None
    for attempt in (1, 2):
        for model in free_models():
            try:
                return _normalize(_call(model, system, user, req_timeout=15))
            except Exception as e:
                last_err = e
                log.warning("[free] %s zawiódł (%s)", model, e)
                time.sleep(1)
        if attempt == 1:
            time.sleep(2)

    try:
        log.warning("Darmowe modele niedostępne — przełączam na płatny %s", paid_fast_model())
        out = _normalize(_call(paid_fast_model(), system, user, req_timeout=15))
        out["_paid_fallback"] = True
        return out
    except Exception as e:
        raise RuntimeError(f"analiza nieudana (free: {last_err}; paid: {e})")


def verify_signal(post_text: str, signal: dict) -> dict:
    """ETAP 2 — drugie spojrzenie mocnym płatnym modelem PO otwarciu pozycji."""
    targets_txt = "; ".join(
        f"{t['ticker']} {t.get('direction')} (waga {t.get('weight', 1.0)})"
        for t in signal.get("targets", [])) or f"{signal.get('ticker')} {signal.get('direction')}"
    user = (f"NEWS:\n{post_text}\n\n"
            f"DECYZJA ETAPU 1 (już wykonana):\n"
            f"typ={signal.get('signal_type')}, news={signal.get('news_type')}, "
            f"cele: {targets_txt}, siła={signal.get('strength')}, "
            f"uzasadnienie={signal.get('reason')}")
    try:
        out = _call(verify_model(), prompts.verify_system(), user, max_tokens=400)
        out.setdefault("keep", True)
        return out
    except Exception as e:
        # weryfikator to zabezpieczenie, nie blokada — gdy padnie, TRZYMAMY pozycję
        log.warning("Weryfikator %s niedostępny (%s) — trzymam pozycję", verify_model(), e)
        return {"keep": True, "confidence": 0, "reason": f"weryfikator niedostępny: {e}",
                "_model": verify_model(), "_error": True}
