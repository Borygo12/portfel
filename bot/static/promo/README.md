# Zrzuty ekranu do sekcji „Aplikacja"

Tu leżą obrazki pokazywane w zakładce **Aplikacja** (`/aplikacja`).
Serwer podaje ten katalog pod adresem `/static/promo/`.

Nazwy plików muszą się zgadzać co do znaku z listą `ZRZUTY`
w `mobile/src/promo.ts` — tam też zmienia się podpisy i dokłada kafelki.

| plik             | co pokazuje                                        |
|------------------|----------------------------------------------------|
| `portfel.webp`   | wartość portfela i przebieg z wpłatami              |
| `kalendarz.webp` | kalendarz wyników spółek                            |
| `fundusz.webp`   | skład ETF-u (spółki, kraje, waluty)                 |
| `korelacje.webp` | korelacje pozycji w portfelu                        |

**Dopóki pliku nie ma, nic się nie psuje**: kafelek rysuje ramkę z napisem
„zrzut wkrótce", a układ strony zostaje taki sam. Po wrzuceniu pliku obrazek
podmienia się sam — ale przy zmianie NAZWY trzeba przebudować web (`promo.ts`).

Proporcja kafelka to 9:19,5 (ekran telefonu), więc zrzut prosto z iPhone'a
albo Androida wejdzie bez przycinania. Szerokość 900 px w zupełności wystarcza —
kafelek na stronie ma ok. 150 px.

**Format: WEBP, nie PNG.** Te same kadry w PNG ważą ~1,5 MB sztuka (6 MB na
stronę), w WEBP ~70 kB i w kafelku nie widać różnicy. Przeliczenie:

```bash
python -c "from PIL import Image; im=Image.open('wejscie.png').convert('RGB'); im.resize((900, round(im.height*900/im.width)), Image.LANCZOS).save('wyjscie.webp', quality=82, method=6)"
```

## Skąd te kadry — i czego z nimi jeszcze nie zrobiono

Pochodzą z `app-store/screenshots/iphone-6.5/` (kolaże marketingowe zrobione
generatorem). Nagłówki i kompozycja są dobre, ale **napisy wewnątrz ekranu
telefonu model zmyślił** — w powiększeniu widać „Missiąc", „Najjepsze",
„Dakle to procuje". Dlatego podpis sekcji na stronie brzmi „Materiały
prezentacyjne", a nie „Prawdziwe ekrany".

Do zrobienia: prawdziwe zrzuty z symulatora iOS albo z builda webowego w oknie
o proporcjach telefonu, wklejone w te same ramki. Wtedy podpis sekcji
w `AppPromoScreen.tsx` można wzmocnić z powrotem.
