# News Trader — bot tradingowy na newsach (Trump / Kongres)

Bot gra CFD na akcje (dźwignia) na podstawie sygnałów newsowych.
Broker (wybór w `.env`, `BROKER=saxo|mt5|capital`):
- **Saxo Bank OpenAPI** (`broker_saxo.py`) — **akcje GPW jako CFD** (dźwignia + short),
  krypto, akcje US/EU. Jedyny sprawdzony broker z realnym API na GPW; open/SL/TP/trailing/close
  przetestowane na SIM. Żywe ceny GPW wymagają subskrypcji danych WSE (parę €/mc).
- **dowolny z MetaTrader 5** (`broker_mt5.py`) — XM/Admirals/Pepperstone: akcje US/EU,
  bez GPW; krypto tylko przez indeks `Crypto_10#`.
- **Capital.com** (`broker_capital.py`).
- (`broker_xtb.py` istnieje, ale XTB wyłączył API dla klientów detalicznych w 03.2025.)

Sygnały:
- **Truth Social** — każdy nowy post Trumpa analizowany przez AI (Claude): ticker, kierunek (long/short), siła sygnału 0–100.
- **GPW / ESPI** (`sources/gpw_espi.py`) — komunikaty cenotwórcze polskich spółek (odpowiednik
  8-K) z darmowego feedu bankier.pl. Grane wg godzin GPW 9:00–17:00 — gdy USA jeszcze śpi,
  a konkurencja mniejsza. Analiza z polskim kontekstem (tickery GPW, realia rynku).
- **SEC EDGAR / Squawk / Gov RSS** — raporty 8-K, agregator nagłówków, rządowe RSS USA.
- **Wystąpienia na żywo (`/live`)** — nasłuch transmisji (FDA advisory committee, wiece Trumpa,
  Biały Dom, NATO, Polska): yt-dlp + ffmpeg → lokalna transkrypcja (faster-whisper) → analiza
  AI (OpenRouter) z kontekstem wydarzenia → sygnał BUY/SELL z pewnością 0–1.
- **Kongres (Quiver API)** — nowo publikowane transakcje polityków (faza 3, jeszcze nie podpięte).

## Struktura (`bot/`)

| Plik | Rola |
|---|---|
| `main.py` | pętla bota: polling Truth Social → analiza → decyzja → zlecenie |
| `analyzer.py` | ocena postów przez Claude API |
| `broker_saxo.py` | klient Saxo Bank OpenAPI (REST) — CFD na GPW, krypto, akcje US/EU |
| `broker_capital.py` | klient REST API Capital.com (sesja, ceny, pozycje, bracket SL/TP) |
| `trader.py` | silnik decyzyjny + bezpieczniki |
| `dashboard.py` + `panel.html` | panel operacyjny ownera (port 8500) |
| `config.py` + `params.json` | parametry strategii — edytowalne z panelu NA ŻYWO, bez restartu bota |
| `sources/truth_social.py` | polling postów Trumpa (ScrapeCreators) |
| `live/` + `live.html` | podstrona "Wystąpienia na żywo": kalendarz wydarzeń (FDA z Federal Register API, kanały YouTube, ręczne), monitor live-checków, sesje: audio → transkrypcja → AI → sygnał |

## Wystąpienia na żywo (`/live`)

1. **Kalendarz**: posiedzenia FDA Advisory Committee dociągane z darmowego API Federal Register
   (data + godzina, przeliczona na czas PL); kanały YouTube sprawdzane pod kątem `isLiveNow`
   przez `youtube.com/@handle/live` (bez API, bez opłat); wydarzenia ręczne z panelu.
2. **Wybór**: owner zaznacza "ŚLEDŹ" przy wydarzeniach na dziś (nie śledzimy wszystkiego —
   każda sesja to whisper na CPU).
3. **Sesja**: gdy stream startuje, monitor sam podpina yt-dlp + ffmpeg → faster-whisper
   transkrybuje lokalnie co ~8 s → AI (OpenRouter, `LIVE_MODEL`) analizuje okno transkrypcji
   z kontekstem wydarzenia (głosowania FDA, wzmianki o spółkach, geopolityka).
4. **Egzekucja**: sygnał z pewnością ≥ progu trafia do brokera TYLKO gdy włączysz
   "Auto-trade z live" ORAZ globalny tryb handlu; inaczej to alert w feedzie panelu.
   Transkrypcje i analizy lądują w `bot/live_logs/` (do backtestów i poprawy promptów).

Wymaga: `pip install -r bot/requirements.txt` + `ffmpeg` w PATH
(zainstalowany w `%LOCALAPPDATA%\ffmpeg\bin` — bot znajdzie go też bez PATH).

## Uruchomienie

```
pip install -r bot/requirements.txt
cd bot
copy .env.example .env    # i uzupełnij klucze
python dashboard.py       # panel: http://localhost:8500
python main.py            # bot (osobne okno/proces)
```

Bot startuje w **trybie obserwacji** (`trading_enabled: false`) — analizuje posty i pokazuje decyzje
w feedzie panelu, ale NIE otwiera pozycji, dopóki nie włączysz przełącznika "Trading włączony".

## Bezpieczniki (w silniku, nie do ominięcia suwakiem)

1. Stop-loss i take-profit w każdej pozycji po stronie brokera (działa gdy bot/VPS padnie).
2. Dzienny limit straty (domyślnie 5%) — bot zamyka wszystko i pauzuje do końca dnia.
3. Limit liczby otwartych pozycji.
4. Kill-switch w panelu: natychmiastowe zamknięcie wszystkiego + blokada tradingu.

## Klucze do `.env`

| Klucz | Skąd |
|---|---|
| `CAPITAL_API_KEY` / `CAPITAL_IDENTIFIER` / `CAPITAL_PASSWORD` | capital.com → Settings → API integrations |
| `CAPITAL_DEMO` | `true` = konto demo, `false` = live |
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `SCRAPECREATORS_API_KEY` | scrapecreators.com (Truth Social) |
| `QUIVER_API_KEY` | api.quiverquant.com — faza 3 |
