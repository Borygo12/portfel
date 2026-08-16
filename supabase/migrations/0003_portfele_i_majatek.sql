-- Portfele i majątek poza rachunkiem maklerskim.
--
-- Wklej całość w Supabase → SQL Editor → Run. Skrypt można puszczać wielokrotnie.
-- Wymaga 0002_portfolio_multiuser.sql (accounts, cash_ops, RLS).
--
-- ============================================================================
-- CO TO ZMIENIA W PRODUKCIE
--
-- Do tej pory Portevo miało JEDEN portfel: wszystko z wgranych raportów XTB
-- zliczone razem. Teraz użytkownik może:
--   * pogrupować rachunki w nazwane portfele („Emerytura", „Spekulacja"),
--   * dopisać do nich majątek, którego żaden broker nie zna — mieszkanie,
--     działkę, złoto, obligacje skarbowe.
--
-- Majątek jest OPCJĄ, nie wymogiem. Kto nie doda ani jednego aktywa ręcznego,
-- nie zobaczy różnicy: wszystkie rachunki lądują w portfelu domyślnym i apka
-- zachowuje się dokładnie jak dziś. To jest warunek, którego nie wolno złamać
-- przy dalszych zmianach — dołożenie tej funkcji nie może nikomu popsuć widoku,
-- który zna.
--
-- ============================================================================
-- DLACZEGO WYCENA MA WŁASNĄ TABELĘ, A NIE KOLUMNĘ `wartosc`
--
-- Bo bez historii karta portfela z mieszkaniem ma płaską kreskę zamiast wykresu.
-- Mieszkanie kupione za 400 tys. i warte dziś 700 tys. to najciekawsza rzecz,
-- jaka jest do pokazania w takim portfelu — a przy jednej kolumnie z bieżącą
-- kwotą ta informacja nie istnieje. Dlatego `manual_valuations` trzyma kolejne
-- wyceny z datami, a bieżąca wartość to po prostu najnowszy wpis.
--
-- Aktywa, które da się wycenić z rynku (złoto, srebro, kryptowaluty), historii
-- nie potrzebują — mają `symbol` i wycenia je ten sam kod, co notowania spółek.

-- ============================================================ portfele

create table if not exists public.portfolios (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
  name        text not null,
  -- kolor i ikona są czysto wizualne, ale przy pięciu portfelach to one
  -- pozwalają rozpoznać właściwy jednym rzutem oka, bez czytania nazw
  color       text default '',
  icon        text default '',
  sort        integer not null default 0,
  created_at  timestamptz not null default now(),
  unique (user_id, name)
);

comment on table public.portfolios is
  'Nazwane portfele użytkownika. Portfel grupuje rachunki maklerskie ORAZ '
  'aktywa wpisane ręcznie — dzięki temu „Emerytura" może zawierać konto XTB, '
  'obligacje i mieszkanie naraz.';

-- Przypisanie rachunku do portfela. NULL = portfel domyślny, czyli zachowanie
-- sprzed tej migracji. Kolumna jest nullable celowo: gdyby wymagała wartości,
-- każdy istniejący rachunek trzeba by przypisać przed pierwszym uruchomieniem.
alter table public.accounts
  add column if not exists portfolio_id uuid references public.portfolios (id) on delete set null;

create index if not exists accounts_portfolio_idx on public.accounts (user_id, portfolio_id);

-- ============================================================ majątek ręczny

create table if not exists public.manual_assets (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null default auth.uid() references auth.users (id) on delete cascade,
  portfolio_id uuid references public.portfolios (id) on delete set null,
  name         text not null,
  -- 'nieruchomosc' | 'metal' | 'krypto' | 'obligacje' | 'gotowka' | 'inne'
  -- Kategoria steruje ikoną, kolorem i tym, do której grupy aktywo wchodzi
  -- w Alokacji — czyli tym, czy mieszkanie stanie obok akcji, czy obok działki.
  category     text not null default 'inne',
  -- 'auto' = wyceniane z rynku po `symbol` (złoto GC=F, bitcoin BTC-USD),
  -- 'manual' = wyceniane wpisami w manual_valuations.
  pricing      text not null default 'manual',
  symbol       text default '',
  quantity     double precision default 0,
  currency     text not null default 'PLN',
  -- ile kosztowało — bez tego nie da się policzyć zysku na mieszkaniu
  cost         double precision default 0,
  cost_date    text default '',
  note         text default '',
  created_at   timestamptz not null default now(),
  sort         integer not null default 0
);

create index if not exists manual_assets_user_idx on public.manual_assets (user_id, portfolio_id);

comment on column public.manual_assets.pricing is
  'auto = wartość liczona z rynku po symbolu razy ilość (złoto, srebro, krypto). '
  'manual = wartość z najnowszego wpisu w manual_valuations (mieszkanie, działka).';

create table if not exists public.manual_valuations (
  id        uuid primary key default gen_random_uuid(),
  user_id   uuid not null default auth.uid() references auth.users (id) on delete cascade,
  asset_id  uuid not null references public.manual_assets (id) on delete cascade,
  date      text not null,                  -- YYYY-MM-DD
  value     double precision not null,
  note      text default '',
  unique (asset_id, date)
);

create index if not exists manual_valuations_asset_idx
  on public.manual_valuations (user_id, asset_id, date);

comment on table public.manual_valuations is
  'Kolejne wyceny aktywa wpisywanego ręcznie. Bieżąca wartość to najnowszy '
  'wpis; cała lista rysuje wykres wartości w czasie.';

-- ============================================================ RLS

alter table public.portfolios        enable row level security;
alter table public.manual_assets     enable row level security;
alter table public.manual_valuations enable row level security;

drop policy if exists "portfele: moje" on public.portfolios;
create policy "portfele: moje" on public.portfolios for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "majątek: mój" on public.manual_assets;
create policy "majątek: mój" on public.manual_assets for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "wyceny: moje" on public.manual_valuations;
create policy "wyceny: moje" on public.manual_valuations for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

grant select, insert, update, delete on public.portfolios        to authenticated;
grant select, insert, update, delete on public.manual_assets     to authenticated;
grant select, insert, update, delete on public.manual_valuations to authenticated;

-- ============================================================ czyszczenie konta
--
-- `wipe_my_portfolio` z 0002 kasuje rachunki i operacje. Musi teraz sprzątać
-- także portfele i majątek — inaczej po „wyczyść portfel" zostałyby osierocone
-- mieszkania w bazie, a użytkownik zobaczyłby je po ponownym imporcie.

-- Ten sam język co w 0002 (`sql`, nie `plpgsql`) — podmiana funkcji ze zmianą
-- języka bywa odrzucana, a tu chodzi tylko o dołożenie trzech kasowań.
create or replace function public.wipe_my_portfolio()
returns void language sql security invoker set search_path = public as $$
  delete from public.cash_ops          where user_id = auth.uid();
  delete from public.closed_positions  where user_id = auth.uid();
  delete from public.accounts          where user_id = auth.uid();
  delete from public.manual_valuations where user_id = auth.uid();
  delete from public.manual_assets     where user_id = auth.uid();
  delete from public.portfolios        where user_id = auth.uid();
$$;

grant execute on function public.wipe_my_portfolio() to authenticated;

-- ============================================================ odczyt raportu AI
--
-- Raport z nieznanego brokera czyta model językowy (bot/report_ai.py). To
-- kosztuje, więc konto bez premium ma jeden taki odczyt, a premium bez limitu.
--
-- Liczymy WYŁĄCZNIE udane odczyty. Nieudana próba nie może zjadać limitu:
-- człowiek nie dostał nic w zamian, a gdyby zjadała, pierwszy raport ucięty
-- przez timeout zamykałby drogę na zawsze i zostawiał wrażenie oszustwa.

create table if not exists public.ai_report_usage (
  user_id  uuid not null default auth.uid() references auth.users (id) on delete cascade,
  used_at  timestamptz not null default now(),
  model    text default '',
  positions integer default 0,
  id       uuid primary key default gen_random_uuid()
);

create index if not exists ai_report_usage_user_idx
  on public.ai_report_usage (user_id, used_at);

alter table public.ai_report_usage enable row level security;

drop policy if exists "odczyty AI: moje" on public.ai_report_usage;
create policy "odczyty AI: moje" on public.ai_report_usage for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

grant select, insert on public.ai_report_usage to authenticated;
