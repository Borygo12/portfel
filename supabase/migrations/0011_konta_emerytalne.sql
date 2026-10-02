-- Konta emerytalne: IKE, IKZE i OKI.
--
-- Wklej całość w Supabase → SQL Editor → Run. Skrypt można puszczać wielokrotnie.
--
-- Rachunek emerytalny to dla brokera zwykły rachunek z innym regulaminem, więc
-- nie budujemy dla niego osobnych tabel — dostaje jedną etykietę. Dzięki temu
-- dalej widać go w Przeglądzie razem ze wszystkim, a narzędzie „Konta emerytalne"
-- po prostu wybiera rachunki z etykietą i liczy je osobno.

-- '' = zwykły rachunek, 'ike', 'ikze', 'oki'
alter table public.accounts
  add column if not exists kind text not null default '';

-- Skąd wzięła się etykieta: 'auto' = rozpoznana z raportu, 'user' = ustawiona
-- ręcznie. Ręczna wygrywa zawsze — ponowne wgranie raportu nie może cofnąć
-- poprawki człowieka.
alter table public.accounts
  add column if not exists kind_source text not null default '';

comment on column public.accounts.kind is
  'Rodzaj rachunku: pusty = zwykły, ike, ikze, oki. Steruje narzędziem „Konta emerytalne".';

-- To samo dla majątku dopisanego ręcznie albo odczytanego przez AI z raportu
-- innego brokera: pozycja z IKE w mBanku ma trafić do IKE, a nie do „reszty".
alter table public.manual_assets
  add column if not exists account_kind text not null default '';

comment on column public.manual_assets.account_kind is
  'Na jakim rodzaju konta leży aktywo: pusty = zwykłe, ike, ikze, oki.';
