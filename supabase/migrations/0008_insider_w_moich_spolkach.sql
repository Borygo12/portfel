-- Powiadomienia „insider kupił/sprzedał spółkę z Twojego portfela".
--
-- Wklej w Supabase → SQL Editor → Run. Skrypt można puszczać wielokrotnie.
-- Wymaga 0005 (notification_prefs).
--
-- Domyślnie WŁĄCZONE, także dla kont bez premium: premium dostaje pełną treść
-- (kto, za ile, po ile), reszta — zapowiedź bez nazwiska i kwoty, najwyżej raz
-- dziennie, z przejściem do strony sprzedażowej. Kto nie chce — wyłącza tutaj.

alter table public.notification_prefs
  add column if not exists insider_holdings boolean not null default true;
