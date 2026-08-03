-- Konta, uprawnienia premium i synchronizacja ustawień między telefonem a panelem web.
--
-- Wklej całość w Supabase → SQL Editor → Run. Skrypt można puszczać wielokrotnie —
-- wszystko jest "if not exists" / "create or replace".
--
-- Zasada bezpieczeństwa: każda tabela ma RLS, a użytkownik widzi wyłącznie własne
-- wiersze. Uprawnienia premium są tylko do ODCZYTU dla użytkownika — nadaje je
-- serwer (service_role) albo webhook płatności, nigdy sam klient.

-- ---------------------------------------------------------------- profile

create table if not exists public.profiles (
  id          uuid primary key references auth.users (id) on delete cascade,
  email       text,
  full_name   text,
  avatar_url  text,
  -- skąd użytkownik trafił do aplikacji; przyda się przy ocenie kanałów sprzedaży
  referrer    text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

comment on table public.profiles is 'Dane konta widoczne w aplikacji — 1:1 z auth.users.';

-- ------------------------------------------------------------ uprawnienia

do $$ begin
  create type public.entitlement_source as enum ('manual', 'trial', 'stripe', 'apple', 'google', 'promo');
exception when duplicate_object then null; end $$;

do $$ begin
  create type public.entitlement_plan as enum ('monthly', 'yearly', 'lifetime', 'trial');
exception when duplicate_object then null; end $$;

create table if not exists public.entitlements (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users (id) on delete cascade,
  -- na razie jeden produkt; kolumna zostaje, gdyby doszły pakiety (np. "bot", "pro")
  product       text not null default 'premium',
  plan          public.entitlement_plan not null default 'monthly',
  source        public.entitlement_source not null default 'manual',
  -- null = bezterminowo (lifetime albo ręczne nadanie)
  expires_at    timestamptz,
  -- ustawiane, gdy subskrypcja zostaje anulowana przed końcem opłaconego okresu
  cancelled_at  timestamptz,
  -- identyfikatory po stronie dostawcy płatności — do dopięcia webhooków
  provider_ref  text,
  customer_ref  text,
  note          text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists entitlements_user_idx on public.entitlements (user_id, product);
create unique index if not exists entitlements_provider_idx
  on public.entitlements (source, provider_ref) where provider_ref is not null;

comment on table public.entitlements is
  'Nadania premium. Aktywne = expires_at w przyszłości lub null.';

-- ------------------------------------------------ ustawienia synchronizowane

create table if not exists public.user_settings (
  user_id     uuid not null references auth.users (id) on delete cascade,
  key         text not null,
  value       jsonb not null,
  -- kto zapisał ostatnio; pozwala pokazać "zmienione na telefonie"
  device      text,
  updated_at  timestamptz not null default now(),
  primary key (user_id, key)
);

comment on table public.user_settings is
  'Drobne preferencje UI (tło, domyślna zakładka, filtry) wspólne dla telefonu i weba.';

-- --------------------------------------------------- obserwowane instrumenty

create table if not exists public.watchlist (
  user_id     uuid not null references auth.users (id) on delete cascade,
  symbol      text not null,
  name        text,
  type        text,
  exchange    text,
  currency    text,
  -- opcjonalny alert cenowy — z tego wyrasta później funkcja premium "Alerty"
  alert_above numeric,
  alert_below numeric,
  added_at    timestamptz not null default now(),
  primary key (user_id, symbol)
);

-- --------------------------------------------- analityka ścieżki sprzedażowej

create table if not exists public.premium_events (
  id         bigserial primary key,
  user_id    uuid references auth.users (id) on delete set null,
  -- 'lock_seen' | 'lock_click' | 'paywall_open' | 'checkout_start' | 'purchase'
  event      text not null,
  feature    text,
  platform   text,
  meta       jsonb,
  created_at timestamptz not null default now()
);

create index if not exists premium_events_user_idx on public.premium_events (user_id, created_at desc);
create index if not exists premium_events_feature_idx on public.premium_events (feature, event);

comment on table public.premium_events is
  'Które kłódki ludzie klikają. Bez tego nie da się poprawiać strony sprzedażowej.';

-- ------------------------------------------------------------- automatyzacje

create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

drop trigger if exists profiles_touch on public.profiles;
create trigger profiles_touch before update on public.profiles
  for each row execute function public.touch_updated_at();

drop trigger if exists entitlements_touch on public.entitlements;
create trigger entitlements_touch before update on public.entitlements
  for each row execute function public.touch_updated_at();

drop trigger if exists user_settings_touch on public.user_settings;
create trigger user_settings_touch before update on public.user_settings
  for each row execute function public.touch_updated_at();

-- Nowy użytkownik dostaje profil od ręki — inaczej aplikacja musiałaby go tworzyć
-- sama i każdy ekran zaczynałby się od sprawdzania, czy profil już jest.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email, full_name, avatar_url)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data ->> 'full_name', new.raw_user_meta_data ->> 'name'),
    new.raw_user_meta_data ->> 'avatar_url'
  )
  on conflict (id) do update
    set email      = excluded.email,
        full_name  = coalesce(public.profiles.full_name, excluded.full_name),
        avatar_url = coalesce(excluded.avatar_url, public.profiles.avatar_url);
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- ------------------------------------------------------------- odczyt statusu

create or replace function public.is_premium(uid uuid default auth.uid())
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.entitlements e
     where e.user_id = uid
       and e.product = 'premium'
       and (e.expires_at is null or e.expires_at > now())
  );
$$;

-- Jeden strzał po wszystko, co aplikacja pokazuje w nagłówku konta.
create or replace function public.me()
returns jsonb language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'user_id',    p.id,
    'email',      p.email,
    'full_name',  p.full_name,
    'avatar_url', p.avatar_url,
    'premium',    public.is_premium(p.id),
    'plan',       (select e.plan from public.entitlements e
                    where e.user_id = p.id and e.product = 'premium'
                      and (e.expires_at is null or e.expires_at > now())
                    order by e.expires_at desc nulls first limit 1),
    'expires_at', (select e.expires_at from public.entitlements e
                    where e.user_id = p.id and e.product = 'premium'
                      and (e.expires_at is null or e.expires_at > now())
                    order by e.expires_at desc nulls first limit 1),
    'source',     (select e.source from public.entitlements e
                    where e.user_id = p.id and e.product = 'premium'
                      and (e.expires_at is null or e.expires_at > now())
                    order by e.expires_at desc nulls first limit 1)
  )
  from public.profiles p where p.id = auth.uid();
$$;

-- ----------------------------------------------- ręczne nadawanie i odbieranie

-- Wywołuj z SQL Editor (działa jako właściciel bazy), nie z aplikacji.
create or replace function public.grant_premium(
  target_email text,
  plan public.entitlement_plan default 'lifetime',
  expires timestamptz default null,
  src public.entitlement_source default 'manual'
) returns uuid language plpgsql security definer set search_path = public as $$
declare uid uuid; ent uuid;
begin
  select id into uid from auth.users where lower(email) = lower(target_email);
  if uid is null then
    raise exception 'Nie ma użytkownika o adresie %. Zaloguj się najpierw w aplikacji.', target_email;
  end if;

  update public.entitlements
     set plan = grant_premium.plan, expires_at = expires, source = src, cancelled_at = null
   where user_id = uid and product = 'premium'
   returning id into ent;

  if ent is null then
    insert into public.entitlements (user_id, plan, expires_at, source)
    values (uid, grant_premium.plan, expires, src)
    returning id into ent;
  end if;

  return ent;
end $$;

create or replace function public.revoke_premium(target_email text)
returns integer language plpgsql security definer set search_path = public as $$
declare uid uuid; n integer;
begin
  select id into uid from auth.users where lower(email) = lower(target_email);
  if uid is null then return 0; end if;
  delete from public.entitlements where user_id = uid and product = 'premium';
  get diagnostics n = row_count;
  return n;
end $$;

-- ---------------------------------------------------------------------- RLS

alter table public.profiles       enable row level security;
alter table public.entitlements   enable row level security;
alter table public.user_settings  enable row level security;
alter table public.watchlist      enable row level security;
alter table public.premium_events enable row level security;

drop policy if exists "profil: czytam swój"   on public.profiles;
drop policy if exists "profil: zmieniam swój" on public.profiles;
create policy "profil: czytam swój"   on public.profiles for select using (auth.uid() = id);
create policy "profil: zmieniam swój" on public.profiles for update using (auth.uid() = id)
  with check (auth.uid() = id);

-- Premium tylko do odczytu: zapis idzie przez service_role (backend / webhook),
-- który z definicji omija RLS. Gdyby klient mógł pisać, wystarczyłby jeden insert
-- z telefonu, żeby mieć premium za darmo.
drop policy if exists "premium: czytam swoje" on public.entitlements;
create policy "premium: czytam swoje" on public.entitlements for select using (auth.uid() = user_id);

drop policy if exists "ustawienia: moje" on public.user_settings;
create policy "ustawienia: moje" on public.user_settings for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "obserwowane: moje" on public.watchlist;
create policy "obserwowane: moje" on public.watchlist for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Zdarzenia sprzedażowe: użytkownik może dopisać własne, ale nie może ich czytać
-- ani kasować — to dane analityczne, nie jego zawartość.
drop policy if exists "zdarzenia: dopisuję swoje" on public.premium_events;
create policy "zdarzenia: dopisuję swoje" on public.premium_events for insert
  with check (auth.uid() = user_id or user_id is null);

-- --------------------------------------------------------------- uprawnienia

grant usage on schema public to anon, authenticated;
grant select, update on public.profiles       to authenticated;
grant select          on public.entitlements   to authenticated;
grant select, insert, update, delete on public.user_settings to authenticated;
grant select, insert, update, delete on public.watchlist     to authenticated;
grant insert          on public.premium_events to authenticated;
grant usage, select   on sequence public.premium_events_id_seq to authenticated;

grant execute on function public.me()               to authenticated;
grant execute on function public.is_premium(uuid)   to authenticated;
-- nadawanie premium zostaje wyłącznie w rękach właściciela bazy
revoke execute on function public.grant_premium(text, public.entitlement_plan, timestamptz, public.entitlement_source) from public, anon, authenticated;
revoke execute on function public.revoke_premium(text) from public, anon, authenticated;
