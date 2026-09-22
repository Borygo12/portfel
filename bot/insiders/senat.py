"""Senat USA — raporty transakcji senatorów (Periodic Transaction Report) z efdsearch.senate.gov.

Dwie pułapki, bez których nic tu nie działa:
1. **Odcisk TLS.** Serwis stoi za Akamai, które odrzuca (403) każdego klienta
   HTTP niebędącego przeglądarką — także zwykłe `requests` i `curl`. `curl_cffi`
   z `impersonate="chrome"` przedstawia się odciskiem Chrome'a i przechodzi.
2. **Oświadczenie.** Przed wyszukiwaniem trzeba zaznaczyć, że rozumie się zakaz
   używania raportów do celów niezgodnych z prawem i komercyjnych innych niż
   informowanie opinii publicznej (5 U.S.C. §13107). Właściciel świadomie
   zgodził się (22.09.2026), żeby skrypt akceptował to przy każdym pobraniu —
   ten sam przepis obejmuje dane Izby i OGE, z których i tak korzystamy.

Raport elektroniczny to tabela HTML: data, właściciel, ticker, walor, typ waloru,
rodzaj transakcji, przedział kwoty. Raporty papierowe (`/search/view/paper/`) to
skany — pomijamy je, jak w Izbie.
"""

from __future__ import annotations

import datetime as dt
import html
import logging
import re
import time

from . import people, store

log = logging.getLogger("insiders.senat")

BASE = "https://efdsearch.senate.gov"
PRZERWA = 1.0
WLASCICIEL = {"spouse": "małżonek", "joint": "wspólnie", "child": "dziecko", "dependent child": "dziecko"}


def _sesja():
    from curl_cffi import requests as cr
    s = cr.Session(impersonate="chrome")
    r = s.get(f"{BASE}/search/home/", timeout=40)
    r.raise_for_status()
    m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.text)
    if not m:
        raise RuntimeError("eFD: brak tokenu formularza")
    s.post(f"{BASE}/search/home/", data={"prohibition_agreement": "1",
                                          "csrfmiddlewaretoken": m.group(1)},
           headers={"Referer": f"{BASE}/search/home/"}, timeout=40)
    return s


def spis(s, od: str) -> list[dict]:
    """Raporty PTR złożone od danego dnia („MM/DD/RRRR")."""
    out, start = [], 0
    csrf = s.cookies.get("csrftoken") or ""
    while True:
        r = s.post(f"{BASE}/search/report/data/", data={
            "start": str(start), "length": "100", "report_types": "[11]", "filer_types": "[]",
            "submitted_start_date": f"{od} 00:00:00", "submitted_end_date": "",
            "candidate_state": "", "senator_state": "", "office_id": "",
            "first_name": "", "last_name": "", "csrfmiddlewaretoken": csrf,
        }, headers={"Referer": f"{BASE}/search/", "X-CSRFToken": csrf}, timeout=40)
        r.raise_for_status()
        dane = r.json()
        wiersze = dane.get("data") or []
        for w in wiersze:
            m = re.search(r'href="(/search/view/(ptr|paper)/([0-9a-f\-]+)/)"', w[3] or "")
            if not m:
                continue
            out.append({"first": w[0], "last": w[1], "office": w[2], "url": BASE + m.group(1),
                        "rodzaj": m.group(2), "id": m.group(3), "filed": _data_us(w[4])})
        start += len(wiersze)
        if not wiersze or start >= int(dane.get("recordsTotal") or 0):
            break
        time.sleep(PRZERWA)
    return out


def _data_us(s: str) -> str:
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", (s or "").strip())
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else ""


def _czysc(s: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _opcje(nazwa: str) -> str:
    n = nazwa.lower()
    czesci = ["opcje call" if "call" in n else "opcje put" if "put" in n else "opcje"]
    m = re.search(r"strike price:\s*\$?([\d,.]+)", nazwa, re.I)
    if m:
        czesci.append(f"cena wykonania {m.group(1).rstrip('0').rstrip('.')} $")
    m = re.search(r"expires:\s*(\d{4})-(\d{2})-(\d{2})", nazwa, re.I)
    if m:
        czesci.append(f"wygasają {m.group(3)}.{m.group(2)}.{m.group(1)}")
    return " · ".join(czesci)


def czytaj(tekst_html: str) -> list[dict]:
    from .house import _kwota
    i = tekst_html.find("<table")
    out = []
    for row in re.findall(r"<tr.*?</tr>", tekst_html[i:] if i >= 0 else "", re.S):
        k = [_czysc(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(k) < 8:
            continue
        _, data, wl, ticker, walor, typ_w, rodzaj, kwota = k[:8]
        r = rodzaj.lower()
        side = "buy" if r.startswith("purchase") else "sell" if r.startswith("sale") else ""
        if not side:
            continue
        opcja = "option" in typ_w.lower()
        if not opcja and typ_w.lower() not in ("stock", "etf", "exchange traded fund", ""):
            continue                            # obligacje, fundusze, nieruchomości
        t = ticker if ticker and ticker != "--" else ""
        if not t:
            m = re.search(r"\(([A-Z][A-Z0-9.\-]{0,6})\)", walor)
            t = m.group(1) if m else ""
        t = t.upper().replace(".", "-")
        if not re.fullmatch(r"[A-Z][A-Z0-9\-]{0,9}", t):
            continue
        liczby = re.findall(r"\$[\d,]+", kwota)
        lo = _kwota(liczby[0]) if liczby else None
        hi = _kwota(liczby[1]) if len(liczby) > 1 else (None if "over" in kwota.lower() else lo)
        out.append({
            "ticker": t, "side": side, "date": _data_us(data), "amt_lo": lo, "amt_hi": hi,
            "owner": WLASCICIEL.get(wl.lower(), ""), "options": opcja,
            "asset": re.sub(r"\s*Option Type:.*$", "", walor)[:120],
            "note": _opcje(walor) if opcja else ("częściowa sprzedaż" if "partial" in r else ""),
        })
    return out


def wczytaj(stop=None) -> dict:
    from . import kongres
    dzis = dt.date.today()
    od = f"01/01/{dzis.year - 1}"
    s = _sesja()
    wpisy = spis(s, od)
    znane = store.seen_filter([f"senat:{w['id']}" for w in wpisy])
    czlonkowie = [c for c in kongres.spis() if c["type"] == "sen"]
    stat = {"raportow": len(wpisy), "nowe_raporty": 0, "papierowe": 0, "transakcje": 0, "nowe_uid": []}
    for w in sorted(wpisy, key=lambda x: x["filed"], reverse=True):
        if f"senat:{w['id']}" in znane:
            continue
        if stop is not None and stop.is_set():
            break
        stat["nowe_raporty"] += 1
        if w["rodzaj"] == "paper":
            stat["papierowe"] += 1
            store.seen_add([f"senat:{w['id']}"])
            continue
        time.sleep(PRZERWA)
        try:
            r = s.get(w["url"], timeout=40)
            if r.status_code != 200:
                continue
            pozycje = czytaj(r.text)
        except Exception as e:  # noqa: BLE001
            log.info("Senat %s: %s", w["id"], e)
            continue
        stat["transakcje"] += len(pozycje)
        stat["nowe_uid"] += _zapisz(w, pozycje, czlonkowie)
        store.seen_add([f"senat:{w['id']}"])
    log.info("Senat: %s", {k: v for k, v in stat.items() if k != "nowe_uid"})
    return stat


def _senator(czl: list[dict], first: str, last: str) -> dict | None:
    from .kongres import _norm
    ln = _norm(re.sub(r",?\s*(jr|sr|iii|ii)\.?$", "", last, flags=re.I))
    f = _norm(first)[:3]
    kand = [c for c in czl if _norm(c["last"]) == ln or _norm(c["last"]).startswith(ln) or ln.startswith(_norm(c["last"]))]
    if len(kand) > 1:
        kand = [c for c in kand if _norm(c["first"]).startswith(f) or _norm(c["nick"]).startswith(f)] or kand
    return max(kand, key=lambda c: c["end"]) if kand else None


def _zapisz(w: dict, pozycje: list[dict], czlonkowie: list[dict]) -> list[str]:
    c = _senator(czlonkowie, w["first"], w["last"])
    stan = (c or {}).get("state", "")
    pid = people.for_senat(w["last"], w["first"], stan)
    kat = people.curated(pid)
    nazwa = (kat or {}).get("name") or (c or {}).get("full") or f"{w['first']} {w['last']}"
    store.upsert_people([{
        "id": pid, "name": nazwa, "cat": "politycy",
        "role": f"Senat USA · {stan}" if stan else "Senat USA", "org": "Kongres USA",
        "source": "senat",
        "extra": {"short": people.nazwisko(nazwa), "state": stan,
                  "party": (kat or {}).get("party") or (c or {}).get("party", ""),
                  "bioguide": (c or {}).get("bioguide", "")},
    }])
    rows = []
    for n, p in enumerate(pozycje):
        if not p["date"]:
            continue
        rows.append({
            "uid": f"senat:{w['id']}:{n}", "person": pid, "source": "senat", "ticker": p["ticker"],
            "asset": p["asset"], "side": p["side"], "date": p["date"], "filed": w["filed"],
            "amt_lo": p["amt_lo"], "amt_hi": p["amt_hi"], "options": 1 if p["options"] else 0,
            "owner": p["owner"], "note": p["note"][:160], "url": w["url"],
        })
    return store.add_trades(rows)
