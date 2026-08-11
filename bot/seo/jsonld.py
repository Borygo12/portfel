"""Dane strukturalne schema.org — opis strony w formie, którą maszyny czytają wprost.

Po co, skoro treść jest w HTML-u: model językowy albo robot musi ZGADYWAĆ, co na
stronie jest nazwą spółki, co datą publikacji raportu, a co przypadkowym tekstem
w stopce. JSON-LD zdejmuje z niego to zgadywanie — mówimy wprost „to jest spółka,
to jest jej ticker, to jest pytanie i odpowiedź”. Google nie obiecuje za to
wyższej pozycji, ale ma to dwa mierzalne skutki: rozszerzone wyniki (FAQ,
okruszki) zabierają więcej miejsca w wynikach, a modele AI cytują takie strony
chętniej, bo mają z czego wziąć fakt bez interpretacji.

Zasada, od której nie ma odstępstwa: **w JSON-LD wolno opisać wyłącznie to, co
jest widoczne na stronie**. Zadeklarowane FAQ, którego użytkownik nie zobaczy,
to powód do ręcznej kary od Google — i słusznie, bo to obietnica bez pokrycia.
Dlatego funkcje FAQ przyjmują tę samą listę pytań, którą `render.faq()` rysuje.
"""

from __future__ import annotations

from . import site

ORGANIZACJA_ID = site.absolute("/#organizacja")
SERWIS_ID = site.absolute("/#serwis")


def organizacja() -> dict:
    """Kto wydaje serwis. Spina wszystkie strony w jeden byt (encję) dla Google."""
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "@id": ORGANIZACJA_ID,
        "name": site.NAME,
        "alternateName": "Portevo.pl",
        "url": site.URL,
        "logo": site.absolute("/static/seo/logo-portevo.png"),
        "image": site.absolute(site.OG_IMAGE),
        "email": site.EMAIL,
        "foundingDate": site.FOUNDED,
        "description": site.DESCRIPTION,
        "areaServed": {"@type": "Country", "name": "Polska"},
        "knowsLanguage": "pl-PL",
        "contactPoint": {
            "@type": "ContactPoint",
            "contactType": "obsługa klienta",
            "email": site.EMAIL,
            "availableLanguage": ["pl"],
        },
    }


def serwis() -> dict:
    """Sam serwis jako witryna — wiąże domenę z wydawcą."""
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "@id": SERWIS_ID,
        "name": site.NAME,
        "url": site.URL,
        "inLanguage": "pl-PL",
        "description": site.DESCRIPTION,
        "publisher": {"@id": ORGANIZACJA_ID},
    }


def aplikacja() -> dict:
    """Aplikacja jako produkt.

    `offers` z ceną 0 jest tu prawdą, nie chwytem: konto i kalendarz wyników są
    darmowe, a płatne są wybrane narzędzia. Wpisanie ceny 0 przy produkcie, który
    wymaga zapłaty za wejście, kończy się utratą rozszerzonych wyników.
    """
    return {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": site.NAME,
        "url": site.URL,
        "applicationCategory": "FinanceApplication",
        "applicationSubCategory": "Kalendarz wyników spółek i portfel inwestycyjny",
        "operatingSystem": "Web, iOS, Android",
        "inLanguage": "pl-PL",
        "description": site.DESCRIPTION,
        "featureList": [
            "Kalendarz wyników spółek z GPW i giełd amerykańskich",
            "Prognozy analityków i historia zaskoczeń wynikami",
            "Śledzenie portfela inwestycyjnego z raportu maklerskiego",
            "Stopa zwrotu, koszty i porównanie z indeksami",
            "Skaner ETF",
            "Analiza alokacji i ryzyka portfela",
            "Kalendarz wydarzeń makroekonomicznych",
        ],
        "offers": {
            "@type": "Offer",
            "price": "0",
            "priceCurrency": "PLN",
            "description": "Konto, kalendarz wyników i portfel bez opłat. "
                           "Część narzędzi analitycznych w wersji płatnej.",
        },
        "publisher": {"@id": ORGANIZACJA_ID},
    }


def okruchy(pozycje) -> dict:
    """Ścieżka nawigacji. `pozycje`: [(adres, nazwa), …] — bez strony głównej."""
    elementy = [{
        "@type": "ListItem", "position": 1,
        "name": site.NAME, "item": site.URL,
    }]
    for i, (adres, nazwa) in enumerate(pozycje, start=2):
        el = {"@type": "ListItem", "position": i, "name": nazwa}
        if adres:
            el["item"] = site.absolute(adres)
        elementy.append(el)
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": elementy}


def pytania(pary) -> dict:
    """FAQ. Dokładnie te same pary, które trafiają do `render.faq()`."""
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [{
            "@type": "Question",
            "name": pytanie,
            "acceptedAnswer": {"@type": "Answer", "text": odpowiedz},
        } for pytanie, odpowiedz in pary],
    }


def strona(sciezka: str, tytul: str, opis: str, typ: str = "WebPage",
           zmieniono: str = "") -> dict:
    """Sama strona — wiąże treść z wydawcą i podaje datę ostatniej zmiany."""
    d = {
        "@context": "https://schema.org",
        "@type": typ,
        "name": tytul,
        "description": opis,
        "url": site.absolute(sciezka),
        "inLanguage": "pl-PL",
        "isPartOf": {"@id": SERWIS_ID},
        "publisher": {"@id": ORGANIZACJA_ID},
    }
    if zmieniono:
        d["dateModified"] = zmieniono
    return d


def artykul(sciezka: str, tytul: str, opis: str, opublikowano: str,
            zmieniono: str = "") -> dict:
    """Poradnik. `author` to organizacja, bo teksty nie są podpisane osobą —
    wpisanie zmyślonego autora byłoby fałszem widocznym przy pierwszym sprawdzeniu."""
    return {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": tytul[:110],
        "description": opis,
        "url": site.absolute(sciezka),
        "mainEntityOfPage": site.absolute(sciezka),
        "inLanguage": "pl-PL",
        "datePublished": opublikowano,
        "dateModified": zmieniono or opublikowano,
        "author": {"@id": ORGANIZACJA_ID},
        "publisher": {"@id": ORGANIZACJA_ID},
        "image": site.absolute(site.OG_IMAGE),
    }


def spolka(nazwa: str, ticker: str, gielda: str = "", opis: str = "",
           strona_www: str = "") -> dict:
    """Spółka jako byt — to po niej model rozpoznaje, o kim jest strona.

    `tickerSymbol` jest najważniejszym polem: to jednoznaczny identyfikator,
    po którym „Orlen” na naszej stronie da się zszyć z „PKN” gdzie indziej.
    """
    d = {
        "@type": "Corporation",
        "name": nazwa,
        "tickerSymbol": ticker,
    }
    if gielda:
        d["memberOf"] = {"@type": "Organization", "name": gielda}
    if opis:
        d["description"] = opis
    if strona_www:
        d["url"] = strona_www
    return d


def strona_spolki(sciezka: str, tytul: str, opis: str, byt_spolki: dict,
                  zmieniono: str = "") -> dict:
    """Podstrona wyników jednej spółki — strona `about` konkretnej firmy."""
    d = strona(sciezka, tytul, opis, zmieniono=zmieniono)
    d["about"] = byt_spolki
    return d


def zbior_pojec(sciezka: str, tytul: str, opis: str, hasla) -> dict:
    """Słownik jako `DefinedTermSet`.

    To najlepiej „cytowalny” typ, jaki mamy: model pytany „co to jest EPS”
    dostaje z tego gotową parę termin–definicja z podanym źródłem, zamiast
    musieć wyłuskiwać ją z akapitu.
    """
    return {
        "@context": "https://schema.org",
        "@type": "DefinedTermSet",
        "@id": site.absolute(sciezka) + "#zbior",
        "name": tytul,
        "description": opis,
        "url": site.absolute(sciezka),
        "inLanguage": "pl-PL",
        "publisher": {"@id": ORGANIZACJA_ID},
        "hasDefinedTerm": [{
            "@type": "DefinedTerm",
            "name": termin,
            "description": definicja,
            "url": site.absolute(f"{sciezka}/{slug}"),
            "inDefinedTermSet": site.absolute(sciezka) + "#zbior",
        } for slug, termin, definicja in hasla],
    }


def lista_pozycji(nazwa: str, pozycje) -> dict:
    """Lista adresów (spis spółek, spis poradników) — pomaga w odkrywaniu podstron."""
    return {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": nazwa,
        "numberOfItems": len(pozycje),
        "itemListElement": [{
            "@type": "ListItem",
            "position": i,
            "name": tytul,
            "url": site.absolute(adres),
        } for i, (adres, tytul) in enumerate(pozycje, start=1)],
    }
