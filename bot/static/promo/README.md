# Zrzuty ekranu do sekcji „Aplikacja"

Tu wrzuca się obrazki pokazywane w zakładce **Aplikacja** (`/aplikacja`).
Serwer podaje ten katalog pod adresem `/static/promo/`.

Oczekiwane pliki — nazwy muszą się zgadzać co do znaku:

| plik            | co ma pokazywać                                    |
|-----------------|----------------------------------------------------|
| `kalendarz.png` | kalendarz wyników spółek                            |
| `portfel.png`   | ekran portfela z wyceną                             |
| `spolka.png`    | karta spółki z prognozami                           |
| `alokacja.png`  | podział portfela                                    |

Lista jest w `mobile/src/promo.ts` (stała `ZRZUTY`) — tam też zmienia się
podpisy i dokłada kolejne kafelki.

**Dopóki pliku nie ma, nic się nie psuje**: kafelek rysuje ramkę z napisem
„zrzut wkrótce", a układ strony zostaje taki sam. Po wrzuceniu pliku obrazek
podmienia się sam, bez zmian w kodzie i bez przebudowy aplikacji.

Proporcja kafelka to 9:19,5 (ekran telefonu), więc zrzut prosto z iPhone'a
albo Androida wejdzie bez przycinania. Rozsądna szerokość to 750–1200 px —
większe pliki tylko spowalniają wczytywanie strony.
