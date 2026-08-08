"""Kalendarz wydarzeń na żywo — darmowe źródła (bez płatnych API).

Trzy źródła wydarzeń:
1. Spotkania FDA Advisory Committee — oficjalne, darmowe API Federal Register
   (FDA ma prawny obowiązek publikować tam ogłoszenia o posiedzeniach, z datą
   i godziną; strona kalendarza FDA renderuje się JS-em i nie da się jej scrapować).
2. Kanały YouTube (Trump/RSBN, Biały Dom, NATO, Polska...) — sprawdzanie strony
   https://youtube.com/@handle/live pod kątem flagi "isLiveNow" (RSS YouTube NIE ma
   znacznika live, dlatego używamy strony /live — też darmowa, bez API).
3. Wydarzenia dodane ręcznie przez ownera z panelu (tytuł + godzina + URL streamu).

Stan trzymamy w plikach JSON (jak params.json) — panel i bot widzą to samo.
"""

import html as html_lib
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta

import requests

log = logging.getLogger("live.calendar")

import paths

# lista wydarzeń zmienia się w trakcie pracy -> katalog danych;
# katalog kanałów jest częścią kodu i jedzie razem z wdrożeniem
EVENTS_FILE = paths.data_path("live_events.json")
CHANNELS_FILE = os.path.join(paths.BOT_DIR, "live_channels.json")

FEDREG_API = "https://www.federalregister.gov/api/v1/documents.json"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,pl;q=0.8",
}
# YouTube bez zgody na cookies przekierowuje na consent.youtube.com — to ciastko to omija
_YT_COOKIES = {"CONSENT": "YES+cb", "SOCS": "CAI"}

CATEGORIES = ("fda", "trump", "usa_gov", "europe", "poland", "manual")

# priorytet ⚡ — te kategorie dostają szybszy nasłuch (krótsze chunki, częstsza analiza,
# częstsze sprawdzanie kanałów). Owner może przełączyć priorytet per wydarzenie w UI.
HOT_CATEGORIES = ("trump", "fda")


def default_priority(category: str) -> str:
    return "high" if category in HOT_CATEGORIES else "normal"

# Startowa lista kanałów — owner edytuje z panelu (dodaj/usuń/włącz nasłuch).
# handle = adres youtube.com/@handle. Jeśli handle się nie zgadza, panel pokaże błąd
# przy sprawdzaniu i wystarczy poprawić w UI.
DEFAULT_CHANNELS = [
    {"id": "rsbn",      "name": "RSBN — wiece Trumpa",        "handle": "@RSBN",               "category": "trump",   "lang": "en", "watch": True},
    {"id": "whitehouse", "name": "Biały Dom (oficjalny)",      "handle": "@WhiteHouse",         "category": "usa_gov", "lang": "en", "watch": True},
    {"id": "foxnews",   "name": "Fox News",                    "handle": "@FoxNews",            "category": "trump",   "lang": "en", "watch": False},
    {"id": "livenow",   "name": "LiveNOW from FOX",            "handle": "@livenowfox",         "category": "usa_gov", "lang": "en", "watch": False},
    {"id": "nato",      "name": "NATO",                        "handle": "@NATO",               "category": "europe",  "lang": "en", "watch": True},
    {"id": "ecaudio",   "name": "Komisja Europejska",          "handle": "@EuropeanCommission", "category": "europe",  "lang": "en", "watch": False},
    {"id": "sejm",      "name": "Sejm RP",                     "handle": "@SejmRP_PL",          "category": "poland",  "lang": "pl", "watch": False},
    {"id": "premierpl", "name": "Kancelaria Premiera RP",      "handle": "@premierrp",          "category": "poland",  "lang": "pl", "watch": False},
    {"id": "nbp",       "name": "Narodowy Bank Polski",        "handle": "@NarodowyBankPolski", "category": "poland",  "lang": "pl", "watch": False},
]


# ---------------------------------------------------------------- pliki stanu

def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_channels() -> list[dict]:
    channels = _load_json(CHANNELS_FILE, None)
    if channels is None:
        channels = [dict(c) for c in DEFAULT_CHANNELS]
        _save_json(CHANNELS_FILE, channels)
    return channels


def save_channels(channels: list[dict]):
    _save_json(CHANNELS_FILE, channels)


def load_events() -> dict:
    """{event_id: event}. Event:
    {id, date 'YYYY-MM-DD', time 'HH:MM'|None, title, category, source,
     url (strona wydarzenia), stream_url (do yt-dlp), status scheduled|live|ended,
     tracked bool, channel_id|None, note}"""
    return _load_json(EVENTS_FILE, {})


def save_events(events: dict):
    _save_json(EVENTS_FILE, events)


def upsert_event(ev: dict) -> dict:
    events = load_events()
    events[ev["id"]] = ev
    save_events(events)
    return ev


def set_tracked(event_id: str, tracked: bool) -> bool:
    events = load_events()
    if event_id not in events:
        return False
    events[event_id]["tracked"] = tracked
    save_events(events)
    return True


def add_manual_event(title: str, date: str, hhmm: str | None,
                     stream_url: str, category: str = "manual") -> dict:
    category = category if category in CATEGORIES else "manual"
    ev = {
        "id": "man_" + uuid.uuid4().hex[:10],
        "date": date, "time": hhmm or None,
        "title": title.strip()[:200],
        "category": category,
        "source": "manual", "url": stream_url, "stream_url": stream_url,
        "status": "scheduled", "tracked": True, "channel_id": None, "note": "",
        "priority": default_priority(category),
    }
    return upsert_event(ev)


def delete_event(event_id: str) -> bool:
    events = load_events()
    if events.pop(event_id, None) is None:
        return False
    save_events(events)
    return True


def events_for_day(date: str | None = None) -> list[dict]:
    date = date or time.strftime("%Y-%m-%d")
    evs = [e for e in load_events().values() if e.get("date") == date]
    evs.sort(key=lambda e: ((e.get("time") or "99:99"), e.get("title", "")))
    return evs


def prune_old_events(keep_days: int = 7):
    """Usuń wydarzenia starsze niż N dni — plik nie rośnie w nieskończoność."""
    cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    events = load_events()
    pruned = {k: v for k, v in events.items() if (v.get("date") or "9999") >= cutoff}
    if len(pruned) != len(events):
        save_events(pruned)


# ------------------------------------------------------- YouTube live-check

def check_channel_live(handle: str) -> dict:
    """Sprawdza, czy kanał nadaje na żywo. Zwraca:
    {live: bool, video_id, title, watch_url, error}."""
    handle = handle.strip()
    if not handle.startswith("@") and "youtube.com" not in handle:
        handle = "@" + handle
    url = handle if handle.startswith("http") else f"https://www.youtube.com/{handle}/live"
    out = {"live": False, "video_id": None, "title": None, "watch_url": None, "error": None}
    try:
        r = requests.get(url, headers=_HEADERS, cookies=_YT_COOKIES, timeout=12)
        if r.status_code == 404:
            out["error"] = "kanał nie istnieje (sprawdź handle)"
            return out
        html = r.text
        # YouTube osadza JSON playera w HTML — szukamy flag zamiast parsować całość.
        # UWAGA: sama "isLive":true pojawia się też przy ZAPLANOWANYCH streamach
        # (poczekalnia) — trwającą transmisję oznacza dopiero "isLiveNow":true.
        is_live = '"isLiveNow":true' in html and '"isUpcoming":true' not in html
        m_id = re.search(r'"videoId":"([\w-]{11})"', html)
        m_title = re.search(r'<meta name="title" content="([^"]{1,300})"', html)
        if is_live and m_id:
            out.update(live=True, video_id=m_id.group(1),
                       title=(html_lib.unescape(m_title.group(1)) if m_title else None),
                       watch_url=f"https://www.youtube.com/watch?v={m_id.group(1)}")
    except requests.RequestException as e:
        out["error"] = str(e)[:200]
    return out


def _video_start_timestamp(video_id: str) -> float | None:
    """Dokładny czas startu zaplanowanego streamu ze strony filmu
    ("startTimestamp":"2026-07-08T13:00:00+00:00" w liveBroadcastDetails)."""
    try:
        r = requests.get(f"https://www.youtube.com/watch?v={video_id}",
                         headers=_HEADERS, cookies=_YT_COOKIES, timeout=12)
        m = re.search(r'"startTimestamp":"([^"]{10,40})"', r.text)
        if m:
            return datetime.fromisoformat(m.group(1)).timestamp()
    except (requests.RequestException, ValueError):
        pass
    return None


def fetch_channel_upcoming(handle: str) -> list[dict]:
    """ZAPLANOWANE streamy kanału (zakładka /streams) — daje kalendarz na jutro/pojutrze,
    zanim transmisja w ogóle się zacznie. Zwraca [{video_id, title, start_ts}].

    Layout YT (2026): kafelki to "lockupViewModel", zaplanowany stream ma w metadanych
    tekst "Scheduled for ..." (strefa niejednoznaczna), więc dokładny czas dociągamy
    ze strony filmu (startTimestamp, ISO z UTC)."""
    handle = handle.strip()
    if not handle.startswith("@"):
        handle = "@" + handle
    r = requests.get(f"https://www.youtube.com/{handle}/streams",
                     headers=_HEADERS, cookies=_YT_COOKIES, timeout=12)
    if r.status_code != 200:
        return []
    r.encoding = "utf-8"
    out = []
    for chunk in r.text.split('"lockupViewModel":{')[1:]:
        if "Scheduled for" not in chunk:
            continue
        if '"badgeText":"Members only"' in chunk:
            continue   # stream tylko dla członków — i tak się nie podepniemy
        m_id = re.search(r'"contentId":"([\w-]{11})"', chunk)
        m_title = re.search(r'"title":\{"content":"((?:[^"\\]|\\.){1,300}?)"', chunk)
        if not m_id:
            continue
        start_ts = _video_start_timestamp(m_id.group(1))
        if not start_ts:
            continue
        title = None
        if m_title:
            try:   # grupa to treść JSON-owego stringa — json.loads poprawnie odkoduje \uXXXX
                title = json.loads(f'"{m_title.group(1)}"')
            except json.JSONDecodeError:
                title = m_title.group(1)
        out.append({"video_id": m_id.group(1),
                    "title": html_lib.unescape(title) if title else None,
                    "start_ts": start_ts})
    return out


def refresh_upcoming(days_ahead: int = 3) -> int:
    """Dociąga zaplanowane streamy WSZYSTKICH kanałów z listy do kalendarza.
    Zwraca liczbę nowych wydarzeń. Id = yt_<kanał>_<videoId> — to samo id, które
    dostanie wydarzenie po wejściu w LIVE, więc flaga 'śledź' przetrwa start streamu."""
    events = load_events()
    added = 0
    horizon = time.time() + days_ahead * 86400
    for ch in load_channels():
        try:
            upcoming = fetch_channel_upcoming(ch.get("handle", ""))
        except requests.RequestException as e:
            log.warning("Upcoming %s: %s", ch.get("handle"), e)
            continue
        for up in upcoming:
            if not (time.time() - 3600 < up["start_ts"] < horizon):
                continue
            ev_id = f"yt_{ch['id']}_{up['video_id']}"
            if ev_id in events:   # nie nadpisuj — owner mógł zmienić tracked/priorytet
                continue
            lt = time.localtime(up["start_ts"])
            events[ev_id] = {
                "id": ev_id,
                "date": time.strftime("%Y-%m-%d", lt), "time": time.strftime("%H:%M", lt),
                "title": up["title"] or f"Zaplanowany stream: {ch['name']}",
                "category": ch.get("category", "manual"), "source": "youtube_upcoming",
                "url": f"https://www.youtube.com/watch?v={up['video_id']}",
                "stream_url": f"https://www.youtube.com/watch?v={up['video_id']}",
                "status": "scheduled", "tracked": False, "channel_id": ch["id"],
                "note": f"zaplanowany stream kanału {ch['name']}",
                "priority": default_priority(ch.get("category", "manual")),
            }
            added += 1
    save_events(events)
    return added


AI_SEARCH_SYSTEM = """Jesteś researcherem tradingowym. Przeszukujesz internet w poszukiwaniu
NADCHODZĄCYCH wydarzeń NA ŻYWO (dziś i najbliższe dni), które mogą poruszyć rynki:
- wystąpienia/wiece/konferencje Donalda Trumpa i administracji USA (Biały Dom, FED, sekretarze). KRYTYCZNE: Odrzucaj zamknięte spotkania bilateralne (bilateral meetings)!,
- FED/FOMC: decyzje o stopach, konferencje, publikacje protokołów (minutes), wystąpienia członków,
- kluczowe publikacje makro USA (CPI, NFP, PKB) z dokładną godziną,
- posiedzenia FDA advisory committee / decyzje o lekach spółek biotech (z datą PDUFA),
- szczyty i konferencje NATO / UE / EBC,
- wydarzenia polskie: decyzje RPP/NBP, expose, konferencje rządu, dane GUS.

Podawaj TYLKO wydarzenia z konkretną datą, które na 100% będą miały TRANSMISJĘ WIDEO/AUDIO NA ŻYWO. 
KRYTYCZNE: Ignoruj zamknięte spotkania dyplomatyczne, obiady i rozmowy bilateralne, z których nie ma strumienia na żywo.
KAŻDE wydarzenie musi być POTWIERDZONE w znalezionym źródle — zawsze podaj source_url.
BARDZO WAŻNE: Zweryfikuj DOKŁADNIE, że data faktycznie jest przyszła lub dzisiejsza (dziś to data podana przez usera). Pomyłka o jeden dzień to błąd krytyczny.
MAKSYMALNIE 10 najważniejszych wydarzeń. Zwięźle — pola po 1 zdaniu.

Odpowiedz WYŁĄCZNIE JSON:
{"events": [{"title": str,               // krótko, po polsku
             "date": "YYYY-MM-DD",
             "time_warsaw": "HH:MM"|null, // czas polski, jeśli znany
             "category": "trump"|"fda"|"usa_gov"|"europe"|"poland",
             "why_markets": str,          // 1 zdanie: czemu to rusza rynek
             "stream_hint": str|null,     // gdzie szukać transmisji (kanał/strona), jeśli wiadomo
             "source_url": str|null}]}"""

SEARCH_MODEL = os.environ.get("LIVE_SEARCH_MODEL", "google/gemini-2.5-flash:online")


def ai_discover_events(days_ahead: int = 2) -> dict:
    """Przycisk „szukaj w internecie”: model z web-searchem (sufiks :online na OpenRouter)
    znajduje wydarzenia na dziś + days_ahead dni i dopisuje je do kalendarza."""
    from analyzer import _call   # leniwie — wspólny klient OpenRouter

    today = time.strftime("%Y-%m-%d")
    horizon = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    user = (f"Dziś jest {today} ({time.strftime('%A')}). Znajdź wydarzenia na żywo istotne "
            f"dla rynków od {today} do {horizon} włącznie. Sprawdź też, gdzie w tych dniach "
            f"będzie Donald Trump (harmonogram prezydenta USA).")
    out = _call(SEARCH_MODEL, AI_SEARCH_SYSTEM, user, max_tokens=4000, req_timeout=90)

    events = load_events()
    added = 0
    for e in (out.get("events") or [])[:25]:
        date, title = e.get("date"), (e.get("title") or "").strip()
        if not title or not date or not (today <= date <= horizon):
            continue
        cat = e.get("category") if e.get("category") in CATEGORIES else "manual"
        ev_id = "ai_" + re.sub(r"\W+", "", (date + title.lower()))[:48]
        if ev_id in events:
            continue
        note = e.get("why_markets") or ""
        if e.get("stream_hint"):
            note += f" | transmisja: {e['stream_hint']}"
        events[ev_id] = {
            "id": ev_id, "date": date, "time": e.get("time_warsaw") or None,
            "title": title[:200], "category": cat, "source": "ai_search",
            "url": e.get("source_url"), "stream_url": None,
            "status": "scheduled", "tracked": False, "channel_id": None,
            "note": note[:300], "priority": default_priority(cat),
        }
        added += 1
    save_events(events)
    return {"added": added, "found": len(out.get("events") or []), "model": out.get("_model")}


AI_ENRICH_SYSTEM = """Jesteś researcherem tradingowym. Dostajesz listę wydarzeń z kalendarza
nasłuchu (wystąpienia na żywo istotne dla rynków). Dla KAŻDEGO wydarzenia sprawdź w internecie:
1. czy to wydarzenie NA PEWNO ma/będzie miało transmisję na żywo? Jeśli to zamknięte spotkanie (np. "bilateral meeting") bez transmisji -> oznacz akcję "delete".
2. dokładną godzinę startu (czas warszawski) — jeśli w kalendarzu brak lub jest nieprecyzyjna,
3. URL transmisji na żywo (konkretny link YouTube watch?v=... / webcast), jeśli już istnieje;
   jeśli nie ma jeszcze linku — napisz w watch_where, GDZIE transmisja się pojawi.
4. kontekst tradingowy (context): 2-4 zdania po polsku — co się będzie działo, jakie spółki/
   tickery/sektory mogą zostać poruszone, na jakie słowa/decyzje uważać, jaka jest stawka rynkowa.

DUPLIKATY: jeśli dwa wpisy opisują TO SAMO wydarzenie (np. dwa razy to samo spotkanie Trumpa
z różnych źródeł), zgrupuj ich id w "duplicates". Zwracaj szczególną uwagę na wydarzenia o tej samej godzinie. Nie grupuj różnych wydarzeń tego samego dnia.

Odpowiedz WYŁĄCZNIE JSON:
{"duplicates": [["id_a","id_b"], ...],
 "updates": [{"id": str,                  // id z listy wejściowej — NIE wymyślaj nowych
              "action": "keep"|"delete",  // ustaw "delete" jeśli to zamknięte spotkanie bez szans na stream
              "time_warsaw": "HH:MM"|null, // tylko jeśli znalazłeś pewną godzinę
              "stream_url": str|null,      // tylko realny, istniejący link do transmisji
              "watch_where": str|null,     // gdzie szukać transmisji, jeśli link jeszcze nie istnieje
              "context": str|null}]}"""


def ai_enrich_events(dates: list[str]) -> dict:
    """Drugi etap researchu: wysyła obecne wydarzenia do modelu z web-searchem,
    który doprecyzowuje godziny, szuka URL-i streamów, dodaje kontekst tradingowy
    i wykrywa duplikaty. Zmiany zapisuje do kalendarza."""
    from analyzer import _call

    events = load_events()
    batch = [e for e in events.values() if e.get("date") in dates
             and e.get("status") != "ended"][:20]
    if not batch:
        return {"updated": 0, "merged": 0, "why": "brak wydarzeń do doprecyzowania"}

    lines = []
    for e in batch:
        lines.append(f'- id={e["id"]} | {e["date"]} {e.get("time") or "godzina nieznana"} | '
                     f'[{e["category"]}] {e["title"]} | '
                     f'stream_url: {"JEST" if e.get("stream_url") else "BRAK"} | '
                     f'notatka: {(e.get("note") or "")[:120]}')
    user = (f"Dziś jest {time.strftime('%Y-%m-%d %H:%M')} (czas warszawski).\n"
            f"WYDARZENIA DO DOPRECYZOWANIA:\n" + "\n".join(lines))
    out = _call(SEARCH_MODEL, AI_ENRICH_SYSTEM, user, max_tokens=6000, req_timeout=120)

    # 1) scal duplikaty — zostaje wpis "najbogatszy" (kanał/stream > śledzony > pierwszy)
    merged = 0
    for group in (out.get("duplicates") or []):
        group = [g for g in group if g in events]
        if len(group) < 2:
            continue
        group.sort(key=lambda i: (bool(events[i].get("channel_id") or events[i].get("stream_url")),
                                  bool(events[i].get("tracked"))), reverse=True)
        keeper = events[group[0]]
        for other_id in group[1:]:
            other = events.pop(other_id)
            keeper["tracked"] = keeper.get("tracked") or other.get("tracked")
            if other.get("priority") == "high":
                keeper["priority"] = "high"
            keeper["time"] = keeper.get("time") or other.get("time")
            keeper["stream_url"] = keeper.get("stream_url") or other.get("stream_url")
            extra = (other.get("note") or "").strip()
            if extra and extra not in (keeper.get("note") or ""):
                keeper["note"] = ((keeper.get("note") or "") + " | " + extra)[:400]
            merged += 1

    # 2) nanieś doprecyzowania
    updated = 0
    deleted = 0
    for up in (out.get("updates") or []):
        if up.get("action") == "delete":
            events.pop(up.get("id"), None)
            deleted += 1
            continue
            
        ev = events.get(up.get("id"))
        if not ev:
            continue
        changed = False
        t = up.get("time_warsaw")
        if t and re.fullmatch(r"\d{2}:\d{2}", str(t)) and not ev.get("time"):
            ev["time"] = t
            changed = True
        u = up.get("stream_url")
        if u and str(u).startswith("http") and not ev.get("stream_url"):
            ev["stream_url"] = str(u).strip()
            changed = True
        if up.get("watch_where"):
            hint = f"transmisja: {up['watch_where']}"
            if hint not in (ev.get("note") or ""):
                ev["note"] = ((ev.get("note") or "") + " | " + hint).strip(" |")[:400]
                changed = True
        if up.get("context"):
            ev["context"] = str(up["context"])[:900]   # trafia do promptu analizy live
            changed = True
        updated += changed
    save_events(events)
    return {"updated": updated, "deleted": deleted, "merged": merged, "sent": len(batch),
            "model": out.get("_model")}


def sync_channel_events(now_live: dict[str, dict]) -> list[dict]:
    """Na podstawie wyników live-checków tworzy/aktualizuje wydarzenia w kalendarzu.

    now_live: {channel_id: wynik check_channel_live}
    Zwraca listę wydarzeń, które WŁAŚNIE przeszły w stan live (do autostartu sesji).
    """
    channels = {c["id"]: c for c in load_channels()}
    events = load_events()
    today = time.strftime("%Y-%m-%d")
    went_live = []

    for ch_id, res in now_live.items():
        ch = channels.get(ch_id)
        if not ch:
            continue
        ev_id = f"yt_{ch_id}_{res.get('video_id') or today}"
        if res.get("live"):
            existing = events.get(ev_id)
            ev = existing or {
                "id": ev_id, "date": today, "time": time.strftime("%H:%M"),
                "title": res.get("title") or f"LIVE: {ch['name']}",
                "category": ch.get("category", "manual"), "source": "youtube",
                "url": res.get("watch_url"), "stream_url": res.get("watch_url"),
                # kanał z włączonym nasłuchem = owner już wybrał, że go śledzimy
                "tracked": bool(ch.get("watch")), "channel_id": ch_id, "note": "",
                "priority": default_priority(ch.get("category", "manual")),
            }
            if ev.get("status") != "live":
                ev["status"] = "live"
                if not existing or ev.get("tracked"):
                    went_live.append(ev)
            events[ev["id"]] = ev
        else:
            # kanał przestał nadawać -> zamknij jego dzisiejsze live-wydarzenia
            for ev in events.values():
                if ev.get("channel_id") == ch_id and ev.get("status") == "live":
                    ev["status"] = "ended"

    save_events(events)
    return went_live


# ------------------------------------------------------------ FOMC calendar

FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"


def fetch_fomc_events() -> list[dict]:
    """Posiedzenia FOMC + publikacje protokołów (minutes) ze strony Fed.

    Strona ma bloki <div class="fomc-meeting"> z miesiącem ("January" albo
    "April/May" przy posiedzeniu na przełomie miesięcy) i dniami ("27-28").
    Rok bierzemy z nagłówka sekcji "2026 FOMC Meetings".
    Generujemy dwa wydarzenia na posiedzenie:
    - dzień decyzji (2. dzień): komunikat 14:00 ET + konferencja prasowa 14:30 ET,
    - protokół (minutes): zawsze 3 tygodnie po decyzji, 14:00 ET — to publikacja
      dokumentu (bez transmisji), ale rynek reaguje natychmiast.
    """
    r = requests.get(FOMC_URL, headers=_HEADERS, timeout=20)
    r.raise_for_status()
    out = []
    parts = re.split(r"(\d{4})\s+FOMC\s+Meetings", r.text)
    for i in range(1, len(parts) - 1, 2):
        year = int(parts[i])
        for m in re.finditer(
                r'fomc-meeting__month[^>]*>(.*?)</div>\s*'
                r'<div[^>]*fomc-meeting__date[^>]*>(.*?)</div>', parts[i + 1], re.S):
            months = re.findall(r"[A-Za-z]+", re.sub(r"<[^>]+>", " ", m.group(1)))
            date_txt = re.sub(r"<[^>]+>", " ", m.group(2))
            if "unscheduled" in date_txt.lower() or "cancelled" in date_txt.lower():
                continue
            days = re.findall(r"\d{1,2}", date_txt)
            end_month = _MONTHS.get((months or [""])[-1].lower())
            if not end_month or not days:
                continue
            try:
                decision = datetime(year, end_month, int(days[-1]))
            except ValueError:
                continue
            dec_date = decision.strftime("%Y-%m-%d")
            span = "-".join(days)
            out.append({
                "id": f"fomc_{dec_date}_decision",
                "date": dec_date,
                "time": _et_to_local_hhmm("2:00", "p.m.", dec_date),
                "title": f"FOMC: decyzja o stopach + konferencja prasowa "
                         f"(posiedzenie {span} {months[-1]})"[:250],
                "category": "usa_gov", "source": "fomc",
                "url": FOMC_URL,
                "stream_url": "https://www.youtube.com/@federalreserve/live",
                "status": "scheduled", "tracked": False, "channel_id": None,
                "note": "Komunikat 14:00 ET, pół godziny później konferencja przewodniczącego "
                        "Fed na YouTube @federalreserve. Rusza USD, indeksy, złoto, obligacje.",
                "priority": "high",
            })
            minutes = decision + timedelta(days=21)
            min_date = minutes.strftime("%Y-%m-%d")
            out.append({
                "id": f"fomc_{min_date}_minutes",
                "date": min_date,
                "time": _et_to_local_hhmm("2:00", "p.m.", min_date),
                "title": f"FOMC: protokół posiedzenia (minutes) z {span} {months[-1]}"[:250],
                "category": "usa_gov", "source": "fomc",
                "url": FOMC_URL, "stream_url": None,
                "status": "scheduled", "tracked": False, "channel_id": None,
                "note": "Publikacja dokumentu o 14:00 ET — BEZ transmisji na żywo (nie ma "
                        "czego nasłuchiwać), ale rynek reaguje natychmiast: USD, indeksy, "
                        "złoto, rentowności. Szczegóły dyskusji o ścieżce stóp.",
                "priority": "high",
            })
    return out


def refresh_fomc(days_ahead: int = 90) -> int:
    """Dociąga posiedzenia i protokoły FOMC do kalendarza. Zwraca liczbę nowych."""
    today = time.strftime("%Y-%m-%d")
    horizon = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    events = load_events()
    added = 0
    for ev in fetch_fomc_events():
        if not (today <= ev["date"] <= horizon):
            continue
        if ev["id"] in events:   # nie nadpisuj — owner mógł zmienić tracked/stream_url
            continue
        events[ev["id"]] = ev
        added += 1
    save_events(events)
    return added


# ------------------------------------------------------------- FDA calendar

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}


def _parse_us_date(text: str) -> str | None:
    """'June 26, 2026' / 'June 26 - 27, 2026' -> '2026-06-26'."""
    m = re.search(r"([A-Za-z]+)\.?\s+(\d{1,2})(?:\s*[-–]\s*\d{1,2})?,?\s+(\d{4})", text)
    if not m:
        return None
    month = _MONTHS.get(m.group(1).lower())
    if not month:
        return None
    try:
        return datetime(int(m.group(3)), month, int(m.group(2))).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _et_to_local_hhmm(hhmm_et: str, ampm: str, date: str) -> str | None:
    """'10:00' + 'a.m.' czasu wschodniego USA -> godzina lokalna (HH:MM)."""
    try:
        h, m = (hhmm_et.split(":") + ["0"])[:2]
        h = int(h) % 12 + (12 if "p" in ampm.lower() else 0)
        dt = datetime(*[int(x) for x in date.split("-")], h, int(m))
        try:
            from zoneinfo import ZoneInfo
            dt = dt.replace(tzinfo=ZoneInfo("America/New_York")).astimezone()
        except Exception:
            dt = dt + timedelta(hours=6)   # ET -> Polska (zwykle +6h), gdy brak tzdata
        return dt.strftime("%H:%M")
    except (ValueError, IndexError):
        return None


def fetch_fda_meetings() -> list[dict]:
    """Nadchodzące posiedzenia FDA Advisory Committee z API Federal Register.
    Sekcja DATES ogłoszenia zawiera datę i godzinę, np.
    'The meeting will be held on July 29, 2026, from 10:00 a.m. to 4:30 p.m. Eastern Time.'"""
    params = {
        "per_page": 40, "order": "newest",
        "conditions[agencies][]": "food-and-drug-administration",
        "conditions[type][]": "NOTICE",
        "conditions[term]": '"notice of meeting" "advisory committee"',
        "fields[]": ["title", "publication_date", "html_url", "dates"],
    }
    r = requests.get(FEDREG_API, params=params, headers=_HEADERS, timeout=20)
    r.raise_for_status()
    out = []
    for doc in r.json().get("results", []):
        title = doc.get("title") or ""
        if "notice of meeting" not in title.lower():
            continue
        dates_txt = doc.get("dates") or ""
        # godzina startu (pierwsza wzmianka "from 10:00 a.m." / "from 9 a.m.")
        m_time = re.search(r"from\s+(\d{1,2}(?::\d{2})?)\s*([ap]\.?m\.?)", dates_txt, re.I)
        # spotkanie może być wielodniowe — event na każdą datę
        for m_date in re.finditer(r"[A-Za-z]+\.?\s+\d{1,2},?\s+\d{4}", dates_txt):
            date = _parse_us_date(m_date.group(0))
            if not date:
                continue
            hhmm = _et_to_local_hhmm(m_time.group(1), m_time.group(2), date) if m_time else None
            committee = title.split(";")[0].strip()
            out.append({
                "id": "fda_" + re.sub(r"\W+", "", (date + committee))[:48].lower(),
                "date": date, "time": hhmm,
                "title": f"FDA: {committee}"[:250],
                "category": "fda", "source": "fda",
                "url": doc.get("html_url"), "stream_url": None,
                "status": "scheduled", "tracked": False, "channel_id": None,
                "note": "Webcast: link YouTube znajdziesz w ogłoszeniu (↗) lub na stronie FDA "
                        "w dniu spotkania — wklej go przyciskiem ✎.",
                "priority": default_priority("fda"),
            })
    return out


def refresh_fda(days_ahead: int = 45) -> int:
    """Dociąga spotkania FDA na najbliższe dni do kalendarza. Zwraca liczbę nowych."""
    today = time.strftime("%Y-%m-%d")
    horizon = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    try:
        meetings = fetch_fda_meetings()
    except Exception as e:
        log.warning("FDA calendar: scraping nieudany: %s", e)
        raise
    events = load_events()
    added = 0
    for m in meetings:
        if not (today <= m["date"] <= horizon):
            continue
        if m["id"] in events:   # nie nadpisuj — owner mógł zaznaczyć tracked / wkleić stream_url
            continue
        events[m["id"]] = m
        added += 1
    save_events(events)
    return added
