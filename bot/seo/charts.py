"""Wykresy podstron SEO — rysowane serwerowo jako SVG wklejony w HTML.

Po co w ogóle: podstrona z samymi tabelami odpowiada na pytanie, ale nie pokazuje
kształtu zjawiska. „Kurs po wynikach: −4,13%, −0,50%, +2,10%” to sześć liczb do
przeczytania; ten sam zestaw jako słupki wokół zera czyta się jednym spojrzeniem.
Człowiek, który po dwóch sekundach widzi obraz, zostaje — a czas na stronie
i brak powrotu do wyników wyszukiwania to jedne z niewielu sygnałów jakości,
które Google mierzy bezbłędnie.

Dlaczego SVG w treści, a nie obrazek ani biblioteka wykresów:

* **Zero dodatkowych żądań.** Wykres jest częścią tego samego dokumentu, więc
  nie ma drugiego pobrania, nie ma przeskoku układu strony i nie psuje LCP.
* **Zero JavaScriptu.** Cała warstwa SEO działa bez skryptów (patrz `render.py`)
  i to się nie zmienia — biblioteka wykresów kosztowałaby setki kilobajtów
  i rysowała dopiero po wykonaniu kodu, czyli po tym, jak robot zrobi zrzut.
* **Ostry na każdym ekranie.** Grafika wektorowa nie ma rozdzielczości, więc
  na telefonie z ekranem retina wygląda tak samo dobrze jak na monitorze.
* **Czytelny dla maszyn.** Liczby zostają w `<text>`, a `<title>`/`<desc>`
  opisują wykres słowami — model językowy przeczyta z niego fakt, a nie kształt.

Dostępność: każdy wykres to `role="img"` z `<title>` i `<desc>`, opakowany
w `<figure>` z podpisem. Czytnik ekranu dostaje zdanie opisujące zawartość,
a nie listę współrzędnych. **Wykres nigdy nie jest jedynym nośnikiem danych** —
pod każdym stoi ta sama tabela. To reguła, nie ozdobnik: obraz bez tabeli jest
niedostępny dla części użytkowników i bezwartościowy dla wyszukiwarki.

Kolory pochodzą ze zmiennych CSS motywu (`--green`, `--red`, `--blue`), więc
wykresy zmienią się razem z resztą serwisu, gdy paleta kiedyś się przesunie.
"""

from __future__ import annotations

from .render import esc, liczba

# Układ współrzędnych jest stały (szerokość 720), a wykres skaluje się przez
# `viewBox` do szerokości rodzica. Dzięki temu rozmiary czcionek i odstępy
# dobiera się raz, a nie osobno dla telefonu i monitora.
SZER = 720
MARGINES = {"lewy": 8, "prawy": 8, "gora": 26, "dol": 40}


# --------------------------------------------------------------- narzędzia


def _txt(x: float, y: float, tekst: str, klasa: str = "", kotwica: str = "middle") -> str:
    k = f' class="{klasa}"' if klasa else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{kotwica}"{k}>'
            f"{esc(tekst)}</text>")


def _figura(svg: str, podpis: str = "", klasa: str = "") -> str:
    cap = f"<figcaption>{esc(podpis)}</figcaption>" if podpis else ""
    return f'<figure class="fig{" " + klasa if klasa else ""}">{svg}{cap}</figure>'


def _svg(wys: int, srodek: str, tytul: str, opis: str) -> str:
    """Ramka wykresu. `role="img"` + `<title>` — dla czytnika ekranu to jeden obraz."""
    return (
        f'<svg class="chart" viewBox="0 0 {SZER} {wys}" width="{SZER}" height="{wys}" '
        f'role="img" preserveAspectRatio="xMidYMid meet" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f"<title>{esc(tytul)}</title><desc>{esc(opis)}</desc>{srodek}</svg>"
    )


def _skrot_daty(iso: str) -> str:
    """„2026-02-25” → „II 26”. Na osi nie ma miejsca na pełną datę."""
    rzymskie = ("I", "II", "III", "IV", "V", "VI",
                "VII", "VIII", "IX", "X", "XI", "XII")
    try:
        rok, mies = iso[:4], int(iso[5:7])
        return f"{rzymskie[mies - 1]} {rok[2:]}"
    except (ValueError, IndexError, TypeError):
        return (iso or "")[:7]


def _kwartal(iso: str) -> str:
    """„2026-04-30” → „Q2 26” — kwartał kalendarzowy, w którym kończy się okres."""
    try:
        rok, mies = iso[:4], int(iso[5:7])
        return f"Q{(mies - 1) // 3 + 1} {rok[2:]}"
    except (ValueError, IndexError, TypeError):
        return (iso or "")[:7]


def _liczby(wartosci) -> list[float]:
    return [float(v) for v in wartosci if isinstance(v, (int, float))]


# --------------------------------------------------------------- reakcja kursu


def reakcje_kursu(historia: list, nazwa: str) -> str:
    """Słupki wokół zera: zmiana kursu na sesji po każdej publikacji wyników.

    To jest najciekawszy wykres na całej podstronie spółki, bo odpowiada na
    pytanie, które ludzie naprawdę zadają przed raportem — „ile ta spółka
    zwykle skacze”. Zero jest osią, więc kierunek widać bez czytania liczb.
    """
    dane = [(h.get("date") or h.get("quarter") or "", h.get("reaction_pct"))
            for h in historia if isinstance(h.get("reaction_pct"), (int, float))]
    dane = dane[-8:]
    if len(dane) < 2:
        return ""

    wys = 250
    pole_g, pole_d = MARGINES["gora"], wys - MARGINES["dol"]
    pole_w = SZER - MARGINES["lewy"] - MARGINES["prawy"]
    zero = (pole_g + pole_d) / 2
    szczyt = max(abs(v) for _, v in dane) or 1.0
    skala = (pole_d - pole_g) / 2 / (szczyt * 1.18)

    krok = pole_w / len(dane)
    szer_slupka = min(58.0, krok * 0.5)

    czesci = [f'<line class="ax" x1="{MARGINES["lewy"]}" y1="{zero:.1f}" '
              f'x2="{SZER - MARGINES["prawy"]}" y2="{zero:.1f}"></line>']

    for i, (data, v) in enumerate(dane):
        srodek = MARGINES["lewy"] + krok * (i + 0.5)
        h = max(2.0, abs(v) * skala)
        y = zero - h if v >= 0 else zero
        klasa = "up" if v >= 0 else "down"
        czesci.append(
            f'<rect class="bar {klasa}" x="{srodek - szer_slupka / 2:.1f}" y="{y:.1f}" '
            f'width="{szer_slupka:.1f}" height="{h:.1f}" rx="3"></rect>')
        # Etykieta zawsze po zewnętrznej stronie słupka — w środku ginie na kolorze.
        czesci.append(_txt(srodek, (y - 7) if v >= 0 else (y + h + 15),
                           f"{'+' if v > 0 else ''}{liczba(v)}%", f"val {klasa}"))
        czesci.append(_txt(srodek, wys - 14, _skrot_daty(data), "ax-lab"))

    dodatnie = sum(1 for _, v in dane if v > 0)
    opis = (f"Wykres słupkowy: zmiana kursu {nazwa} na sesji po {len(dane)} ostatnich "
            f"publikacjach wyników. Wzrost po {dodatnie} z nich, spadek po "
            f"{len(dane) - dodatnie}. Największy ruch: {liczba(szczyt)}%.")
    return _figura(
        _svg(wys, "".join(czesci), f"Reakcja kursu {nazwa} po wynikach", opis),
        f"Zmiana kursu {nazwa} na sesji po publikacji raportu. "
        f"Zielony słupek to wzrost, czerwony spadek.")


# --------------------------------------------------------------- EPS


def prognoza_i_wynik(historia: list, nazwa: str, waluta: str = "") -> str:
    """Pary słupków: czego oczekiwali analitycy i co spółka pokazała.

    Wykres świadomie zaczyna się od zera — słupki obcięte u dołu wyolbrzymiają
    różnicę i sugerowałyby dramat tam, gdzie chodzi o kilka groszy na akcję.
    """
    dane = [(h.get("quarter") or "", h.get("estimate"), h.get("eps"))
            for h in historia
            if isinstance(h.get("estimate"), (int, float))
            and isinstance(h.get("eps"), (int, float))]
    dane = dane[-6:]
    if len(dane) < 2:
        return ""

    wszystkie = _liczby([x for _, a, b in dane for x in (a, b)])
    # Ujemny EPS (spółka pod kreską) to normalny przypadek — wtedy oś musi
    # sięgać poniżej zera, inaczej strata wyszłaby jako słupek zerowy.
    dol = min(0.0, min(wszystkie))
    gora = max(0.0, max(wszystkie)) or 1.0
    rozpietosc = (gora - dol) or 1.0

    wys = 262
    pole_g, pole_d = MARGINES["gora"] + 12, wys - MARGINES["dol"]
    pole_w = SZER - MARGINES["lewy"] - MARGINES["prawy"]
    skala = (pole_d - pole_g) / (rozpietosc * 1.15)
    zero_y = pole_d - (0.0 - dol) * skala

    krok = pole_w / len(dane)
    szer_slupka = min(30.0, krok * 0.26)
    czesci = [f'<line class="ax" x1="{MARGINES["lewy"]}" y1="{zero_y:.1f}" '
              f'x2="{SZER - MARGINES["prawy"]}" y2="{zero_y:.1f}"></line>']

    for i, (kwartal, prog, wynik) in enumerate(dane):
        srodek = MARGINES["lewy"] + krok * (i + 0.5)
        for przesuniecie, wartosc, klasa in (
                (-szer_slupka * 0.58, prog, "est"), (szer_slupka * 0.58, wynik, "act")):
            h = max(2.0, abs(wartosc) * skala)
            y = zero_y - h if wartosc >= 0 else zero_y
            czesci.append(
                f'<rect class="bar {klasa}" x="{srodek + przesuniecie - szer_slupka / 2:.1f}" '
                f'y="{y:.1f}" width="{szer_slupka:.1f}" height="{h:.1f}" rx="3"></rect>')
            czesci.append(_txt(srodek + przesuniecie,
                               (y - 6) if wartosc >= 0 else (y + h + 14),
                               liczba(wartosc), "val"))
        czesci.append(_txt(srodek, wys - 14, _kwartal(kwartal), "ax-lab"))

    czesci.append('<g class="legend">'
                  f'<rect class="bar est" x="{MARGINES["lewy"]}" y="6" width="12" '
                  'height="12" rx="2"></rect>'
                  + _txt(MARGINES["lewy"] + 18, 16, "prognoza analityków", "leg", "start")
                  + f'<rect class="bar act" x="{MARGINES["lewy"] + 168}" y="6" width="12" '
                    'height="12" rx="2"></rect>'
                  + _txt(MARGINES["lewy"] + 186, 16, "wynik spółki", "leg", "start")
                  + "</g>")

    pobite = sum(1 for _, a, b in dane if b > a)
    opis = (f"Wykres słupkowy porównujący prognozę zysku na akcję z wynikiem "
            f"{nazwa} w {len(dane)} ostatnich kwartałach. Wynik wyższy od prognozy "
            f"w {pobite} z nich.")
    return _figura(
        _svg(wys, "".join(czesci), f"Prognoza a wynik EPS — {nazwa}", opis),
        f"Zysk na akcję {nazwa}: prognoza analityków i rzeczywisty wynik"
        + (f", w {waluta}." if waluta else "."))


# --------------------------------------------------------------- przychody


def przychody_i_marza(kwartaly: list, nazwa: str, waluta: str = "") -> str:
    """Słupki przychodów z nałożoną linią marży netto.

    Dwie osie na jednym obrazku są zwykle złym pomysłem, ale tutaj niosą jedną
    myśl: czy wzrost sprzedaży idzie w parze z rentownością. Rosnące słupki
    i opadająca linia to obraz, którego z dwóch osobnych wykresów nie widać.
    """
    dane = [k for k in kwartaly
            if isinstance(k.get("revenue"), (int, float)) and k.get("revenue")]
    dane = dane[-8:]
    if len(dane) < 3:
        return ""

    maks = max(k["revenue"] for k in dane) or 1.0
    marze = [k.get("net_margin") if isinstance(k.get("net_margin"), (int, float))
             else None for k in dane]
    ma_marze = sum(1 for m in marze if m is not None) >= 3

    wys = 258
    pole_g, pole_d = MARGINES["gora"] + 10, wys - MARGINES["dol"]
    pole_w = SZER - MARGINES["lewy"] - MARGINES["prawy"]
    krok = pole_w / len(dane)
    szer_slupka = min(56.0, krok * 0.52)

    czesci = [f'<line class="ax" x1="{MARGINES["lewy"]}" y1="{pole_d:.1f}" '
              f'x2="{SZER - MARGINES["prawy"]}" y2="{pole_d:.1f}"></line>']

    for i, k in enumerate(dane):
        srodek = MARGINES["lewy"] + krok * (i + 0.5)
        h = max(2.0, (k["revenue"] / maks) * (pole_d - pole_g))
        czesci.append(
            f'<rect class="bar rev" x="{srodek - szer_slupka / 2:.1f}" '
            f'y="{pole_d - h:.1f}" width="{szer_slupka:.1f}" height="{h:.1f}" rx="3"></rect>')
        czesci.append(_txt(srodek, wys - 14, _kwartal(k.get("date") or ""), "ax-lab"))

    if ma_marze:
        widoczne = [m for m in marze if m is not None]
        m_min, m_max = min(widoczne + [0.0]), max(widoczne)
        rozpietosc = (m_max - m_min) or 1.0
        punkty, kropki = [], []
        for i, m in enumerate(marze):
            if m is None:
                continue
            x = MARGINES["lewy"] + krok * (i + 0.5)
            y = pole_d - 18 - ((m - m_min) / rozpietosc) * (pole_d - pole_g - 46)
            punkty.append(f"{x:.1f},{y:.1f}")
            kropki.append(f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="3.6"></circle>')
            kropki.append(_txt(x, y - 10, f"{liczba(m)}%", "val mg"))
        czesci.append(f'<polyline class="line" points="{" ".join(punkty)}"></polyline>')
        czesci += kropki

    czesci.append('<g class="legend">'
                  f'<rect class="bar rev" x="{MARGINES["lewy"]}" y="4" width="12" '
                  'height="12" rx="2"></rect>'
                  + _txt(MARGINES["lewy"] + 18, 14, "przychody kwartalne", "leg", "start")
                  + (f'<line class="line" x1="{MARGINES["lewy"] + 166}" y1="10" '
                     f'x2="{MARGINES["lewy"] + 186}" y2="10"></line>'
                     + _txt(MARGINES["lewy"] + 192, 14, "marża netto", "leg", "start")
                     if ma_marze else "")
                  + "</g>")

    pierwszy, ostatni = dane[0]["revenue"], dane[-1]["revenue"]
    kierunek = "rosną" if ostatni > pierwszy else "spadają"
    opis = (f"Wykres słupkowy przychodów kwartalnych {nazwa} z ostatnich "
            f"{len(dane)} kwartałów; przychody {kierunek}"
            + (", nałożona linia pokazuje marżę netto." if ma_marze else "."))
    return _figura(
        _svg(wys, "".join(czesci), f"Przychody i marża {nazwa}", opis),
        f"Przychody kwartalne {nazwa}"
        + (f" w {waluta}" if waluta else "")
        + (" i marża netto tego samego kwartału." if ma_marze else "."))


# --------------------------------------------------------------- skuteczność


def tarcza_skutecznosci(procent: float, kwartaly: int, nazwa: str) -> str:
    """Pierścień: w ilu procentach kwartałów spółka pobiła prognozę.

    Mały wykres kołowy jest zwykle marnym pomysłem, ale jedna wartość z zakresu
    0–100% to dokładnie ten przypadek, w którym pierścień czyta się szybciej
    niż liczbę — i dobrze wygląda obok nagłówka.
    """
    if not isinstance(procent, (int, float)) or not kwartaly:
        return ""
    p = max(0.0, min(100.0, float(procent)))
    r, obwod = 54.0, 2 * 3.141592653589793 * 54.0
    wypelnienie = obwod * p / 100.0

    svg = (
        '<svg class="ring" viewBox="0 0 140 140" width="140" height="140" role="img" '
        'xmlns="http://www.w3.org/2000/svg">'
        f"<title>Skuteczność {esc(nazwa)} wobec prognoz</title>"
        f"<desc>{esc(f'Spółka pobiła prognozy analityków w {liczba(p, 0)}% z ostatnich {kwartaly} kwartałów.')}</desc>"
        f'<circle class="tor" cx="70" cy="70" r="{r}"></circle>'
        f'<circle class="luk" cx="70" cy="70" r="{r}" '
        f'stroke-dasharray="{wypelnienie:.1f} {obwod - wypelnienie:.1f}" '
        'transform="rotate(-90 70 70)"></circle>'
        f'<text class="ring-v" x="70" y="70" text-anchor="middle">{esc(liczba(p, 0))}%</text>'
        f'<text class="ring-k" x="70" y="92" text-anchor="middle">powyżej prognoz</text>'
        "</svg>"
    )
    return _figura(svg, f"Udział kwartałów, w których wynik {nazwa} przebił "
                        f"konsensus analityków — z {kwartaly} ostatnich raportów.",
                   klasa="ring-fig")


# --------------------------------------------------------------- styl


#: Dokładany do arkusza w `render.py`. Trzymany tutaj, żeby wygląd wykresu
#: mieszkał w jednym pliku z jego geometrią — inaczej zmiana koloru słupka
#: wymagałaby skakania między dwoma modułami.
CSS = """
.fig{margin:20px 0 0;background:var(--card);border:1px solid var(--border);
  border-radius:var(--r);padding:16px 14px 12px;overflow-x:auto}
.fig figcaption{color:var(--dim);font-size:12.5px;line-height:1.55;padding:10px 4px 0}
/* `min-width` zamiast czystego skalowania: wykres wpisany w szerokość telefonu
   zmniejsza razem z sobą wszystkie napisy, bo one też są w układzie współrzędnych
   SVG — przy 360 px opisy osi robią się nieczytelne. Lepiej, żeby na wąskim
   ekranie dało się wykres przesunąć palcem, dokładnie jak tabelę obok. */
svg.chart{display:block;width:100%;min-width:480px;height:auto;overflow:visible}
svg.chart .ax{stroke:var(--border-2);stroke-width:1}
svg.chart .bar{fill:var(--dim)}
svg.chart .bar.up{fill:var(--green)}
svg.chart .bar.down{fill:var(--red)}
svg.chart .bar.est{fill:#3b475f}
svg.chart .bar.act{fill:var(--green)}
svg.chart .bar.rev{fill:#2a4a72}
svg.chart .line{fill:none;stroke:var(--amber);stroke-width:2.4;
  stroke-linejoin:round;stroke-linecap:round}
svg.chart .dot{fill:var(--amber)}
svg.chart text{font-family:inherit;fill:var(--muted)}
svg.chart .val{font-size:13.5px;font-weight:700;fill:var(--text)}
svg.chart .val.up{fill:var(--green)}
svg.chart .val.down{fill:var(--red)}
svg.chart .val.mg{fill:var(--amber);font-size:11.5px}
svg.chart .ax-lab{font-size:13px;fill:var(--dim)}
svg.chart .leg{font-size:13px;fill:var(--muted)}
.fig.ring-fig{display:flex;gap:18px;align-items:center;flex-wrap:wrap}
svg.ring{flex:0 0 auto}
svg.ring .tor{fill:none;stroke:var(--border);stroke-width:13}
svg.ring .luk{fill:none;stroke:var(--green);stroke-width:13;stroke-linecap:round}
svg.ring .ring-v{font-size:30px;font-weight:800;fill:var(--text);
  dominant-baseline:middle}
svg.ring .ring-k{font-size:11px;fill:var(--dim)}
"""
