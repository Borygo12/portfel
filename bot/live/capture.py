"""Capture & STT — audio ze streamu na żywo -> tekst, lokalnie i za darmo.

Pipeline: yt-dlp (rozwiązuje URL streamu, np. manifest HLS z YouTube/Rumble/webcastu)
-> ffmpeg (dekoduje do surowego PCM 16 kHz mono na stdout)
-> faster-whisper (lokalna transkrypcja chunków co N sekund).

Wszystko w wątkach (spójnie z resztą bota). Ciężkie zależności (yt_dlp,
faster_whisper) importowane leniwie — panel działa nawet bez nich, a UI
pokazuje czego brakuje (deps_status()).
"""

import logging
import os
import shutil
import subprocess
import threading
import time

log = logging.getLogger("live.capture")

import paths

LOGS_DIR = os.path.join(paths.DATA_DIR, "live_logs")

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2  # PCM s16le mono

_whisper_model = None
_whisper_name = None
_whisper_lock = threading.Lock()


def find_ffmpeg() -> str | None:
    """ffmpeg z PATH albo z typowych lokalizacji (świeża instalacja nie jest
    widoczna w PATH procesów uruchomionych przed nią)."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.environ.get("FFMPEG_PATH", ""),
        os.path.join(local, "ffmpeg", "bin", "ffmpeg.exe"),
        os.path.join(local, "Microsoft", "WinGet", "Links", "ffmpeg.exe"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
    ]
    # winget instaluje paczkę Gyan.FFmpeg do katalogu z wersją w nazwie
    winget_pkgs = os.path.join(local, "Microsoft", "WinGet", "Packages")
    try:
        import glob
        candidates += glob.glob(os.path.join(winget_pkgs, "Gyan.FFmpeg*", "ffmpeg-*", "bin", "ffmpeg.exe"))
    except OSError:
        pass
    for cand in candidates:
        if cand and os.path.exists(cand):
            # dopisz do PATH procesu — yt-dlp i ewentualne podprocesy też go zobaczą
            os.environ["PATH"] = os.path.dirname(cand) + os.pathsep + os.environ.get("PATH", "")
            return cand
    return None


def deps_status() -> dict:
    """Co jest zainstalowane — pokazywane w UI, żeby owner wiedział co doinstalować."""
    out = {"ffmpeg": bool(find_ffmpeg())}
    for mod in ("yt_dlp", "faster_whisper", "numpy"):
        try:
            __import__(mod)
            out[mod] = True
        except ImportError:
            out[mod] = False
    out["ready"] = all(out.values())
    return out


def _get_whisper(model_name: str):
    """Jeden model whispera na proces (ładowanie trwa i zjada RAM)."""
    global _whisper_model, _whisper_name
    with _whisper_lock:
        if _whisper_model is None or _whisper_name != model_name:
            from faster_whisper import WhisperModel
            log.info("Ładuję faster-whisper '%s' (pierwszy raz = pobranie modelu)...", model_name)
            # CPU domyślnie: "auto" wybiera CUDA nawet bez bibliotek cuBLAS i wywala się
            # przy transkrypcji. Masz GPU + CUDA 12? Ustaw LIVE_WHISPER_DEVICE=cuda w .env.
            device = os.environ.get("LIVE_WHISPER_DEVICE", "cpu")
            _whisper_model = WhisperModel(model_name, device=device, compute_type="int8")
            _whisper_name = model_name
    return _whisper_model


def resolve_stream_url(page_url: str) -> str:
    """yt-dlp zamienia URL strony (YouTube/Rumble/webcast) na bezpośredni URL audio."""
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "format": "bestaudio/best",
            "noplaylist": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(page_url, download=False)
    if info.get("url"):
        return info["url"]
    for f in (info.get("formats") or [])[::-1]:
        if f.get("url") and (f.get("acodec") not in (None, "none")):
            return f["url"]
    raise RuntimeError("yt-dlp nie znalazł strumienia audio pod tym URL")


class LiveCapture:
    """Jedna sesja nasłuchu: stream -> transkrypcja -> callback z tekstem.

    on_text(text: str, ts: float) wołany po każdym przetranskrybowanym chunku.
    """

    def __init__(self, stream_page_url: str, *, lang: str | None = None,
                 chunk_seconds: int = 8, whisper_model: str = "small",
                 on_text=None, log_name: str = "session"):
        self.page_url = stream_page_url
        self.lang = lang if lang in ("pl", "en") else None  # None = autodetekcja
        self.chunk_seconds = max(3, int(chunk_seconds))
        self.whisper_model = whisper_model
        self.on_text = on_text
        self.status = {"running": False, "stage": "idle", "error": None,
                       "started_at": None, "seconds_captured": 0, "last_text_at": None}
        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        os.makedirs(LOGS_DIR, exist_ok=True)
        safe = "".join(c if c.isalnum() else "_" for c in log_name)[:60]
        self.log_path = os.path.join(
            LOGS_DIR, f"{time.strftime('%Y-%m-%d_%H%M%S')}_{safe}.log")

    # ------------------------------------------------------------- lifecycle

    def start(self):
        if self.status["running"]:
            return
        self._stop.clear()
        self.status.update(running=True, stage="starting", error=None,
                           started_at=time.time())
        self._thread = threading.Thread(target=self._run, name="live-capture", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
            except OSError:
                pass

    # ------------------------------------------------------------------ core

    def _log(self, line: str):
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {line}\n")
        except OSError:
            pass

    def _run(self):
        try:
            self.status["stage"] = "resolving_url"
            audio_url = resolve_stream_url(self.page_url)
            self._log(f"[capture] URL rozwiązany: {self.page_url}")

            self.status["stage"] = "loading_whisper"
            model = _get_whisper(self.whisper_model)

            self.status["stage"] = "capturing"
            # ffmpeg czyta HLS/DASH natywnie; -re nie jest potrzebne dla live
            cmd = [find_ffmpeg() or "ffmpeg", "-loglevel", "error", "-i", audio_url,
                   "-f", "s16le", "-acodec", "pcm_s16le",
                   "-ac", "1", "-ar", str(SAMPLE_RATE), "-"]
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

            chunk_bytes = self.chunk_seconds * BYTES_PER_SECOND
            buf = b""
            while not self._stop.is_set():
                data = self._proc.stdout.read(BYTES_PER_SECOND)  # ~1 s na iterację
                if not data:
                    if self._proc.poll() is not None:
                        break   # stream się skończył
                    time.sleep(0.2)
                    continue
                buf += data
                self.status["seconds_captured"] += len(data) / BYTES_PER_SECOND
                if len(buf) >= chunk_bytes:
                    self._transcribe(model, buf[:chunk_bytes])
                    buf = buf[chunk_bytes:]
            if buf and not self._stop.is_set():
                self._transcribe(model, buf)
            self.status["stage"] = "ended"
        except Exception as e:
            log.exception("Sesja capture padła")
            self.status["error"] = str(e)[:300]
            self.status["stage"] = "error"
            self._log(f"[capture] BŁĄD: {e}")
        finally:
            self.stop()
            self.status["running"] = False

    def _transcribe(self, model, pcm: bytes):
        import numpy as np
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        try:
            segments, _info = model.transcribe(
                audio, language=self.lang, beam_size=1,
                vad_filter=True, vad_parameters={"min_silence_duration_ms": 400})
            text = " ".join(s.text.strip() for s in segments).strip()
        except Exception as e:
            log.warning("Whisper: błąd transkrypcji chunku: %s", e)
            return
        if not text:
            return
        self.status["last_text_at"] = time.time()
        self._log(f"[stt] {text}")
        if self.on_text:
            try:
                self.on_text(text, time.time())
            except Exception:
                log.exception("Callback on_text rzucił wyjątek")
