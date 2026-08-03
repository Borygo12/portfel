"""Orkiestracja modułu "Wystąpienia na żywo".

- Monitor (wątek): odświeża kalendarz FDA, sprawdza kanały YouTube pod kątem live,
  autostartuje sesje dla śledzonych wydarzeń, próbuje wystartować śledzone
  wydarzenia z ręcznym URL-em gdy nadejdzie ich godzina.
- Sesja (LiveEventSession): capture+STT (live.capture) + pętla NLP (live.nlp)
  + przekazanie mocnych fragmentów do pełnej analizy (tylko gdy live_auto_analyze).

Wszystkie sygnały i analizy lecą też do wspólnego feedu (state.log_signal),
więc widać je również na głównym panelu.
"""

import logging
import threading
import time

import state
from config import load_params
from live import calendar as cal
from live import nlp
from live.capture import LiveCapture, deps_status

log = logging.getLogger("live.manager")

_sessions: dict[str, "LiveEventSession"] = {}
_monitor_thread: threading.Thread | None = None
_monitor_running = threading.Event()
_monitor_status = {"running": False, "last_poll": None, "last_fda_refresh": None,
                   "last_error": None, "channel_checks": {}}
_lock = threading.Lock()


# ------------------------------------------------------------------- sesja

class LiveEventSession:
    def __init__(self, event: dict):
        self.event = event
        self.id = event["id"]
        params = load_params()
        lang = None
        for ch in cal.load_channels():
            if ch["id"] == event.get("channel_id"):
                lang = ch.get("lang")
        # priorytet ⚡: wydarzenia Trump/FDA (lub ręcznie oznaczone) słuchamy i analizujemy
        # szybciej — krótsze chunki audio i częstsze zapytania do AI
        self.hot = event.get("priority") == "high"
        chunk_key = "live_chunk_seconds_hot" if self.hot else "live_chunk_seconds"
        self.transcript: list[dict] = []   # {t, text}
        self.analyses: list[dict] = []     # odpowiedzi NLP (też te bez sygnału)
        self.signals: list[dict] = []      # wykryte sygnały + status egzekucji
        self._sent: dict[tuple, float] = {}  # (ticker, direction) -> ts, deduplikacja
        self._last_analyzed_len = 0
        self._stop = threading.Event()
        self.capture = LiveCapture(
            event.get("stream_url") or event.get("url"),
            lang=lang,
            chunk_seconds=int(params.get(chunk_key, 5 if self.hot else 8)),
            whisper_model=params.get("live_whisper_model", "small"),
            on_text=self._on_text,
            log_name=event.get("title", "event"))
        self._nlp_thread = threading.Thread(target=self._nlp_loop,
                                            name=f"live-nlp-{self.id}", daemon=True)

    def start(self):
        self.capture.start()
        self._nlp_thread.start()

    def stop(self):
        self._stop.set()
        self.capture.stop()

    @property
    def running(self) -> bool:
        return self.capture.status["running"] or self._nlp_thread.is_alive()

    def _on_text(self, text: str, ts: float):
        self.transcript.append({"t": ts, "text": text})

    def _window_text(self, seconds: int) -> str:
        cutoff = time.time() - seconds
        parts = [c["text"] for c in self.transcript if c["t"] >= cutoff]
        return " ".join(parts)[-4000:]

    def _nlp_loop(self):
        last_run = time.time()
        while not self._stop.is_set():
            params = load_params()
            key = "live_analyze_seconds_hot" if self.hot else "live_analyze_seconds"
            interval = max(4, int(params.get(key, 6 if self.hot else 12)))
            
            now = time.time()
            sleep_time = interval - (now - last_run)
            if sleep_time > 0:
                steps = max(1, int(sleep_time * 2))
                for _ in range(steps):
                    if self._stop.is_set():
                        return
                    time.sleep(0.5)
            
            last_run = time.time()
            if len(self.transcript) == self._last_analyzed_len:
                if not self.capture.status["running"]:
                    return   # stream się skończył i nie ma nic nowego
                continue
            self._last_analyzed_len = len(self.transcript)
            window = self._window_text(int(params.get("live_window_seconds", 90)))
            if len(window.strip()) < 25:
                continue
            recent = [f"{s['ticker']} {s['direction']}" for s in self.signals[-5:]]
            t0 = time.time()
            res = nlp.analyze_window(self.event, window, recent)
            res["ts"] = time.strftime("%H:%M:%S")
            res["took_s"] = round(time.time() - t0, 1)
            self.analyses.append(res)
            self.analyses = self.analyses[-200:]
            if res.get("signal_detected") and res.get("ticker"):
                self._handle_signal(res, window, params)

    def _handle_signal(self, res: dict, window: str, params: dict):
        ticker = str(res["ticker"]).upper()
        direction = "short" if str(res.get("direction", "")).upper() == "SELL" else "long"
        cooldown = float(params.get("live_signal_cooldown_minutes", 5)) * 60
        key = (ticker, direction)
        if time.time() - self._sent.get(key, 0) < cooldown:
            return
        self._sent[key] = time.time()

        conf = float(res.get("confidence") or 0)
        threshold = float(params.get("live_confidence_threshold", 0.85))
        # stary klucz live_auto_trade zostaje jako zapas, żeby istniejące params.json działały
        auto = params.get("live_auto_analyze", params.get("live_auto_trade", False))
        sig_entry = {"ts": time.strftime("%H:%M:%S"), "ticker": ticker,
                     "direction": res.get("direction"), "confidence": conf,
                     "event_type": res.get("event_type"),
                     "reasoning": res.get("reasoning"), "quote": res.get("quote"),
                     "executed": False, "exec_why": ""}

        # sygnał w formacie analyzer-a — feed panelu go rozumie
        signal = {"tradable": True, "signal_type": "direct",
                  "news_type": "political_statement", "strength": int(conf * 100),
                  "targets": [{"ticker": ticker, "direction": direction, "weight": 1.0,
                               "size": "large", "why": res.get("reasoning", "")}],
                  "ticker": ticker, "direction": direction,
                  "reason": res.get("reasoning", ""), "_model": res.get("_model")}
        result = {"action": "skipped", "why": ""}

        if conf < threshold:
            result["why"] = f"pewność {conf:.2f} < próg {threshold:.2f} — tylko alert"
        elif not auto:
            result["why"] = "pogłębiona analiza fragmentów live wyłączona — tylko alert"
        else:
            try:
                import runner
                quote_text = res.get("quote") or window[-200:]
                title = self.event.get('title', 'LIVE')
                post = {
                    "text": f"[LIVE AUDIO: {title}] {quote_text} (Wstępna analiza: {res.get('reasoning')})",
                    "source": "live_stream",
                    "_age_seconds": 0
                }
                if runner._executor:
                    runner._executor.submit(runner.handle_post, post, params)
                else:
                    import threading
                    threading.Thread(target=runner.handle_post, args=(post, params), daemon=True).start()
                
                result = {"action": "forwarded", "why": "Przekazano do głównego analizatora w panelu"}
                sig_entry["executed"] = True
            except Exception as e:
                result = {"action": "error", "why": f"Błąd przekazania: {str(e)[:200]}"}
        sig_entry["exec_why"] = result.get("why", "")
        self.signals.append(sig_entry)

        quote = res.get("quote") or window[-200:]
        state.log_signal({
            "post": f"🎙 [{self.event.get('title', '')[:80]}] „{quote[:180]}”",
            "signal": signal,
            "decision": "FORWARDED" if result.get("action") == "forwarded" else ("SHORT" if direction == "short" else "BUY"),
            "source": "live_event", "result": result,
            "latency": f"analiza {res.get('took_s', '?')} s",
        })

    def to_dict(self, transcript_after: int = 0, analyses_after: int = 0) -> dict:
        return {
            "id": self.id, "event": self.event, "running": self.running,
            "capture": dict(self.capture.status),
            "log_path": self.capture.log_path,
            "transcript_len": len(self.transcript),
            "analyses_len": len(self.analyses),
            "transcript": [{"t": time.strftime("%H:%M:%S", time.localtime(c["t"])),
                            "text": c["text"]}
                           for c in self.transcript[transcript_after:]],
            "analyses": self.analyses[analyses_after:],
            "signals": self.signals[-30:],
        }


# ----------------------------------------------------------------- sterowanie

def start_session(event_id: str) -> dict:
    with _lock:
        existing = _sessions.get(event_id)
        if existing and existing.running:
            return {"started": False, "why": "sesja już działa"}
        events = cal.load_events()
        ev = events.get(event_id)
        if not ev:
            return {"started": False, "why": "wydarzenie nie istnieje"}
        if not (ev.get("stream_url") or ev.get("url")):
            return {"started": False, "why": "wydarzenie nie ma URL streamu — dodaj go (✎)"}
        deps = deps_status()
        if not deps["ready"]:
            missing = ", ".join(k for k, v in deps.items() if k != "ready" and not v)
            return {"started": False, "why": f"brakuje zależności: {missing} "
                    f"(pip install -r requirements.txt + ffmpeg w PATH; "
                    f"jeśli już zainstalowane — zrestartuj bota)"}
        sess = LiveEventSession(ev)
        _sessions[event_id] = sess
        sess.start()
        log.info("Sesja live wystartowała: %s", ev.get("title"))
        return {"started": True}


def stop_session(event_id: str) -> bool:
    sess = _sessions.get(event_id)
    if not sess:
        return False
    sess.stop()
    return True


def get_session(event_id: str) -> "LiveEventSession | None":
    return _sessions.get(event_id)


def sessions_overview() -> list[dict]:
    out = []
    for s in _sessions.values():
        d = s.to_dict(transcript_after=len(s.transcript), analyses_after=len(s.analyses))
        d["transcript"] = []
        d["analyses"] = []
        out.append(d)
    return out


# ------------------------------------------------------------------- monitor

def _monitor_loop():
    last_fda = 0.0
    next_check: dict[str, float] = {}    # channel_id -> kiedy sprawdzić następnym razem
    start_attempts: dict[str, float] = {}  # event_id -> ostatnia próba (backoff)
    log.info("Monitor wydarzeń live wystartował.")
    while _monitor_running.is_set():
        params = load_params()
        try:
            # 1) FDA + zaplanowane streamy kanałów + porządki — co 30 min
            if time.time() - last_fda > 1800:
                last_fda = time.time()
                cal.prune_old_events()
                try:
                    added = cal.refresh_fda()
                    up = cal.refresh_upcoming()
                    fomc_added = cal.refresh_fomc()
                    _monitor_status["last_fda_refresh"] = time.time()
                    if added or up or fomc_added:
                        log.info("Kalendarz: +%d FDA, +%d zaplanowanych streamów, +%d FOMC", added, up, fomc_added)
                except Exception as e:
                    _monitor_status["last_error"] = f"kalendarz: {e}"

            # 2) kanały YouTube z włączonym nasłuchem.
            # Adaptacyjne tempo: kanały ⚡ (Trump/FDA lub flaga hot) sprawdzamy co
            # live_poll_seconds_hot (domyślnie 15 s), resztę co live_poll_seconds.
            hot_poll = max(10, int(params.get("live_poll_seconds_hot", 15)))
            norm_poll = max(20, int(params.get("live_poll_seconds", 45)))
            checks = dict(_monitor_status.get("channel_checks") or {})
            now = time.time()
            for ch in cal.load_channels():
                if not ch.get("watch"):
                    checks.pop(ch["id"], None)
                    continue
                if now < next_check.get(ch["id"], 0):
                    continue
                hot = ch.get("hot") or ch.get("category") in cal.HOT_CATEGORIES
                next_check[ch["id"]] = now + (hot_poll if hot else norm_poll)
                res = cal.check_channel_live(ch.get("handle", ""))
                checks[ch["id"]] = {**res, "checked_at": time.time(), "hot": hot}
            _monitor_status["channel_checks"] = checks
            went_live = cal.sync_channel_events(checks)
            for ev in went_live:
                if ev.get("tracked"):
                    r = start_session(ev["id"])
                    log.info("Kanał wszedł LIVE: %s -> autostart: %s", ev["title"], r)

            # 3) śledzone wydarzenia z URL-em, których godzina nadeszła
            # (backoff 120 s — webcast bywa dostępny kilka minut po planowanym starcie)
            today = time.strftime("%Y-%m-%d")
            now_hhmm = time.strftime("%H:%M")
            for ev in cal.events_for_day(today):
                if not ev.get("tracked") or ev.get("status") == "ended":
                    continue
                sess = _sessions.get(ev["id"])
                if sess and (sess.running or sess.capture.status["stage"] == "ended"):
                    continue
                if not (ev.get("stream_url") or "").strip():
                    continue
                if ev.get("time") and ev["time"] > now_hhmm:
                    continue
                if time.time() - start_attempts.get(ev["id"], 0) < 120:
                    continue
                start_attempts[ev["id"]] = time.time()
                r = start_session(ev["id"])
                if r.get("started"):
                    log.info("Autostart wydarzenia %s (%s)", ev["title"], ev.get("time"))

            _monitor_status["last_poll"] = time.time()
        except Exception as e:
            log.exception("Monitor live: błąd pętli — kontynuuję")
            _monitor_status["last_error"] = str(e)[:200]

        # pętla kręci się szybko (rytm nadają terminy per kanał w next_check)
        for _ in range(20):   # ~10 s
            if not _monitor_running.is_set():
                break
            time.sleep(0.5)
    log.info("Monitor wydarzeń live zatrzymany.")


def monitor_start() -> bool:
    global _monitor_thread
    if _monitor_running.is_set():
        return False
    _monitor_running.set()
    _monitor_status.update(running=True, last_error=None)
    _monitor_thread = threading.Thread(target=_monitor_loop, name="live-monitor", daemon=True)
    _monitor_thread.start()
    return True


def monitor_stop() -> bool:
    if not _monitor_running.is_set():
        return False
    _monitor_running.clear()
    _monitor_status["running"] = False
    return True


def monitor_status() -> dict:
    return dict(_monitor_status)
