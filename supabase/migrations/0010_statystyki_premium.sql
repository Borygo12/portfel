-- 0010: statystyki dla Kokpitu — sesje, wykluczanie kont właściciela, lista premium.
--
-- 1. `ai_report_usage` — tabela z 0003, która na produkcji nigdy nie powstała.
--    Bez niej zapis „odczytu AI" cicho się nie udawał, a limit darmowego odczytu
--    nie miał czego liczyć.
-- 2. `activity_daily.sessions` — ile razy ktoś wszedł do apki (przerwa > 30 min
--    = nowe wejście). Liczy baza, więc restart serwera nie nabija wejść.
-- 3. `activity_summary(p_days, p_exclude)` — jak w 0009, ale bez urządzeń kont
--    z `p_exclude` (właściciel, konta testowe). Wyklucza URZĄDZENIE, a nie tylko
--    konto: telefon właściciela po wylogowaniu dalej jest jego telefonem.
-- 4. `premium_users(p_exclude)` — każdy z premium: co kupił, do kiedy, czy się
--    odnawia, ile płacił, jak często wchodzi, z czego korzysta.

-- ---------------------------------------------------------------- 1. odczyty AI
create table if not exists public.ai_report_usage (
  user_id  uuid not null default auth.uid() references auth.users (id) on delete cascade,
  used_at  timestamptz not null default now(),
  model    text default '',
  positions integer default 0,
  id       uuid primary key default gen_random_uuid()
);
create index if not exists ai_report_usage_user_idx on public.ai_report_usage (user_id, used_at);
alter table public.ai_report_usage enable row level security;
drop policy if exists "odczyty AI: moje" on public.ai_report_usage;
create policy "odczyty AI: moje" on public.ai_report_usage for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);
grant select, insert on public.ai_report_usage to authenticated;

-- ---------------------------------------------------------------- 2. sesje
alter table public.activity_daily add column if not exists sessions int not null default 1;

create or replace function public.activity_bump(p_rows jsonb)
returns void
language sql
security definer
set search_path = public
as $$
  insert into public.activity_daily as a
         (day, visitor, user_id, platform, first_seen, last_seen, minutes, screens, sessions)
  select ((r->>'first_seen')::timestamptz at time zone 'Europe/Warsaw')::date,
         r->>'visitor',
         nullif(r->>'user_id', '')::uuid,
         r->>'platform',
         (r->>'first_seen')::timestamptz,
         (r->>'last_seen')::timestamptz,
         coalesce((r->>'minutes')::int, 0),
         coalesce(r->'screens', '{}'::jsonb),
         1
    from jsonb_array_elements(p_rows) r
  on conflict (day, visitor) do update set
    user_id    = coalesce(excluded.user_id, a.user_id),
    platform   = excluded.platform,
    -- ponad pół godziny ciszy i znowu jest = nowe wejście do aplikacji
    sessions   = a.sessions + case when excluded.first_seen - a.last_seen > interval '30 minutes'
                                   then 1 else 0 end,
    first_seen = least(a.first_seen, excluded.first_seen),
    last_seen  = greatest(a.last_seen, excluded.last_seen),
    minutes    = a.minutes + excluded.minutes,
    screens    = (
      select coalesce(jsonb_object_agg(k, n), '{}'::jsonb)
        from (select k, sum(v::int) as n
                from (select key as k, value as v from jsonb_each_text(a.screens)
                      union all
                      select key, value from jsonb_each_text(excluded.screens)) t
               group by k) s
    );
$$;

-- ---------------------------------------------------------------- 3. podsumowanie
drop function if exists public.activity_summary(int);

create or replace function public.activity_summary(p_days int default 30, p_exclude uuid[] default '{}')
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
  with
  dzis as (
    select (now() at time zone 'Europe/Warsaw')::date as d,
           ((now() at time zone 'Europe/Warsaw')::date::timestamp at time zone 'Europe/Warsaw') as polnoc
  ),
  -- urządzenia, na których choć raz było zalogowane konto wykluczone
  wykl as (
    select distinct visitor from public.activity_daily where user_id = any(p_exclude)
  ),
  ad as (
    select a.* from public.activity_daily a
     where not exists (select 1 from wykl where wykl.visitor = a.visitor)
  ),
  start as (select min(first_seen) as od, min(day) as d from public.activity_daily),
  online as (
    select platform, count(*) as n, count(user_id) as zal
      from ad where last_seen > now() - interval '3 minutes'
     group by platform
  ),
  pierwszy as (select visitor, min(day) as d from ad group by visitor),
  dzien as (select ad.* from ad, dzis where ad.day = dzis.d),
  uzytk as (
    select u.* from auth.users u where not (u.id = any(p_exclude))
  ),
  seria as (
    select g.d::date as day,
           (select count(*) from ad where ad.day = g.d::date) as odwiedzajacy,
           (select count(distinct ad.user_id) from ad where ad.day = g.d::date) as zalogowani,
           -- pierwszy dzień liczenia: każde urządzenie jest „nowe", więc go nie liczymy
           case when g.d::date > (select d from start)
                then (select count(*) from pierwszy p where p.d = g.d::date) end as nowi,
           (select coalesce(sum(ad.sessions), 0) from ad where ad.day = g.d::date) as wejscia,
           (select coalesce(sum(ad.minutes), 0) from ad where ad.day = g.d::date) as minuty,
           (select count(*) from uzytk u
             where (u.created_at at time zone 'Europe/Warsaw')::date = g.d::date) as rejestracje
      from dzis, generate_series(dzis.d - (p_days - 1), dzis.d, interval '1 day') g(d)
  ),
  ekrany as (
    select k as ekran, sum(v::int) as n
      from dzien, jsonb_each_text(dzien.screens) e(k, v)
     group by k order by n desc limit 12
  )
  select jsonb_build_object(
    'teraz', now(),
    'liczone_od', (select od from start),
    'wykluczone_urzadzenia', (select count(*) from wykl),
    'online', (select coalesce(sum(n), 0) from online),
    'online_zalogowani', (select coalesce(sum(zal), 0) from online),
    'online_platformy', (select coalesce(jsonb_object_agg(platform, n), '{}'::jsonb) from online),
    'dzis', jsonb_build_object(
      'od', (select polnoc from dzis),
      'odwiedzajacy', (select count(*) from dzien),
      'zalogowani',   (select count(distinct user_id) from dzien),
      'nowi',         (select case when dzis.d > start.d
                                   then (select count(*) from pierwszy where pierwszy.d = dzis.d) end
                         from dzis, start),
      'wejscia',      (select coalesce(sum(sessions), 0) from dzien),
      'minuty',       (select coalesce(sum(minutes), 0) from dzien),
      'logowania',    (select count(*) from uzytk u, dzis where u.last_sign_in_at >= dzis.polnoc),
      'rejestracje',  (select count(*) from uzytk u, dzis where u.created_at >= dzis.polnoc),
      'platformy',    (select coalesce(jsonb_object_agg(platform, n), '{}'::jsonb)
                         from (select platform, count(*) n from dzien group by platform) p)
    ),
    'wau', (select count(distinct visitor) from ad, dzis where day > dzis.d - 7),
    'mau', (select count(distinct visitor) from ad, dzis where day > dzis.d - 30),
    'ekrany', (select coalesce(jsonb_agg(jsonb_build_object('ekran', ekran, 'n', n)), '[]'::jsonb) from ekrany),
    'dni', (select coalesce(jsonb_agg(to_jsonb(seria) order by day), '[]'::jsonb) from seria)
  );
$$;

-- ---------------------------------------------------------------- 4. lista premium
create or replace function public.premium_users(p_exclude uuid[] default '{}')
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
  with ent as (
    -- jedno (najświeższe) uprawnienie na konto
    select distinct on (e.user_id) e.*
      from public.entitlements e
     where e.product = 'premium'
     order by e.user_id, e.created_at desc
  ),
  platnosci as (
    -- webhook potrafił zapisać ten sam zakup dwa razy — liczymy po identyfikatorze płatności
    select user_id, count(*) as ile, sum(kwota) as grosze, max(kiedy) as ostatnia
      from (select distinct on (coalesce(meta->>'sesja', meta->>'transakcja', meta->>'faktura', id::text))
                   user_id, coalesce((meta->>'kwota')::int, 0) as kwota, created_at as kiedy
              from public.premium_events
             where event in ('purchase', 'renewal')
             order by coalesce(meta->>'sesja', meta->>'transakcja', meta->>'faktura', id::text), created_at) x
     group by user_id
  ),
  akt as (
    select user_id,
           count(distinct day) filter (where day > current_date - 30) as dni30,
           count(distinct day) as dni,
           sum(sessions) as wejscia,
           sum(minutes) as minuty,
           max(last_seen) as ostatnio,
           array_agg(distinct platform) as platformy
      from public.activity_daily where user_id is not null
     group by user_id
  ),
  ekr as (
    select user_id, jsonb_agg(jsonb_build_object('ekran', k, 'n', n) order by n desc) as ekrany
      from (select a.user_id, k, sum(v::int) as n
              from public.activity_daily a, jsonb_each_text(a.screens) e(k, v)
             where a.user_id is not null
             group by a.user_id, k) s
     group by user_id
  )
  select coalesce(jsonb_agg(jsonb_build_object(
    'user_id', ent.user_id,
    'email', p.email,
    'imie', p.full_name,
    'konto_od', p.created_at,
    'ostatnie_logowanie', u.last_sign_in_at,
    'plan', ent.plan,
    'zrodlo', ent.source,
    'kupione', ent.created_at,
    'wygasa', ent.expires_at,
    'anulowane', ent.cancelled_at,
    'notatka', ent.note,
    'wykluczone', ent.user_id = any(p_exclude),
    'platnosci', coalesce(pl.ile, 0),
    'zaplacone_grosze', coalesce(pl.grosze, 0),
    'dni_aktywne_30', coalesce(akt.dni30, 0),
    'dni_aktywne', coalesce(akt.dni, 0),
    'wejscia', coalesce(akt.wejscia, 0),
    'minuty', coalesce(akt.minuty, 0),
    'ostatnio_w_apce', akt.ostatnio,
    'platformy', coalesce(to_jsonb(akt.platformy), '[]'::jsonb),
    'ekrany', coalesce(ekr.ekrany, '[]'::jsonb),
    'raporty_ai', (select count(*) from public.ai_report_usage r where r.user_id = ent.user_id),
    'portfele', (select count(*) from public.portfolios x where x.user_id = ent.user_id),
    'konta_maklerskie', (select count(*) from public.accounts x where x.user_id = ent.user_id),
    'aktywa_reczne', (select count(*) from public.manual_assets x where x.user_id = ent.user_id),
    'obserwowane', (select count(*) from public.watchlist x where x.user_id = ent.user_id),
    'insiderzy', (select count(*) from public.insider_follows x where x.user_id = ent.user_id),
    'push', exists(select 1 from public.push_tokens x where x.user_id = ent.user_id),
    'powiadomienia', (select count(*) from public.notifications x where x.user_id = ent.user_id)
  ) order by ent.created_at desc), '[]'::jsonb)
    from ent
    join public.profiles p on p.id = ent.user_id
    left join auth.users u on u.id = ent.user_id
    left join platnosci pl on pl.user_id = ent.user_id
    left join akt on akt.user_id = ent.user_id
    left join ekr on ekr.user_id = ent.user_id;
$$;

revoke all on function public.activity_summary(int, uuid[]) from public, anon, authenticated;
revoke all on function public.premium_users(uuid[]) from public, anon, authenticated;
grant execute on function public.activity_summary(int, uuid[]) to service_role;
grant execute on function public.premium_users(uuid[]) to service_role;
