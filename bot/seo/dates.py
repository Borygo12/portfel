"""Daty po polsku — jedno miejsce dla całej warstwy SEO.

Formatowanie daty wygląda na drobiazg, ale rozjeżdża się natychmiast, gdy każdy
moduł robi je po swojemu: na jednej podstronie „26 sierpnia 2026”, na drugiej
„26.08.2026”, w trzeciej angielskie „Aug 26”. Dla czytelnika to niechlujstwo,
a dla Google — sygnał, że strony pochodzą z różnych źródeł.

Nazwy miesięcy są w dopełniaczu („26 sierpnia”), bo tak brzmi data mówiona
po polsku. Skróty na osiach wykresów i w listach dziennych są mianownikowe,
bo skrót nie odmienia się w żadnym języku.
"""

from __future__ import annotations

import datetime as dt

MIESIACE = ("stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
            "lipca", "sierpnia", "września", "października", "listopada", "grudnia")

MIESIACE_M = ("styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
              "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień")

SKROTY = ("sty", "lut", "mar", "kwi", "maj", "cze",
          "lip", "sie", "wrz", "paź", "lis", "gru")

DNI = ("poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela")


def _data(iso) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(iso or "")[:10])
    except (ValueError, TypeError):
        return None


def dlugo(iso) -> str:
    """„2026-08-26” → „26 sierpnia 2026”. Pusty napis, gdy daty nie ma."""
    d = _data(iso)
    return f"{d.day} {MIESIACE[d.month - 1]} {d.year}" if d else ""


def krotko(iso) -> str:
    """„2026-08-26” → „26 sie”. Do list, w których rok jest oczywisty."""
    d = _data(iso)
    return f"{d.day} {SKROTY[d.month - 1]}" if d else ""


def z_dniem_tygodnia(iso) -> str:
    """„2026-08-26” → „środa, 26 sierpnia”. Nagłówek dnia w kalendarzu."""
    d = _data(iso)
    if not d:
        return ""
    return f"{DNI[d.weekday()]}, {d.day} {MIESIACE[d.month - 1]}"


def dzis() -> str:
    return dlugo(dt.date.today().isoformat())
