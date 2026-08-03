"""Sterowalna pętla bota — start()/stop() w wątku tła.

Bot NASŁUCHUJE i ANALIZUJE. Nie składa zleceń, nie łączy się z żadnym brokerem
i niczego nie poleca — po analizie zapisuje wydźwięk wiadomości i oddaje sprawę
`outcomes`, który sprawdza potem, jak zachował się kurs.

Dzięki temu przycisk START w panelu faktycznie uruchamia monitorowanie newsów
w tym samym procesie co dashboard (jeden proces = jeden przycisk).
main.py nadal potrafi odpalić to samotnie (np. na VPS bez UI).
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import outcomes
import state
import strategy
from analyzer import analyze_post, verify_signal
from config import load_params
from sources import sec_edgar, truth_social, squawk, gov_rss, gpw_espi, sitemap_monitor, knf_registry, knf_announcements

log = logging.getLogger("runner")

_thread: threading.Thread | None = None
_running = threading.Event()
_executor: ThreadPoolExecutor | None = None
_status = {"running": False, "started_at": None, "last_poll": None,
           "last_error": None, "cycles": 0}
_last_edgar = 0.0
_last_squawk = 0.0
_last_gov = 0.0
_last_truth = 0.0
_last_gpw = 0.0
_last_sitemap = 0.0
_last_knf = 0.0
_last_knf_ann = 0.0
_last_outcomes = 0.0


def is_running() -> bool:
    return _running.is_set()


def status() -> dict:
    return dict(_status)


def _blocked_by(signal: dict, params: dict, source: str = "truth_social") -> dict | None:
    """Bramki odsiewające szum. Zwraca result-dict gdy odpuszczamy, None gdy analizujemy dalej."""
    if not signal.get("tradable") or not signal.get("targets"):
        return {"action": "ignored", "why": "news nie wskazuje konkretnej spółki"}
    if signal["strength"] < params["min_signal_strength"]:
        return {"action": "ignored",
                "why": f"wydźwięk za słaby ({signal['strength']} < próg {params['min_signal_strength']})"}
    stype = signal.get("signal_type", "direct")
    if stype == "thematic" and not params.get("thematic_enabled", True):
        return {"action": "ignored", "why": "sygnały tematyczne wyłączone w ustawieniach"}
    if stype == "macro" and not params.get("macro_enabled", True):
        return {"action": "ignored", "why": "sygnały makro wyłączone w ustawieniach"}
    # godziny sesji zależą od źródła: GPW gra rano (czas PL), reszta wg sesji USA.
    # macro/crypto pomijają bramkę (makro reaguje z wyprzedzeniem, crypto handluje 24/7).
    if stype not in ("macro", "crypto") and not strategy.market_open_for_source(source):
        rynek = "GPW" if strategy.market_for_source(source) == "pl" else "USA"
        return {"action": "after_hours",
                "why": f"news po sesji {rynek} — wartość informacyjna spada, bo do otwarcia "
                       "rynek zdąży ją wycenić. Analiza zostaje zapisana bez pomiaru kursu."}
    return None


def handle_post(post: dict, params: dict):
    text = post.get("text") or post.get("content", "")
    if not text.strip():
        return
    age = post.get("_age_seconds")
    log.info("Nowy post (wiek: %s s): %.120s", f"{age:.0f}" if age else "?", text)

    # Filtr godzin sesji jest w _blocked_by() — tam wyłącza sygnały akcji poza sesją,
    # ale przepuszcza crypto (24/7) i macro. Nie blokujemy tutaj przed AI.

    t0 = time.time()
    signal = analyze_post(text, source=post.get("source", "truth_social"))
    log.info("Ocena AI w %.1f s: %s", time.time() - t0, signal)

    # skrót dla feedu: jaki wydźwięk ma wiadomość dla wskazanej spółki.
    # To opis wymowy newsa, nie zalecenie kupna ani sprzedaży.
    tone = "brak"
    if signal.get("tradable") and signal.get("targets"):
        tone = "negatywny" if signal.get("direction") == "short" else "pozytywny"

    entry = {"post": text[:280], "signal": signal, "tone": tone,
             "source": post.get("source", "truth_social"),
             "latency": f"post→analiza {(age or 0) + time.time() - t0:.0f} s"}

    blocked = _blocked_by(signal, params, post.get("source", "truth_social"))
    if blocked:
        entry["result"] = blocked
        if blocked["action"] == "after_hours":
            for t in signal.get("targets", []):
                strategy.record_mention(t["ticker"])
    else:
        tracked = []
        for target in signal["targets"]:
            t_tone = "negatywny" if target.get("direction") == "short" else "pozytywny"
            strategy.record_mention(target["ticker"])
            # Pomiar kursu nie może wywrócić analizy — Yahoo bywa niedostępny.
            try:
                outcomes.record(target["ticker"], t_tone, signal.get("strength", 0),
                                post.get("source", "truth_social"))
                tracked.append(target["ticker"])
            except Exception as e:
                log.debug("Nie zapisano punktu odniesienia dla %s: %s", target["ticker"], e)
        entry["result"] = {
            "action": "analyzed",
            "why": "; ".join(f"{t['ticker']}: {(t.get('why') or '')[:60]}"
                             for t in signal["targets"]),
            "tracked": tracked,
        }

        if params.get("verify_enabled", True):
            tv = time.time()
            verdict = verify_signal(text, signal)
            entry["verify"] = {**verdict, "took_s": round(time.time() - tv, 1)}
            log.info("Weryfikacja (%s): %s", verdict.get("_model"), verdict)
            if not verdict.get("keep", True):
                entry["result"]["action"] = "questioned"
                entry["result"]["why"] = f"drugi model podważa analizę: {verdict.get('reason', '')}"

    state.log_signal(entry)


def _loop():
    global _last_edgar, _last_squawk, _last_gov, _last_truth, _last_gpw, _last_sitemap, _last_knf, _last_knf_ann, _last_outcomes
    log.info("Pętla bota wystartowała. Parametry: %s", load_params())
    truth_social.prime()  # nie analizujemy postów sprzed startu
    sec_edgar.prime()
    squawk.prime()
    gov_rss.prime()
    gpw_espi.prime()
    sitemap_monitor.prime()
    knf_registry.prime()
    knf_announcements.prime()
    while _running.is_set():
        params = load_params()

        # update polls state for UI
        _status["polls"] = {
            "truth": {"ts": _last_truth, "interval": params.get("truth_social_poll_seconds", 5), "enabled": params.get("truth_social_enabled", True)},
            "squawk": {"ts": _last_squawk, "interval": params.get("squawk_poll_seconds", 5), "enabled": params.get("squawk_enabled", True)},
            "edgar": {"ts": _last_edgar, "interval": params.get("sec_poll_seconds", 20), "enabled": params.get("sec_edgar_enabled", True)},
            "gov": {"ts": _last_gov, "interval": params.get("gov_rss_poll_seconds", 60), "enabled": params.get("gov_rss_enabled", True)},
            "gpw": {"ts": _last_gpw, "interval": params.get("gpw_espi_poll_seconds", 45), "enabled": params.get("gpw_espi_enabled", True)},
            "sitemap": {"ts": _last_sitemap, "interval": params.get("sitemap_poll_seconds", 3600), "enabled": params.get("sitemap_enabled", False)},
            "knf": {"ts": _last_knf, "interval": params.get("knf_poll_seconds", 300), "enabled": params.get("knf_enabled", True)},
            "knf_ann": {"ts": _last_knf_ann, "interval": params.get("knf_ann_poll_seconds", 180), "enabled": params.get("knf_ann_enabled", True)},
        }
        
        state.heartbeat()
        try:
            if params["kill_switch"]:
                pass   # pauza: nasłuch stoi, nic nie analizujemy
            else:
                # Dopisanie pomiarów kursu (1h / 1d) do wcześniejszych analiz.
                # Odpytuje sieć, więc trzymamy to w osobnym try — awaria Yahoo
                # nie ma prawa zatrzymać nasłuchu newsów.
                if time.time() - _last_outcomes >= 60:
                    _last_outcomes = time.time()
                    try:
                        filled = outcomes.tick()
                        if filled:
                            log.info("Uzupełniono %d pomiarów kursu po analizach", filled)
                    except Exception as e:
                        log.debug("Pomiar kursów pominięty: %s", e)
                # 1) Truth Social (z interwałem, nie co cykl)
                truth_interval = params.get("truth_social_poll_seconds", 5)
                if params.get("truth_social_enabled", True) and \
                        time.time() - _last_truth >= truth_interval:
                    _last_truth = time.time()
                    try:
                        for post in truth_social.fetch_new_posts(params["max_post_age_minutes"]):
                            if not _running.is_set():
                                break
                            _executor.submit(handle_post, post, params)
                    except Exception as e:
                        log.debug("Truth Social niedostępny: %s", e)
                # 2) SEC EDGAR (rzadszy interwał — feed i tak odświeża się ~co minutę)
                if params.get("sec_edgar_enabled", True) and \
                        time.time() - _last_edgar >= params["sec_poll_seconds"]:
                    _last_edgar = time.time()
                    # Dawniej filtrem była lista walorów dostępnych u brokera.
                    # Bez brokera przepuszczamy wszystko, co ma rozpoznany ticker.
                    forms = ["8-K"] + (["10-Q"] if params.get("sec_edgar_10q") else [])
                    for form in forms:
                        for filing in sec_edgar.fetch_new_filings(
                                params["max_filing_age_minutes"], form):
                            if not _running.is_set():
                                break
                            _executor.submit(handle_post, filing, params)
                # 3) Squawk (TreeNews)
                if params.get("squawk_enabled", True) and \
                        time.time() - _last_squawk >= params.get("squawk_poll_seconds", 5):
                    _last_squawk = time.time()
                    for sq in squawk.fetch_new_squawks(params["max_post_age_minutes"]):
                        if not _running.is_set():
                            break
                        _executor.submit(handle_post, sq, params)
                # 4) Gov RSS
                if params.get("gov_rss_enabled", True) and \
                        time.time() - _last_gov >= params.get("gov_rss_poll_seconds", 60):
                    _last_gov = time.time()
                    for gov_news in gov_rss.fetch_new_gov_news(params["max_post_age_minutes"]):
                        if not _running.is_set():
                            break
                        _executor.submit(handle_post, gov_news, params)
                # 5) GPW ESPI (komunikaty spółek — polski odpowiednik 8-K)
                if params.get("gpw_espi_enabled", True) and \
                        time.time() - _last_gpw >= params.get("gpw_espi_poll_seconds", 45):
                    _last_gpw = time.time()
                    for report in gpw_espi.fetch_new_gpw_reports(params.get("max_gpw_age_minutes", 30)):
                        if not _running.is_set():
                            break
                        _executor.submit(handle_post, report, params)
                # 6) Sitemap Monitor (eksperymentalny — wymaga uzupełnionej watchlisty)
                if params.get("sitemap_enabled", False) and \
                        time.time() - _last_sitemap >= params.get("sitemap_poll_seconds", 3600):
                    _last_sitemap = time.time()
                    for ev in sitemap_monitor.fetch_new_sitemap_events():
                        if not _running.is_set():
                            break
                        _executor.submit(handle_post, ev, params)
                # 7) KNF — rejestr krótkiej sprzedaży (mirror: shorty.pl)
                if params.get("knf_enabled", True) and \
                        time.time() - _last_knf >= params.get("knf_poll_seconds", 300):
                    _last_knf = time.time()
                    for ev in knf_registry.fetch_new_knf_events(params.get("knf_max_age_minutes", 60)):
                        if not _running.is_set():
                            break
                        _executor.submit(handle_post, ev, params)
                # 8) KNF — komunikaty i decyzje (kary, cofnięcia licencji, postępowania)
                if params.get("knf_ann_enabled", True) and \
                        time.time() - _last_knf_ann >= params.get("knf_ann_poll_seconds", 180):
                    _last_knf_ann = time.time()
                    for ev in knf_announcements.fetch_new_knf_announcements(params.get("knf_ann_max_age_minutes", 120)):
                        if not _running.is_set():
                            break
                        _executor.submit(handle_post, ev, params)
            _status["last_poll"] = time.time()
            _status["last_error"] = None
        except Exception as e:
            log.exception("Błąd w pętli — kontynuuję")
            _status["last_error"] = str(e)
        _status["cycles"] += 1
        # śpij w krótkich kawałkach, żeby STOP działał od razu
        for _ in range(max(1, int(params.get("truth_social_poll_seconds", 5)))):
            if not _running.is_set():
                break
            time.sleep(0.5)
    log.info("Pętla bota zatrzymana.")


def start() -> bool:
    global _thread, _executor
    if _running.is_set():
        return False
    _running.set()
    _executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="ai-worker")
    _status.update(running=True, started_at=time.time(), last_error=None)
    _thread = threading.Thread(target=_loop, name="bot-loop", daemon=True)
    _thread.start()
    return True


def stop() -> bool:
    global _executor
    if not _running.is_set():
        return False
    _running.clear()
    if _executor:
        # cancel_futures=True: zadania JESZCZE NIE zaczęte (np. dziesiątki handle_post
        # zakolejkowane po jednym pollu z wieloma sygnałami) NIE odpalą się po STOP.
        # Bez tego flag'a stop() nie przerywał kolejki — zlecenia i tak leciały dalej.
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None
    _status["running"] = False
    return True
