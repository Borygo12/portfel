-- Konta emerytalne, część druga: małżonek, konta wpisywane ręcznie (IKE-Obligacje,
-- TFI, PPK, PPE) i przypomnienie o limicie.
--
-- Wklej całość w Supabase → SQL Editor → Run. Skrypt można puszczać wielokrotnie.
-- Wymaga 0011_konta_emerytalne.sql.

-- ============================================================ czyje to konto
--
-- '' = moje, 'malzonek' = współmałżonka. Limity IKE i IKZE są na osobę, więc
-- dwa rachunki IKE w jednej rodzinie to dwa osobne limity — a bez tej kolumny
-- zlewałyby się w jeden i wychodziłoby „przekroczenie".
alter table public.accounts
  add column if not exists kind_owner text not null default '';

alter table public.manual_assets
  add column if not exists account_owner text not null default '';

-- ============================================================ konta ręczne
--
-- Konto, z którego nie ma raportu maklerskiego: IKE-Obligacje w PKO BP, IKE
-- w funduszu, PPK u pracodawcy. Znamy o nim tyle, ile człowiek wpisze:
-- dzisiejszą wartość i wpłaty rok po roku.
create table if not exists public.retirement_accounts (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
  -- '' = moje, 'malzonek'
  owner       text not null default '',
  -- 'ike' | 'ikze' | 'ppk' | 'ppe'
  kind        text not null,
  name        text not null,
  institution text not null default '',
  value       double precision not null default 0,
  value_date  text not null default '',
  note        text not null default '',
  created_at  timestamptz not null default now()
);

create index if not exists retirement_accounts_user_idx
  on public.retirement_accounts (user_id, kind);

-- Wpłaty na konto ręczne. `year = 0` oznacza „łącznie, bez podziału na lata" —
-- tak wpisuje się PPK, gdzie człowiek zna sumę z aplikacji instytucji, a nie
-- historię. `source` rozdziela wpłaty własne, pracodawcy i państwa: przy
-- zwrocie z PPK każda z nich jest traktowana inaczej.
create table if not exists public.retirement_deposits (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null default auth.uid() references auth.users (id) on delete cascade,
  account_id uuid not null references public.retirement_accounts (id) on delete cascade,
  year       integer not null default 0,
  amount     double precision not null default 0,
  -- 'wlasne' | 'pracodawca' | 'panstwo'
  source     text not null default 'wlasne',
  unique (account_id, year, source)
);

create index if not exists retirement_deposits_account_idx
  on public.retirement_deposits (user_id, account_id);

alter table public.retirement_accounts enable row level security;
alter table public.retirement_deposits enable row level security;

drop policy if exists "konta emerytalne: moje" on public.retirement_accounts;
create policy "konta emerytalne: moje" on public.retirement_accounts for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "wpłaty emerytalne: moje" on public.retirement_deposits;
create policy "wpłaty emerytalne: moje" on public.retirement_deposits for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

grant select, insert, update, delete on public.retirement_accounts to authenticated;
grant select, insert, update, delete on public.retirement_deposits to authenticated;

-- ============================================================ przypomnienie
--
-- „Zostało Ci 8 460 zł limitu IKE i 31 dni" — w listopadzie i grudniu.
-- Domyślnie włączone, jak przypomnienia o wynikach.
alter table public.notification_prefs
  add column if not exists retirement_limit boolean not null default true;
