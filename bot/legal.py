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

    lang = d.get("lang", "pl")
    # Etykiety obudowy strony (powrót, data, stopka) idą za językiem dokumentu:
    # angielska polityka z polską stopką wygląda jak pomyłka, a to ten adres
    # ogląda recenzent App Store w lokalizacji en-US.
    if lang == "en":
        wroc, obowiazuje = "← Portevo", "Effective from"
        stopka = [("/privacy", "Privacy"), ("/terms", "Terms"),
                  ("/privacy-choices", "Privacy choices"), ("/support", "Contact"),
                  ("/", "App")]
    else:
        wroc, obowiazuje = "← Portevo", "Obowiązuje od"
        stopka = [("/prywatnosc", "Prywatność"), ("/regulamin", "Regulamin"),
                  ("/prywatnosc/wybory", "Twoje wybory"), ("/kontakt", "Kontakt"),
                  ("/", "Aplikacja")]
    stopka_html = "·".join(f'<a href="{a}">{_esc(t)}</a>' for a, t in stopka)

    return f"""<!DOCTYPE html>
<html lang="{lang}">
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
  <div class="top"><a href="/">{wroc}</a><span>{_esc(UPDATED)}</span></div>
  <h1>{_esc(d['title'])}</h1>
  <p class="lead">{_esc(d['lead'])}</p>
  <p class="upd">{obowiazuje} {_esc(UPDATED)}</p>
  {''.join(parts)}
  <footer>{stopka_html}</footer>
</div>
</body>
</html>"""


# ------------------------------------------------- wersje angielskie i wybory

# Po co osobne dokumenty po angielsku, skoro aplikacja jest polska: App Store
# Connect trzyma adresy prawne OSOBNO dla każdej lokalizacji, a językiem
# podstawowym Portevo jest English (U.S.). Recenzent wchodzący na polski adres
# widzi dokument w języku, którego nie zna — a to on ocenia, czy odnośnik
# „działa". Treść jest tłumaczeniem, nie osobną umową: rozjazd wersji językowych
# byłby gorszy niż brak tłumaczenia, więc zmiany nanosi się w OBU naraz.

PRIVACY_EN = {
    "slug": "privacy-en",
    "path": "/privacy",
    "lang": "en",
    "title": "Privacy Policy",
    "lead": "In short: we store only what the app needs to work. We do not sell "
            "your data and we do not track you across other sites.",
    "sections": [
        _sec(
            "Who is responsible for your data",
            f"The data controller is {_ADMIN}. "
            "Write to that address in any matter concerning your data — we reply within 30 days.",
        ),
        _sec(
            "What we collect",
            "Only what you provide yourself or what the account cannot work without:",
            bullets=[
                "Email address and password (stored encrypted) — for signing in. "
                "When you sign in with Google we receive your email address and account name.",
                "Your portfolio data: transactions from the reports you upload, instrument "
                "names, amounts, watched companies and app settings.",
                "Payment status (whether and until when you have Premium).",
                "Technical request data: IP address, time, device type — kept in server logs "
                "for security and troubleshooting.",
                "Product events: which Premium features you open — without portfolio contents, "
                "so we know what to build next.",
            ],
        ),
        _sec(
            "Why, and on what legal basis",
            "Account and portfolio data are processed to perform the service agreement "
            "(Art. 6(1)(b) GDPR). Logs and security measures rely on our legitimate interest "
            "(Art. 6(1)(f)). Accounting records for purchases are kept because tax law "
            "requires it (Art. 6(1)(c)).",
            "We do not carry out profiling with legal effects, nor automated decision-making "
            "about you.",
        ),
        _sec(
            "What we do NOT do",
            bullets=[
                "We do not sell or rent your data.",
                "We do not connect to your brokerage account and have no access to your money "
                "— portfolio data comes only from the reports you upload.",
                "We do not execute transactions on your behalf.",
                "We embed no third-party advertising or tracking pixels.",
            ],
        ),
        _sec(
            "Who processes data on our behalf",
            "We use services the app could not run without. They are processors bound by "
            "data processing agreements:",
            bullets=[
                "Supabase — accounts, sign-in and database (servers in the European Union).",
                "Railway — application hosting.",
                "Google — only if you choose to sign in with Google.",
                "Market data providers — they receive the instrument symbol, never your "
                "personal data or position sizes.",
                "Language models used for analysis — they receive the text of a news item or "
                "a company report, not your account data.",
            ],
        ),
        _sec(
            "How long we keep it",
            "Account data is kept for as long as the account exists. When you delete the "
            "account we erase it together with the portfolio — immediately and irreversibly. "
            "Technical logs expire after 90 days. Accounting records are kept for 5 years "
            "because the law requires it.",
        ),
        _sec(
            "Your rights",
            "You have the right to access your data, rectify it, erase it, restrict processing, "
            "port it and object. You may also lodge a complaint with the President of the "
            "Personal Data Protection Office (ul. Stawki 2, 00-193 Warsaw, Poland).",
            "You can delete your account with all its data yourself, without writing to us: in "
            "the app, the “More” tab → “Delete account”. It also works in the browser.",
        ),
        _sec(
            "Browser storage and cookies",
            "We use no cookies for tracking or advertising. In the browser we store only what "
            "the app needs to run, in the local storage of your device:",
            bullets=[
                "the signed-in session token — otherwise every refresh would sign you out,",
                "view settings: chosen background, last tab, server address.",
            ],
        ),
        _sec(
            "Children",
            "The service is not intended for people under 16 and we do not knowingly collect "
            "their data.",
        ),
        _sec(
            "Changes",
            f"Last updated: {UPDATED}. We announce material changes in the app before they "
            "take effect.",
        ),
    ],
}

TERMS_EN = {
    "slug": "terms-en",
    "path": "/terms",
    "lang": "en",
    "title": "Terms of Use (EULA)",
    "lead": "Portevo shows and analyses your portfolio. It is not an investment adviser "
            "and it does not execute transactions.",
    "sections": [
        _sec(
            "What Portevo is",
            f"Portevo is an application ({SITE} and a mobile app) for tracking an investment "
            "portfolio, company earnings calendars and market events. The service is provided "
            f"by {_ADMIN}.",
        ),
        _sec(
            "This is not investment advice",
            "Content in the app is informational and educational. It is not investment advice, "
            "a recommendation, or an offer to buy or sell financial instruments.",
            "Part of the analysis is produced by a language model and may contain errors. "
            "Quotes come from third-party providers, may be delayed and may be incomplete. "
            "Investment decisions are yours alone, at your own risk.",
        ),
        _sec(
            "Account",
            "Some features require an account. Provide a real email address, do not share your "
            "password and do not create an account for somebody else. You can delete the "
            "account at any time in the “More” tab; deletion also erases portfolio data.",
        ),
        _sec(
            "Paid version — the Portevo Premium subscription",
            "Some features are paid. The price, the billing period and the scope are shown "
            "before purchase, on the same screen as the purchase button.",
            "Two billing periods are available: monthly (1 month) and yearly (12 months). Both "
            "are auto-renewable subscriptions: at the end of a period they renew for another "
            "period of the same length and a further charge is made, until you turn off "
            "automatic renewal.",
            "If you are a consumer you have 14 days to withdraw from the agreement. By starting "
            "to use the digital content immediately you agree to performance before that period "
            "ends, which — under applicable law — excludes the right of withdrawal to the "
            "extent already performed.",
        ),
        _sec(
            "In-app purchases on iPhone (App Store)",
            "In the iOS app the subscription is sold and billed by Apple as an in-app purchase. "
            "The following Apple rules then apply:",
            bullets=[
                "Payment is charged to your App Store account upon confirmation of purchase.",
                "The subscription renews automatically and the account is charged for the next "
                "period within 24 hours before the end of the current period.",
                "You can turn renewal off yourself: iPhone Settings → your name → "
                "Subscriptions. This must be done at least 24 hours before the period ends; "
                "turning it off during a period does not shorten access, which lasts until the "
                "end of that period.",
                "The current price and currency are always the ones shown by the App Store — "
                "those are binding.",
                "No refund is given for the unused part of a period if you cancel yourself; "
                "refund requests are handled by Apple (reportaproblem.apple.com), not by us.",
            ],
        ),
        _sec(
            "End User License Agreement (EULA)",
            "These terms are also the end user license agreement. We grant you a "
            "non-transferable, non-exclusive license to use the Portevo application on devices "
            "that you own or control, in accordance with the rules of the store you downloaded "
            "the application from.",
            "This agreement is concluded solely between you and us — Apple is not a party to "
            "it. We, not Apple, are responsible for the application, its content and support; "
            "Apple has no obligation to furnish maintenance and support services, or to handle "
            "any claims relating to the application. Apple and its subsidiaries are third-party "
            "beneficiaries of this agreement and may enforce it against you.",
            "By using the application you represent that you are not located in an embargoed "
            "country and are not listed on any sanctions list.",
            f"Questions about this agreement: {OWNER_MAIL}.",
        ),
        _sec(
            "Rules of use",
            bullets=[
                "Do not circumvent security measures or paid-version limits.",
                "Do not download data automatically in a way that burdens the server.",
                "Do not resell access to the service or its data.",
            ],
        ),
        _sec(
            "Availability and liability",
            "We do our best to keep the service running, but we do not guarantee continuity — "
            "updates and provider outages happen. We are not liable for losses resulting from "
            "investment decisions or from unavailability of market data. This does not limit "
            "liability that cannot be excluded by law.",
        ),
        _sec(
            "Complaints",
            f"Send complaints to {OWNER_MAIL}. We respond within 14 days.",
        ),
        _sec(
            "Changes to these terms",
            f"Last updated: {UPDATED}. We announce changes in the app in advance; continued use "
            "after they take effect means acceptance.",
        ),
    ],
}

SUPPORT_EN = {
    "slug": "support-en",
    "path": "/support",
    "lang": "en",
    "title": "Contact and support",
    "lead": "One address, and it goes straight to the author of the app.",
    "sections": [
        _sec(
            "Write to us",
            f"Email: {OWNER_MAIL}",
            "We usually reply within two business days, at the latest within 14 days.",
        ),
        _sec(
            "Most common matters",
            bullets=[
                "I cannot see my data — check that you are signed in to the same account; the "
                "portfolio belongs to the account, not to the device.",
                "The uploaded report changed nothing — upload the transaction history file "
                "from your brokerage account (an XTB report in XLSX format).",
                "I forgot my password — choose password recovery on the sign-in screen.",
                "I want to delete my account — the “More” tab → “Delete account”. "
                "It erases everything, at once, without writing to us.",
                "I bought Premium but still see the free version — in the “More” tab press "
                "“Refresh”; if that does not help, write to us with the account email address.",
            ],
        ),
        _sec(
            "Reporting a bug",
            "What helps most: what you did, what you saw, which phone or browser you use, and "
            "a screenshot. The app version is in “More” → “Connection”.",
        ),
        _sec(
            "Important documents",
            bullets=[
                f"Privacy Policy: {SITE}/privacy",
                f"Terms of Use (EULA): {SITE}/terms",
                f"Your privacy choices: {SITE}/privacy-choices",
            ],
        ),
    ],
}

# --------------------------------------------------------- wybory prywatności

# „User Privacy Choices URL" w App Store Connect to pole na stronę, na której
# człowiek realnie COŚ ROBI ze swoimi danymi, a nie czyta o nich kolejny raz.
# U nas wyborów jest mało, bo mało zbieramy — i dokładnie to ta strona mówi
# wprost, zamiast udawać panel z dziesięcioma przełącznikami do niczego.

_CHOICES_PL = [
    "Nie sprzedajemy i nie udostępniamy Twoich danych nikomu w celach "
    "marketingowych — nie ma więc czego wyłączać.",
    "Nie śledzimy Cię w innych aplikacjach ani na innych stronach. W aplikacji "
    "nie ma ani jednego SDK reklamowego, więc systemowe pytanie o zgodę na "
    "śledzenie (ATT) w ogóle się nie pojawia.",
    "Usunięcie konta i wszystkich danych: w aplikacji zakładka „Więcej” → "
    "„Usuń konto”. Działa też w przeglądarce, jest natychmiastowe i nie wymaga "
    "pisania do nas.",
    "Wgląd w dane i sprostowanie: portfel, obserwowane i ustawienia widzisz "
    "w aplikacji; poprawiasz je tam, gdzie je wprowadziłeś.",
    "Kopia danych albo sprzeciw wobec przetwarzania: napisz na adres niżej — "
    "odpowiadamy do 30 dni.",
    "Pamięć przeglądarki: zapisujemy tylko token sesji i ustawienia widoku. "
    "Wyczyścisz je, wylogowując się albo kasując dane witryny w przeglądarce.",
]

_CHOICES_EN = [
    "We do not sell or share your data with anyone for marketing purposes — so "
    "there is nothing here to opt out of.",
    "We do not track you across other apps or websites. The app contains no "
    "advertising SDK at all, which is why the system tracking prompt (ATT) never "
    "appears.",
    "Delete your account and all data: in the app, the “More” tab → "
    "“Delete account”. It also works in the browser, takes effect immediately "
    "and needs no message to us.",
    "Access and rectification: your portfolio, watchlist and settings are visible "
    "in the app; you correct them where you entered them.",
    "A copy of your data, or an objection to processing: write to the address "
    "below — we reply within 30 days.",
    "Browser storage: we keep only the session token and view settings. You can "
    "clear them by signing out or by clearing site data in your browser.",
]

CHOICES = {
    "slug": "choices",
    "path": "/prywatnosc/wybory",
    "title": "Twoje wybory prywatności",
    "lead": "Co możesz zrobić ze swoimi danymi w Portevo — i czego nie musisz "
            "wyłączać, bo tego nie robimy.",
    "sections": [
        _sec("Twoje wybory", bullets=_CHOICES_PL),
        _sec(
            "Kontakt w sprawach danych",
            f"Administrator: {_ADMIN}.",
            f"Pełna polityka prywatności: {SITE}/prywatnosc",
        ),
    ],
}

CHOICES_EN = {
    "slug": "choices-en",
    "path": "/privacy-choices",
    "lang": "en",
    "title": "Your privacy choices",
    "lead": "What you can do with your data in Portevo — and what you do not need "
            "to switch off, because we do not do it.",
    "sections": [
        _sec("Your choices", bullets=_CHOICES_EN),
        _sec(
            "Data protection contact",
            f"Controller: {_ADMIN}.",
            f"Full privacy policy: {SITE}/privacy",
        ),
    ],
}

_EN_DOCS = (PRIVACY_EN, TERMS_EN, SUPPORT_EN, CHOICES, CHOICES_EN)

DOCS.update({d["slug"]: d for d in _EN_DOCS})

# Adresy angielskie przejmują `/privacy`, `/terms` i `/support`: wcześniej były
# tylko aliasami polskich dokumentów, a to właśnie te adresy wpisuje się
# w sklepach dla lokalizacji angielskiej.
ROUTES.update({d["path"]: d["slug"] for d in _EN_DOCS})
