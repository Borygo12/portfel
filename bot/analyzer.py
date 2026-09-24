"""Analiza postów przez AI (OpenRouter) — dwustopniowa.

ETAP 1 (SZYBKI, decyzja): analyze_post()
  Liczy się czas. Kolejność prób:
    1. darmowe modele :free, jedna runda, z pominięciem modeli „na karze"
    2. gdy wszystkie darmowe padną -> szybki PŁATNY model (kredyty) — żeby nigdy
       nie przegapić sygnału tylko dlatego, że darmowy provider był zajęty.
  Długie teksty (SEC, długie ESPI): darmowe streszczenie -> DARMOWA analiza
  streszczenia -> płatny dopiero, gdy darmowe zawiodą.

  Zmierzone 24.09.2026 na prawdziwych newsach (ten sam prompt co bot):
  * wszystkie darmowe modele „myślą" przed odpowiedzią (500–1400 tokenów).
    Przy limicie 900 odpowiedź ucinała się w połowie JSON-a, a streszczenie
    z limitem 250 wychodziło puste — i każda taka porażka kończyła się płatnym
    modelem. Z `reasoning.enabled = false` te same modele odpowiadają w 2–5 s
    zamiast 12–45 s i bez uciętych odpowiedzi;
  * 3 z 6 modeli z listy nie miały już darmowej wersji (gpt-oss-120b,
    qwen3-next-80b, llama-3.3-70b) — tylko traciły czas.

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


# ------------------------------------------- darmowe modele: kara i statystyki
# Model, który właśnie odpowiedział 429/503 albo przekroczył czas, dostaje krótką
# karę — kolejne newsy go omijają zamiast odbijać się od niego co kilka sekund.
# Przekroczenie czasu zjada dzienny limit darmowych zapytań, a nic nie daje.
KARA_S = 90
_kara: dict[str, float] = {}
#: Liczniki per model za bieżącą dobę (UTC — tak liczy limit OpenRouter).
#: Panel dev pokazuje z nich, który model naprawdę pracuje, a który tylko zawodzi.
_stat: dict = {"dzien": "", "modele": {}, "sciezki": {}}


def _licz(model: str, wynik: str, sek: float = 0.0) -> None:
    dzien = time.strftime("%Y-%m-%d", time.gmtime())
    if _stat["dzien"] != dzien:
        _stat["dzien"], _stat["modele"], _stat["sciezki"] = dzien, {}, {}
    m = _stat["modele"].setdefault(model, {"ok": 0, "czas_ok_s": 0.0})
    m[wynik] = m.get(wynik, 0) + 1
    if wynik == "ok":
        m["czas_ok_s"] = round(m["czas_ok_s"] + sek, 1)


def _sciezka(nazwa: str) -> None:
    """Czym skończyła się analiza: darmowy / płatny / płatny po streszczeniu itd."""
    _licz("_", "_")                       # przełączenie doby, jeśli trzeba
    _stat["modele"].pop("_", None)
    _stat["sciezki"][nazwa] = _stat["sciezki"].get(nazwa, 0) + 1


def statystyki_modeli() -> dict:
    teraz = time.time()
    return {"dzien_utc": _stat["dzien"], "modele": _stat["modele"], "sciezki": _stat["sciezki"],
            "na_karze": {m: int(t - teraz) for m, t in _kara.items() if t > teraz}}


def _rodzaj_bledu(e: Exception) -> str:
    s = str(e).lower()
    if "timeout" in s:
        return "timeout"
    if "404" in s or "unavailable for free" in s:
        return "nie_istnieje_404"
    if "429" in s or "rate" in s:
        return "limit_429"
    if "503" in s or "overload" in s or "502" in s:
        return "przeciazony_503"
    if "json" in s or "pusta" in s:
        return "zla_odpowiedz"
    return "inny"


def _free_try(model: str, system: str, user: str, max_tokens: int, req_timeout: int,
              parse_json: bool = True):
    """Jedno podejście do darmowego modelu: bez „myślenia", z liczeniem i karą."""
    t0 = time.time()
    try:
        out = _call(model, system, user, max_tokens=max_tokens, req_timeout=req_timeout,
                    parse_json=parse_json, extra={"reasoning": {"enabled": False}})
    except Exception as e:
        rodzaj = _rodzaj_bledu(e)
        _licz(model, rodzaj)
        if rodzaj in ("timeout", "limit_429", "przeciazony_503", "nie_istnieje_404"):
            _kara[model] = time.time() + (6 * 3600 if rodzaj == "nie_istnieje_404" else KARA_S)
        raise
    _licz(model, "ok", time.time() - t0)
    return out


def _free_round(system: str, user: str, max_tokens: int = 1200, req_timeout: int = 15,
                parse_json: bool = True):
    """Jedna runda po darmowych modelach, które nie są na karze. None = żaden nie dał rady."""
    teraz = time.time()
    kolejka = [m for m in free_models() if _kara.get(m, 0) <= teraz]
    if not kolejka:
        # wszystkie na karze — spróbuj chociaż tego, któremu kara kończy się najszybciej
        kolejka = sorted(free_models(), key=lambda m: _kara.get(m, 0))[:1]
    for model in kolejka:
        try:
            return _free_try(model, system, user, max_tokens, req_timeout, parse_json)
        except Exception as e:
            log.warning("[free] %s zawiódł (%s)", model, str(e)[:160])
    return None


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


def _call(model: str, system: str, user: str, max_tokens: int = 900, req_timeout: int = 18,
          parse_json: bool = True, usage_out: dict | None = None,
          extra: dict | None = None) -> dict | str:
    """`usage_out` — słownik, do którego trafia pole `usage` z odpowiedzi OpenRoutera
    (tokeny i koszt), dla wywołujących, którzy prowadzą własny rachunek.
    `extra` — dodatkowe pola zapytania (np. `reasoning`)."""
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
                **(extra or {}),
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
    if usage_out is not None and isinstance(data.get("usage"), dict):
        usage_out.update(data["usage"])
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
    """Tylko darmowe AI, bez „myślenia" — wtedy mieści się w kilku sekundach.
    Dawniej limit 250 tokenów zjadało samo „myślenie" i streszczenie wychodziło puste."""
    user = f"RAPORT DO STRESZCZENIA:\n{text}"
    out = _free_round(prompts.summary_system(), user, max_tokens=500, req_timeout=20,
                      parse_json=False)
    if not out or len(str(out).strip()) < 40:
        raise RuntimeError("Wszystkie darmowe modele zawiodły przy streszczaniu.")
    return str(out)


def analyze_post(post_text: str, source: str = "truth_social") -> dict:
    """ETAP 1 — szybka decyzja. Optymalizacje pod długie teksty."""
    reject = pre_filter(post_text)
    if reject:
        # `prefilter: True` to jedyny wiarygodny znacznik „nie pytaliśmy modelu".
        # Wcześniej rozpoznawał to rachunek kosztów po przedrostku „[pre-filtr" —
        # czyli po TREŚCI zdania pisanego dla człowieka. Wystarczyło je poprawić,
        # żeby odsiane wpisy zaczęły się liczyć jako płatne wywołania.
        return {"tradable": False, "ticker": None, "direction": None, "targets": [],
                "prefilter": True,
                "strength": 0, "reason": f"Pominięte bez analizy: {reject}."}

    if source == "squawk" and not _squawk_noise_filter(post_text):
        # Powód pisany po ludzku, bo trafia wprost na ekran użytkownika. „brak
        # słowa-klucza, pomijam AI" opisywało implementację, a nie to, co się
        # stało z wiadomością — i po takim wpisie nikt nie wiedział, czy bot coś
        # przeoczył, czy świadomie odpuścił.
        return {"tradable": False, "ticker": None, "direction": None, "targets": [],
                "prefilter": True,
                "strength": 0,
                "reason": "Zwykły komentarz rynkowy bez nowego faktu — nie ma tu "
                          "przejęcia, wyników ani decyzji urzędu, więc odpuszczamy "
                          "analizę AI."}

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
            # Streszczenie jest krótkie — najpierw analizują je DARMOWE modele.
            # Wcześniej szło od razu do płatnego i to była większość rachunku
            # (SEC + długie ESPI); płatny został tylko jako zapas.
            user = f"ŹRÓDŁO: {source}\n\nSTRESZCZENIE RAPORTU (oryginał miał {len(post_text)} znaków):\n{summary}"
            free = _free_round(system, user)
            if free is not None:
                out = _normalize(free)
                out["_summarized"] = True
                _sciezka("darmowy_po_streszczeniu")
                return out
            out = _normalize(_call(paid_fast_model(), system, user, req_timeout=18))
            out["_paid_fallback"] = True
            out["_summarized"] = True
            _sciezka("platny_po_streszczeniu")
            return out
        except Exception as e:
            log.warning("Streszczanie przerwane (%s). Pełny raport: najpierw darmowe, potem płatny.", e)
            user = f"ŹRÓDŁO: {source}\n\nNEWS:\n{post_text}"
            free = _free_round(system, user, req_timeout=25)
            if free is not None:
                _sciezka("darmowy_pelny_raport")
                return _normalize(free)
            try:
                out = _normalize(_call(paid_fast_model(), system, user, req_timeout=25))
                out["_paid_fallback"] = True
                _sciezka("platny_pelny_raport")
                return out
            except Exception as e2:
                raise RuntimeError(f"Analiza długiego tekstu całkowicie padła (Paid error: {e2})")

    # Klasyczna ścieżka dla krótkich tekstów (Truth Social)
    user = f"ŹRÓDŁO: {source}\n\nNEWS:\n{post_text}"
    # Jedna runda. Dawniej były dwie po całej liście z przerwami — druga trafiała
    # w te same przeciążone modele, a każda próba z odpowiedzią (także złą)
    # zjadała dzienny limit. Model, który właśnie zawiódł, i tak siedzi na karze.
    free = _free_round(system, user)
    if free is not None:
        _sciezka("darmowy")
        return _normalize(free)
    last_err = "wszystkie darmowe modele zawiodły albo są na karze"

    try:
        log.warning("Darmowe modele niedostępne — przełączam na płatny %s", paid_fast_model())
        out = _normalize(_call(paid_fast_model(), system, user, req_timeout=15))
        out["_paid_fallback"] = True
        _sciezka("platny_krotki")
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
