-- Powiadomienia: newsy o Twoich spółkach + kalendarz wyników.
--
-- Wklej całość w Supabase → SQL Editor → Run. Skrypt można puszczać wielokrotnie.
-- Wymaga 0001 (profiles, watchlist) i 0002 (cash_ops, RLS).
--
-- ZASADA JAK W CAŁEJ BAZIE: rozdziału danych pilnuje RLS, nie kod. Każda tabela
-- ma `user_id ... default auth.uid()` i politykę „widzisz i zmieniasz swoje".
-- Silnik powiadomień chodzi jednak BEZ zalogowanego użytkownika (leci w tle,
-- w reakcji na newsa), więc łączy się rolą serwisową — patrz `db.service_scope`.
-- Dlatego te tabele świadomie NIE mają nic wrażliwego poza treścią powiadomienia.

-- ======================================================== ustawienia powiadomień

create table if not exists public.notification_prefs (
  user_id        uuid primary key default auth.uid()
                 references auth.users (id) on delete cascade,

  -- Trzy stany z ekranu bota: 'off' | 'all' | 'strong'.
  -- Świadomie tekst, a nie bool: „nie / wszystko / tylko mocne" to jedno
  -- pytanie o trzech odpowiedziach, a nie dwa niezależne przełączniki.
  news_mode      text not null default 'off'
                 check (news_mode in ('off', 'all', 'strong')),

  -- Kalendarz wyników. Dwie różne rzeczy, więc dwa przełączniki:
  -- dzienne = „dziś raportuje spółka, którą masz", tygodniowe = poniedziałkowy przegląd.
  earnings_daily   boolean not null default true,
  earnings_weekly  boolean not null default true,

  -- Kanały dostarczenia. Skrzynka w aplikacji jest zawsze — te dwa dokładają
  -- powiadomienie systemowe na telefonie i e-mail (głównie dla przeglądarki).
  push_enabled   boolean not null default true,
  email_enabled  boolean not null default false,

  -- Kiedy pytaliśmy o zgodę na e-mail. NULL = jeszcze nie pytaliśmy, więc
  -- aplikacja ma pokazać pytanie po zalogowaniu. Dzięki temu „nie, dziękuję"
  -- jest zapamiętane i nie wraca przy każdym uruchomieniu.
  email_asked_at timestamptz,

  updated_at     timestamptz not null default now()
);

comment on table public.notification_prefs is
  'Co i jak wysyłać. Brak wiersza = domyślne wartości z tej definicji.';

alter table public.notification_prefs enable row level security;

do $$ begin
  create policy "swoje ustawienia powiadomien" on public.notification_prefs
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());
exception when duplicate_object then null; end $$;

-- ============================================================== tokeny do pusha

create table if not exists public.push_tokens (
  -- Token Expo (ExponentPushToken[...]) jest kluczem: to samo urządzenie po
  -- przelogowaniu ma trafić do nowego właściciela, a nie zostać u poprzedniego.
  token        text primary key,
  user_id      uuid not null default auth.uid()
               references auth.users (id) on delete cascade,
  platform     text default '',
  -- Expo odpowiada 'DeviceNotRegistered', gdy ktoś odinstalował aplikację.
  -- Wtedy kasujemy wiersz — inaczej wysyłka w nieskończoność puka w nieistniejące
  -- urządzenie i psuje statystyki dostarczeń.
  last_seen_at timestamptz not null default now(),
  created_at   timestamptz not null default now()
);

create index if not exists push_tokens_user_idx on public.push_tokens (user_id);

alter table public.push_tokens enable row level security;

do $$ begin
  create policy "swoje tokeny push" on public.push_tokens
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());
exception when duplicate_object then null; end $$;

-- ====================================================== skrzynka w aplikacji

create table if not exists public.notifications (
  id         bigserial primary key,
  user_id    uuid not null default auth.uid()
             references auth.users (id) on delete cascade,

  -- 'news' | 'earnings_today' | 'earnings_week'
  kind       text not null,
  title      text not null,
  body       text not null default '',
  -- symbol, którego dotyczy — aplikacja robi z tego przejście do karty spółki
  symbol     text default '',
  meta       jsonb,

  -- Klucz przeciw duplikatom. Ten sam news wpada do kilku źródeł naraz, a pętla
  -- bota potrafi zobaczyć go dwa razy; bez tego telefon dzwoni dwa razy o tym
  -- samym. Dla wyników dnia kluczem jest data + symbol, więc nawet restart
  -- serwera w środku dnia nie wyśle przypomnienia po raz drugi.
  dedup_key  text not null,

  read_at    timestamptz,
  created_at timestamptz not null default now()
);

create unique index if not exists notifications_dedup_idx
  on public.notifications (user_id, dedup_key);
create index if not exists notifications_user_idx
  on public.notifications (user_id, created_at desc);

alter table public.notifications enable row level security;

do $$ begin
  create policy "swoje powiadomienia" on public.notifications
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());
exception when duplicate_object then null; end $$;

-- ================================================= spółki, które kogoś obchodzą
--
-- Po co osobna tabela, skoro dane są w `watchlist` i `cash_ops`:
-- liczba akcji per spółka wychodzi dopiero z PRZEPARSOWANIA komentarzy operacji
-- (OPEN/CLOSE ... @ cena). Robienie tego dla wszystkich kont przy każdym newsie
-- oznaczałoby przeliczanie portfeli kilkadziesiąt razy na minutę.
--
-- Dlatego trzymamy tu gotowy wynik: „ten użytkownik ma / obserwuje ten symbol".
-- Odświeża się przy wejściu do aplikacji i raz na dobę przed wysyłką o wynikach.
-- To jest CACHE — źródłem prawdy zostają portfel i lista obserwowanych.

create table if not exists public.user_symbols (
  user_id    uuid not null default auth.uid()
             references auth.users (id) on delete cascade,
  symbol     text not null,
  -- 'position' = ma w portfelu, 'watch' = obserwuje. Pozycja jest ważniejsza,
  -- więc spółka trzymana w portfelu nie dubluje się jako obserwowana.
  relation   text not null default 'watch' check (relation in ('position', 'watch')),
  updated_at timestamptz not null default now(),
  primary key (user_id, symbol)
);

create index if not exists user_symbols_symbol_idx on public.user_symbols (symbol);

alter table public.user_symbols enable row level security;

do $$ begin
  create policy "swoje symbole" on public.user_symbols
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());
exception when duplicate_object then null; end $$;

comment on table public.user_symbols is
  'Cache: które spółki obchodzą którego użytkownika. Wypełniany z portfela '
  'i listy obserwowanych, czytany przez silnik powiadomień.';
