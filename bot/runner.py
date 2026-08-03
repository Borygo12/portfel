"""Sterowalna pętla bota — start()/stop() w wątku tła.

Dzięki temu przycisk START w panelu faktycznie uruchamia monitorowanie newsów
w tym samym procesie co dashboard (jeden proces = jeden przycisk).
main.py nadal potrafi odpalić to samotnie (np. na VPS bez UI).
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import state
import strategy
import trader
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
_tradable_cache: set = set()
_tradable_at = 0.0


def _tradable_tickers() -> set:
    """Zbiór tradowalnych tickerów (cache ~1h) — filtr EDGAR przed AI."""
    global _tradable_cache, _tradable_at
    if _tradable_cache and time.time() - _tradable_at < 3600:
        return _tradable_cache
    try:
        if trader.client.configured and hasattr(trader.client, "tradable_tickers"):
            _tradable_cache = trader.client.tradable_tickers()
            _tradable_at = time.time()
    except Exception:
        log.exception("Nie udało się pobrać listy tradowalnych tickerów")
    return _tradable_cache


def is_running() -> bool:
    return _running.is_set()


def status() -> dict:
    return dict(_status)


def _blocked_by(signal: dict, params: dict, source: str = "truth_social") -> dict | None:
    """Bramki PRZED egzekucją. Zwraca result-dict gdy nie gramy, None gdy gramy."""
    if not signal.get("tradable") or not signal.get("targets"):
        return {"action": "ignored", "why": "news nie daje grywalnego sygnału"}
    if signal["strength"] < params["min_signal_strength"]:
        return {"action": "ignored",
                "why": f"sygnał za słaby ({signal['strength']} < próg {params['min_signal_strength']})"}
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
                "why": f"news po sesji {rynek} — bot odpuszcza (przewaga to reakcja w minutę; "
                       "do otwarcia rynek zdąży wycenić). Możesz zagrać ręcznie."}
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

    # decyzja skrótowa dla feedu: BUY / SHORT / SKIP
    decision = "SKIP"
    if signal.get("tradable") and signal.get("targets"):
        decision = "SHORT" if signal.get("direction") == "short" else "BUY"

    entry = {"post": text[:280], "signal": signal, "decision": decision,
             "source": post.get("source", "truth_social"),
             "latency": f"post→decyzja {(age or 0) + time.time() - t0:.0f} s"}

    blocked = _blocked_by(signal, params, post.get("source", "truth_social"))
    if blocked:
        entry["result"] = blocked
        if blocked["action"] == "after_hours":
            for t in signal.get("targets", []):
                strategy.record_mention(t["ticker"])
    else:
        trades = []
        for target in signal["targets"]:
            res = trader.open_trade(target["ticker"], target["direction"],
                                    target.get("why") or signal.get("reason", ""),
                                    signal=signal, target=target)
            trades.append(res)
            strategy.record_mention(target["ticker"])
        opened = [r for r in trades if r.get("action") == "opened"]
        entry["result"] = {
            "action": "opened" if opened else trades[0].get("action", "skipped"),
            "why": ("; ".join(f"{r['ticker']}: {r.get('why', '')[:60]}" for r in trades)
                    if len(trades) > 1 else trades[0].get("why", "")),
            "trades": trades,
        }
        if len(opened) == 1:
            entry["result"]["sizing"] = opened[0].get("sizing")

        if opened and params.get("verify_enabled", True):
            tv = time.time()
            verdict = verify_signal(text, signal)
            entry["verify"] = {**verdict, "took_s": round(time.time() - tv, 1)}
            log.info("Weryfikacja (%s): %s", verdict.get("_model"), verdict)
            if not verdict.get("keep", True):
                closed = all(trader.close_position(r.get("positionId")) for r in opened)
                entry["result"]["action"] = "closed_by_verifier" if closed else "verifier_reject_failed"
                entry["result"]["why"] = f"weryfikator zamknął: {verdict.get('reason', '')}"

    state.log_signal(entry)


def _loop():
    global _last_edgar, _last_squawk, _last_gov, _last_truth, _last_gpw, _last_sitemap, _last_knf, _last_knf_ann
    log.info("Pętla bota wystartowała. Parametry: %s", load_params())
    truth_social.prime()  # nie gramy na postach sprzed startu
    sec_edgar.prime(_tradable_tickers())
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
                try:
                    trader.close_everything()
                except Exception as e:
                    log.warning("kill_switch: broker niedostępny (%s)", e)
            else:
                # Zarządzanie pozycjami woła brokera. Gdy broker leży (np. wygasły token),
                # NIE może to zabić nasłuchu newsów — izolujemy je w osobnym try.
                # Dzięki temu analiza AI działa dalej nawet bez połączenia z brokerem.
                try:
                    trader.manage_positions(params)
                except Exception as e:
                    _status["broker_error"] = str(e)
                    log.debug("manage_positions pominięte (broker): %s", e)
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
                    tradable = _tradable_tickers()
                    forms = ["8-K"] + (["10-Q"] if params.get("sec_edgar_10q") else [])
                    for form in forms:
                        for filing in sec_edgar.fetch_new_filings(
                                params["max_filing_age_minutes"], form, tradable):
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
