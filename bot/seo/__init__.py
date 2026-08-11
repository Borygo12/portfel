"""Warstwa SEO Portevo — strony, które musi zobaczyć Google, a nie tylko człowiek.

Po co to w ogóle istnieje osobno od aplikacji:

Interfejs Portevo to jedna aplikacja w React Native, eksportowana przez Expo do
`web/` jako **pojedynczy plik `index.html` plus bundle JavaScriptu**. Cały ekran
rysuje się dopiero po uruchomieniu skryptu, a nawigacja siedzi w `useState` —
nie ma adresów URL dla zakładek i nie ma żadnego HTML-a, który dałoby się
zaindeksować. Robot, który wchodzi na dowolny adres, dostaje pusty `<div id="root">`.
Dla wyszukiwarki to jedna strona bez treści.

Dlatego treść pozycjonowana NIE jest ekranem aplikacji, tylko zwykłymi stronami
generowanymi tu, po stronie serwera: bez JavaScriptu, bez zależności, gotowe
w pierwszej odpowiedzi HTTP. Ten sam wzorzec, co `legal.py` — tam sprawdził się
przy recenzentach App Store, którzy otwierają adres bez konta i bez skryptów.

Podział na pliki:

  site.py         — adres kanoniczny, brand, domyślne opisy; jedno źródło prawdy
  keywords.py     — polskie frazy w klastrach, dobierane per podstrona
  render.py       — szkielet strony: styl, nagłówek, stopka, sekcje, FAQ
  jsonld.py       — dane strukturalne schema.org (to czyta Google i modele AI)
  features.py     — podstrony funkcji (kalendarz wyników, portfel, ETF…)
  companies.py    — katalog spółek z GPW i USA, z których robią się podstrony
  company_page.py — złożenie podstrony jednej spółki z danych z `earnings/`
  guides.py       — poradniki pod frazy informacyjne
  glossary.py     — słownik pojęć giełdowych
  shell.py        — wstrzykiwanie meta i ikon do `web/index.html` aplikacji
  routes.py       — router FastAPI: adresy, sitemap, robots, llms.txt

Zasada, której trzymamy się wszędzie: to, co widzi robot, ma być dokładnie tym,
co widzi człowiek. Żadnych tekstów ukrytych pod `display:none`, żadnego
podstawiania innej treści pod User-Agenta wyszukiwarki. Google nazywa to
cloakingiem i karze wyrzuceniem z indeksu — a nam wystarczy, że strony są po
prostu dobre.
"""
