-- Złoto w portfelu pokazowym — żeby było na czym zobaczyć, jak działa majątek.
--
-- Wklej w Supabase → SQL Editor → Run, PO uruchomieniu 0003. Można puszczać
-- wielokrotnie: skrypt najpierw kasuje poprzednie aktywo o tej nazwie.
--
-- Podmień adres e-mail na ten, którego używa konto pokazowe (zmienna
-- DEMO_EMAIL w Railway; jeśli ustawiasz DEMO_USER_ID, wstaw identyfikator
-- wprost zamiast podzapytania).

do $$
declare
  demo_uid uuid;
  pid uuid;
  aid uuid;
begin
  -- ⬇⬇⬇  TU WPISZ ADRES KONTA POKAZOWEGO  ⬇⬇⬇
  select id into demo_uid from auth.users
   where lower(email) = lower('borygoo45@gmail.com');

  if demo_uid is null then
    raise notice 'Nie ma takiego użytkownika — popraw adres e-mail w skrypcie.';
    return;
  end if;

  -- Portfel, do którego wpada majątek konta pokazowego.
  insert into public.portfolios (user_id, name, color, icon, sort)
  values (demo_uid, 'Majątek', '#ffd24a', '🏦', 10)
  on conflict (user_id, name) do update set color = excluded.color
  returning id into pid;

  -- Czyścimy poprzednie, żeby ponowne uruchomienie nie mnożyło sztabek.
  delete from public.manual_assets
   where user_id = demo_uid and name = 'Złoto inwestycyjne';

  -- 3500 zł w złocie. Wycena `auto`: ilość razy kurs uncji z rynku, więc
  -- wartość i wykres żyją same, bez dopisywania czegokolwiek ręcznie.
  -- Ilość policzona przy kursie około 4437 USD za uncję i 3,72 PLN za dolara:
  -- 3500 / (4437 * 3,72) ≈ 0,212 uncji. Wartość będzie się wahać z kursem
  -- złota i dolara i TAK MA BYĆ — to jest sens wyceny automatycznej.
  insert into public.manual_assets
    (user_id, portfolio_id, name, category, pricing, symbol, quantity,
     currency, cost, cost_date, note, sort)
  values
    (demo_uid, pid, 'Złoto inwestycyjne', 'metal', 'auto', 'GC=F', 0.212,
     'USD', 3500, to_char(current_date - interval '6 months', 'YYYY-MM-DD'),
     'Przykładowa pozycja konta pokazowego — 3500 zł ulokowane w złocie.', 0)
  returning id into aid;

  raise notice 'Gotowe. Portfel % i złoto % dodane do konta pokazowego.', pid, aid;
end $$;
