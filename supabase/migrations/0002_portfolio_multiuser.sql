-- Dane portfela w Supabase — wielu użytkowników, każdy widzi wyłącznie swoje.
--
-- Wklej całość w Supabase → SQL Editor → Run. Skrypt można puszczać wielokrotnie.
-- Wymaga wcześniejszego 0001_auth_premium_sync.sql (profiles, entitlements, RLS).
--
-- KLUCZOWA ZASADA: rozdziału danych pilnuje BAZA, nie kod aplikacji.
-- Każda tabela użytkownika ma `user_id ... default auth.uid()` oraz politykę RLS.
-- Dzięki temu zapytanie "select * from cash_ops" bez żadnego WHERE zwraca tylko
-- wiersze pytającego, a zapomniany filtr w kodzie nie jest w stanie odsłonić
-- cudzego portfela. Backend łączy się rolą `authenticated` i podaje tożsamość
-- w `request.jwt.claims` — patrz bot/db.py.
--
-- Tabele dzielą się na dwie grupy:
--   * DANE UŻYTKOWNIKA (accounts, cash_ops, closed_positions, watchlist) — prywatne,
--   * WSPÓLNY CACHE RYNKOWY (price_cache, price_meta, instrument_meta) — jeden dla
--     wszystkich. Kurs Orlenu jest ten sam dla każdego, więc pobieramy go raz.
--     To jest powód, dla którego 25 użytkowników kosztuje tyle co jeden.

-- ============================================================ role użytkowników

do $$ begin
  create type public.app_role as enum ('user', 'dev', 'owner');
exception when duplicate_object then null; end $$;

alter table public.profiles
  add column if not exists role public.app_role not null default 'user';

comment on column public.profiles.role is
  'user = zwykłe konto. dev = konto testowe: ma premium i może je w aplikacji '
  'chwilowo wyłączyć, żeby zobaczyć widok bez premium. owner = właściciel.';

-- Konto deweloperskie: premium bez płacenia + możliwość podglądu obu wariantów.
-- Wywołuj z SQL Editor: select public.grant_dev('ktos@example.com');
create or replace function public.grant_dev(target_email text)
returns uuid language plpgsql security definer set search_path = public as $$
declare uid uuid;
begin
  select id into uid from auth.users where lower(email) = lower(target_email);
  if uid is null then
    raise exception 'Nie ma użytkownika o adresie %. Niech najpierw założy konto w aplikacji.', target_email;
  end if;

  update public.profiles set role = 'dev' where id = uid;

  -- dev widzi premium, ale to nadanie ma źródło 'promo' — nie miesza się w statystykach
  -- sprzedaży z prawdziwymi zakupami
  perform public.grant_premium(target_email, 'lifetime', null, 'promo');
  return uid;
end $$;

create or replace function public.revoke_dev(target_email text)
returns integer language plpgsql security definer set search_path = public as $$
declare uid uuid;
begin
  select id into uid from auth.users where lower(email) = lower(target_email);
  if uid is null then return 0; end if;
  update public.profiles set role = 'user' where id = uid;
  perform public.revoke_premium(target_email);
  return 1;
end $$;

revoke execute on function public.grant_dev(text)  from public, anon, authenticated;
revoke execute on function public.revoke_dev(text) from public, anon, authenticated;

-- ==================================================== dane portfela (prywatne)

create table if not exists public.accounts (
  user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
  account     text not null,
  currency    text not null,
  broker      text not null default 'XTB',
  label       text default '',
  date_from   text default '',
  date_to     text default '',
  imported_at text default '',
  -- stawki prowizji ustawione ręcznie w aplikacji (JSON jako tekst — tak zapisuje kod)
  fees        text default '',
  primary key (user_id, account)
);

comment on table public.accounts is
  'Konta maklerskie użytkownika. Numer konta bywa taki sam u różnych osób, '
  'dlatego kluczem jest para (user_id, account).';

create table if not exists public.cash_ops (
  user_id    uuid not null default auth.uid() references auth.users (id) on delete cascade,
  account    text not null,
  op_id      text not null,
  type       text not null,
  ticker     text default '',
  instrument text default '',
  time       text not null,
  amount     double precision not null,
  comment    text default '',
  product    text default '',
  primary key (user_id, account, op_id)
);

create index if not exists cash_ops_time_idx on public.cash_ops (user_id, time);

create table if not exists public.closed_positions (
  user_id        uuid not null default auth.uid() references auth.users (id) on delete cascade,
  -- position_id|close_time|volume — częściowe zamknięcie to osobny wiersz
  key            text not null,
  account        text not null,
  instrument     text default '',
  category       text default '',
  ticker         text default '',
  type           text default '',
  volume         double precision default 0,
  open_price     double precision default 0,
  open_time      text default '',
  close_price    double precision default 0,
  close_time     text default '',
  profit         double precision default 0,
  gross_profit   double precision default 0,
  purchase_value double precision default 0,
  sale_value     double precision default 0,
  commission     double precision default 0,
  swap           double precision default 0,
  rollover       double precision default 0,
  close_origin   text default '',
  position_id    text default '',
  primary key (user_id, key)
);

create index if not exists closed_positions_acct_idx on public.closed_positions (user_id, account);

-- watchlist powstał już w 0001; dokładamy tylko to, czego używa kod
alter table public.watchlist
  add column if not exists note text default '';

alter table public.watchlist
  alter column user_id set default auth.uid();

-- ================================================ wspólny cache rynkowy

create table if not exists public.price_cache (
  symbol text not null,              -- symbol źródłowy, np. 'cdr.wa' / '^spx' / 'usdpln'
  date   text not null,              -- YYYY-MM-DD
  close  double precision not null,
  primary key (symbol, date)
);

comment on table public.price_cache is
  'Notowania dzienne wspólne dla wszystkich kont. Bez user_id — kurs jest jeden. '
  'Zapisuje wyłącznie serwer (service_role); użytkownik może tylko czytać.';

create table if not exists public.price_meta (
  symbol     text primary key,
  source     text default '',        -- 'stooq' | 'yahoo' | 'none'
  last_fetch text default '',        -- ISO UTC ostatniej próby
  status     text default ''         -- 'ok' | 'empty' | 'error'
);

create table if not exists public.instrument_meta (
  ticker     text primary key,
  quote_type text default '',
  sector     text default '',
  industry   text default '',
  long_name  text default '',
  fetched_at text default ''
);

comment on table public.instrument_meta is
  'Branża i typ instrumentu z Yahoo. Wspólne — te same dane dla każdego konta.';

-- ============================================================== automatyzacje

-- Kasowanie konta użytkownika ma sprzątać po sobie w całości. Klucze obce robią
-- to dla wierszy z user_id; ta funkcja jest do ręcznego czyszczenia z aplikacji.
create or replace function public.wipe_my_portfolio()
returns void language sql security invoker set search_path = public as $$
  delete from public.cash_ops         where user_id = auth.uid();
  delete from public.closed_positions where user_id = auth.uid();
  delete from public.accounts         where user_id = auth.uid();
$$;

-- ====================================================================== RLS

alter table public.accounts         enable row level security;
alter table public.cash_ops         enable row level security;
alter table public.closed_positions enable row level security;
alter table public.price_cache      enable row level security;
alter table public.price_meta       enable row level security;
alter table public.instrument_meta  enable row level security;

drop policy if exists "konta: moje" on public.accounts;
create policy "konta: moje" on public.accounts for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "operacje: moje" on public.cash_ops;
create policy "operacje: moje" on public.cash_ops for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "pozycje zamknięte: moje" on public.closed_positions;
create policy "pozycje zamknięte: moje" on public.closed_positions for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Cache rynkowy: czyta każdy zalogowany, pisze tylko serwer (service_role omija RLS).
-- Gdyby klient mógł pisać, mógłby podmienić kurs i zafałszować cudze wykresy.
drop policy if exists "ceny: czyta każdy zalogowany" on public.price_cache;
create policy "ceny: czyta każdy zalogowany" on public.price_cache for select
  using (auth.role() = 'authenticated');

drop policy if exists "meta cen: czyta każdy zalogowany" on public.price_meta;
create policy "meta cen: czyta każdy zalogowany" on public.price_meta for select
  using (auth.role() = 'authenticated');

drop policy if exists "meta instrumentów: czyta każdy zalogowany" on public.instrument_meta;
create policy "meta instrumentów: czyta każdy zalogowany" on public.instrument_meta for select
  using (auth.role() = 'authenticated');

-- =============================================================== uprawnienia

grant select, insert, update, delete on public.accounts         to authenticated;
grant select, insert, update, delete on public.cash_ops         to authenticated;
grant select, insert, update, delete on public.closed_positions to authenticated;
grant select on public.price_cache     to authenticated;
grant select on public.price_meta      to authenticated;
grant select on public.instrument_meta to authenticated;

grant execute on function public.wipe_my_portfolio() to authenticated;
