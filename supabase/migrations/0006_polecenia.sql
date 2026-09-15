-- Kody polecające twórców (kampania z twórcami na TikToku).
--
-- Wklej całość w Supabase → SQL Editor → Run. Skrypt można puszczać wielokrotnie.
-- Wymaga 0001 (profiles, entitlements, premium_events).
--
-- Jak to działa w skrócie:
--   * twórca dostaje kod (np. KASIA); właściciel zakłada go w „Więcej" → Ustawienia
--     dev → Kody polecające albo wprost w tabeli `referral_codes`;
--   * użytkownik wpisuje kod przy logowaniu (także przez Google), w „Więcej"
--     albo na ekranie zakupu — jedno konto = jeden kod, bez zmiany na inny;
--   * pierwsze `free_slots` osób dostaje `free_days` dni premium od twórcy
--     („kto pierwszy, ten lepszy") — tylko w przeglądarce, patrz `apply_referral`;
--   * prowizję liczy się z płatności w `premium_events` (purchase / renewal)
--     od kont przypisanych do kodu, zawsze od chwili przypisania.
--
-- ZASADA: te tabele są WYŁĄCZNIE dla serwera (klucz serwisowy). RLS jest włączony
-- i celowo nie ma żadnej polityki — telefon nie ma jak przypisać sobie kodu
-- z pominięciem sprawdzeń ani podejrzeć, kto przyszedł od którego twórcy.

-- ========================================================= kody twórców

create table if not exists public.referral_codes (
  -- Wielkie litery, cyfry, „-" i „_". Serwer normalizuje wpis użytkownika
  -- (spacje, małe litery, „@" z nicku), więc „@kasia" i „KASIA" to ten sam kod.
  code            text primary key check (code ~ '^[A-Z0-9_-]{3,24}$'),
  creator_name    text not null,
  -- nick na TikToku — do raportu i do rozpoznania twórcy w panelu
  creator_handle  text,
  -- adres, na który idzie comiesięczny raport; po nim też odsiewamy
  -- „polecenie samego siebie" (twórca wpisujący własny kod)
  contact_email   text,

  -- procent od przychodu netto z płatności poleconych kont
  commission_pct  numeric(5,2) not null default 50 check (commission_pct between 0 and 100),

  -- Darmowe premium dla widzów: ile miejsc, ile zajętych i na ile dni.
  -- `free_used` podbija się atomowo w `apply_referral`, więc przy pięciu
  -- miejscach dwie osoby wpisujące kod w tej samej sekundzie nie zrobią szóstego.
  free_slots      integer not null default 5 check (free_slots >= 0),
  free_used       integer not null default 0 check (free_used >= 0),
  free_days       integer not null default 30 check (free_days >= 0),

  active          boolean not null default true,
  note            text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

comment on table public.referral_codes is
  'Kody polecające twórców: prowizja, pula darmowego premium, kontakt do raportu.';

-- ================================================ przypisania kont do kodów

create table if not exists public.referrals (
  id          bigserial primary key,
  -- `on delete set null`, a nie kaskada: gdy polecony skasuje konto, jego
  -- przeszłe płatności dalej należą się twórcy i raport nie może ich zgubić
  user_id     uuid unique references auth.users (id) on delete set null,
  code        text not null references public.referral_codes (code) on update cascade,
  -- gdzie wpisano kod: 'signup' okno logowania, 'more' ekran „Więcej",
  -- 'paywall' ekran zakupu, 'link' wejście z adresu portevo.pl/k/KOD
  source      text not null default 'more'
              check (source in ('signup', 'more', 'paywall', 'link')),
  platform    text,
  -- ile dni darmowego premium dostało to konto z puli twórcy (null = nic)
  reward_days integer,
  reward_at   timestamptz,
  created_at  timestamptz not null default now()
);

create index if not exists referrals_code_idx on public.referrals (code, created_at);

comment on table public.referrals is
  'Które konto przyszło od którego twórcy. Jedno konto = jeden kod, na zawsze.';

alter table public.referral_codes enable row level security;
alter table public.referrals      enable row level security;

drop trigger if exists referral_codes_touch on public.referral_codes;
create trigger referral_codes_touch before update on public.referral_codes
  for each row execute function public.touch_updated_at();

-- Prowizja z App Store: płatność zapisuje się w `premium_events` z numerem
-- transakcji w `meta`. Ten indeks pozwala tanio sprawdzić „czy już ją liczyliśmy"
-- — Apple przysyła tę samą transakcję przy zakupie, przywracaniu i powiadomieniu.
create index if not exists premium_events_txn_idx
  on public.premium_events ((meta ->> 'transakcja')) where meta ? 'transakcja';

-- ============================================================ przypisanie

-- Jedno wywołanie, jedna transakcja: sprawdzenie kodu, przypisanie konta
-- i ewentualne darmowe premium. W Pythonie byłyby to cztery osobne zapytania,
-- a między nimi wyścig o ostatnie wolne miejsce z puli.
--
-- p_reward = false → samo przypisanie. Tak woła serwer dla aplikacji z App Store
-- i Google Play: odblokowanie premium kodem wpisanym W APLIKACJI to własny
-- mechanizm odblokowania treści (wytyczna Apple 3.1.1) i odrzucenie wydania.
-- Premium odebrane na stronie działa potem w aplikacji zgodnie z 3.1.3(b).
-- Ponowne wpisanie TEGO SAMEGO kodu w przeglądarce odbiera nagrodę, jeśli
-- jeszcze jest pula — dzięki temu nikt nie traci, że zaczął od iPhone'a.
create or replace function public.apply_referral(
  p_user uuid, p_code text, p_source text default 'more',
  p_platform text default '', p_reward boolean default false
) returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_code   text := upper(regexp_replace(coalesce(p_code, ''), '[\s@#]', '', 'g'));
  v_src    text := case when p_source in ('signup', 'more', 'paywall', 'link') then p_source else 'more' end;
  c        public.referral_codes%rowtype;
  r        public.referrals%rowtype;
  v_email  text;
  v_days   integer;
  v_left   integer;
begin
  if p_user is null then
    return jsonb_build_object('ok', false, 'error', 'login');
  end if;

  select * into c from public.referral_codes where code = v_code;
  if not found or not c.active then
    return jsonb_build_object('ok', false, 'error', 'unknown');
  end if;

  select * into r from public.referrals where user_id = p_user;

  if found and r.code <> v_code then
    return jsonb_build_object('ok', false, 'error', 'other', 'code', r.code);
  end if;

  if not found then
    select lower(email) into v_email from auth.users where id = p_user;
    if c.contact_email is not null and v_email = lower(c.contact_email) then
      return jsonb_build_object('ok', false, 'error', 'own');
    end if;

    -- „Ostatnia szansa" jest przy zakupie: konto, które już płaci, nie dopisze
    -- sobie kodu. Inaczej twórcy mogliby zbierać prowizję od klientów, których
    -- nie przyprowadzili — wystarczyłoby poprosić o wpisanie kodu. Kto płacił
    -- kiedyś i zrezygnował, może wrócić z kodem — wtedy twórca realnie go odzyskał.
    if exists (select 1 from public.entitlements e
                where e.user_id = p_user and e.product = 'premium'
                  and e.source in ('stripe', 'apple')
                  and (e.expires_at is null or e.expires_at > now())) then
      return jsonb_build_object('ok', false, 'error', 'paid');
    end if;

    insert into public.referrals (user_id, code, source, platform)
    values (p_user, v_code, v_src, nullif(p_platform, ''))
    on conflict (user_id) do nothing
    returning * into r;

    if r.id is null then
      -- równoległe przypisanie z drugiego urządzenia wygrało wyścig
      select * into r from public.referrals where user_id = p_user;
      if r.code <> v_code then
        return jsonb_build_object('ok', false, 'error', 'other', 'code', r.code);
      end if;
    end if;
  end if;

  -- ------------------------------------------------ darmowe premium od twórcy
  v_days := null;
  if p_reward and r.reward_at is null and c.free_days > 0
     -- kto już ma aktywne premium, nie zabiera miejsca komuś, kto go nie ma
     and not public.is_premium(p_user) then
    update public.referral_codes
       set free_used = free_used + 1
     where code = v_code and free_used < free_slots
    returning free_days into v_days;

    if v_days is not null then
      insert into public.entitlements (user_id, product, plan, source, expires_at, provider_ref, note)
      values (p_user, 'premium', 'trial', 'promo', now() + make_interval(days => v_days),
              'ref:' || v_code || ':' || p_user::text, 'Kod polecający ' || v_code)
      on conflict do nothing;

      update public.referrals set reward_days = v_days, reward_at = now() where id = r.id;
    end if;
  end if;

  select free_slots - free_used into v_left from public.referral_codes where code = v_code;

  return jsonb_build_object(
    'ok', true,
    'code', v_code,
    'creator', c.creator_name,
    'handle', c.creator_handle,
    'reward_days', v_days,
    'already_rewarded', r.reward_at is not null and v_days is null,
    'slots_left', greatest(v_left, 0)
  );
end $$;

revoke execute on function public.apply_referral(uuid, text, text, text, boolean)
  from public, anon, authenticated;
grant execute on function public.apply_referral(uuid, text, text, text, boolean) to service_role;
