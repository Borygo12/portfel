"""Szkielet strony SEO — styl, nagłówek, stopka i klocki, z których składa się treść.

Wszystko jest tu jednym plikiem HTML bez zewnętrznych zasobów: styl siedzi
w `<style>`, ikona i logo to jedyne obrazki, JavaScriptu nie ma wcale. Powód nie
jest estetyczny, tylko mierzalny — Core Web Vitals są potwierdzonym czynnikiem
rankingowym, a strona bez blokujących zasobów rysuje się w pierwszym przebiegu
i wchodzi w zielone progi LCP/INP bez żadnej optymalizacji.

Wygląd trzyma paletę aplikacji (`mobile/src/theme.ts`), żeby przejście z Google
na stronę, a potem ze strony do aplikacji, było jednym płynnym ruchem, a nie
skokiem między dwoma różnymi produktami.

Rozwijane pytania w FAQ robimy na `<details>`, a nie na skrypcie: element działa
bez JS, jest dostępny z klawiatury, a jego treść siedzi w HTML-u od razu — więc
robot ją widzi nawet zwinietą. Gdyby FAQ dopisywał się skryptem, w danych
strukturalnych deklarowalibyśmy treść, której na stronie nie ma, a to Google
traktuje jak oszustwo.
"""

from __future__ import annotations

import html

from . import site

# --------------------------------------------------------------- narzędzia


def esc(tekst) -> str:
    """Tekst bezpieczny w treści i w atrybutach HTML."""
    return html.escape("" if tekst is None else str(tekst), quote=True)


def liczba(v, miejsca: int = 2) -> str:
    """Liczba po polsku: 1 234,56 — spacja nierozdzielająca, przecinek dziesiętny."""
    if v is None:
        return "—"
    try:
        tekst = f"{float(v):,.{miejsca}f}"
    except (TypeError, ValueError):
        return "—"
    return tekst.replace(",", " ").replace(".", ",")


def duza(v, waluta: str = "") -> str:
    """Duże kwoty po ludzku: 2 901 100 986 368 → „2,90 bln USD”."""
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    a = abs(v)
    jednostka, dzielnik = (
        ("bln", 1e12) if a >= 1e12 else ("mld", 1e9) if a >= 1e9
        else ("mln", 1e6) if a >= 1e6 else ("tys.", 1e3) if a >= 1e3 else ("", 1)
    )
    czesc = liczba(v / dzielnik, 0 if dzielnik == 1 else 2)
    return f"{czesc}{' ' + jednostka if jednostka else ''}{' ' + waluta if waluta else ''}"


def procent(v, ze_znakiem: bool = True) -> str:
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    znak = "+" if (ze_znakiem and v > 0) else ""
    return f"{znak}{liczba(v, 2)}%"


# --------------------------------------------------------------- styl

CSS = """
:root{
  --bg:#080b11;--elev:#0f131c;--card:#141926;--card-hi:#1a2030;
  --border:#212938;--border-2:#2d3750;
  --text:#eef1f7;--muted:#9aa3b8;--dim:#5c6479;
  --green:#2fd48a;--green-dim:rgba(47,212,138,.12);
  --red:#ff5c6c;--amber:#ffb454;--blue:#4f9bff;--orange:#ff8a3d;
  --r:14px;--maxw:1080px;
  color-scheme:dark;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth;-webkit-text-size-adjust:100%}
body{
  background:var(--bg);color:var(--text);
  font:16px/1.68 "Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,
       "Helvetica Neue",Arial,sans-serif;
  font-feature-settings:"kern","liga";
  text-rendering:optimizeLegibility;
  overflow-x:hidden;
}
a{color:var(--green);text-decoration:none}
a:hover{text-decoration:underline}
img{max-width:100%;height:auto}
.wrap{max-width:var(--maxw);margin:0 auto;padding:0 22px}
.narrow{max-width:780px}
.skip{position:absolute;left:-9999px}
.skip:focus{left:14px;top:14px;z-index:99;background:var(--green);color:#06120c;
  padding:10px 16px;border-radius:10px;font-weight:700}

/* ---------- nagłówek ---------- */
header.top{
  position:sticky;top:0;z-index:40;
  background:rgba(8,11,17,.86);backdrop-filter:blur(14px);
  border-bottom:1px solid var(--border);
}
.top .wrap{display:flex;align-items:center;gap:26px;height:64px}
.brand{display:flex;align-items:center;gap:9px;flex:0 0 auto}
.brand img{width:28px;height:28px;border-radius:7px}
.brand b{font-size:18px;font-weight:800;letter-spacing:-.4px;color:var(--text)}
.brand span{color:var(--orange)}
nav.main{display:flex;gap:20px;flex:1;flex-wrap:wrap;font-size:14.5px}
nav.main a{color:var(--muted);font-weight:500}
nav.main a:hover,nav.main a[aria-current]{color:var(--text);text-decoration:none}
.btn{
  display:inline-block;background:var(--green);color:#06120c;
  padding:9px 17px;border-radius:11px;font-weight:700;font-size:14.5px;
  border:1px solid transparent;white-space:nowrap;
}
.btn:hover{background:#3ee39a;text-decoration:none}
.btn.ghost{background:transparent;color:var(--text);border-color:var(--border-2)}
.btn.ghost:hover{background:var(--card-hi);border-color:var(--green)}
.btn.big{padding:13px 26px;font-size:16px;border-radius:13px}

/* ---------- okruchy ---------- */
.crumbs{font-size:13px;color:var(--dim);padding:22px 0 0}
.crumbs a{color:var(--dim)}
.crumbs a:hover{color:var(--muted)}
.crumbs i{font-style:normal;padding:0 7px;opacity:.55}

/* ---------- nagłówek treści ---------- */
.hero{padding:44px 0 8px}
.eyebrow{
  display:inline-block;font-size:11.5px;font-weight:800;letter-spacing:1.3px;
  text-transform:uppercase;color:var(--green);background:var(--green-dim);
  padding:6px 12px;border-radius:999px;margin-bottom:18px;
}
h1{font-size:clamp(30px,5.2vw,46px);font-weight:800;letter-spacing:-1.4px;
   line-height:1.1;max-width:19ch}
.hero.wide h1{max-width:26ch}
.lead{color:var(--muted);font-size:clamp(16.5px,2vw,19px);margin-top:18px;max-width:62ch}
.meta{color:var(--dim);font-size:13px;margin-top:14px}
.actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:28px}

/* ---------- sekcje ---------- */
section{padding:38px 0 0}
section>h2{font-size:clamp(21px,3vw,27px);font-weight:800;letter-spacing:-.7px;
  margin-bottom:14px;scroll-margin-top:80px}
section>h3{font-size:18px;font-weight:800;letter-spacing:-.3px;margin:24px 0 8px}
section p{color:var(--muted);margin-top:12px;max-width:70ch}
section p strong{color:var(--text);font-weight:650}
ul.dots{margin-top:14px;display:grid;gap:10px;list-style:none;max-width:70ch}
ul.dots li{color:var(--muted);padding-left:23px;position:relative}
ul.dots li::before{content:"";position:absolute;left:4px;top:.66em;width:6px;height:6px;
  border-radius:50%;background:var(--green)}
ul.dots li b{color:var(--text);font-weight:650}

/* ---------- karty ---------- */
.grid{display:grid;gap:14px;margin-top:20px;
  grid-template-columns:repeat(auto-fit,minmax(258px,1fr))}
.card{
  background:var(--card);border:1px solid var(--border);border-radius:var(--r);
  padding:20px;display:block;color:inherit;
  transition:border-color .16s ease,background .16s ease,transform .16s ease;
}
a.card:hover{border-color:var(--green);background:var(--card-hi);
  text-decoration:none;transform:translateY(-2px)}
.card h3{font-size:16.5px;font-weight:750;letter-spacing:-.25px;color:var(--text)}
.card p{font-size:14px;color:var(--muted);margin-top:8px;line-height:1.6}
.card .tag{font-size:11px;font-weight:800;letter-spacing:1px;text-transform:uppercase;
  color:var(--dim);display:block;margin-bottom:9px}

/* ---------- liczby ---------- */
.stats{display:grid;gap:12px;margin-top:20px;
  grid-template-columns:repeat(auto-fit,minmax(158px,1fr))}
.stat{background:var(--elev);border:1px solid var(--border);border-radius:12px;padding:16px}
.stat .k{font-size:11.5px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;
  color:var(--dim)}
.stat .v{font-size:23px;font-weight:800;letter-spacing:-.7px;margin-top:7px}
.stat .v.up{color:var(--green)}.stat .v.down{color:var(--red)}
.stat .n{font-size:12.5px;color:var(--muted);margin-top:5px}

/* ---------- tabela ---------- */
.scroll{overflow-x:auto;margin-top:20px;border:1px solid var(--border);
  border-radius:var(--r);background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:14.5px;min-width:520px}
caption{text-align:left;color:var(--dim);font-size:13px;padding:14px 16px 0}
th,td{padding:11px 16px;text-align:left;border-bottom:1px solid var(--border)}
th{color:var(--dim);font-size:11.5px;font-weight:800;letter-spacing:.7px;
  text-transform:uppercase;white-space:nowrap}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover{background:var(--card-hi)}
td.num{text-align:right;font-variant-numeric:tabular-nums}
th.num{text-align:right}
.up{color:var(--green)}.down{color:var(--red)}

/* ---------- FAQ ---------- */
.faq{margin-top:20px;display:grid;gap:10px}
details{background:var(--card);border:1px solid var(--border);border-radius:12px}
details[open]{border-color:var(--border-2)}
summary{padding:15px 18px;cursor:pointer;font-weight:650;list-style:none;
  display:flex;justify-content:space-between;gap:14px;align-items:center}
summary::-webkit-details-marker{display:none}
summary::after{content:"+";color:var(--green);font-size:19px;font-weight:400;flex:0 0 auto}
details[open] summary::after{content:"−"}
details p{padding:0 18px 16px;margin-top:0}

/* ---------- pasek zachęty ---------- */
.cta{
  margin-top:44px;background:linear-gradient(135deg,rgba(47,212,138,.10),rgba(79,155,255,.07));
  border:1px solid var(--border-2);border-radius:18px;padding:32px;
}
.cta h2{font-size:clamp(20px,2.6vw,26px);letter-spacing:-.6px;margin:0}
.cta p{margin-top:10px;max-width:56ch}

/* ---------- chmurki linków ---------- */
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}
.chip{background:var(--card);border:1px solid var(--border);border-radius:999px;
  padding:7px 14px;font-size:13.5px;color:var(--muted)}
a.chip:hover{border-color:var(--green);color:var(--text);text-decoration:none}

/* ---------- zastrzeżenie ---------- */
.disclaimer{margin-top:34px;border-left:3px solid var(--amber);
  background:rgba(255,180,84,.06);padding:14px 18px;border-radius:0 10px 10px 0}
.disclaimer p{color:var(--muted);font-size:13.5px;margin:0}

/* ---------- stopka ---------- */
footer.bottom{margin-top:72px;border-top:1px solid var(--border);
  background:var(--elev);padding:40px 0 34px}
.cols{display:grid;gap:26px;grid-template-columns:repeat(auto-fit,minmax(190px,1fr))}
.cols h4{font-size:11.5px;font-weight:800;letter-spacing:1px;text-transform:uppercase;
  color:var(--dim);margin-bottom:12px}
.cols ul{list-style:none;display:grid;gap:8px}
.cols a{color:var(--muted);font-size:14px}
.cols a:hover{color:var(--text)}
.legal{margin-top:32px;padding-top:22px;border-top:1px solid var(--border);
  color:var(--dim);font-size:12.5px;display:flex;justify-content:space-between;
  gap:16px;flex-wrap:wrap}

@media (max-width:720px){
  .top .wrap{height:auto;padding-top:12px;padding-bottom:12px;flex-wrap:wrap;gap:12px}
  nav.main{order:3;width:100%;gap:14px;font-size:13.5px}
  .hero{padding-top:30px}
  .cta{padding:24px}
}
@media (prefers-reduced-motion:reduce){
  *{transition:none!important;animation:none!important}
  html{scroll-behavior:auto}
}
"""

# --------------------------------------------------------------- nawigacja

#: Górna nawigacja. Kolejność nieprzypadkowa: pierwszy jest kalendarz wyników,
#: bo to on ma sprzedawać produkt (patrz keywords.py).
NAV = (
    ("/kalendarz-wynikow-spolek", "Kalendarz wyników"),
    ("/wyniki-finansowe", "Wyniki spółek"),
    ("/portfel-inwestycyjny", "Portfel"),
    ("/skaner-etf", "ETF"),
    ("/poradniki", "Poradniki"),
    ("/slownik", "Słownik"),
)

FOOTER = (
    ("Funkcje", (
        ("/kalendarz-wynikow-spolek", "Kalendarz wyników spółek"),
        ("/portfel-inwestycyjny", "Portfel inwestycyjny"),
        ("/skaner-etf", "Skaner ETF"),
        ("/analiza-portfela", "Analiza i ryzyko portfela"),
        ("/notowania-spolek", "Notowania i wskaźniki"),
        ("/kalendarz-makroekonomiczny", "Kalendarz makro"),
        ("/analiza-newsow-ai", "Analiza newsów AI"),
    )),
    ("Wyniki spółek", (
        ("/wyniki-finansowe", "Wszystkie spółki"),
        ("/wyniki-finansowe/gpw", "Spółki z GPW"),
        ("/wyniki-finansowe/usa", "Spółki z USA"),
    )),
    ("Wiedza", (
        ("/poradniki", "Poradniki"),
        ("/slownik", "Słownik giełdowy"),
    )),
    ("Portevo", (
        ("/", "Otwórz aplikację"),
        ("/premium", "Wersja płatna"),
        ("/kontakt", "Kontakt i pomoc"),
        ("/regulamin", "Regulamin"),
        ("/prywatnosc", "Polityka prywatności"),
    )),
)

LOGO = "/static/seo/logo-portevo.png"

#: Zastrzeżenie prawne. Musi być na KAŻDEJ stronie mówiącej o spółkach — to
#: jednocześnie wymóg regulaminu, warunek weryfikacji w App Store i sygnał
#: E-E-A-T dla Google w tematyce „Your Money or Your Life”, gdzie treści bez
#: jawnego zastrzeżenia są oceniane niżej.
DISCLAIMER = (
    "Portevo nie jest doradcą inwestycyjnym. Dane i analizy mają charakter "
    "informacyjny i edukacyjny, nie stanowią rekomendacji ani oferty kupna lub "
    "sprzedaży instrumentów finansowych. Notowania pochodzą od zewnętrznych "
    "dostawców i bywają opóźnione. Decyzje inwestycyjne podejmujesz na własne ryzyko."
)


# --------------------------------------------------------------- klocki treści


def sekcja(tytul: str, *akapity: str, lista=None, kotwica: str = "",
           html_dodatkowy: str = "") -> str:
    """Sekcja z nagłówkiem H2, akapitami i opcjonalną listą."""
    idatr = f' id="{esc(kotwica)}"' if kotwica else ""
    czesci = [f"<h2{idatr}>{esc(tytul)}</h2>"]
    czesci += [f"<p>{a}</p>" for a in akapity if a]
    if lista:
        czesci.append("<ul class=\"dots\">"
                      + "".join(f"<li>{x}</li>" for x in lista) + "</ul>")
    if html_dodatkowy:
        czesci.append(html_dodatkowy)
    return "<section>" + "".join(czesci) + "</section>"


def karty(pozycje) -> str:
    """Siatka kart. Pozycja: (adres, tytuł, opis) albo (adres, tytuł, opis, etykieta)."""
    out = []
    for p in pozycje:
        adres, tytul, opis = p[0], p[1], p[2]
        etykieta = p[3] if len(p) > 3 else ""
        tag = f'<span class="tag">{esc(etykieta)}</span>' if etykieta else ""
        znacznik = "a" if adres else "div"
        atr = f' href="{esc(adres)}"' if adres else ""
        out.append(f'<{znacznik} class="card"{atr}>{tag}'
                   f"<h3>{esc(tytul)}</h3><p>{esc(opis)}</p></{znacznik}>")
    return '<div class="grid">' + "".join(out) + "</div>"


def statystyki(pozycje) -> str:
    """Kafle z liczbami. Pozycja: (etykieta, wartość, nota, kierunek)."""
    out = []
    for p in pozycje:
        etykieta, wartosc = p[0], p[1]
        nota = p[2] if len(p) > 2 else ""
        kierunek = p[3] if len(p) > 3 else ""
        klasa = f" {kierunek}" if kierunek in ("up", "down") else ""
        out.append(f'<div class="stat"><div class="k">{esc(etykieta)}</div>'
                   f'<div class="v{klasa}">{esc(wartosc)}</div>'
                   + (f'<div class="n">{esc(nota)}</div>' if nota else "")
                   + "</div>")
    return '<div class="stats">' + "".join(out) + "</div>"


def tabela(naglowki, wiersze, podpis: str = "") -> str:
    """Tabela przewijana w poziomie na wąskim ekranie.

    Nagłówek: napis albo („napis”, True) gdy kolumna liczbowa (wyrównanie do prawej).
    Komórka: napis albo („napis”, "up"/"down"/"num") gdy ma dostać klasę.
    """
    th = []
    for h in naglowki:
        tekst, num = (h, False) if isinstance(h, str) else (h[0], h[1])
        th.append(f'<th class="num">{esc(tekst)}</th>' if num else f"<th>{esc(tekst)}</th>")
    tr = []
    for w in wiersze:
        td = []
        for c in w:
            if isinstance(c, tuple):
                tekst, klasa = c[0], c[1]
                td.append(f'<td class="num {esc(klasa)}">{esc(tekst)}</td>'
                          if klasa in ("up", "down", "num")
                          else f'<td class="{esc(klasa)}">{esc(tekst)}</td>')
            else:
                td.append(f"<td>{esc(c)}</td>")
        tr.append("<tr>" + "".join(td) + "</tr>")
    cap = f"<caption>{esc(podpis)}</caption>" if podpis else ""
    return ('<div class="scroll"><table>' + cap + "<thead><tr>" + "".join(th)
            + "</tr></thead><tbody>" + "".join(tr) + "</tbody></table></div>")


def faq(pary) -> str:
    """Pytania i odpowiedzi. Treść jest w HTML-u od razu, nawet gdy pozycja zwinięta."""
    out = []
    for pytanie, odpowiedz in pary:
        out.append(f"<details><summary>{esc(pytanie)}</summary>"
                   f"<p>{esc(odpowiedz)}</p></details>")
    return '<div class="faq">' + "".join(out) + "</div>"


def chipsy(linki) -> str:
    """Rząd linków-pigułek — do gęstego linkowania wewnętrznego."""
    out = []
    for adres, tekst in linki:
        out.append(f'<a class="chip" href="{esc(adres)}">{esc(tekst)}</a>')
    return '<div class="chips">' + "".join(out) + "</div>"


def zacheta(tytul: str, tekst: str, adres: str = "/",
            etykieta: str = "Otwórz Portevo", drugi=None) -> str:
    """Pasek zachęty na końcu strony — jedyne miejsce, gdzie prosimy o kliknięcie."""
    drugi_html = ""
    if drugi:
        drugi_html = f'<a class="btn ghost" href="{esc(drugi[0])}">{esc(drugi[1])}</a>'
    return (f'<div class="cta"><h2>{esc(tytul)}</h2><p>{esc(tekst)}</p>'
            f'<div class="actions"><a class="btn big" href="{esc(adres)}">{esc(etykieta)}</a>'
            f"{drugi_html}</div></div>")


def zastrzezenie() -> str:
    return f'<div class="disclaimer"><p>{esc(DISCLAIMER)}</p></div>'


# --------------------------------------------------------------- cała strona


def _okruchy(pozycje) -> str:
    if not pozycje:
        return ""
    czesci = ['<a href="/">Portevo</a>']
    for adres, tekst in pozycje:
        czesci.append(f'<a href="{esc(adres)}">{esc(tekst)}</a>' if adres else esc(tekst))
    return '<nav class="crumbs">' + "<i>›</i>".join(czesci) + "</nav>"


def _naglowek(aktywny: str) -> str:
    linki = []
    for adres, tekst in NAV:
        biezacy = ' aria-current="page"' if aktywny.startswith(adres) else ""
        linki.append(f'<a href="{esc(adres)}"{biezacy}>{esc(tekst)}</a>')
    return (
        '<header class="top"><div class="wrap">'
        f'<a class="brand" href="/"><img src="{LOGO}" alt="" width="28" height="28">'
        "<b>Port<span>evo</span></b></a>"
        '<nav class="main" aria-label="Główna">' + "".join(linki) + "</nav>"
        '<a class="btn" href="/">Otwórz aplikację</a>'
        "</div></header>"
    )


def _stopka() -> str:
    kolumny = []
    for tytul, linki in FOOTER:
        pozycje = "".join(f'<li><a href="{esc(a)}">{esc(t)}</a></li>' for a, t in linki)
        kolumny.append(f"<div><h4>{esc(tytul)}</h4><ul>{pozycje}</ul></div>")
    return (
        '<footer class="bottom"><div class="wrap">'
        '<div class="cols">' + "".join(kolumny) + "</div>"
        '<div class="legal"><span>© 2026 Portevo. Kalendarz wyników spółek '
        "i portfel inwestycyjny.</span>"
        f'<span>Kontakt: <a href="mailto:{esc(site.EMAIL)}">{esc(site.EMAIL)}</a></span>'
        "</div></div></footer>"
    )


def strona(*, sciezka: str, tytul: str, opis: str, h1: str, lead: str,
           bloki, nadtytul: str = "", okruchy=None, jsonld=None,
           akcje=None, aktualizacja: str = "", szeroki_naglowek: bool = False,
           noindex: bool = False) -> str:
    """Gotowy dokument HTML jednej podstrony.

    `tytul` to `<title>` i og:title — do 60 znaków, bo dłuższe Google ucina.
    `opis` to meta description — 140–160 znaków; nie jest czynnikiem rankingowym,
    ale decyduje, czy ktoś kliknie wynik, więc pisze się go jak obietnicę.
    """
    kanoniczny = site.absolute(sciezka)
    obrazek = site.absolute(site.OG_IMAGE)

    dane = ""
    if jsonld:
        import json
        dane = "".join(
            '<script type="application/ld+json">'
            + json.dumps(d, ensure_ascii=False, separators=(",", ":"))
            + "</script>" for d in jsonld
        )

    przyciski = ""
    if akcje:
        czesci = []
        for i, (adres, etykieta) in enumerate(akcje):
            klasa = "btn big" if i == 0 else "btn ghost big"
            czesci.append(f'<a class="{klasa}" href="{esc(adres)}">{esc(etykieta)}</a>')
        przyciski = '<div class="actions">' + "".join(czesci) + "</div>"

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(tytul)}</title>
<meta name="description" content="{esc(opis)}">
<meta name="robots" content="{'noindex, follow' if noindex else
    'index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1'}">
<link rel="canonical" href="{esc(kanoniczny)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{esc(site.NAME)}">
<meta property="og:locale" content="{esc(site.LOCALE)}">
<meta property="og:title" content="{esc(tytul)}">
<meta property="og:description" content="{esc(opis)}">
<meta property="og:url" content="{esc(kanoniczny)}">
<meta property="og:image" content="{esc(obrazek)}">
<meta property="og:image:width" content="{site.OG_IMAGE_W}">
<meta property="og:image:height" content="{site.OG_IMAGE_H}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(tytul)}">
<meta name="twitter:description" content="{esc(opis)}">
<meta name="twitter:image" content="{esc(obrazek)}">
<meta name="theme-color" content="#080b11">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/png" href="/static/seo/icon-192.png" sizes="192x192">
<link rel="apple-touch-icon" href="/static/seo/apple-touch-icon.png">
<link rel="manifest" href="/manifest.webmanifest">
<style>{CSS}</style>
{dane}</head>
<body>
<a class="skip" href="#tresc">Przejdź do treści</a>
{_naglowek(sciezka)}
<main id="tresc">
<div class="wrap">
{_okruchy(okruchy)}
<div class="hero{' wide' if szeroki_naglowek else ''}">
{f'<span class="eyebrow">{esc(nadtytul)}</span>' if nadtytul else ''}
<h1>{esc(h1)}</h1>
<p class="lead">{lead}</p>
{f'<p class="meta">Aktualizacja: {esc(aktualizacja)}</p>' if aktualizacja else ''}
{przyciski}
</div>
{''.join(bloki)}
</div>
</main>
{_stopka()}
</body>
</html>"""
