"""Parametry strategii — współdzielone między botem a dashboardem przez params.json.

Bot czyta parametry na początku każdej iteracji pętli, dashboard zapisuje je
po zmianie suwaka — zmiany działają na żywo, bez restartu bota.

Suwaki główne (panel /) i zaawansowane (podstrona /settings).
"""

import json
import os

PARAMS_FILE = os.path.join(os.path.dirname(__file__), "params.json")

DEFAULTS = {
    # --- główne wyłączniki ---
    "trading_enabled": False,   # False = tryb obserwacji: bot analizuje i loguje, NIE otwiera pozycji
    "kill_switch": False,       # True = natychmiast zamknij wszystko i nic nie otwieraj

    # --- aktywne konto brokera (suwak w panelu) ---
    # saxo_demo | saxo_live | xm_demo | xm_live
    "active_account": "saxo_live",
    # bot newsowy NIE startuje sam — czeka na START w panelu (ikona pulpitu
    # otwiera najpierw ekran wyboru: Portfel / Bot)
    "autostart_monitoring": False,

    # --- AGRESYWNOŚĆ (główny suwak ryzyka ownera) ---
    # 0-100: skaluje wielkość KAŻDEJ pozycji (0 -> x0.4, 50 -> x1.0, 100 -> x1.6).
    # Wysoko = gramy grubo (mały kapitał, dużo do ugrania). Owner zmniejsza przy większych wpłatach.
    "aggressiveness": 80,

    # --- filtr sygnałów ---
    "min_signal_strength": 70,  # 0-100; poniżej progu post jest ignorowany

    # --- weryfikacja etapu 2 (mocny płatny model sprawdza trade po wejściu) ---
    "verify_enabled": True,

    # --- wielkość pozycji i dźwignia (baza, mnożona przez mnożniki strategii) ---
    "position_pct_of_equity": 15,
    "max_leverage": 3,
    "max_open_positions": 4,    # tematyczne sygnały otwierają do 3 pozycji naraz

    # --- wyjście z pozycji ---
    "take_profit_pct": 6.0,
    "stop_loss_pct": 3.0,
    "max_hold_hours": 6,        # zamknij po N godzinach (pozycje z ręczną flagą "trzymaj" pomijane)
    "runaway_tp_pct": 25,       # ruch na plus >= N% -> auto take-profit (chyba że "trzymaj")
    "priced_in_hours": 4,       # po ilu godzinach uznajemy informację za w 100% wycenioną (wskaźnik w UI)
    "volatility_scaling": True, # TP/SL skalowane zmiennością spółki (ATR) zamiast sztywnych progów

    # --- korekta "news już wyceniony" ---
    "already_priced_move_pct": 10,        # duża spółka: ruch >= N% dziś = news pewnie wyceniony
    "already_priced_move_pct_small": 25,  # bardzo mała spółka rusza się mocniej -> wyższy próg
    "already_priced_weight": 0.5,         # po przekroczeniu progu graj tym ułamkiem wielkości

    # --- sygnały tematyczne (sektor bez nazwy spółki: kwanty, drony, złoto, bitcoin...) ---
    "thematic_enabled": True,
    "thematic_size_factor": 0.35,   # każda z max 3 pozycji tematycznych = ułamek normalnej wielkości

    # --- sygnały makro (wojna / szok dla całego rynku -> US100 short/long) ---
    "macro_enabled": True,
    "macro_size_factor": 0.5,

    # --- pamięć wzmianek (Trump chwali Della 4. raz w tygodniu -> słabszy sygnał) ---
    "repeat_mention_decay": True,

    # --- bezpieczniki ---
    "daily_loss_limit_pct": 5.0,

    # --- źródła sygnałów ---
    "truth_social_enabled": True,
    "sec_edgar_enabled": True,   # raporty 8-K (zdarzenia bieżące) + 10-Q
    "sec_edgar_10q": False,      # dołącz też raporty kwartalne 10-Q (więcej szumu)
    "squawk_enabled": True,      # darmowy agregator Terminala Bloomberga (TreeNews)
    "gov_rss_enabled": True,     # RSS Departamentu Stanu USA, OFAC, itp.
    "gpw_espi_enabled": True,    # raporty ESPI/EBI spółek GPW (polski odpowiednik 8-K)
    "sitemap_enabled": False,    # eksperymentalny SEO sitemap monitor (wymaga uzupełnionej watchlisty)
    "knf_enabled": True,         # rejestr krótkiej sprzedaży KNF (mirror: shorty.pl) — short squeeze / smart money
    "knf_ann_enabled": True,     # komunikaty i decyzje KNF (kary, cofnięcia licencji) — oficjalny RSS knf.gov.pl

    # --- wystąpienia na żywo (podstrona /live) ---
    "live_auto_trade": False,           # True = sygnały z live idą do brokera (wymaga też trading_enabled)
    "live_confidence_threshold": 0.85,  # minimalna pewność AI do egzekucji
    "live_whisper_model": "base",       # tiny/base/small/medium — jakość vs szybkość CPU i miejsce na dysku
    "live_chunk_seconds": 8,            # co ile sekund audio -> tekst
    "live_window_seconds": 90,          # okno transkrypcji wysyłane do AI
    "live_analyze_seconds": 12,         # co ile sekund analiza AI
    "live_poll_seconds": 45,            # co ile sekund sprawdzanie, czy kanały weszły LIVE
    # tryb ⚡ (wydarzenia priorytetowe: Trump, FDA) — wszystko szybciej
    "live_chunk_seconds_hot": 5,        # krótsze chunki = tekst szybciej na ekranie
    "live_analyze_seconds_hot": 6,      # częstsza analiza AI
    "live_poll_seconds_hot": 15,        # częstszy live-check gorących kanałów
    "live_signal_cooldown_minutes": 5,  # nie powtarzaj sygnału na ten sam ticker+kierunek

    # --- polling / świeżość ---
    "truth_social_poll_seconds": 5,
    "squawk_poll_seconds": 5,     # TreeNews ma nowe nagłówki w kilka sekund
    "sec_poll_seconds": 20,       # EDGAR aktualizuje się ~co minutę, nie trzeba częściej
    "gov_rss_poll_seconds": 60,   # Rządowe RSS rzadziej się aktualizują
    "gpw_espi_poll_seconds": 15,  # PAP (dystrybutor ESPI) publikuje w chwili raportu; pytamy często, by alert był natychmiast
    "sitemap_poll_seconds": 3600, # sitemap.xml sprawdzamy raz na godzinę — nie ma sensu częściej
    "knf_poll_seconds": 300,      # shorty.pl odświeża dane z KNF co ~15 min, pytamy częściej na zapas
    "knf_max_age_minutes": 60,    # graj tylko zdarzenia z rejestru młodsze niż to
    "knf_ann_poll_seconds": 180,  # komunikaty/decyzje KNF — 3 min, wolniejszy feed niż rejestr shortów
    "knf_ann_max_age_minutes": 120,
    "max_post_age_minutes": 10,
    "max_filing_age_minutes": 30, # 8-K bywa widoczne w feedzie kilka-kilkanaście min po złożeniu
    "max_gpw_age_minutes": 30,    # ESPI bywa w feedzie kilka-kilkanaście min po publikacji
}


def load_params() -> dict:
    params = dict(DEFAULTS)
    if os.path.exists(PARAMS_FILE):
        try:
            with open(PARAMS_FILE, encoding="utf-8") as f:
                params.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return params


def save_params(updates: dict):
    params = load_params()
    params.update({k: v for k, v in updates.items() if k in DEFAULTS})
    with open(PARAMS_FILE, "w", encoding="utf-8") as f:
        json.dump(params, f, indent=2, ensure_ascii=False)
    return params
