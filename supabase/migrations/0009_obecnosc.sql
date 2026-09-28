-- 0009: obecność — kto jest w Portevo TERAZ i ilu ludzi było danego dnia.
--
-- Skąd dane: aplikacja (telefon i przeglądarka) oraz podstrony pozycjonowane
-- wysyłają co minutę krótki sygnał „jestem" na `POST /api/ping`. Serwer zbiera
-- je w pamięci i co pół minuty dopisuje tu przez `activity_bump` — jeden wiersz
-- na osobę na dzień, a nie wiersz na każdy sygnał.
--
-- `visitor` to losowy identyfikator urządzenia/przeglądarki (nie konto), więc
-- liczy się też gości bez logowania. `user_id` dochodzi, gdy ktoś jest zalogowany.
--
-- Czyta to Kokpit przez `activity_summary` (kluczem serwerowym). Aplikacja nie
-- ma tu żadnego dostępu: RLS włączony bez polityk = tylko service_role.

create table if not exists public.activity_daily (
  day        date        not null,              -- dzień w czasie polskim
  visitor    text        not null,
  user_id    uuid,
  platform   text        not null,              -- ios | android | web | seo
  first_seen timestamptz not null,
  last_seen  timestamptz not null,
  minutes    int         not null default 0,    -- przybliżony czas w apce
  screens    jsonb       not null default '{}'::jsonb,  -- {"overview": 3, ...}
  primary key (day, visitor)
);

create index if not exists activity_daily_last_seen_idx on public.activity_daily (last_seen desc);
create index if not exists activity_daily_visitor_idx on public.activity_daily (visitor, day);

alter table public.activity_daily enable row level security;
revoke all on public.activity_daily from anon, authenticated;

comment on table public.activity_daily is
  'Obecność w Portevo: wiersz na urządzenie na dzień. Pisze serwer (activity_bump), czyta Kokpit (activity_summary).';


-- Dopisanie paczki z pamięci serwera. Sumuje, a nie nadpisuje — restart serwera
-- w środku dnia nie kasuje więc tego, co już się uzbierało.
create or replace function public.activity_bump(p_rows jsonb)
returns void
language sql
security definer
set search_path = public
as $$
  insert into public.activity_daily as a
         (day, visitor, user_id, platform, first_seen, last_seen, minutes, screens)
  select ((r->>'first_seen')::timestamptz at time zone 'Europe/Warsaw')::date,
         r->>'visitor',
         nullif(r->>'user_id', '')::uuid,
         r->>'platform',
         (r->>'first_seen')::timestamptz,
         (r->>'last_seen')::timestamptz,
         coalesce((r->>'minutes')::int, 0),
         coalesce(r->'screens', '{}'::jsonb)
    from jsonb_array_elements(p_rows) r
  on conflict (day, visitor) do update set
    user_id    = coalesce(excluded.user_id, a.user_id),
    platform   = excluded.platform,
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


-- Jeden obiekt z pełnym obrazem dla Kokpitu — jedno zapytanie zamiast dziesięciu.
create or replace function public.activity_summary(p_days int default 30)
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
  -- „online" = sygnał w ciągu ostatnich 3 minut (apka wysyła co minutę)
  online as (
    select platform, count(*) as n, count(user_id) as zal
      from public.activity_daily
     where last_seen > now() - interval '3 minutes'
     group by platform
  ),
  pierwszy as (
    select visitor, min(day) as d from public.activity_daily group by visitor
  ),
  dzien as (
    select a.* from public.activity_daily a, dzis where a.day = dzis.d
  ),
  seria as (
    select g.d::date as day,
           (select count(*) from public.activity_daily a where a.day = g.d::date) as odwiedzajacy,
           (select count(distinct a.user_id) from public.activity_daily a where a.day = g.d::date) as zalogowani,
           (select count(*) from pierwszy p where p.d = g.d::date) as nowi,
           (select coalesce(sum(a.minutes), 0) from public.activity_daily a where a.day = g.d::date) as minuty,
           (select count(*) from auth.users u
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
    'online', (select coalesce(sum(n), 0) from online),
    'online_zalogowani', (select coalesce(sum(zal), 0) from online),
    'online_platformy', (select coalesce(jsonb_object_agg(platform, n), '{}'::jsonb) from online),
    'dzis', jsonb_build_object(
      'odwiedzajacy', (select count(*) from dzien),
      'zalogowani',   (select count(distinct user_id) from dzien),
      'nowi',         (select count(*) from pierwszy, dzis where pierwszy.d = dzis.d),
      'minuty',       (select coalesce(sum(minutes), 0) from dzien),
      'logowania',    (select count(*) from auth.users u, dzis where u.last_sign_in_at >= dzis.polnoc),
      'rejestracje',  (select count(*) from auth.users u, dzis where u.created_at >= dzis.polnoc),
      'platformy',    (select coalesce(jsonb_object_agg(platform, n), '{}'::jsonb)
                         from (select platform, count(*) n from dzien group by platform) p)
    ),
    'wau', (select count(distinct visitor) from public.activity_daily, dzis where day > dzis.d - 7),
    'mau', (select count(distinct visitor) from public.activity_daily, dzis where day > dzis.d - 30),
    'ekrany', (select coalesce(jsonb_agg(jsonb_build_object('ekran', ekran, 'n', n)), '[]'::jsonb) from ekrany),
    'dni', (select coalesce(jsonb_agg(to_jsonb(seria) order by day), '[]'::jsonb) from seria)
  );
$$;

revoke all on function public.activity_bump(jsonb) from public, anon, authenticated;
revoke all on function public.activity_summary(int) from public, anon, authenticated;
grant execute on function public.activity_bump(jsonb) to service_role;
grant execute on function public.activity_summary(int) to service_role;
