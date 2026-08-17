"""Dokumenty prawne Portevo — JEDNO źródło treści dla strony i dla aplikacji.

Po co osobny moduł zamiast trzech plików HTML: te same teksty muszą być w trzech
miejscach naraz i muszą się zgadzać co do słowa.

  * strona internetowa — Apple i Google wymagają **publicznego adresu URL**
    polityki prywatności i wsparcia; musi otwierać się bez logowania i bez JS,
  * aplikacja na telefonie — recenzent App Store szuka tego samego wewnątrz apki,
  * ekran „usuń konto" — opisuje dokładnie to, co robi przycisk.

Dlatego treść siedzi tu jako dane, a `render_html()` i `/api/legal/...` tylko ją
podają. Zmiana zdania w polityce = jedna edycja, nie trzy.

Dane administratora bierzemy ze zmiennych środowiskowych — repozytorium jest
prywatne, ale adres i nazwa firmy to nie jest coś, co ma leżeć w kodzie.
"""

from __future__ import annotations

import os

# --------------------------------------------------------------- kto wydaje

# Administratora danych trzeba wskazać z imienia i nazwiska albo nazwy firmy — tego
# nie da się zgadnąć za właściciela i nie wolno tu wpisać czegoś nieprawdziwego.
# Dopóki `LEGAL_OWNER` nie jest ustawione, strona krzyczy zamiast kłamać.
OWNER_NAME = os.environ.get("LEGAL_OWNER") or "[UZUPEŁNIJ: LEGAL_OWNER — imię i nazwisko lub nazwa firmy]"
OWNER_MAIL = os.environ.get("LEGAL_EMAIL") or os.environ.get("OWNER_EMAIL") or "kontakt@portevo.pl"
OWNER_ADDR = os.environ.get("LEGAL_ADDRESS") or ""
SITE = (os.environ.get("PUBLIC_URL") or "https://portevo.pl").rstrip("/")
UPDATED = "11 sierpnia 2026"

_ADMIN = OWNER_NAME + (f", {OWNER_ADDR}" if OWNER_ADDR else "") + f" (kontakt: {OWNER_MAIL})"


def _sec(h: str, *body: str, bullets: list[str] | None = None) -> dict:
    return {"h": h, "p": [b for b in body if b], "list": bullets or []}


# --------------------------------------------------------------- dokumenty

PRIVACY = {
    "slug": "privacy",
    "path": "/prywatnosc",
    "title": "Polityka prywatności",
    "lead": "Krótko: przechowujemy tylko to, bez czego aplikacja nie zadziała. "
            "Nie sprzedajemy danych i nie śledzimy Cię po innych stronach.",
    "sections": [
        _sec(
            "Kto odpowiada za dane",
            f"Administratorem danych osobowych jest {_ADMIN}. "
            "W sprawach dotyczących danych pisz na ten adres — odpowiadamy do 30 dni.",
        ),
        _sec(
            "Jakie dane zbieramy",
            "Wyłącznie te, które sam podajesz albo które są niezbędne do działania konta:",
            bullets=[
                "Adres e-mail i hasło (hasło w postaci zaszyfrowanej) — do logowania. "
                "Przy logowaniu przez Google dostajemy adres e-mail i nazwę konta.",
                "Dane Twojego portfela: operacje z raportów, które sam wgrywasz, "
                "nazwy instrumentów, kwoty, obserwowane spółki i ustawienia aplikacji.",
                "Status płatności (czy i do kiedy masz premium).",
                "Dane techniczne zapytań do serwera: adres IP, godzina, rodzaj urządzenia — "
                "w logach, potrzebne do bezpieczeństwa i diagnozowania awarii.",
                "Zdarzenia produktowe: które funkcje premium klikasz — bez treści portfela, "
                "żeby wiedzieć, co rozwijać.",
            ],
        ),
        _sec(
            "Po co i na jakiej podstawie",
            "Dane konta i portfela przetwarzamy, żeby wykonać umowę o świadczenie usługi "
            "(art. 6 ust. 1 lit. b RODO). Logi i zabezpieczenia opieramy na prawnie "
            "uzasadnionym interesie (lit. f). Dokumenty księgowe za zakupy trzymamy, bo "
            "wymaga tego prawo podatkowe (lit. c).",
            "Nie stosujemy profilowania wywołującego skutki prawne ani automatycznego "
            "podejmowania decyzji wobec Ciebie.",
        ),
        _sec(
            "Czego NIE robimy",
            bullets=[
                "Nie sprzedajemy ani nie wynajmujemy danych.",
                "Nie łączymy się z Twoim rachunkiem maklerskim i nie mamy dostępu do Twoich "
                "pieniędzy — dane portfela biorą się wyłącznie z raportów, które wgrywasz.",
                "Nie wykonujemy transakcji w Twoim imieniu.",
                "Nie osadzamy reklam ani śledzących pikseli innych firm.",
            ],
        ),
        _sec(
            "Komu powierzamy dane",
            "Korzystamy z usług, bez których serwis nie mógłby działać. To podmioty "
            "przetwarzające, związane umowami powierzenia:",
            bullets=[
                "Supabase — konta, logowanie i baza danych (serwery w Unii Europejskiej).",
                "Railway — hosting serwera aplikacji.",
                "Google — wyłącznie gdy sam wybierzesz logowanie przez Google.",
                "Dostawcy notowań i danych rynkowych — dostają symbol instrumentu, "
                "nigdy Twoich danych osobowych ani wielkości pozycji.",
                "Modele językowe używane do analiz — dostają treść newsa lub raportu "
                "spółki, nie dane Twojego konta.",
            ],
        ),
        _sec(
            "Jak długo",
            "Dane konta trzymamy tak długo, jak istnieje konto. Po usunięciu konta kasujemy "
            "je razem z portfelem — natychmiast i bezpowrotnie. Logi techniczne wygasają po "
            "90 dniach. Dokumenty księgowe przechowujemy 5 lat, bo tak każe prawo.",
        ),
        _sec(
            "Twoje prawa",
            "Masz prawo dostępu do danych, ich sprostowania, usunięcia, ograniczenia "
            "przetwarzania, przenoszenia oraz sprzeciwu. Możesz też złożyć skargę do Prezesa "
            "Urzędu Ochrony Danych Osobowych (ul. Stawki 2, 00-193 Warszawa).",
            "Usunięcie konta wraz ze wszystkimi danymi zrobisz sam, bez pisania do nas: "
            "w aplikacji zakładka „Więcej” → „Usuń konto”. Działa też w przeglądarce.",
        ),
        _sec(
            "Pamięć przeglądarki i pliki cookies",
            "Nie używamy plików cookies do śledzenia ani do reklam. W przeglądarce zapisujemy "
            "wyłącznie dane niezbędne do działania aplikacji, w pamięci lokalnej urządzenia:",
            bullets=[
                "token zalogowanej sesji — inaczej wylogowywałoby Cię przy każdym odświeżeniu,",
                "ustawienia widoku: wybrane tło, ostatnia zakładka, adres serwera.",
            ],
            # najczęstsze pytanie z banera — odpowiedź musi być tuż obok listy
        ),
        _sec(
            "Dzieci",
            "Serwis nie jest przeznaczony dla osób poniżej 16 roku życia i świadomie nie "
            "zbieramy ich danych.",
        ),
        _sec(
            "Zmiany",
            f"Ostatnia aktualizacja: {UPDATED}. O istotnych zmianach informujemy w aplikacji "
            "przed ich wejściem w życie.",
        ),
    ],
}

TERMS = {
    "slug": "terms",
    "path": "/regulamin",
    "title": "Regulamin",
    "lead": "Portevo pokazuje i analizuje Twój portfel. Nie jest doradcą inwestycyjnym "
            "i nie wykonuje transakcji.",
    "sections": [
        _sec(
            "Czym jest Portevo",
            f"Portevo to aplikacja ({SITE} oraz aplikacja mobilna) do śledzenia portfela "
            "inwestycyjnego, kalendarza wyników spółek i wydarzeń rynkowych. Usługę świadczy "
            f"{_ADMIN}.",
        ),
        _sec(
            "To nie jest porada inwestycyjna",
            "Treści w aplikacji mają charakter informacyjny i edukacyjny. Nie stanowią porady "
            "inwestycyjnej, rekomendacji ani oferty kupna lub sprzedaży instrumentów "
            "finansowych w rozumieniu obowiązujących przepisów.",
            "Część analiz przygotowuje model językowy i mogą one zawierać błędy. Notowania "
            "pochodzą od zewnętrznych dostawców, bywają opóźnione i mogą być niekompletne. "
            "Decyzje inwestycyjne podejmujesz wyłącznie na własną odpowiedzialność i ryzyko.",
        ),
        _sec(
            "Konto",
            "Do korzystania z części funkcji potrzebne jest konto. Podaj prawdziwy adres "
            "e-mail, nie udostępniaj hasła i nie zakładaj konta za kogoś innego. Konto możesz "
            "usunąć w każdej chwili w zakładce „Więcej”; usunięcie kasuje także dane portfela.",
        ),
        _sec(
            "Wersja płatna — subskrypcja Portevo Premium",
            "Część funkcji jest płatna. Cena, okres rozliczeniowy i zakres są widoczne przed "
            "zakupem, na tym samym ekranie, na którym stoi przycisk zakupu.",
            "Dostępne są dwa okresy rozliczeniowe: miesięczny (1 miesiąc) i roczny "
            "(12 miesięcy). Oba są subskrypcjami odnawialnymi automatycznie: po zakończeniu "
            "okresu przedłużają się na kolejny taki sam okres i pobierana jest kolejna opłata, "
            "dopóki nie wyłączysz odnawiania.",
            "Jeśli jesteś konsumentem, masz 14 dni na odstąpienie od umowy. Rozpoczynając "
            "korzystanie z treści cyfrowych od razu, zgadzasz się na wykonanie usługi przed "
            "upływem tego terminu, co — zgodnie z przepisami — wyłącza prawo odstąpienia w "
            "zakresie już wykonanym.",
        ),
        _sec(
            "Zakupy w aplikacji na iPhonie (App Store)",
            "W aplikacji na iOS subskrypcję sprzedaje i rozlicza Apple, w ramach zakupu "
            "w aplikacji. Obowiązują wtedy poniższe zasady Apple:",
            bullets=[
                "Opłata pobierana jest z konta App Store w chwili potwierdzenia zakupu.",
                "Subskrypcja odnawia się automatycznie, a konto jest obciążane za kolejny "
                "okres w ciągu 24 godzin przed końcem bieżącego okresu.",
                "Odnawianie wyłączysz sam: Ustawienia iPhone’a → Twoje imię → Subskrypcje. "
                "Trzeba to zrobić najpóźniej 24 godziny przed końcem okresu; wyłączenie "
                "w trakcie okresu nie skraca dostępu, który zostaje do jego końca.",
                "Aktualną cenę i walutę zawsze pokazuje App Store — to ona jest wiążąca.",
                "Niewykorzystanej części okresu nie zwracamy, gdy sam zrezygnujesz; wnioski "
                "o zwrot rozpatruje Apple (reportaproblem.apple.com), nie my.",
            ],
        ),
        _sec(
            "Umowa licencyjna (EULA)",
            "Ten regulamin jest jednocześnie umową licencyjną użytkownika końcowego. "
            "Udzielamy Ci niezbywalnej, niewyłącznej licencji na korzystanie z aplikacji "
            "Portevo na urządzeniach, których jesteś właścicielem lub które kontrolujesz, "
            "zgodnie z zasadami sklepu, z którego pobrałeś aplikację.",
            "Umowa jest zawierana wyłącznie między Tobą a nami — Apple nie jest jej stroną. "
            "Za aplikację, jej treść i wsparcie odpowiadamy my; Apple nie ma obowiązku "
            "świadczenia wsparcia ani obsługi ewentualnych roszczeń dotyczących aplikacji. "
            "Apple i jego podmioty zależne są beneficjentami tej umowy i mogą egzekwować jej "
            "postanowienia wobec Ciebie jako jej strony trzeciej.",
            "Korzystając z aplikacji oświadczasz, że nie przebywasz w kraju objętym embargiem "
            "i nie figurujesz na listach podmiotów objętych sankcjami.",
            f"Pytania dotyczące tej umowy: {OWNER_MAIL}.",
        ),
        _sec(
            "Zasady korzystania",
            bullets=[
                "Nie obchodź zabezpieczeń ani ograniczeń wersji płatnej.",
                "Nie pobieraj danych automatycznie w sposób obciążający serwer.",
                "Nie odsprzedawaj dostępu ani danych z serwisu.",
            ],
        ),
        _sec(
            "Dostępność i odpowiedzialność",
            "Staramy się, żeby serwis działał bez przerw, ale nie gwarantujemy ciągłości — "
            "aktualizacje i awarie dostawców zdarzają się. Nie odpowiadamy za straty "
            "wynikające z decyzji inwestycyjnych ani z niedostępności danych rynkowych. "
            "Nie ogranicza to odpowiedzialności, której zgodnie z prawem wyłączyć nie można.",
        ),
        _sec(
            "Reklamacje",
            f"Reklamacje zgłaszaj na {OWNER_MAIL}. Odpowiadamy w ciągu 14 dni.",
        ),
        _sec(
            "Zmiany regulaminu",
            f"Ostatnia aktualizacja: {UPDATED}. O zmianach informujemy w aplikacji z "
            "wyprzedzeniem; dalsze korzystanie po ich wejściu w życie oznacza akceptację.",
        ),
    ],
}

SUPPORT = {
    "slug": "support",
    "path": "/kontakt",
    "title": "Kontakt i pomoc",
    "lead": "Piszesz na jeden adres i trafia to prosto do autora aplikacji.",
    "sections": [
        _sec(
            "Napisz do nas",
            f"E-mail: {OWNER_MAIL}",
            "Odpowiadamy zwykle w ciągu dwóch dni roboczych, najpóźniej w ciągu 14 dni.",
        ),
        _sec(
            "Najczęstsze sprawy",
            bullets=[
                "Nie widzę swoich danych — sprawdź, czy jesteś zalogowany na tym samym "
                "koncie; portfel jest przypisany do konta, nie do urządzenia.",
                "Wgrany raport nic nie zmienił — wgraj plik z historią operacji z rachunku "
                "maklerskiego (raport z XTB w formacie XLSX).",
                "Zapomniałem hasła — na ekranie logowania wybierz odzyskiwanie hasła.",
                "Chcę usunąć konto — zakładka „Więcej” → „Usuń konto”. Kasuje wszystko, "
                "od razu, bez pisania do nas.",
                "Kupiłem premium, a mam wersję darmową — w zakładce „Więcej” naciśnij "
                "„Odśwież”; jeśli nie pomoże, napisz i podaj adres e-mail konta.",
            ],
        ),
        _sec(
            "Zgłoszenie błędu",
            "Najbardziej pomaga: co robiłeś, co zobaczyłeś, jaki masz telefon lub "
            "przeglądarkę oraz zrzut ekranu. Wersję aplikacji znajdziesz w „Więcej” → "
            "„Połączenie”.",
        ),
        _sec(
            "Ważne dokumenty",
            bullets=[
                f"Polityka prywatności: {SITE}/prywatnosc",
                f"Regulamin: {SITE}/regulamin",
            ],
        ),
    ],
}

DOCS = {d["slug"]: d for d in (PRIVACY, TERMS, SUPPORT)}

#: adresy URL → dokument; osobno polskie (kanoniczne) i angielskie (dla sklepów)
ROUTES = {
    "/prywatnosc": "privacy", "/privacy": "privacy",
    "/regulamin": "terms", "/terms": "terms",
    "/kontakt": "support", "/support": "support",
}


def doc(slug: str) -> dict | None:
    """Dokument w postaci danych — tego używa aplikacja przez `/api/legal/...`."""
    d = DOCS.get(slug)
    if not d:
        return None
    return {"slug": d["slug"], "title": d["title"], "lead": d["lead"],
            "updated": UPDATED, "url": SITE + d["path"], "sections": d["sections"]}


# ------------------------------------------------------------------- strona

_CSS = """
:root{--bg:#0a0d13;--card:#141926;--border:#232b3d;--text:#e8ebf2;--muted:#8b93a7;
--dim:#5c6479;--green:#2fd48a}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--text);
font:16px/1.65 "Segoe UI Variable Display","Segoe UI",system-ui,sans-serif}
.wrap{max-width:760px;margin:0 auto;padding:34px 22px 90px}
a{color:var(--green)}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:40px;
font-size:13.5px}
.top a{color:var(--muted);text-decoration:none}
.top a:hover{color:var(--text)}
h1{font-size:clamp(28px,5vw,38px);font-weight:800;letter-spacing:-1px;line-height:1.15}
.lead{color:var(--muted);margin-top:14px;font-size:17px}
.upd{color:var(--dim);font-size:12.5px;margin-top:10px}
section{margin-top:34px;padding-top:26px;border-top:1px solid var(--border)}
h2{font-size:19px;font-weight:800;letter-spacing:-.2px;margin-bottom:12px}
p{color:var(--muted);margin-top:10px}
ul{margin:12px 0 0;padding:0;list-style:none;display:grid;gap:9px}
li{color:var(--muted);padding-left:22px;position:relative}
li::before{content:"";position:absolute;left:4px;top:.62em;width:6px;height:6px;
border-radius:50%;background:var(--green)}
footer{margin-top:52px;color:var(--dim);font-size:12.5px;text-align:center}
footer a{color:var(--dim);margin:0 8px}
"""


def _esc(t: str) -> str:
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render_html(slug: str) -> str | None:
    """Zwykła strona HTML — bez JS, bez zależności, otwiera się w każdej przeglądarce.

    Recenzent App Store i Google wchodzą na ten adres z automatu; strona ma się
    pokazać nawet wtedy, gdy aplikacja webowa akurat się nie zbudowała.
    """
    d = DOCS.get(slug)
    if not d:
        return None

    parts = []
    for s in d["sections"]:
        body = "".join(f"<p>{_esc(p)}</p>" for p in s["p"])
        if s["list"]:
            body += "<ul>" + "".join(f"<li>{_esc(x)}</li>" for x in s["list"]) + "</ul>"
        parts.append(f"<section><h2>{_esc(s['h'])}</h2>{body}</section>")

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(d['title'])} — Portevo</title>
<meta name="description" content="{_esc(d['lead'])}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{SITE}{d['path']}">
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="top"><a href="/">← Portevo</a><span>{_esc(UPDATED)}</span></div>
  <h1>{_esc(d['title'])}</h1>
  <p class="lead">{_esc(d['lead'])}</p>
  <p class="upd">Obowiązuje od {_esc(UPDATED)}</p>
  {''.join(parts)}
  <footer>
    <a href="/prywatnosc">Prywatność</a>·<a href="/regulamin">Regulamin</a>
    ·<a href="/kontakt">Kontakt</a>·<a href="/">Aplikacja</a>
  </footer>
</div>
</body>
</html>"""
