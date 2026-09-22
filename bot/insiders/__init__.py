"""Insajderzy — kto z wewnątrz kupuje i sprzedaje akcje, i co z tego wyszło.

Trzy źródła, wszystkie oficjalne i darmowe:

* **SEC Form 4** (`sec.py`) — prezesi, członkowie zarządu, rady dyrektorów
  i udziałowcy powyżej 10%. Historia z kwartalnych paczek SEC, bieżące dni
  z dziennych indeksów, a świeże zgłoszenia z kanału „getcurrent".
* **Izba Reprezentantów** (`house.py`) — zgłoszenia transakcji kongresmenów
  (STOCK Act) w PDF-ach, czytane parserem tekstu, a w razie kłopotu modelem.
* **OGE** (`oge.py`) — prezydent i członkowie gabinetu. Skany OGE mają fatalne
  OCR, więc bierzemy je już odczytane z otwartego repozytorium `open-cabinet`
  (licencja MIT), które co kilka dni przerabia nowe formularze.

Senatu świadomie nie ma: `efdsearch.senate.gov` odrzuca automaty (403
z każdego adresu, na którym to sprawdzaliśmy). Wolimy brak niż źródło, które
raz działa, a raz nie.

Wszystko ląduje w jednej bazie SQLite na trwałym dysku (`store.py`). To dane
publiczne i wspólne dla wszystkich kont — Supabase trzyma tylko to, co należy
do konkretnego użytkownika: kogo obserwuje (`follow.py`).
"""
