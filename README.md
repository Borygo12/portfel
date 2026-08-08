# Portevo — portfel inwestycyjny, dane spółek i nasłuch wiadomości

Aplikacja dla inwestora indywidualnego. Pokazuje, co masz w portfelu i jak sobie radzi,
prześwietla spółki i fundusze, pilnuje kalendarza wyników, a w tle nasłuchuje wiadomości
z rynku i ocenia, w którą stronę mogą przesunąć kurs.

**Portevo niczego nie kupuje ani nie sprzedaje.** Nie łączy się z brokerem, nie składa zleceń
i nie wydaje rekomendacji inwestycyjnych. To narzędzie do obserwacji i analizy — decyzje
zostają po Twojej stronie.

---

## Z czego się składa

| Część | Co robi |
|---|---|
| **Portfel** | Import raportów z konta maklerskiego (XTB), wycena w PLN, wykres wartości, koszty, podatki, pozycje zamknięte |
| **Spółki** | Wyszukiwarka światowa, fundamenty, wskaźniki, lista obserwowanych |
| **Earnings** | Kalendarz wyników kwartalnych (świat + GPW) i wydarzeń makro |
| **ETF** | Skaner funduszy, prześwietlenie składu, porównywarka |
| **Analizy premium** | Ryzyko i koncentracja, korelacje, ekspozycja walutowa, symulator „co jeśli" |
| **Nasłuch wiadomości** | Zbiera newsy z kilku źródeł i ocenia ich wydźwięk dla konkretnych spółek |
| **Wystąpienia na żywo** | Transkrypcja transmisji na żywo i wyłapywanie z nich istotnych informacji |
| **Mózg AI** | Edytowalne prompty i kategorie wiadomości — sterowanie tym, jak AI ocenia newsy |
| **Konta i premium** | Logowanie przez Supabase (Google / e-mail), katalog funkcji spod kłódki |

Interfejs mieszka w **osobnym repozytorium aplikacji** (Expo — jeden kod na telefon
i na przeglądarkę). To repozytorium zawiera serwer danych: liczy, zbiera i udostępnia
wszystko przez API.

---

## Nasłuch wiadomości — jak to działa

Bot chodzi w pętli po źródłach, a każdą nową wiadomość oddaje do AI, która odpowiada na
jedno pytanie: **czy to jest istotne dla jakiejś spółki i w którą stronę może pchnąć kurs.**
Wynik trafia do feedu w aplikacji jako sygnał informacyjny — z tickerem, oczekiwanym
wydźwiękiem i siłą 0–100. Nic więcej się z nim nie dzieje.

Źródła:

- **GPW / ESPI** (`sources/gpw_espi.py`) — komunikaty cenotwórcze polskich spółek
  (odpowiednik amerykańskiego 8-K) z darmowego feedu bankier.pl, z polskim kontekstem.
- **KNF** (`sources/knf_registry.py`, `sources/knf_announcements.py`) — rejestr krótkiej
  sprzedaży (przez mirror shorty.pl) oraz komunikaty i decyzje regulatora.
- **SEC EDGAR** (`sources/sec_edgar.py`) — raporty bieżące spółek amerykańskich.
- **Truth Social** (`sources/truth_social.py`) — posty Trumpa (przez ScrapeCreators).
- **Squawk i rządowe RSS** (`sources/squawk.py`, `sources/gov_rss.py`) — agregatory nagłówków.
- **Monitor sitemap** (`sources/sitemap_monitor.py`) — eksperyment: nowe podstrony na
  witrynach spółek potrafią wyprzedzić oficjalny komunikat.
- **Wystąpienia na żywo** (`live/`) — yt-dlp + ffmpeg pobierają dźwięk transmisji,
  faster-whisper transkrybuje go lokalnie, a AI czyta transkrypcję z kontekstem wydarzenia.

### Skuteczność zamiast obietnic

`outcomes.py` zapisuje, jaki wydźwięk przypisano wiadomości, a potem sprawdza w danych
notowań, jak faktycznie zachował się kurs w kolejnych godzinach. Dzięki temu aplikacja
pokazuje liczbę („na tylu analizach kurs poszedł we wskazaną stronę"), a nie deklarację.

---

## Struktura (`bot/`)

| Plik / katalog | Rola |
|---|---|
| `dashboard.py` | serwer danych (FastAPI, port 8500) — całe API aplikacji |
| `runner.py` | sterowalna pętla nasłuchu: start/stop w wątku tła |
| `main.py` | uruchomienie samej pętli, bez serwera (np. w tle) |
| `analyzer.py` | ocena wiadomości przez AI (OpenRouter, zapasowo Anthropic) |
| `prompts.py` + `prompts.json` | prompty i kategorie wiadomości — edytowalne z aplikacji na żywo |
| `strategy.py` | pamięć wzmianek o spółce i godziny sesji giełdowych |
| `outcomes.py` | weryfikacja: co kurs zrobił po analizie |
| `config.py` + `params.json` | parametry nasłuchu — zmieniane z aplikacji bez restartu |
| `state.py` | wspólny stan bota i serwera (feed analiz, heartbeat) |
| `portfolio/` | konta maklerskie: import, wycena, ceny, koszty, wykresy |
| `earnings/` | kalendarz wyników i wydarzeń makro |
| `etf/` | katalog i prześwietlenie funduszy |
| `live/` | wystąpienia na żywo: kalendarz, przechwytywanie dźwięku, transkrypcja, analiza |
| `sources/` | źródła wiadomości (jedno źródło = jeden plik) |
| `premium.py` | katalog funkcji premium — jedno źródło prawdy dla apki i strony |
| `supabase_auth.py`, `supabase_sync.py`, `account_api.py` | konta, uprawnienia, synchronizacja ustawień |
| `allocation_pro.py` | analizy premium: ryzyko, korelacje, symulacje |
| `gpw_tickers.py` | mapa najpłynniejszych spółek GPW (nazwa → ticker) |

---

## Uruchomienie

```bash
pip install -r bot/requirements.txt
```

```bash
cd bot && copy .env.example .env
```

Uzupełnij klucze w `.env`, a potem:

```bash
python bot/dashboard.py
```

Serwer wstaje na `http://localhost:8500`. Pod `/` zobaczysz stronę statusu z adresem
i tokenem do podłączenia telefonu. Nasłuch wiadomości włącza się z aplikacji; można go też
uruchomić osobno przez `python bot/main.py`.

Moduł wystąpień na żywo ma osobne, cięższe zależności — instaluje się go tylko tam,
gdzie ma naprawdę działać:

```bash
pip install -r bot/requirements-live.txt
```

Wymaga też **ffmpeg** (Windows: `winget install ffmpeg`). Bot znajdzie go również
w `%LOCALAPPDATA%\ffmpeg\bin`, bez dodawania do PATH. W chmurze tego nie
instalujemy — transkrypcja na CPU byłaby najdroższą pozycją rachunku.

## Konta, dane i rozdział użytkowników

Portevo jest wielokontowe. Zasada, na której to stoi: **rozdziału danych pilnuje
baza, nie kod aplikacji.**

Każda tabela z danymi użytkownika ma w Supabase kolumnę `user_id` z domyślną
wartością `auth.uid()` i politykę RLS. Serwer łączy się rolą `authenticated`
i podaje tożsamość zalogowanego w `request.jwt.claims` ([db.py](bot/db.py)), więc
`select * from cash_ops` — bez żadnego `WHERE` — zwraca wyłącznie wiersze
pytającego. Zapomniany filtr w kodzie nie jest w stanie odsłonić cudzego portfela.

Co jest wspólne, a co prywatne:

| Wspólne dla wszystkich | Prywatne (RLS) |
|---|---|
| `price_cache`, `price_meta`, `instrument_meta` | `accounts`, `cash_ops`, `closed_positions`, `watchlist` |
| feed analiz newsów, kalendarz wyników, dane spółek | ustawienia konta, uprawnienia premium |

Notowania pobierają się **raz dla wszystkich** — dlatego dwudziestu użytkowników
kosztuje niewiele więcej niż jeden. Bot newsowy działa tak samo: jedna pętla
analizuje post raz, a wynik trafia do wspólnego feedu.

### Role kont

| Rola | Skąd | Co daje |
|---|---|---|
| `user` | domyślnie po rejestracji | funkcje darmowe, premium po wykupieniu |
| `dev` | `select public.grant_dev('adres@email');` | premium bez płacenia **oraz** przełącznik podglądu wersji bez premium |
| `owner` | zmienna `OWNER_EMAIL` | jak `dev` plus sterowanie botem |

Konto `dev` służy do testów obu wariantów interfejsu. Aplikacja wysyła nagłówek
`X-Premium-View: off`, a serwer honoruje go **tylko** dla dev i ownera — dla
zwykłego konta jest ignorowany, więc nie da się nim nadać sobie premium.
Odebranie: `select public.revoke_dev('adres@email');`

## Wdrożenie na Railway

Repozytorium jest gotowe do podpięcia: [Dockerfile](Dockerfile) buduje obraz bez
modułu `/live` (~250 MB zamiast ~1,5 GB), a [railway.json](railway.json) ustawia
health-check i restarty.

**1. Baza.** W Supabase → SQL Editor uruchom po kolei
`supabase/migrations/0001_auth_premium_sync.sql`, potem `0002_portfolio_multiuser.sql`.

**2. Przeniesienie dotychczasowych danych** (jednorazowo, z komputera):

```bash
python bot/migrate_sqlite_to_supabase.py --email twoj@email.pl --dry-run
```

Skrypt tylko czyta stary plik SQLite. Bez `--dry-run` zapisuje.

**3. Railway** → New Project → Deploy from GitHub → to repozytorium. W zakładce
Variables wklej zmienne z [bot/.env.example](bot/.env.example) — wymagane są
`SUPABASE_DB_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`,
`OWNER_EMAIL`, `PANEL_API_TOKEN` oraz klucz do analizy AI.

**4. Dysk.** Dodaj Volume zamontowany pod `/data` — tam lądują parametry nasłuchu,
feed analiz i token. Bez dysku aplikacja wstanie, ale te pliki wrócą do domyślnych
po każdym wdrożeniu.

**5. Supabase → Authentication → URL Configuration** — dopisz adres z Railway do
Redirect URLs, inaczej logowanie Google wróci pod `localhost`.

Od tej pory każdy push na `main` buduje i wdraża nową wersję.

Zmienna `PORTEVO_CLOUD=1` (ustawiona w Dockerfile) włącza wymóg logowania także dla
połączeń lokalnych — w chmurze „localhost" to adres proxy hostingu, więc zaufanie
mu byłoby dziurą.

## Klucze w `.env`

| Klucz | Skąd | Do czego |
|---|---|---|
| `SUPABASE_DB_URL` | Supabase → Database → Transaction pooler | baza (wymagane) |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | Supabase → API | logowanie (wymagane) |
| `SUPABASE_SERVICE_KEY` | Supabase → API | uprawnienia i role — **tylko serwer** |
| `OWNER_EMAIL` | Twój adres | konto właściciela |
| `PANEL_API_TOKEN` | wymyślasz sam | połączenie telefonu bez logowania |
| `OPENROUTER_API_KEY` | openrouter.ai → Keys | analiza wiadomości |
| `SCRAPECREATORS_API_KEY` | scrapecreators.com | Truth Social |
| `QUIVER_API_KEY` | api.quiverquant.com | transakcje kongresmenów (planowane) |

Dane portfela i notowania pochodzą z darmowych źródeł (Yahoo Finance, Nasdaq, NBP,
Eurostat, FXStreet) i nie wymagają kluczy.

---

## Zastrzeżenie

Portevo służy do obserwacji rynku i porządkowania własnych danych. Nie jest doradztwem
inwestycyjnym ani rekomendacją w rozumieniu przepisów o obrocie instrumentami finansowymi.
Oceny wydźwięku wiadomości generuje model językowy i bywają błędne. Za decyzje inwestycyjne
odpowiada wyłącznie użytkownik.
