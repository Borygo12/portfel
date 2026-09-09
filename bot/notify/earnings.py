"""Powiadomienia z kalendarza wyników: „dziś raportuje spółka, którą masz".

Dwa zadania, obydwa odpalane przez `jobs.py`:

* **codziennie rano** — spółki z Twojego portfela i listy obserwowanych, które
  publikują wyniki DZISIAJ, razem z porą publikacji;
* **w poniedziałek** — przegląd całego tygodnia, żeby dało się zaplanować.

Skąd bierze się pora: kalendarz Nasdaqa nie podaje godziny zegarowej, tylko
`bmo` (przed otwarciem) albo `amc` (po zamknięciu). Zamiast udawać dokładność,
której nie ma, tłumaczymy to na czas polski widełkami — „przed 15:30" i „po
22:00" to informacja prawdziwa i wystarczająca, żeby wiedzieć, kiedy zaglądnąć.
"""

from __future__ import annotations

import datetime as dt
import logging

from . import engine, store

log = logging.getLogger("notify.earnings")

# Pora publikacji w czasie polskim. Sesja w USA trwa 15:30–22:00 (zimą),
# więc „przed otwarciem" i „po zamknięciu" mają sens jako widełki.
PORY = {
    "bmo": "przed otwarciem rynku (do 15:30)",
    "amc": "po zamknięciu rynku (po 22:00)",
    "tbd": "godzina jeszcze niepodana",
}
PORY_KROTKO = {"bmo": "przed sesją", "amc": "po sesji", "tbd": "godz. nieznana"}


def _dni_robocze(od: dt.date, ile: int) -> list[str]:
    dni, dzien = [], od
    while len(dni) < ile:
        if dzien.weekday() < 5:
            dni.append(dzien.isoformat())
        dzien += dt.timedelta(days=1)
    return dni


def _kalendarz(od: str, do: str) -> dict:
    """{data: [wiersze]} z modułu kalendarza. Zadanie w tle może poczekać dłużej."""
    from earnings import calendar as earn_cal
    raw, _pending = earn_cal.range_days(od, do, budget_sec=45.0)
    return raw


def _moje_wiersze(uid: str, raw: dict) -> dict:
    """{data: [wiersze spółek tego konta]} — z portfela i obserwowanych."""
    relacje = {(s["symbol"] or "").upper(): s["relation"]
               for s in store.symbole_uzytkownika(uid)}
    if not relacje:
        return {}
    out = {}
    for data, wiersze in raw.items():
        moje = [dict(w, relacja=relacje[w["symbol"]])
                for w in wiersze if w.get("symbol", "").upper() in relacje]
        if moje:
            out[data] = sorted(moje, key=lambda w: w["symbol"])
    return out


def _opis(w: dict) -> str:
    return f"{w['symbol']} ({PORY_KROTKO.get(w.get('time'), 'godz. nieznana')})"


# --------------------------------------------------------------- zadanie dzienne


def dzisiejsze(dzien: str = "") -> int:
    """Powiadomienia o spółkach raportujących dziś. Zwraca liczbę wysłanych."""
    data = dzien or dt.date.today().isoformat()
    if dt.date.fromisoformat(data).weekday() >= 5:
        return 0                                   # w weekend nikt nie raportuje

    konta = store.konta_z_powiadomieniami("earnings_daily")
    konta = sorted(store.tylko_premium(konta))
    if not konta:
        return 0

    raw = _kalendarz(data, data)
    if not raw.get(data):
        return 0

    wyslane = 0
    for uid in konta:
        try:
            moje = _moje_wiersze(uid, raw).get(data) or []
        except Exception as e:  # noqa: BLE001
            log.warning("Nie zebrano spółek konta %s: %s", uid, e)
            continue
        if not moje:
            continue

        if len(moje) == 1:
            w = moje[0]
            tytul = f"{w['symbol']} publikuje dziś wyniki"
            tresc = (f"{w.get('name') or w['symbol']} — "
                     f"{PORY.get(w.get('time'), PORY['tbd'])}. "
                     "Wejdź do Portevo po prognozy i reakcję kursu po poprzednich wynikach.")
        else:
            tytul = f"Dziś wyniki: {len(moje)} Twoje spółki"
            tresc = ("Raportują: " + ", ".join(_opis(w) for w in moje[:6])
                     + (" i inne." if len(moje) > 6 else ".")
                     + " Szczegóły i prognozy są w aplikacji.")

        if engine.powiadom(
            uid, "earnings_today", tytul, tresc,
            dedup_key=f"earnings:{data}",
            symbol=moje[0]["symbol"],
            meta={"date": data, "symbols": [w["symbol"] for w in moje]},
        ):
            wyslane += 1

    log.info("Wyniki dnia %s — powiadomiono %s kont", data, wyslane)
    return wyslane


# ------------------------------------------------------------ zadanie tygodniowe


def tydzien(od: str = "") -> int:
    """Poniedziałkowy przegląd: co z Twojego portfela raportuje w tym tygodniu."""
    start = dt.date.fromisoformat(od) if od else dt.date.today()
    dni = _dni_robocze(start, 5)

    konta = store.konta_z_powiadomieniami("earnings_weekly")
    konta = sorted(store.tylko_premium(konta))
    if not konta:
        return 0

    raw = _kalendarz(dni[0], dni[-1])
    wyslane = 0
    for uid in konta:
        try:
            moje = _moje_wiersze(uid, raw)
        except Exception as e:  # noqa: BLE001
            log.warning("Nie zebrano spółek konta %s: %s", uid, e)
            continue
        moje = {d: w for d, w in moje.items() if d in dni}
        if not moje:
            continue

        ile = sum(len(w) for w in moje.values())
        nazwy = [f"{_dzien_krotko(d)}: {', '.join(w['symbol'] for w in wiersze)}"
                 for d, wiersze in sorted(moje.items())]

        tytul = (f"W tym tygodniu wyniki {ile} Twoich spółek"
                 if ile > 1 else "W tym tygodniu wyniki Twojej spółki")
        tresc = " · ".join(nazwy[:5]) + ". Otwórz Portevo, żeby zobaczyć prognozy."

        if engine.powiadom(
            uid, "earnings_week", tytul, tresc,
            dedup_key=f"earnings-week:{dni[0]}",
            meta={"from": dni[0], "to": dni[-1],
                  "symbols": sorted({w["symbol"] for ws in moje.values() for w in ws})},
        ):
            wyslane += 1

    log.info("Przegląd tygodnia od %s — powiadomiono %s kont", dni[0], wyslane)
    return wyslane


_DNI = ["pon", "wt", "śr", "czw", "pt", "sob", "niedz"]


def _dzien_krotko(data: str) -> str:
    return _DNI[dt.date.fromisoformat(data).weekday()]
