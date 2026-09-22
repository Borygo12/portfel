"""„Transakcje insiderów" — sekcja pozycjonowana z żywymi danymi z bazy insiderów.

Po co: po polsku nie ma nigdzie bieżącej listy tego, co kupują Nancy Pelosi,
Donald Trump czy kongresmeni. Są artykuły (Bankier, Parkiet, Rzeczpospolita),
które opowiadają o tym raz na kwartał, i anglojęzyczne trackery. Mamy dane,
których w polskim internecie nie ma — a to jest dokładnie ten rodzaj treści,
który po marcowej aktualizacji Google 2026 („scaled content abuse") dalej
rankuje: strona zbudowana na unikalnych, żywych danych, nie na szablonie tekstu.

Adresy:
* `/transakcje-insiderow` — przegląd: ranking person, świeże ujawnienia,
  prawdziwy wykres z twarzami, skąd dane;
* `/transakcje-insiderow/<osoba>` — profil: wynik zakupów, struktura, ostatnie
  transakcje, podsumowanie AI (gdy już jest), pytania;
* `/transakcje-insiderow/kongres-usa`, `/gpw`, `/spolki-usa` — rankingi klas.

Strony osób powstają TYLKO dla tych, którzy mają co pokazać (katalog ręczny
z transakcjami w bazie albo kongresmen z co najmniej kilkoma zgłoszeniami
w dwóch latach). Pusty profil „brak danych" to dokładnie ta chuda strona,
za którą Google tnie ruch całej domenie.

Każda strona prowadzi do aplikacji w trzech miejscach, nie jednym na końcu:
przycisk w nagłówku treści, pasek „obserwuj — powiadomimy" zaraz pod liczbami
i zachęta na dole. Adresy z `?` dostają `nofollow` (patrz `render._rel`).

Zdjęcia: portrety leżą pod `/api/insiders/foto/…`, a `/api/` jest zablokowane
w robots.txt — Google nie pobrałby zdjęcia Pelosi ani do grafiki, ani do
podglądu linku. Dlatego strony używają aliasu `/zdjecia/insiderzy/…`
(trasa w `routes.py`), który podaje ten sam plik.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import threading
import time

from . import charts, companies, jsonld, logos, render, site
from . import dates
from .render import esc

log = logging.getLogger("seo.insiders")

data_pl = dates.dlugo

BAZA = "/transakcje-insiderow"
ZMIENIONO = "2026-09-22"
APLIKACJA = "/insajderzy"             # panel insiderów w aplikacji (web)

KLASY_STRON = {
    "kongres-usa": {
        "h1": "Transakcje kongresmenów USA — kto kupuje, kto sprzedaje",
        "tytul": "Transakcje kongresmenów USA na żywo | Portevo",
        "opis": "Akcje kupowane i sprzedawane przez członków Kongresu USA: ranking "
                "najaktywniejszych, najczęściej kupowane spółki i świeże zgłoszenia "
                "STOCK Act. Po polsku, codziennie.",
        "nadtytul": "Kongres USA",
    },
    "gpw": {
        "h1": "Transakcje insiderów na GPW — zarządy i rady nadzorcze",
        "tytul": "Transakcje insiderów GPW — zakupy zarządów | Portevo",
        "opis": "Zakupy i sprzedaże akcji przez członków zarządów i rad nadzorczych "
                "spółek z GPW (MAR art. 19): świeże zgłoszenia i spółki, w które "
                "insiderzy wkładają najwięcej.",
        "nadtytul": "Polska giełda",
    },
    "spolki-usa": {
        "h1": "Zakupy prezesów i zarządów spółek z USA",
        "tytul": "Zakupy insiderów w spółkach z USA (Form 4) | Portevo",
        "opis": "Największe zakupy akcji własnych spółek przez prezesów, dyrektorów "
                "i dużych udziałowców w USA z formularzy Form 4 SEC — oraz spółki, "
                "w których kupuje kilku insiderów naraz.",
        "nadtytul": "Wall Street · Form 4",
    },
}

# ------------------------------------------------------------------ pamięć

_pamiec: dict[str, tuple[float, object]] = {}
_zamek = threading.Lock()
TTL_S = 20 * 60


def _zapamietane(klucz: str, oblicz, ttl: float = TTL_S):
    """Wynik trzymany kilkanaście minut. Nieświeży idzie od razu, nowy liczy
    się w tle — robot Google nie może czekać na przeliczenie rankingu."""
    teraz = time.time()
    hit = _pamiec.get(klucz)
    if hit and teraz - hit[0] < ttl:
        return hit[1]
    if hit:
        def w_tle():
            try:
                _pamiec[klucz] = (time.time(), oblicz())
            except Exception:  # noqa: BLE001
                log.exception("Odświeżenie %s", klucz)
        with _zamek:
            if _pamiec.get(klucz) is hit:        # jeszcze nikt nie odświeża
                _pamiec[klucz] = (teraz, hit[1])
                threading.Thread(target=w_tle, daemon=True).start()
        return hit[1]
    wynik = oblicz()
    _pamiec[klucz] = (teraz, wynik)
    return wynik


# ------------------------------------------------------------------ dane


def _store():
    from insiders import store
    return store


def _people():
    from insiders import people
    return people


def _osoba(pid: str, wiersz: dict | None, stat: dict | None = None,
           akt: dict | None = None) -> dict:
    import insiders_api
    return insiders_api._osoba(pid, wiersz, stat, akt)


def _walor(nazwa: str) -> str:
    import insiders_api
    return insiders_api._walor(nazwa)


def zdjecie(adres: str) -> str:
    """Adres zdjęcia widoczny dla robotów (alias spoza zablokowanego `/api/`)."""
    return (adres or "").replace("/api/insiders/foto/", "/zdjecia/insiderzy/")


def _mapa() -> dict[str, str]:
    """slug strony → identyfikator persony. Tylko ci, którzy mają co pokazać."""
    def licz():
        store, people = _store(), _people()
        m: dict[str, str] = {}
        ile = store.person_counts([k["id"] for k in people.KATALOG])
        for k in people.KATALOG:
            if ile.get(k["id"]):
                m[k["id"]] = k["id"]
        od = (dt.date.today() - dt.timedelta(days=730)).isoformat()
        wiersze = store._rows(
            "select person, count(*) as n from trades where (person like 'house-%' "
            "or person like 'senat-%') and date >= ? and ticker != '' "
            "group by person having n >= 8", (od,))
        dane = store.people_rows([w["person"] for w in wiersze])
        for w in sorted(wiersze, key=lambda x: -x["n"]):
            pid = w["person"]
            nazwa = (dane.get(pid) or {}).get("name") or ""
            if not nazwa:
                continue
            slug = people.slug(nazwa)
            if not slug or slug in m or slug in KLASY_STRON:
                stan = ((dane.get(pid) or {}).get("extra") or {}).get("state", "")
                slug = people.slug(f"{nazwa} {stan}")
            if slug and slug not in m and slug not in KLASY_STRON:
                m[slug] = pid
        return m
    return _zapamietane("mapa", licz, 3600)


def _slug_osoby(pid: str) -> str:
    for slug, p in _mapa().items():
        if p == pid:
            return slug
    return ""


def adres_osoby(pid: str) -> str:
    """Adres profilu albo pusty napis, gdy persona strony nie ma."""
    s = _slug_osoby(pid)
    return f"{BAZA}/{s}" if s else ""


def adresy() -> list[str]:
    return [BAZA] + [f"{BAZA}/{k}" for k in KLASY_STRON] + [f"{BAZA}/{s}" for s in _mapa()]


def ostatnie_zgloszenie(pid: str) -> str:
    """Dzień ostatniego zgłoszenia persony — prawdziwy `lastmod` do sitemapy."""
    w = _store()._rows("select max(filed) as f from trades where person=?", (pid,))
    return (w[0]["f"] if w and w[0]["f"] else "") or ZMIENIONO


def wpisy_sitemapy() -> list[tuple[str, str, str, str]]:
    dzis = dt.date.today().isoformat()
    poz = [(BAZA, "daily", "0.9", dzis)]
    poz += [(f"{BAZA}/{k}", "daily", "0.8", dzis) for k in KLASY_STRON]
    for slug, pid in _mapa().items():
        poz.append((f"{BAZA}/{slug}", "daily", "0.7", ostatnie_zgloszenie(pid)[:10]))
    return poz


def _panel() -> dict:
    import insiders_api
    return insiders_api._wspolny_panel()


def _stat(pid: str) -> dict | None:
    """Statystyki z pamięci bazy. Brak → liczymy w tle (notowania z sieci)
    i pokazujemy stronę bez wyniku, zamiast kazać robotowi czekać."""
    st = _store().stats_get(pid, 14 * 86400)
    if st is None:
        def w_tle():
            try:
                from insiders import perf
                perf.statystyki(pid)
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=w_tle, daemon=True).start()
    return st


# ------------------------------------------------------------------ formatowanie


def krotko(v) -> str:
    """Kwota po ludzku, bez zbędnych zer: 1 001 · 250 tys. · 1,5 mln · 2 mld."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    a = abs(v)
    if a < 10_000:
        return render.liczba(v, 0)
    if a < 1_000_000:
        return f"{render.liczba(round(v / 1000), 0)} tys."
    jedn, dziel = ("mld", 1e9) if a >= 1e9 else ("mln", 1e6)
    x = v / dziel
    tekst = render.liczba(x, 0 if abs(x) >= 100 else 1)
    return f"{tekst.replace(',0', '')} {jedn}"


def _kwota(t: dict) -> str:
    cur = "zł" if (t.get("cur") == "PLN") else "$"
    lo, hi = t.get("amt_lo"), t.get("amt_hi")
    if lo and hi and abs(hi - lo) > 1:
        # przedział z Kongresu: „1 tys.–15 tys. $", a nie „1 001–15 tys. $"
        dolny = f"{render.liczba(round(lo / 1000), 0)} tys." if 1000 <= lo < 10_000 <= hi else krotko(lo)
        return f"{dolny}–{krotko(hi)} {cur}"
    v = lo or hi
    return f"{krotko(v)} {cur}" if v else "—"


def _kasa(v, cur: str = "USD") -> str:
    if not v:
        return "—"
    return f"≈ {krotko(v)} {'zł' if cur == 'PLN' else '$'}"


def pelne_zdania(tekst: str) -> str:
    """Tekst ucięty w pół zdania (stare podsumowania AI) — do ostatniej kropki."""
    t = (tekst or "").strip()
    if t.endswith((".", "!", "?")):
        return t
    k = max(t.rfind(". "), t.rfind("! "), t.rfind("? "))
    return t[:k + 1] if k > 40 else t


def _plural(n: int, jeden: str, kilka: str, wiele: str) -> str:
    if n == 1:
        return jeden
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return kilka
    return wiele


def _inicjaly(nazwa: str) -> str:
    cz = [c for c in (nazwa or "").replace(".", " ").split() if c[:1].isalpha()]
    if not cz:
        return "?"
    return (cz[0][0] + (cz[-1][0] if len(cz) > 1 else "")).upper()


def awatar(p: dict, rozmiar: int = 48, ramka: str = "", ladowanie: str = "lazy") -> str:
    """Zdjęcie w kółku z ramką (złota/srebrna/brązowa) albo inicjały."""
    foto = zdjecie(p.get("photo") or "")
    kl = f"av {ramka}".strip()
    styl = f"--av:{int(rozmiar)}px"
    if foto:
        srodek = (f'<img src="{esc(foto)}" alt="{esc(p.get("name"))}" width="{rozmiar}" '
                  f'height="{rozmiar}" loading="{ladowanie}" decoding="async">')
    else:
        srodek = f'<i aria-hidden="true">{esc(_inicjaly(p.get("name") or ""))}</i>'
    return f'<span class="{esc(kl)}" style="{styl}">{srodek}</span>'


def _ramka(i: int) -> str:
    return ("gold", "silver", "bronze")[i] if i < 3 else ""


def _spolka_z_tickera(ticker: str) -> dict | None:
    return companies.po_symbolu(ticker) if ticker else None


def _logo_tickera(ticker: str, nazwa: str, rozmiar: int = 34) -> str:
    s = _spolka_z_tickera(ticker)
    return logos.znak(s or {"symbol": ticker, "name": nazwa or ticker}, rozmiar)


def _opis_roli(o: dict) -> str:
    czesci = [o.get("role") or "", o.get("org") if o.get("org") and o.get("org") != "Kongres USA" else ""]
    partie = {"D": "Demokraci", "R": "Republikanie", "I": "Niezależni"}
    if o.get("party") in partie:
        czesci.append(partie[o["party"]])
    return " · ".join(c for c in czesci if c)


# ------------------------------------------------------------------ klocki


def _wiersz_osoby(o: dict, i: int | None = None, prawa: str = "", nota: str = "") -> str:
    adres = adres_osoby(o["id"])
    zn, atr = ("a", f' href="{esc(adres)}"') if adres else ("div", "")
    nr = f'<span class="nr">{i + 1}</span>' if i is not None else ""
    akt = o.get("activity") or {}
    n = (akt.get("buys") or 0) + (akt.get("sells") or 0)
    pod = _opis_roli(o)
    if n:
        pod += f" · {n} {_plural(n, 'transakcja', 'transakcje', 'transakcji')} w roku"
    bok = ""
    if prawa:
        bok = f'<div class="side"><b>{prawa}</b>{esc(nota)}</div>'
    return (f'<{zn} class="row prow{" top1" if i == 0 else ""}"{atr}>{nr}'
            f'{awatar(o, 46, _ramka(i) if i is not None else "")}'
            f'<div class="main"><div class="nm">{esc(o["name"])}</div>'
            f'<div class="sub">{esc(pod)}</div></div>{bok}</{zn}>')


def _wynik_html(o: dict) -> tuple[str, str]:
    st = o.get("stats") or {}
    akt = o.get("activity") or {}
    r = st.get("ret_12m")
    if r is not None:
        kl = "up" if r >= 0 else "down"
        return f'<span class="pill {kl}">{esc(render.procent(r))}</span>', "zakupy · 12 mies."
    if akt.get("bought"):
        return esc(_kasa(akt["bought"], o.get("cur"))), "kupione w roku"
    if akt.get("sold"):
        return f'<span class="down">{esc(_kasa(akt["sold"], o.get("cur")))}</span>', "sprzedane w roku"
    return "—", ""


def _wiersz_transakcji(t: dict, osoba: dict | None = None) -> str:
    kupno = t["side"] == "buy"
    spolka = _spolka_z_tickera(t.get("ticker") or "")
    nazwa = _walor(t.get("asset") or "") or (spolka or {}).get("name") or t.get("ticker")
    kto = ""
    if osoba:
        adres = adres_osoby(osoba["id"])
        kto = (f'<a class="who" href="{esc(adres)}">{esc(osoba["name"])}</a>' if adres
               else f'<span class="who">{esc(osoba["name"])}</span>')
    link = companies.adres(spolka) if spolka else ""
    walor = (f'<a href="{esc(link)}">{esc(nazwa)}</a>' if link else esc(nazwa))
    dopiski = [x for x in ("opcje" if t.get("options") else "", t.get("owner") or "") if x]
    return (
        '<div class="row trow">'
        f'{awatar(osoba, 40, "buy" if kupno else "sell") if osoba else _logo_tickera(t.get("ticker"), nazwa)}'
        f'<div class="main"><div class="nm">{kto}{" · " if kto else ""}'
        f'<span class="{"up" if kupno else "down"}">{"kupno" if kupno else "sprzedaż"}</span> '
        f'<b class="tk">{esc(t.get("ticker"))}</b></div>'
        f'<div class="sub">{walor}{" · " + esc(" · ".join(dopiski)) if dopiski else ""}</div></div>'
        f'<div class="side"><b>{esc(_kwota(t))}</b>{esc(data_pl(t["date"]))}</div></div>')


def _lista(html_wierszy: list[str], naglowek: tuple[str, str] | None = None,
           wiecej: tuple[str, str] | None = None) -> str:
    if not html_wierszy:
        return ""
    glowa = (f'<div class="head"><b>{esc(naglowek[0])}</b><span>{esc(naglowek[1])}</span></div>'
             if naglowek else "")
    stopka = (f'<a class="more" href="{esc(wiecej[0])}"{render._rel(wiecej[0])}>{esc(wiecej[1])} →</a>'
              if wiecej else "")
    return '<div class="rows">' + glowa + "".join(html_wierszy) + stopka + "</div>"


_KOLORY = ["#2fd48a", "#4f9bff", "#b78bff", "#ffb454", "#ff5c9a", "#5ce1e6",
           "#ff8a3d", "#c6e05c", "#8a93a8", "#5c6479"]


def koło(pozycje: list[dict], cur: str = "USD", podpis: str = "") -> str:
    """Wykres kołowy zakupów w SVG (bez JS) z legendą obok."""
    pozycje = [p for p in pozycje if (p.get("value") or 0) > 0][:10]
    if not pozycje:
        return ""
    razem = sum(p["value"] for p in pozycje) or 1.0
    r, obw = 70.0, 2 * math.pi * 70.0
    luki, legenda, przes = [], [], 0.0
    for i, p in enumerate(pozycje):
        dl = p["value"] / razem * obw
        kolor = _KOLORY[i % len(_KOLORY)]
        luki.append(f'<circle r="{r}" cx="100" cy="100" fill="none" stroke="{kolor}" '
                    f'stroke-width="26" stroke-dasharray="{max(dl - 1.5, 0.5):.2f} {obw:.2f}" '
                    f'stroke-dashoffset="{-przes:.2f}" transform="rotate(-90 100 100)"/>')
        przes += dl
        nazwa = p.get("ticker") or ""
        opis = _walor(p.get("name") or "") if p.get("ticker") else (p.get("name") or "")
        legenda.append(
            f'<li><i style="background:{kolor}"></i><b>{esc(nazwa or opis)}</b>'
            f'<span>{esc(opis if nazwa else "")}</span>'
            f'<em>{esc(render.liczba(p["value"] / razem * 100, 1))}%</em></li>')
    svg = (f'<svg viewBox="0 0 200 200" width="200" height="200" role="img" '
           f'aria-label="{esc(podpis or "Struktura zakupów")}">{"".join(luki)}'
           f'<text x="100" y="94" text-anchor="middle" class="dk">ZAKUPY</text>'
           f'<text x="100" y="116" text-anchor="middle" class="dv">{esc(krotko(razem))} '
           f'{"zł" if cur == "PLN" else "$"}</text></svg>')
    return f'<div class="donut">{svg}<ul>{"".join(legenda)}</ul></div>'


def wykres_z_twarzami(ticker: str, twarze: list[dict], nazwa: str) -> str:
    """Prawdziwy kurs z roku i twarze w dniach zakupów — to samo, co w aplikacji.

    `twarze`: [{date, osoba}] — najwyżej kilka, różne osoby."""
    try:
        from insiders import perf
        px = perf.notowania(ticker)
    except Exception:  # noqa: BLE001
        px = None
    if not px or len(px.get("c") or []) < 60:
        return ""
    od = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    pary = [(d, c) for d, c in zip(px["d"], px["c"]) if d >= od]
    if len(pary) < 60:
        return ""
    W, H, P = 720, 300, 28
    lo = min(c for _, c in pary)
    hi = max(c for _, c in pary)
    zakres = (hi - lo) or 1.0
    n = len(pary)

    def xy(i: int, c: float) -> tuple[float, float]:
        return (P + i / (n - 1) * (W - 2 * P), 30 + (1 - (c - lo) / zakres) * (H - 70))

    punkty = [xy(i, c) for i, (_, c) in enumerate(pary)]
    linia = " ".join(f"{x:.1f},{y:.1f}" for x, y in punkty)
    obszar = f"{P},{H - 40} " + linia + f" {W - P},{H - 40}"
    daty = [d for d, _ in pary]
    import bisect
    defs, znaczniki, uzyte = [], [], set()
    zajete: dict[str, list[float]] = {"gora": [], "dol": []}
    kolejne = sorted(twarze, key=lambda tw: tw["date"])
    for k, tw in enumerate(kolejne):
        o = tw["osoba"]
        if o["id"] in uzyte:
            continue
        i = min(bisect.bisect_left(daty, tw["date"]), n - 1)
        x, y = punkty[i]
        wolne = lambda strona: all(abs(x - z) >= 46 for z in zajete[strona])
        strona = "gora" if y > 70 else "dol"
        if not wolne(strona):
            inna = "dol" if strona == "gora" else "gora"
            if not wolne(inna) or (inna == "gora" and y <= 70) or (inna == "dol" and y > H - 110):
                continue
            strona = inna
        zajete[strona].append(x)
        cy = y - 42 if strona == "gora" else y + 42
        foto = zdjecie(o.get("photo") or "")
        cid = f"tw{k}"
        uzyte.add(o["id"])
        if foto:
            defs.append(f'<clipPath id="{cid}"><circle cx="{x:.1f}" cy="{cy:.1f}" r="17"/></clipPath>')
            twarz = (f'<image href="{esc(foto)}" x="{x - 17:.1f}" y="{cy - 17:.1f}" width="34" '
                     f'height="34" clip-path="url(#{cid})" preserveAspectRatio="xMidYMin slice"/>')
        else:
            twarz = (f'<circle cx="{x:.1f}" cy="{cy:.1f}" r="17" fill="#1a2030"/>'
                     f'<text x="{x:.1f}" y="{cy + 5:.1f}" text-anchor="middle" class="fi">'
                     f'{esc(_inicjaly(o["name"]))}</text>')
        znaczniki.append(
            f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{cy:.1f}" class="st"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" class="pt"/>'
            f'<circle cx="{x:.1f}" cy="{cy:.1f}" r="19" class="rg"/>{twarz}'
            f'<text x="{x:.1f}" y="{(cy + 32) if cy > y else (cy - 24):.1f}" text-anchor="middle" '
            f'class="fl">{esc(o.get("short") or o["name"])}</text>')
        if len(uzyte) >= 6:
            break
    ostatni = pary[-1][1]
    zmiana = (ostatni / pary[0][1] - 1) * 100 if pary[0][1] else 0
    svg = (f'<svg class="facechart" viewBox="0 0 {W} {H}" role="img" '
           f'aria-label="Kurs {esc(nazwa)} z ostatniego roku z zaznaczonymi zakupami insiderów">'
           f'<defs><linearGradient id="fg" x1="0" x2="0" y1="0" y2="1">'
           f'<stop offset="0" stop-color="#2fd48a" stop-opacity=".28"/>'
           f'<stop offset="1" stop-color="#2fd48a" stop-opacity="0"/></linearGradient>{"".join(defs)}</defs>'
           f'<polygon points="{obszar}" fill="url(#fg)"/>'
           f'<polyline points="{linia}" fill="none" stroke="#2fd48a" stroke-width="2.2" '
           f'stroke-linejoin="round"/>{"".join(znaczniki)}'
           f'<text x="{P}" y="{H - 14}" class="ax">{esc(data_pl(pary[0][0]))}</text>'
           f'<text x="{W - P}" y="{H - 14}" text-anchor="end" class="ax">{esc(data_pl(pary[-1][0]))}</text>'
           f'</svg>')
    return (f'<figure class="fcwrap"><div class="fchead"><b>{esc(nazwa)} · {esc(ticker)}</b>'
            f'<span class="{"up" if zmiana >= 0 else "down"}">{esc(render.procent(zmiana))} w roku</span></div>'
            f'{svg}<figcaption>Prawdziwy kurs z ostatnich 12 miesięcy i twarze w dniach, '
            f'w których te osoby kupiły akcje. W aplikacji tak wygląda wykres każdej spółki.'
            f'</figcaption></figure>')


def pasek_obserwuj(o: dict) -> str:
    """Wezwanie zaraz pod liczbami — w chwili największego zainteresowania."""
    return (
        '<div class="follow">'
        f'{awatar(o, 44)}'
        f'<div class="ft"><b>Powiadomimy Cię, gdy {esc(o["name"])} znowu kupi lub sprzeda</b>'
        '<span>Obserwuj w Portevo — push i e-mail przy każdym nowym zgłoszeniu, '
        'a twarz pojawi się na wykresie spółki.</span></div>'
        f'<a class="btn" href="{esc(APLIKACJA)}?osoba={esc(o["id"])}" rel="nofollow">🔔 Obserwuj</a>'
        '</div>')


def karta_osoby(o: dict, st: dict, ostatnia: dict, ramka: str) -> str:
    """Prawa strona nagłówka profilu — duże zdjęcie i to, po co ktoś tu przyszedł."""
    r = (st or {}).get("ret_12m")
    wynik = (f'<span class="pill big {"up" if r >= 0 else "down"}">{esc(render.procent(r))}</span>'
             f'<small>wynik zakupów z 12 miesięcy</small>') if r is not None else ""
    kupno = ostatnia["side"] == "buy"
    return (
        f'<div class="pcard"><div class="pc-photo">{awatar(o, 132, ramka or "plain", "eager")}</div>'
        f'<b class="pc-name">{esc(o["name"])}</b><span class="pc-role">{esc(_opis_roli(o))}</span>'
        f'<div class="pc-ret">{wynik}</div>'
        f'<div class="pc-last"><span>Ostatnia transakcja</span>'
        f'<b><em class="{"up" if kupno else "down"}">{"kupno" if kupno else "sprzedaż"}</em> '
        f'{esc(ostatnia.get("ticker"))} · {esc(data_pl(ostatnia["date"]))}</b>'
        f'<small>{esc(_kwota(ostatnia))}</small></div>'
        f'<a class="btn pc-btn" href="{esc(APLIKACJA)}?osoba={esc(o["id"])}" rel="nofollow">'
        f'🔔 Powiadamiaj mnie</a></div>')


def karta_bohatera(liderzy: list[dict]) -> str:
    """Prawa strona nagłówka: trzy pierwsze miejsca rankingu, jak w aplikacji."""
    rzedy = []
    for i, o in enumerate(liderzy[:3]):
        wynik, nota = _wynik_html(o)
        adres = adres_osoby(o["id"]) or APLIKACJA
        rzedy.append(
            f'<a class="hrow{" top1" if i == 0 else ""}" href="{esc(adres)}">'
            f'<span class="nr">{i + 1}</span>{awatar(o, 52 if i == 0 else 44, _ramka(i), "eager")}'
            f'<span class="hn"><b>{esc(o["name"])}</b><small>{esc(_opis_roli(o))}</small></span>'
            f'<span class="hv">{wynik}<small>{esc(nota)}</small></span></a>')
    return ('<div class="herocard"><div class="hc-top"><span class="live"></span>'
            'Ranking insiderów · na żywo</div>' + "".join(rzedy)
            + f'<a class="hc-more" href="{esc(APLIKACJA)}">Otwórz pełny ranking w aplikacji →</a></div>')


# ------------------------------------------------------------------ przegląd


def _wybrane_twarze(liderzy: list[dict]) -> tuple[str, list[dict]]:
    """Spółka na wykres przeglądu: ta, którą w roku kupiło najwięcej znanych osób."""
    store = _store()
    od = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    pids = [o["id"] for o in liderzy[:30]]
    trans = store.trades_for_people(pids, od)
    po = {o["id"]: o for o in liderzy}
    wg: dict[str, dict[str, str]] = {}
    for t in trans:
        if t["side"] != "buy" or not t.get("ticker") or "." in t["ticker"]:
            continue
        wg.setdefault(t["ticker"], {}).setdefault(t["person"], t["date"])
    ranking = sorted(wg.items(), key=lambda kv: (-sum(1 for p in kv[1] if po[p].get("photo")),
                                                 -len(kv[1])))
    for ticker, osoby in ranking[:4]:
        twarze = sorted(({"date": d, "osoba": po[p]} for p, d in osoby.items()),
                        key=lambda x: (not x["osoba"].get("photo"), x["osoba"].get("rank") or 999))
        if len(twarze) >= 2:
            return ticker, twarze[:6]
    return "", []


def _przeglad() -> str:
    panel = _panel()
    liderzy = [o for o in panel.get("leaders") or []]
    # ta sama kolejność co w aplikacji: katalog ważności, aktywni wyżej
    akt = lambda o: ((o.get("activity") or {}).get("buys") or 0) + ((o.get("activity") or {}).get("sells") or 0)
    liderzy.sort(key=lambda o: (not akt(o), o.get("rank") or 9999, -akt(o)))
    osoby = {**(panel.get("persons") or {}), **{o["id"]: o for o in liderzy}}
    zrodla = panel.get("sources") or {}

    bloki = []
    razem = sum(v or 0 for v in zrodla.values())
    bloki.append("<section>" + render.statystyki([
        ("Transakcji w bazie", render.liczba(razem, 0), "z oficjalnych rejestrów"),
        ("Kongres USA", render.liczba((zrodla.get("house") or 0) + (zrodla.get("senat") or 0), 0),
         "Izba i Senat (STOCK Act)"),
        ("Prezydent i rząd", render.liczba(zrodla.get("oge") or 0, 0), "formularze OGE 278-T"),
        ("Zarządy spółek USA", render.liczba(zrodla.get("sec") or 0, 0), "SEC Form 4"),
        ("Insiderzy GPW", render.liczba(zrodla.get("gpw") or 0, 0), "MAR art. 19 (ESPI)"),
    ]) + "</section>")

    bloki.append(render.sekcja(
        "Najważniejsze persony",
        "Ranking ułożony tak jak w aplikacji: najpierw osoby, których portfele śledzi "
        "cały rynek, potem najaktywniejsi. <strong>Wynik 12 mies.</strong> to stopa "
        "zwrotu portfela odtworzonego z ich zakupów z ostatniego roku — tak, jakby "
        "kupić to samo, tego samego dnia.",
        html_dodatkowy=_lista([_wiersz_osoby(o, i, *_wynik_html(o)) for i, o in enumerate(liderzy[:15])],
                              ("Ranking", "wynik zakupów z 12 miesięcy"),
                              (APLIKACJA, "Pełny ranking z filtrami w aplikacji"))))

    ticker, twarze = _wybrane_twarze(liderzy)
    if ticker:
        sp = _spolka_z_tickera(ticker)
        wyk = wykres_z_twarzami(ticker, twarze, (sp or {}).get("name") or ticker)
        if wyk:
            bloki.append(render.sekcja(
                "Twarze na wykresie — kto kupił i kiedy",
                "Najbardziej rozpoznawalna funkcja Portevo: na wykresie każdej spółki "
                "stoi zdjęcie osoby w dniu, w którym kupiła akcje. Od razu widać, "
                "czy Pelosi weszła przed wzrostem, czy na górce.",
                html_dodatkowy=wyk + '<div class="actions">'
                f'<a class="btn big" href="/?spolka={esc(ticker)}" rel="nofollow">Zobacz ten wykres w aplikacji</a>'
                f'<a class="btn ghost big" href="{esc(APLIKACJA)}">Panel insiderów</a></div>'))

    feed = panel.get("feed") or []
    znane = [t for t in feed if adres_osoby(t["person"])]
    feed = znane[:8] + [t for t in feed if t not in znane[:8]]
    bloki.append(render.sekcja(
        "Świeżo ujawnione",
        "Najnowsze zgłoszenia — po dniu ujawnienia, nie transakcji. Kongres ma na "
        "zgłoszenie do 45 dni, więc dzisiejsza wiadomość bywa zakupem sprzed miesiąca.",
        html_dodatkowy=_lista([_wiersz_transakcji(_surowa(t), osoby.get(t["person"]))
                               for t in feed[:14] if osoby.get(t["person"])],
                              ("Ostatnie zgłoszenia", "Kongres, rząd, SEC, GPW"),
                              (APLIKACJA, "Wszystkie zgłoszenia na żywo w aplikacji"))))

    bloki.append(render.sekcja(
        "Rankingi według grup",
        html_dodatkowy=render.karty([
            (f"{BAZA}/kongres-usa", "Kongres USA", "Kto w Kongresie handluje najwięcej, "
             "które spółki kupują politycy i co zgłosili w tym miesiącu.", "Politycy"),
            (f"{BAZA}/donald-trump" if "donald-trump" in _mapa() else f"{BAZA}/kongres-usa",
             "Donald Trump", "Tysiące pozycji z formularzy OGE — co kupują doradcy "
             "zarządzający majątkiem prezydenta.", "Prezydent"),
            (f"{BAZA}/spolki-usa", "Prezesi spółek z USA", "Największe zakupy akcji "
             "własnych firm z Form 4 i spółki, w których kupuje kilku insiderów naraz.", "SEC"),
            (f"{BAZA}/gpw", "Insiderzy na GPW", "Zarządy i rady nadzorcze polskich "
             "spółek: kto kupuje akcje własnej firmy i za ile.", "Polska"),
        ])))

    bloki.append(render.sekcja(
        "Skąd są te dane",
        lista=[
            "<b>Kongres USA</b> — raporty PTR z Izby Reprezentantów i Senatu. Ustawa "
            "STOCK Act każe zgłosić transakcję do 45 dni; kwoty podawane są przedziałami "
            "(np. 1 001–15 000 $).",
            "<b>Prezydent i rząd</b> — formularze 278-T urzędu etyki (OGE), udostępniane "
            "przez projekt open-cabinet.",
            "<b>Zarządy spółek z USA</b> — Form 4 z systemu EDGAR komisji SEC, do dwóch "
            "dni roboczych po transakcji, z dokładną ceną i liczbą akcji.",
            "<b>Znane fundusze</b> — kwartalne portfele 13F (Buffett, Burry, Ackman…).",
            "<b>GPW</b> — powiadomienia z art. 19 rozporządzenia MAR publikowane w ESPI, "
            "do 3 dni roboczych, kwoty w złotych.",
        ]))

    pary = [
        ("Co to są transakcje insiderów?",
         "To zakupy i sprzedaże akcji przez osoby, które znają spółkę od środka "
         "(prezesi, członkowie zarządu i rady, duzi udziałowcy) albo mają wpływ na "
         "przepisy (kongresmeni, członkowie rządu). Prawo każe je jawnie zgłaszać."),
        ("Co ostatnio kupuje Nancy Pelosi?",
         _odpowiedz_ostatnie("nancy-pelosi", osoby)),
        ("Czy kongresmeni w USA mogą handlować akcjami?",
         "Tak. Muszą jednak zgłosić każdą transakcję powyżej 1000 $ do 45 dni "
         "(STOCK Act z 2012 r.). Projekty zakazu handlu przez członków Kongresu "
         "wracają co kadencję, ale do dziś nie weszły w życie."),
        ("Czy kopiowanie transakcji insiderów się opłaca?",
         "Nie ma gwarancji. Zgłoszenia przychodzą z opóźnieniem (w Kongresie do 45 dni), "
         "a przeszłe wyniki nie przesądzają o przyszłych. Portevo pokazuje dane i wynik "
         "historyczny — nie daje rekomendacji."),
        ("Jak dostać powiadomienie o transakcji konkretnej osoby?",
         "W aplikacji Portevo wystarczy dotknąć dzwonka przy osobie w rankingu. "
         "Po każdym nowym zgłoszeniu przychodzi powiadomienie na telefon i e-mail."),
    ]
    bloki.append(render.sekcja("Najczęstsze pytania", kotwica="pytania",
                               html_dodatkowy=render.faq(pary)))
    bloki.append(render.zacheta(
        "Śledź insiderów w aplikacji",
        "Ranking z filtrami, profil każdej osoby z wykresem zakupów, twarze na "
        "wykresach spółek i powiadomienia, gdy obserwowana osoba znowu kupi. "
        "Podgląd za darmo, bez karty.",
        adres=APLIKACJA, etykieta="Otwórz panel insiderów",
        drugi=("/?zaloguj=1", "Załóż darmowe konto")))
    bloki.append(render.zastrzezenie())

    tytul = "Transakcje insiderów: co kupują Pelosi, Trump i prezesi"
    opis = ("Na żywo po polsku: co kupują i sprzedają Nancy Pelosi, Donald Trump, "
            "kongresmeni USA, prezesi spółek i insiderzy z GPW. Ranking z wynikiem "
            "zakupów, świeże zgłoszenia i twarze na wykresach.")
    okruchy = [("", "Transakcje insiderów")]
    return render.strona(
        sciezka=BAZA, tytul=tytul + " | Portevo", opis=opis,
        h1="Transakcje insiderów: co kupują Pelosi, Trump i prezesi",
        lead=("Kongresmeni, prezydent, członkowie rządu USA i zarządy spółek muszą "
              "ujawniać swoje transakcje akcjami. Zbieramy je prosto z oficjalnych "
              "rejestrów — i pokazujemy po polsku, z wynikiem i zdjęciem."),
        nadtytul="Nowość · na żywo", okruchy=okruchy, szeroki_naglowek=True,
        aktualizacja=data_pl(dt.date.today().isoformat()),
        akcje=[(APLIKACJA, "Otwórz panel insiderów"), (f"{BAZA}/kongres-usa", "Ranking Kongresu")],
        wizual=karta_bohatera(liderzy),
        bloki=bloki,
        obrazek=zdjecie((liderzy[0] if liderzy else {}).get("photo") or ""),
        jsonld=[jsonld.strona(BAZA, tytul, opis, typ="CollectionPage"),
                jsonld.okruchy(okruchy), jsonld.pytania(pary)])


def _surowa(t: dict) -> dict:
    """Transakcja z panelu (format aplikacji) → format bazy dla klocków strony."""
    return {**t, "amt_lo": t.get("lo"), "amt_hi": t.get("hi")}


def _odpowiedz_ostatnie(pid: str, osoby: dict) -> str:
    store = _store()
    kupna = [t for t in store.trades_for_person(pid, limit=200) if t["side"] == "buy"][:4]
    nazwa = (osoby.get(pid) or {}).get("name") or "Ta osoba"
    if not kupna:
        return f"{nazwa} nie zgłosiła ostatnio zakupów akcji."
    czesci = [f"{t['ticker']} ({data_pl(t['date'])}, {_kwota(t)})" for t in kupna]
    return (f"Ostatnie zgłoszone zakupy: {', '.join(czesci)}. Lista aktualizuje się "
            f"automatycznie z oficjalnych zgłoszeń — pełna historia jest na stronie profilu.")


# ------------------------------------------------------------------ profil osoby

ZRODLA_OPIS = {
    "house": ("raporty PTR Izby Reprezentantów", "do 45 dni od transakcji (STOCK Act)"),
    "senat": ("raporty PTR Senatu USA", "do 45 dni od transakcji (STOCK Act)"),
    "oge": ("formularze 278-T urzędu etyki (OGE)", "do 45 dni od transakcji"),
    "sec": ("formularze Form 4 komisji SEC", "do 2 dni roboczych od transakcji"),
    "f13": ("kwartalne raporty 13F funduszu", "do 45 dni po końcu kwartału"),
    "gpw": ("powiadomienia MAR art. 19 w raportach ESPI", "do 3 dni roboczych"),
}


def _profil(slug: str) -> str | None:
    pid = _mapa().get(slug)
    if not pid:
        return None
    store, people = _store(), _people()
    wiersz = store.people_rows([pid]).get(pid)
    stat = _stat(pid)
    od12 = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    trans = store.trades_for_person(pid, limit=4000)
    if not trans:
        return None
    rok = [t for t in trans if t["date"] >= od12]
    akt = {"buys": sum(1 for t in rok if t["side"] == "buy"),
           "sells": sum(1 for t in rok if t["side"] == "sell"),
           "last": trans[0]["date"]}
    o = _osoba(pid, wiersz, stat, akt)
    nazwa = o["name"]
    cur = o.get("cur") or "USD"
    k = people.curated(pid) or {}
    rank = k.get("rank") or 0
    ramka = _ramka(rank - 1) if 1 <= rank <= 3 else ""

    st = stat or {}
    kupna = [t for t in trans if t["side"] == "buy"]
    ostatnie_kupno = kupna[0] if kupna else None
    bloki = []

    r = st.get("ret_12m")
    kafle = [
        ("Wynik zakupów · 12 mies.", render.procent(r) if r is not None else "liczymy…",
         "portfel odtworzony z zakupów", ("up" if (r or 0) >= 0 else "down") if r is not None else ""),
        ("Zakupy w roku", str(akt["buys"]), _kasa(st.get("bought"), cur) if st.get("bought") else ""),
        ("Sprzedaże w roku", str(akt["sells"]), _kasa(st.get("sold"), cur) if st.get("sold") else ""),
        ("Ostatnia transakcja", data_pl(trans[0]["date"]),
         f"{'kupno' if trans[0]['side'] == 'buy' else 'sprzedaż'} {trans[0].get('ticker')}"),
        ("Wszystkich w bazie", render.liczba(len(trans), 0), "od początku zbierania"),
    ]
    bloki.append("<section>" + render.statystyki(kafle) + pasek_obserwuj(o) + "</section>")

    try:
        from insiders import ai
        podsum = ai.zapisane(pid)
    except Exception:  # noqa: BLE001
        podsum = None
    if podsum:
        bloki.append(render.sekcja(
            "W skrócie",
            f'<span class="aiq">{esc(pelne_zdania(podsum["text"]))}</span>',
            f'<span class="note">Podsumowanie napisane przez AI na podstawie zgłoszeń; '
            f'aktualizowane codziennie.</span>'))

    bloki.append(render.sekcja(
        f"Co ostatnio kupuje i sprzedaje {nazwa}",
        (f"Ostatnie zgłoszone kupno: <strong>{esc(ostatnie_kupno['ticker'])}</strong> "
         f"({esc(data_pl(ostatnie_kupno['date']))}, {esc(_kwota(ostatnie_kupno))})."
         if ostatnie_kupno else ""),
        html_dodatkowy=_lista([_wiersz_transakcji(t) for t in trans[:15]],
                              ("Ostatnie transakcje", f"z {len(trans)} w bazie"),
                              (f"{APLIKACJA}?osoba={pid}", "Pełna historia w aplikacji"))))

    alloc = st.get("alloc") or []
    if alloc:
        bloki.append(render.sekcja(
            "Na co szły pieniądze",
            ("Zakupy z ostatnich 12 miesięcy według kwot." if st.get("alloc_basis") == "12m"
             else "Cała historia zakupów — w ostatnim roku nie było żadnego."),
            html_dodatkowy=koło(alloc, cur, f"Struktura zakupów: {nazwa}")))

    # prawdziwy wykres z twarzą tej osoby w dniu największego zakupu z roku
    kupna_rok = [t for t in kupna if t["date"] >= od12 and t.get("ticker") and "." not in t["ticker"]]
    if kupna_rok and cur == "USD":
        naj = max(kupna_rok, key=lambda t: (t.get("amt_hi") or t.get("amt_lo") or 0))
        sp = _spolka_z_tickera(naj["ticker"])
        wyk = wykres_z_twarzami(naj["ticker"], [{"date": naj["date"], "osoba": o}],
                                (sp or {}).get("name") or _walor(naj.get("asset") or "") or naj["ticker"])
        if wyk:
            bloki.append(render.sekcja(
                f"Największy zakup z roku na wykresie: {naj['ticker']}",
                "Tak Portevo pokazuje insiderów — twarz stoi na kursie w dniu zakupu.",
                html_dodatkowy=wyk))

    src = o.get("source") or "sec"
    co, kiedy = ZRODLA_OPIS.get(src, ZRODLA_OPIS["sec"])
    bio = k.get("bio") or ""
    bloki.append(render.sekcja(
        f"Kim jest {nazwa} i skąd te dane",
        esc(bio) if bio else f"{esc(nazwa)} — {esc(_opis_roli(o))}.",
        f"Transakcje pochodzą z oficjalnych źródeł: {esc(co)}, zgłaszanych {esc(kiedy)}. "
        "Portevo pobiera je automatycznie i tłumaczy na polski — nic nie jest wpisywane ręcznie."))

    pary = [
        (f"Co ostatnio kupuje {nazwa}?",
         _odpowiedz_ostatnie(pid, {pid: o})),
        (f"Jaki wynik mają zakupy {nazwa}?",
         (f"Portfel odtworzony z zakupów z ostatnich 12 miesięcy ma wynik {render.procent(r)} "
          f"(tak, jakby kupić te same akcje tego samego dnia i trzymać do dziś)."
          if r is not None else
          "Wynik liczymy z kursów wszystkich kupionych spółek — pojawi się tu po przeliczeniu.")),
        (f"Jak szybko widać nowe transakcje {nazwa}?",
         f"Tak szybko, jak trafią do rejestru: {kiedy}. Portevo sprawdza rejestry "
         "kilka razy na godzinę i wysyła powiadomienie obserwującym."),
        (f"Czy warto kopiować transakcje {nazwa}?",
         "To decyzja inwestora. Zgłoszenia przychodzą z opóźnieniem, a przeszły wynik "
         "nie gwarantuje przyszłego. Portevo pokazuje dane, nie rekomendacje."),
    ]
    bloki.append(render.sekcja("Najczęstsze pytania", kotwica="pytania",
                               html_dodatkowy=render.faq(pary)))

    # inni z tej samej grupy — gęste linkowanie wewnętrzne
    panel = _panel()
    podobni = [x for x in panel.get("leaders") or []
               if x["id"] != pid and x.get("cat") == o.get("cat") and adres_osoby(x["id"])][:8]
    if len(podobni) < 4:
        podobni += [x for x in panel.get("leaders") or []
                    if x["id"] != pid and x not in podobni and adres_osoby(x["id"])][:8 - len(podobni)]
    if podobni:
        bloki.append(render.sekcja(
            "Zobacz też",
            html_dodatkowy='<div class="ptiles">' + "".join(
                f'<a class="ptile" href="{esc(adres_osoby(x["id"]))}">{awatar(x, 40)}'
                f'<span><b>{esc(x["name"])}</b><small>{esc(_opis_roli(x))}</small></span></a>'
                for x in podobni) + "</div>"))

    bloki.append(render.zacheta(
        f"Obserwuj {nazwa} w Portevo",
        "Powiadomienie przy każdej nowej transakcji, pełna historia, wykres zakupów "
        "i twarz na wykresie każdej kupionej spółki.",
        adres=f"{APLIKACJA}?osoba={pid}", etykieta="🔔 Obserwuj w aplikacji",
        drugi=(BAZA, "Wszyscy insiderzy")))
    bloki.append(render.zastrzezenie())

    rokteraz = dt.date.today().year
    tytul = f"{nazwa}: portfel i transakcje akcjami {rokteraz}"
    if len(tytul) > 50:
        tytul = f"{nazwa}: transakcje akcjami {rokteraz}"
    opis = (f"Co kupuje i sprzedaje {nazwa}? Ostatnia transakcja: "
            f"{data_pl(trans[0]['date'])} ({'kupno' if trans[0]['side'] == 'buy' else 'sprzedaż'} "
            f"{trans[0].get('ticker')})."
            + (f" Wynik zakupów z roku: {render.procent(r)}." if r is not None else "")
            + " Pełna lista z oficjalnych zgłoszeń, po polsku.")
    sciezka = f"{BAZA}/{slug}"
    okruchy = [(BAZA, "Transakcje insiderów"), ("", nazwa)]
    foto = zdjecie(o.get("photo") or "")
    osoba_ld = {"@type": "Person", "name": nazwa,
                "jobTitle": _opis_roli(o) or None,
                "image": site.absolute(foto.split("?")[0]) if foto else None,
                "description": bio or None}
    osoba_ld = {k2: v for k2, v in osoba_ld.items() if v}
    profil_ld = {"@context": "https://schema.org", "@type": "ProfilePage",
                 "name": tytul, "url": site.absolute(sciezka),
                 "dateModified": ostatnie_zgloszenie(pid)[:10],
                 "inLanguage": "pl-PL", "mainEntity": osoba_ld}
    return render.strona(
        sciezka=sciezka, tytul=tytul + " | Portevo", opis=opis[:300],
        h1=f"{nazwa}: co kupuje i sprzedaje",
        lead=(f"Wszystkie ujawnione transakcje akcjami — z wynikiem zakupów, strukturą "
              f"portfela i datą każdego zgłoszenia. {esc(_opis_roli(o))}."),
        nadtytul="Transakcje insiderów", okruchy=okruchy, szeroki_naglowek=True,
        wizual=karta_osoby(o, st, trans[0], ramka),
        aktualizacja=data_pl(ostatnie_zgloszenie(pid)[:10]),
        akcje=[(f"{APLIKACJA}?osoba={pid}", "🔔 Obserwuj i dostawaj powiadomienia"),
               (BAZA, "Ranking insiderów")],
        bloki=bloki, obrazek=foto,
        jsonld=[profil_ld, jsonld.okruchy(okruchy), jsonld.pytania(pary)])


# ------------------------------------------------------------------ klasy


def _kongres() -> str:
    store = _store()
    od12 = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    akt = [a for a in store.activity(od12, ("house", "senat"))]
    akt.sort(key=lambda a: -(a["buys"] + a["sells"]))
    wiersze = store.people_rows([a["person"] for a in akt[:60]])
    osoby = []
    for a in akt[:60]:
        o = _osoba(a["person"], wiersze.get(a["person"]), store.stats_get(a["person"], 14 * 86400), a)
        osoby.append(o)
    # partie
    d = sum(1 for o in osoby if o.get("party") == "D")
    rp = sum(1 for o in osoby if o.get("party") == "R")
    # najczęściej kupowane przez Kongres
    top = store._rows(
        "select ticker, max(asset) as asset, count(*) as n, count(distinct person) as osob "
        "from trades where source in ('house','senat') and side='buy' and date >= ? "
        "and ticker != '' group by ticker order by osob desc, n desc limit 15", (od12,))
    bloki = ["<section>" + render.statystyki([
        ("Aktywnych polityków", str(len(akt)), "z transakcją w roku"),
        ("Transakcji w roku", render.liczba(sum(a["buys"] + a["sells"] for a in akt), 0), "Izba i Senat"),
        ("Demokraci / Republikanie", f"{d} / {rp}", "wśród 60 najaktywniejszych"),
    ]) + "</section>"]
    bloki.append(render.sekcja(
        "Najaktywniejsi w Kongresie",
        "Kolejność według liczby transakcji w ostatnich 12 miesiącach.",
        html_dodatkowy=_lista([_wiersz_osoby(o, i, *_wynik_html(o)) for i, o in enumerate(osoby[:40])],
                              ("Ranking Kongresu", "12 miesięcy"),
                              (APLIKACJA, "Obserwuj polityków w aplikacji"))))
    if top:
        bloki.append(render.sekcja(
            "Które spółki kupują politycy",
            "Spółki, które w ostatnim roku kupiło najwięcej różnych członków Kongresu.",
            html_dodatkowy=render.tabela(
                ["Spółka", ("Kupujących polityków", True), ("Zakupów", True)],
                [((_walor(t["asset"] or "") or t["ticker"]) + f" ({t['ticker']})",
                  (str(t["osob"]), "num"), (str(t["n"]), "num")) if not _spolka_z_tickera(t["ticker"]) else
                 (((_walor(t["asset"] or "") or t["ticker"]) + f" ({t['ticker']})", "link",
                   companies.adres(_spolka_z_tickera(t["ticker"]))),
                  (str(t["osob"]), "num"), (str(t["n"]), "num")) for t in top])))
    feed = store.feed((dt.date.today() - dt.timedelta(days=30)).isoformat(), limit=20,
                      sources=("house", "senat"))
    fo = store.people_rows(list({t["person"] for t in feed}))
    bloki.append(render.sekcja(
        "Zgłoszenia z ostatnich 30 dni",
        html_dodatkowy=_lista([_wiersz_transakcji(t, _osoba(t["person"], fo.get(t["person"])))
                               for t in feed])))
    return _strona_klasy("kongres-usa", bloki, [
        ("Kto w Kongresie handluje akcjami najczęściej?",
         f"W ostatnich 12 miesiącach najwięcej transakcji zgłosili: "
         + ", ".join(o["name"] for o in osoby[:5]) + "."),
        ("Ile czasu mają kongresmeni na zgłoszenie transakcji?",
         "45 dni od transakcji (STOCK Act). Kwoty podają przedziałami, np. 15 001–50 000 $."),
        ("Czy transakcje małżonków też są zgłaszane?",
         "Tak — raport obejmuje małżonka i dzieci na utrzymaniu. U Nancy Pelosi "
         "większość transakcji to konta męża, Paula Pelosiego."),
    ])


def _gpw() -> str:
    store = _store()
    od90 = (dt.date.today() - dt.timedelta(days=90)).isoformat()
    feed = store.feed((dt.date.today() - dt.timedelta(days=45)).isoformat(), limit=30,
                      sources=("gpw",))
    fo = store.people_rows(list({t["person"] for t in feed}))
    top = store._rows(
        "select ticker, max(asset) as asset, count(distinct person) as osob, "
        "sum(case when side='buy' then coalesce(amt_lo,0) else 0 end) as kup, "
        "sum(case when side='sell' then coalesce(amt_lo,0) else 0 end) as sprz "
        "from trades where source='gpw' and date >= ? and ticker != '' "
        "group by ticker having kup > 0 order by kup desc limit 15", (od90,))
    bloki = [render.sekcja(
        "Spółki, w które insiderzy włożyli najwięcej (90 dni)",
        "Suma zakupów akcji przez członków zarządu, rady nadzorczej i osoby z nimi "
        "związane — minus to, co sprzedali, widać w ostatniej kolumnie.",
        html_dodatkowy=render.tabela(
            ["Spółka", ("Insiderów", True), ("Kupili", True), ("Sprzedali", True)],
            [(((t["asset"] or t["ticker"]), "link", companies.adres(_spolka_z_tickera(t["ticker"])))
              if _spolka_z_tickera(t["ticker"]) else (t["asset"] or t["ticker"]),
              (str(t["osob"]), "num"), (krotko(t["kup"]) + " zł", "up"),
              (krotko(t["sprz"]) + " zł" if t["sprz"] else "—", "num")) for t in top]))]
    bloki.append(render.sekcja(
        "Świeże zgłoszenia z GPW",
        "Członek zarządu lub rady musi zgłosić transakcję do 3 dni roboczych (MAR art. 19).",
        html_dodatkowy=_lista([_wiersz_transakcji(t, _osoba(t["person"], fo.get(t["person"])))
                               for t in feed[:25]], ("Ostatnie zgłoszenia", "kwoty w złotych"),
                              (APLIKACJA, "Insiderzy GPW w aplikacji"))))
    return _strona_klasy("gpw", bloki, [
        ("Gdzie sprawdzić transakcje insiderów na GPW?",
         "Źródłem są raporty ESPI z powiadomieniami z art. 19 MAR. Portevo zbiera je "
         "automatycznie, łączy ze spółką i pokazuje na wykresie kursu w dniu zakupu."),
        ("Kto jest insiderem w spółce z GPW?",
         "Osoby pełniące obowiązki zarządcze — członkowie zarządu i rady nadzorczej — "
         "oraz osoby blisko z nimi związane (np. małżonkowie, spółki przez nie kontrolowane)."),
        ("Od jakiej kwoty zgłasza się transakcję?",
         "Obowiązek dotyczy transakcji po przekroczeniu 20 000 euro łącznie w roku kalendarzowym."),
    ])


def _usa() -> str:
    store = _store()
    od90 = (dt.date.today() - dt.timedelta(days=90)).isoformat()
    duze = store._rows(
        "select * from trades where source='sec' and side='buy' and date >= ? "
        "and coalesce(amt_lo,0) >= 250000 order by amt_lo desc limit 25", (od90,))
    fo = store.people_rows(list({t["person"] for t in duze}))
    klaster = store._rows(
        "select ticker, max(asset) as asset, count(distinct person) as osob, "
        "sum(coalesce(amt_lo,0)) as suma from trades where source='sec' and side='buy' "
        "and date >= ? and ticker != '' group by ticker having osob >= 3 "
        "order by osob desc, suma desc limit 15", (od90,))
    bloki = [render.sekcja(
        "Największe zakupy insiderów w USA (90 dni)",
        "Zakupy akcji na rynku (kod P w Form 4) — bez opcji i przydziałów z wynagrodzenia. "
        "Insider, który wydaje własne pieniądze, mówi więcej niż ten, który sprzedaje.",
        html_dodatkowy=_lista([_wiersz_transakcji(t, _osoba(t["person"], fo.get(t["person"])))
                               for t in duze], ("Zakupy od 250 tys. $", "Form 4 · SEC"),
                              (APLIKACJA, "Wszystkie zgłoszenia w aplikacji")))]
    if klaster:
        bloki.append(render.sekcja(
            "Spółki, w których kupuje kilku insiderów naraz",
            "Kilku członków zarządu kupujących w tym samym czasie to w badaniach "
            "jeden z mocniejszych sygnałów z transakcji insiderów.",
            html_dodatkowy=render.tabela(
                ["Spółka", ("Kupujących insiderów", True), ("Razem", True)],
                [((((_walor(t["asset"] or "") or t["ticker"]) + f" ({t['ticker']})"), "link",
                   companies.adres(_spolka_z_tickera(t["ticker"])))
                  if _spolka_z_tickera(t["ticker"]) else ((_walor(t["asset"] or "") or t["ticker"]) + f" ({t['ticker']})"),
                  (str(t["osob"]), "num"), (krotko(t["suma"]) + " $", "num")) for t in klaster])))
    return _strona_klasy("spolki-usa", bloki, [
        ("Co to jest Form 4?",
         "Formularz, którym insider spółki z USA zgłasza komisji SEC transakcję na jej "
         "akcjach — do dwóch dni roboczych, z liczbą akcji i ceną."),
        ("Czy zakup akcji przez prezesa to dobry znak?",
         "Często tak jest odbierany — insider sprzedaje z wielu powodów (podatki, dom), "
         "ale kupuje zwykle z jednego. To wciąż nie rekomendacja."),
    ])


def _strona_klasy(klucz: str, bloki: list[str], pary) -> str:
    cfg = KLASY_STRON[klucz]
    bloki = list(bloki)
    bloki.append(render.sekcja("Najczęstsze pytania", kotwica="pytania",
                               html_dodatkowy=render.faq(pary)))
    bloki.append(render.sekcja(
        "Inne rankingi",
        html_dodatkowy=render.chipsy([(BAZA, "Wszyscy insiderzy")] + [
            (f"{BAZA}/{k}", KLASY_STRON[k]["nadtytul"]) for k in KLASY_STRON if k != klucz]
            + [(f"{BAZA}/nancy-pelosi", "Nancy Pelosi"), (f"{BAZA}/donald-trump", "Donald Trump")])))
    bloki.append(render.zacheta(
        "Twarze insiderów na wykresie każdej spółki",
        "W Portevo każda transakcja z tej listy stoi na wykresie kursu w dniu zakupu — "
        "ze zdjęciem albo funkcją osoby. Obserwuj, kogo chcesz, i dostawaj powiadomienia.",
        adres=APLIKACJA, etykieta="Otwórz panel insiderów",
        drugi=("/?zaloguj=1", "Załóż darmowe konto")))
    bloki.append(render.zastrzezenie())
    sciezka = f"{BAZA}/{klucz}"
    okruchy = [(BAZA, "Transakcje insiderów"), ("", cfg["nadtytul"])]
    return render.strona(
        sciezka=sciezka, tytul=cfg["tytul"], opis=cfg["opis"], h1=cfg["h1"],
        lead=esc(cfg["opis"]), nadtytul=cfg["nadtytul"], okruchy=okruchy,
        szeroki_naglowek=True, aktualizacja=data_pl(dt.date.today().isoformat()),
        akcje=[(APLIKACJA, "Otwórz panel insiderów"), (BAZA, "Ranking insiderów")],
        bloki=bloki,
        jsonld=[jsonld.strona(sciezka, cfg["tytul"], cfg["opis"], typ="CollectionPage"),
                jsonld.okruchy(okruchy), jsonld.pytania(pary)])


# ------------------------------------------------------------------ wejście


def zbuduj(slug: str = "") -> str | None:
    """HTML strony albo None (404)."""
    try:
        if not slug:
            return _zapamietane("przeglad", _przeglad)
        if slug == "kongres-usa":
            return _zapamietane("kongres", _kongres)
        if slug == "gpw":
            return _zapamietane("gpw", _gpw)
        if slug == "spolki-usa":
            return _zapamietane("usa", _usa)
        if slug not in _mapa():
            return None
        return _zapamietane(f"osoba:{slug}", lambda: _profil(slug))
    except Exception:  # noqa: BLE001 — baza insiderów niedostępna nie może dać 500
        log.exception("Strona insiderów %s", slug)
        return None


def sekcja_spolki(symbol: str, nazwa: str) -> str:
    """Blok „Transakcje insiderów" na karcie spółki (`/wyniki-finansowe/…`)."""
    try:
        store = _store()
        od = (dt.date.today() - dt.timedelta(days=730)).isoformat()
        tick = symbol.upper()
        trans = store.trades_for_tickers([tick], od, limit=400)
    except Exception:  # noqa: BLE001
        return ""
    if not trans:
        return ""
    od12 = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    rok = [t for t in trans if t["date"] >= od12]
    wiersze = store.people_rows(list({t["person"] for t in trans}))
    kup = [t for t in rok if t["side"] == "buy"]
    cur = "PLN" if tick.endswith(".WA") else "USD"
    osoby = {p: _osoba(p, wiersze.get(p)) for p in {t["person"] for t in trans[:40]}}
    # znane osoby na górę — to one są powodem, żeby tu zajrzeć
    lista = sorted(trans[:40], key=lambda t: t["date"], reverse=True)
    znani = [t for t in lista if people_rank(t["person"])][:3]
    reszta = [t for t in lista if t not in znani][:8 - len(znani)]
    kafle = render.statystyki([
        ("Zakupy insiderów · 12 mies.", str(len(kup)), _kasa(sum(t.get("amt_lo") or 0 for t in kup), cur)),
        ("Sprzedaże · 12 mies.", str(len(rok) - len(kup)), ""),
        ("Różnych osób", str(len({t["person"] for t in rok})), "w ostatnim roku"),
        ("Ostatnia transakcja", data_pl(trans[0]["date"]), ""),
    ])
    return render.sekcja(
        f"Transakcje insiderów: {nazwa}",
        "Kto z zarządu, rady nadzorczej, Kongresu USA albo rządu kupował i sprzedawał "
        "akcje tej spółki — z oficjalnych zgłoszeń.",
        kotwica="insiderzy",
        html_dodatkowy=kafle + _lista(
            [_wiersz_transakcji(t, osoby[t["person"]]) for t in znani + reszta],
            ("Ostatnie transakcje", "Form 4, STOCK Act, OGE, MAR"),
            (f"/?spolka={symbol}", "Zobacz twarze insiderów na wykresie w aplikacji")))


def people_rank(pid: str) -> int:
    k = _people().curated(pid)
    return (k or {}).get("rank") or 0


# ------------------------------------------------------------------ styl

CSS = """
.av{position:relative;display:inline-flex;flex:0 0 auto;width:var(--av,48px);height:var(--av,48px);
  border-radius:50%;overflow:hidden;background:#1a2030;border:2px solid var(--border-2);
  align-items:center;justify-content:center;vertical-align:middle}
.av img{width:100%;height:100%;object-fit:cover;object-position:50% 15%}
.av i{font-style:normal;font-weight:800;color:var(--muted);font-size:calc(var(--av,48px)*.34)}
.av.gold{border:3px solid #f5c451;box-shadow:0 0 0 3px rgba(245,196,81,.18),0 8px 26px rgba(245,196,81,.25)}
.av.silver{border:3px solid #dfe4ee;box-shadow:0 0 0 3px rgba(223,228,238,.12)}
.av.bronze{border:3px solid #e7a36b;box-shadow:0 0 0 3px rgba(231,163,107,.14)}
.av.buy{border-color:var(--green)}.av.sell{border-color:var(--red)}
.rows .row .nr{width:22px;flex:0 0 22px;text-align:center;font-weight:800;color:var(--dim);font-size:14px}
.rows .prow.top1{background:linear-gradient(90deg,rgba(245,196,81,.10),transparent 70%)}
.rows .prow.top1 .nr{color:#f5c451}
.pill{display:inline-block;padding:3px 10px;border-radius:999px;font-weight:800;font-size:14px}
.pill.up{background:var(--green-dim);color:var(--green)}
.pill.down{background:rgba(255,92,108,.12);color:var(--red)}
.rows .trow .nm{font-size:14.5px}
.rows .trow .nm .who{color:var(--text);font-weight:700}
.rows .trow .tk{font-weight:800;color:var(--text)}
.rows .trow .sub a{color:var(--muted)}
/* nagłówek z wizualem */
.herocard{background:linear-gradient(160deg,#151b29,#0f131c);border:1px solid var(--border-2);
  border-radius:20px;padding:16px;box-shadow:0 30px 80px rgba(0,0,0,.45)}
.hc-top{display:flex;align-items:center;gap:8px;font-size:11.5px;font-weight:800;
  letter-spacing:1px;text-transform:uppercase;color:var(--dim);padding:2px 4px 12px}
.live{width:8px;height:8px;border-radius:50%;background:var(--green);
  box-shadow:0 0 0 0 rgba(47,212,138,.6);animation:puls 1.8s infinite}
@keyframes puls{0%{box-shadow:0 0 0 0 rgba(47,212,138,.55)}70%{box-shadow:0 0 0 9px rgba(47,212,138,0)}100%{box-shadow:0 0 0 0 rgba(47,212,138,0)}}
.hrow{display:flex;align-items:center;gap:12px;padding:11px 10px;border-radius:14px;
  border:1px solid var(--border);background:var(--card);margin-bottom:8px;color:inherit}
.hrow:hover{border-color:var(--green);text-decoration:none}
.hrow.top1{border-color:rgba(245,196,81,.5);background:linear-gradient(90deg,rgba(245,196,81,.12),var(--card))}
.hrow .nr{font-weight:800;color:var(--dim);width:14px}
.hrow.top1 .nr{color:#f5c451}
.hn{flex:1;min-width:0;display:flex;flex-direction:column}
.hn b{font-size:15.5px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hn small,.hv small{font-size:11.5px;color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hv{display:flex;flex-direction:column;align-items:flex-end;font-weight:800;gap:2px}
.hc-more{display:block;text-align:center;font-size:13.5px;font-weight:700;padding:8px 0 2px}
.pid{margin-bottom:16px}
.pcard{background:linear-gradient(165deg,#171e2e,#0f131c);border:1px solid var(--border-2);
  border-radius:22px;padding:24px 22px 20px;text-align:center;display:flex;flex-direction:column;
  align-items:center;gap:6px;box-shadow:0 30px 80px rgba(0,0,0,.45);max-width:380px;margin-left:auto}
.pc-photo{margin-bottom:8px}
.pc-name{font-size:21px;font-weight:800;letter-spacing:-.4px}
.pc-role{font-size:13px;color:var(--dim)}
.pc-ret{display:flex;flex-direction:column;align-items:center;gap:4px;margin-top:10px}
.pc-ret small{font-size:12px;color:var(--dim)}
.pill.big{font-size:22px;padding:6px 16px}
.pc-last{width:100%;margin-top:14px;padding:12px;border-radius:14px;background:var(--card);
  border:1px solid var(--border);display:flex;flex-direction:column;gap:3px}
.pc-last span{font-size:11px;font-weight:800;letter-spacing:.8px;text-transform:uppercase;color:var(--dim)}
.pc-last b{font-size:15px}.pc-last em{font-style:normal}
.pc-last small{font-size:12.5px;color:var(--muted)}
.pc-btn{width:100%;margin-top:12px;text-align:center;padding:12px}
.av.plain{border-color:var(--border-2)}
@media (max-width:900px){.pcard{margin:0 auto}}
/* pasek obserwowania */
.follow{display:flex;align-items:center;gap:14px;margin-top:16px;padding:14px 16px;
  border-radius:16px;border:1px solid rgba(47,212,138,.35);
  background:linear-gradient(90deg,rgba(47,212,138,.10),rgba(79,155,255,.05))}
.follow .ft{flex:1;min-width:0;display:flex;flex-direction:column;gap:3px}
.follow .ft b{font-size:15px}.follow .ft span{font-size:13px;color:var(--muted)}
@media (max-width:640px){.follow{flex-wrap:wrap}.follow .btn{width:100%;text-align:center}}
/* koło */
.donut{display:flex;gap:26px;align-items:center;flex-wrap:wrap;margin-top:18px;
  background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:20px}
.donut svg{flex:0 0 auto}
.donut .dk{fill:var(--dim);font-size:10px;font-weight:800;letter-spacing:1.4px}
.donut .dv{fill:var(--text);font-size:17px;font-weight:800}
.donut ul{list-style:none;display:grid;gap:9px;flex:1;min-width:230px}
.donut li{display:flex;align-items:center;gap:10px;font-size:14px}
.donut li i{width:10px;height:10px;border-radius:3px;flex:0 0 auto}
.donut li b{color:var(--text);min-width:56px}
.donut li span{color:var(--dim);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.donut li em{font-style:normal;font-weight:750;color:var(--text);font-variant-numeric:tabular-nums}
/* wykres z twarzami */
.fcwrap{margin-top:18px;background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:16px 16px 12px}
.fchead{display:flex;justify-content:space-between;gap:10px;font-size:14px;padding:0 4px 6px}
.facechart{width:100%;height:auto;display:block}
.facechart .st{stroke:#9aa3b8;stroke-opacity:.5;stroke-width:1.2}
.facechart .pt{fill:#2fd48a;stroke:#080b11;stroke-width:2}
.facechart .rg{fill:#0f131c;stroke:#2fd48a;stroke-width:2.5}
.facechart .fl{fill:#eef1f7;font-size:11.5px;font-weight:700}
.facechart .fi{fill:#9aa3b8;font-size:12px;font-weight:800}
.facechart .ax{fill:#5c6479;font-size:11px}
.fcwrap figcaption{font-size:12.5px;color:var(--dim);padding:8px 4px 0}
/* kafle osób */
.ptiles{display:grid;gap:10px;margin-top:18px;grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}
.ptile{display:flex;align-items:center;gap:12px;background:var(--card);border:1px solid var(--border);
  border-radius:12px;padding:10px 12px;color:inherit}
.ptile:hover{border-color:var(--green);text-decoration:none}
.ptile span{display:flex;flex-direction:column;min-width:0}
.ptile b{font-size:14.5px;color:var(--text)}
.ptile small{font-size:12px;color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.aiq{display:block;color:var(--text);font-size:16.5px;line-height:1.7;border-left:3px solid #b78bff;padding-left:16px}
.note{font-size:12.5px;color:var(--dim)}
"""
