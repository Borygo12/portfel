-- Insajderzy: kogo obserwuje użytkownik (powiadomienia o transakcjach persony).
--
-- Wklej całość w Supabase → SQL Editor → Run. Skrypt można puszczać wielokrotnie.
-- Wymaga 0001 (auth) i 0005 (notifications — tam lądują powiadomienia).
--
-- Same transakcje NIE są w Supabase: to dane publiczne, wspólne i odtwarzalne,
-- trzymane w SQLite na dysku serwera (bot/insiders/store.py). Tu jest wyłącznie
-- to, co należy do konkretnego człowieka.

create table if not exists public.insider_follows (
  user_id     uuid not null default auth.uid()
              references auth.users (id) on delete cascade,
  -- identyfikator persony z bot/insiders/people.py: „nancy-pelosi",
  -- „sec-1494730", „house-greene-marjorie-ga14"…
  person_id   text not null,
  -- nazwa w chwili dodania — żeby lista w panelu dało się pokazać bez
  -- sięgania do bazy transakcji, i żeby było wiadomo, kogo dotyczył wiersz
  person_name text not null default '',
  created_at  timestamptz not null default now(),
  primary key (user_id, person_id)
);

-- silnik powiadomień pyta „kto obserwuje tę personę" — po person_id
create index if not exists insider_follows_person_idx on public.insider_follows (person_id);

alter table public.insider_follows enable row level security;

do $$ begin
  create policy "swoje obserwowane persony" on public.insider_follows
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());
exception when duplicate_object then null; end $$;

-- Supabase nadaje to domyślnie nowym tabelom w `public`, ale serwer łączy się
-- rolą `authenticated` (db.py) — lepiej mieć to zapisane wprost niż polegać
-- na ustawieniach projektu, które ktoś kiedyś może zmienić.
grant select, insert, update, delete on public.insider_follows to authenticated;

comment on table public.insider_follows is
  'Persony (insiderzy), których transakcje użytkownik chce dostawać jako powiadomienia.';
