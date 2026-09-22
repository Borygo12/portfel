"""Kongresmeni: partia, oficjalne nazwisko i portret z otwartej bazy `congress-legislators`.

Spis zgłoszeń Izby podaje tylko nazwisko, imię i okręg („Pelosi, Nancy, CA11").
Partii w nim nie ma, a imię bywa pełne („Kelly Louise"), choć polityk używa
skróconego. Repozytorium `unitedstates/congress-legislators` (domena publiczna,
utrzymywane od lat przez GovTrack i dziennikarzy) ma dla każdego członka numer
Bioguide, partię, okręg i oficjalne brzmienie nazwiska — a pod tym numerem leży
jego oficjalny portret (`unitedstates/images`).

Łączymy po nazwisku i stanie, a przy kilku kandydatach — po okręgu. Bierzemy
obecnych członków i tych, którzy odeszli w ostatnich latach: Marjorie Taylor
Greene zrezygnowała w styczniu 2026, a jej zgłoszenia z 2025 zostają w bazie.
"""

from __future__ import annotations

import logging
import re
import unicodedata

import requests

from . import people, store

log = logging.getLogger("insiders.kongres")

ZRODLA = [
    "https://unitedstates.github.io/congress-legislators/legislators-current.json",
    "https://unitedstates.github.io/congress-legislators/legislators-historical.json",
]
OD_ROKU = "2023-01-01"
PARTIE = {"Democrat": "D", "Republican": "R", "Independent": "I"}


def _norm(s: str) -> str:
    t = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", t.lower())


def spis() -> list[dict]:
    """Członkowie z kadencjami od 2023 roku — obie izby."""
    out = []
    for url in ZRODLA:
        try:
            r = requests.get(url, timeout=90)
            r.raise_for_status()
            dane = r.json()
        except Exception as e:  # noqa: BLE001
            log.warning("congress-legislators %s: %s", url.rsplit("/", 1)[-1], e)
            continue
        for l in dane:
            kadencje = [t for t in l.get("terms") or [] if (t.get("end") or "") >= OD_ROKU]
            if not kadencje:
                continue
            ost = kadencje[-1]
            imie = l.get("name") or {}
            out.append({
                "bioguide": (l.get("id") or {}).get("bioguide", ""),
                "last": imie.get("last", ""), "first": imie.get("first", ""),
                "nick": imie.get("nickname", ""),
                "full": imie.get("official_full") or f"{imie.get('first', '')} {imie.get('last', '')}",
                "type": ost.get("type"), "state": ost.get("state", ""),
                "district": ost.get("district"), "party": PARTIE.get(ost.get("party", ""), ""),
                "end": ost.get("end", ""),
            })
    return out


def dopasuj(czlonkowie: list[dict], last: str, first: str, stan_okreg: str,
            izba: str = "rep") -> dict | None:
    """Członek dla wpisu ze spisu zgłoszeń („Greene", „Marjorie Taylor", „GA14")."""
    stan = (stan_okreg or "")[:2].upper()
    okreg = re.sub(r"\D", "", stan_okreg or "")
    ln = _norm(last)
    kand = [c for c in czlonkowie if c["type"] == izba and c["state"] == stan
            and (_norm(c["last"]) == ln or ln.endswith(_norm(c["last"])) or _norm(c["last"]).endswith(ln))]
    if len(kand) > 1 and okreg:
        kand = [c for c in kand if str(c.get("district")) == str(int(okreg))] or kand
    if len(kand) > 1 and first:
        f = _norm(first.split()[0])
        kand = [c for c in kand if _norm(c["first"]).startswith(f[:3]) or _norm(c["nick"]).startswith(f[:3])] or kand
    return max(kand, key=lambda c: c["end"]) if kand else None


def uzupelnij(stop=None) -> dict:
    """Dopisuje partię, oficjalne nazwisko i portret wszystkim kongresmenom z bazy."""
    from . import photos

    czl = spis()
    if not czl:
        return {"czlonkowie": 0}
    wiersze = [dict(r) for r in store.conn().execute(
        "select * from people where source='house'")]
    zmiany, portrety, bez = [], [], 0
    import json as _json
    for w in wiersze:
        ex = _json.loads(w.get("extra") or "{}")
        m = re.match(r"house-(.+)-([a-z]{2}\d*)$", w["id"])
        stan = (ex.get("state") or (m.group(2) if m else "")).replace("-", "")
        c = dopasuj(czl, ex.get("last") or w["name"].split()[-1], ex.get("first") or w["name"].split()[0], stan)
        if not c:
            bez += 1
            continue
        k = people.curated(w["id"])
        nazwa = (k or {}).get("name") or c["full"]
        ex.update(bioguide=c["bioguide"], party=c["party"], short=people.nazwisko(nazwa))
        zmiany.append({**w, "name": nazwa, "extra": ex})
        portrety.append((w["id"], c["bioguide"]))
    store.upsert_people(zmiany)
    # senatorowie mają numer Bioguide zapisany już przy pobraniu raportu (senat.py)
    for w in store.conn().execute("select id, extra from people where source='senat'"):
        b = _json.loads(w[1] or "{}").get("bioguide")
        if b:
            portrety.append((w[0], b))
    stat = {"czlonkowie": len(czl), "dopasowani": len(zmiany), "bez_dopasowania": bez}
    stat["portrety"] = photos.pobierz_portrety(portrety, stop=stop)
    log.info("Kongres: %s", stat)
    return stat
