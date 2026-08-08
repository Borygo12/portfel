"""Źródło: SEO Sitemap Monitor — zarys (Moduł 4A ze "Speed-Bota").

Koncepcja: małe spółki (gamedev, biotech, tech) czasem publikują ukrytą podstronę
pod duże ogłoszenie ("/partnership-with-x/") kilka godzin/dni PRZED oficjalnym
komunikatem ESPI, ale strona jest już zaindeksowana w sitemap.xml. Co
`sitemap_poll_seconds` (domyślnie 3600s) pobieramy sitemap.xml każdej spółki
z watchlisty i diffujemy względem ostatnio zapisanego stanu — nowy URL = alarm.

To SPEKULACJA, nie potwierdzony fakt (patrz prompts.py, sekcja "polish" —
tag "[SITEMAP-PRZEDSYGNAŁ]" jest tam oceniany bardzo ostrożnie). Dlatego, w
odróżnieniu od reszty źródeł GPW, te zdarzenia NIGDY nie trafiają do
analyzer.fast_regex_filter() — zawsze idą przez normalną ocenę LLM.

KONFIGURACJA: uzupełnij sitemap_watchlist.json listą
  [{"name": "Nazwa Spółki", "ticker": "TIC", "sitemap_url": "https://.../sitemap.xml"}, ...]
Pusta lista (domyślnie) = moduł jest no-op. Nie zgadujemy URL-i za Ciebie — to
wymaga wiedzy, które małe spółki GPW warto obserwować.
"""

import hashlib
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone

import requests

log = logging.getLogger("sitemap_monitor")

import paths

_DIR = os.path.dirname(__file__)
# watchlista jest częścią kodu (edytowana ręcznie), stan narasta w trakcie pracy
WATCHLIST_FILE = os.path.join(_DIR, "sitemap_watchlist.json")
STATE_FILE = paths.data_path("sitemap_state.json")

_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _load_watchlist() -> list[dict]:
    try:
        with open(WATCHLIST_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def _load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError:
        log.warning("Nie udało się zapisać %s", STATE_FILE)


_MAX_SUB_SITEMAPS = 15   # limit rekursji dla dużych indeksów (WordPress/Yoast/AIOSEO)
_MAX_URLS_PER_SITE = 5000  # ponad to = katalog e-commerce, nie strona firmowa/PR (patrz niżej)


def _fetch_one(sitemap_url: str) -> tuple[list[str], bool]:
    """Zwraca (lista <loc>, czy_to_index). Index (<sitemapindex>) wskazuje na PODrzędne
    pliki sitemap (np. page-sitemap.xml), a nie realne podstrony — trzeba wejść głębiej."""
    r = requests.get(sitemap_url, headers=_HEADERS, timeout=10)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    tag = root.tag.rsplit("}", 1)[-1]
    locs = [loc.text.strip() for loc in root.findall(".//sm:loc", _SITEMAP_NS) if loc.text]
    return locs, tag == "sitemapindex"


def _fetch_urls(sitemap_url: str) -> set[str]:
    """Pobiera realne URL-e podstron. Wiele stron (zwłaszcza WordPress) publikuje pod
    /sitemap.xml INDEKS wskazujący na pod-sitemapy (page-sitemap.xml, post-sitemap.xml...)
    zamiast płaskiej listy — index sam w sobie prawie nigdy się nie zmienia (nowa
    podstrona ląduje w JEDNEJ z pod-sitemap, nie w indeksie), więc trzeba wejść rekurencyjnie."""
    top, is_index = _fetch_one(sitemap_url)
    if not is_index:
        return set(top)
    urls: set[str] = set()
    for sub_url in top[:_MAX_SUB_SITEMAPS]:
        try:
            sub_locs, _ = _fetch_one(sub_url)
            urls.update(sub_locs)
        except Exception as e:
            log.debug("Pod-sitemap %s niedostępny: %s", sub_url, e)
    return urls


_POLL_WORKERS = 12
_POLL_BUDGET_SECONDS = 45  # twardy limit czasu całego przebiegu (patrz niżej, dlaczego)

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def _looks_stale(url: str) -> bool:
    """Heurystyka: URL zawierający rok wyraźnie starszy niż ostatnie ~2 lata to
    prawie na pewno stara/archiwalna podstrona (dawny raport, stary komunikat),
    którą crawler/CMS dopiero teraz dorzucił do sitemap.xml — NIE świeża informacja.
    Bez tego np. dane finansowe za 2018 albo umowa z 2019 wyglądają jak "nowy news"
    tylko dlatego, że to MY zobaczyliśmy je pierwszy raz w sitemapie."""
    years = [int(m.group(0)) for m in _YEAR_RE.finditer(url)]
    if not years:
        return False
    current_year = datetime.now(timezone.utc).year
    return max(years) < current_year - 1


def _check_company(company: dict) -> tuple[str, str, set[str] | None, str | None]:
    """Zwraca (name, ticker, urls albo None przy błędzie, komunikat błędu albo None)."""
    name, ticker, url = company.get("name"), company.get("ticker"), company.get("sitemap_url")
    if not (name and ticker and url):
        return name or "?", ticker or "?", None, "niekompletny wpis w watchlist"
    try:
        return name, ticker, _fetch_urls(url), None
    except Exception as e:
        return name, ticker, None, str(e)[:150]


def fetch_new_sitemap_events(max_age_minutes: float | None = None) -> list[dict]:
    """Zwraca zdarzenia dla nowo wykrytych URL-i w sitemap.xml spółek z watchlisty.
    Pierwszy odczyt dla danego tickera to baseline (nie alarmuje) — patrz prime().

    Pobiera WSZYSTKIE spółki RÓWNOLEGLE (ThreadPoolExecutor) z twardym budżetem czasu
    (_POLL_BUDGET_SECONDS) — sekwencyjne pobieranie (jedna domena na raz, część z nich
    to indeksy z do 15 pod-sitemapami) potrafiło zablokować całą pętlę bota na wiele
    minut, gdy trafiła się martwa/wolna domena (DNS timeout, zawieszony serwer) — ta
    funkcja jest wołana SYNCHRONICZNIE wewnątrz runner._loop(), więc każda sekunda tutaj
    to sekunda, w której bot NIE sprawdza Truth Social/SEC/Squawk/KNF/ESPI."""
    watchlist = _load_watchlist()
    if not watchlist:
        return []
    state = _load_state()
    out = []
    now = datetime.now(timezone.utc)

    results: dict[str, tuple[str, set[str] | None, str | None]] = {}
    with ThreadPoolExecutor(max_workers=_POLL_WORKERS, thread_name_prefix="sitemap") as ex:
        futures = {ex.submit(_check_company, c): c for c in watchlist}
        try:
            for fut in as_completed(futures, timeout=_POLL_BUDGET_SECONDS):
                name, ticker, urls, err = fut.result()
                if ticker != "?":
                    results[ticker] = (name, urls, err)
        except FuturesTimeoutError:
            done = sum(1 for f in futures if f.done())
            log.warning("Sitemap poll: budżet %ds wyczerpany, %d/%d spółek nie zdążyło — "
                       "pomijam resztę w tym cyklu (nadrobią następnym razem)",
                       _POLL_BUDGET_SECONDS, len(futures) - done, len(futures))

    for ticker, (name, current, err) in results.items():
        if err is not None or current is None:
            log.debug("Sitemap %s (%s) niedostępny: %s", name, ticker, err)
            continue

        if len(current) > _MAX_URLS_PER_SITE:
            # duży e-commerce/katalog produktowy -> ciągły szum (setki tysięcy URL-i,
            # zmieniają się bez związku z komunikatami spółki), a nie strona firmowa/PR
            log.warning("Sitemap %s (%s) ma %d URL-i (limit %d) — pomijam jako nienadający się "
                       "do tego typu monitoringu, rozważ usunięcie z watchlisty",
                       name, ticker, len(current), _MAX_URLS_PER_SITE)
            continue

        known = set(state.get(ticker) or [])
        is_first_read = ticker not in state
        new_urls = current - known
        # WAŻNE: zapisujemy PEŁNY zbiór, bez ucinania — obcięcie tu psuje diff (znane
        # URL-e wypadały z zapisanego stanu i wracały jako "nowe" przy kolejnym pollu,
        # mimo że były stare). _MAX_URLS_PER_SITE (5000) już chroni przed rozrostem pliku.
        state[ticker] = list(current)

        if is_first_read or not new_urls:
            continue

        for new_url in new_urls:
            if _looks_stale(new_url):
                log.debug("Sitemap %s: pomijam jako stara podstrona (rok w URL): %s", name, new_url)
                continue
            uid = hashlib.md5(new_url.encode("utf-8")).hexdigest()[:10]
            text = f"[SITEMAP-PRZEDSYGNAŁ] {name} ({ticker}): nowa podstrona wykryta: {new_url}"
            out.append({
                "id": f"sitemap_{ticker}_{uid}",
                "text": text,
                "created_at": now.isoformat(),
                "_age_seconds": 0,
                "source": "gpw_espi",
                "url": new_url,
                "ticker": ticker,
            })
            log.info("Sitemap ALERT: %s -> %s", name, new_url)

    _save_state(state)
    return out


def check_connectivity() -> list[dict]:
    """Sprawdzenie na żądanie (panel /settings) — te same zapytania co poll, ale
    NIE zapisuje stanu i NIE generuje sygnałów. Tylko raport co działa, a co nie."""
    watchlist = _load_watchlist()
    if not watchlist:
        return []
    out = []
    with ThreadPoolExecutor(max_workers=_POLL_WORKERS, thread_name_prefix="sitemap-check") as ex:
        futures = {ex.submit(_check_company, c): c for c in watchlist}
        try:
            for fut in as_completed(futures, timeout=_POLL_BUDGET_SECONDS):
                name, ticker, urls, err = fut.result()
                out.append({"name": name, "ticker": ticker, "ok": err is None,
                           "url_count": len(urls) if urls is not None else 0,
                           "error": err})
        except FuturesTimeoutError:
            log.warning("Sitemap check_connectivity: budżet %ds wyczerpany", _POLL_BUDGET_SECONDS)
    return out


def prime():
    """Zasiewa baseline dla wszystkich spółek z watchlisty — nie alarmuje przy starcie."""
    try:
        fetch_new_sitemap_events()
    except Exception:
        log.exception("Sitemap prime() nieudane")
