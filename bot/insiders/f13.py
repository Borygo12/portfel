"""Znani inwestorzy — kwartalne portfele funduszy z formularzy 13F (SEC).

Fundusz zarządzający ponad 100 mln $ w akcjach USA musi co kwartał pokazać
wszystkie pozycje (13F-HR, do 45 dni po końcu kwartału). To jedyne oficjalne
okno w portfele Buffetta, Burry'ego czy Ackmana poza ich zakupami powyżej 10%.

13F to STAN, nie transakcje. Transakcje wyliczamy sami — różnica między
kolejnymi kwartałami:
* nowa pozycja albo więcej akcji → zakup,
* mniej akcji albo zamknięta pozycja → sprzedaż.
Dokładnego dnia nie znamy — tylko kwartał. Transakcja dostaje ostatni dzień
kwartału, a aplikacja podpisuje ją „zmiana w kwartale", zamiast udawać precyzję.
Kwota = zmiana liczby akcji × cena z końca kwartału (wartość / akcje).

Progi: fundusze typu Bridgewater mają tysiąc pozycji i co kwartał przesuwają je
wszystkie o drobne kwoty. Bierzemy zmiany od 1 mln $ i co najmniej 0,05% portfela —
reszta to szum, który zasypałby wykres.

Tickery: 13F podaje CUSIP. Tłumaczy go OpenFIGI (darmowe API Bloomberga,
bez klucza do 25 zapytań na minutę) — raz na CUSIP, wynik trzymamy na stałe.
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET

import requests

from . import people, store

log = logging.getLogger("insiders.f13")

UA = {"User-Agent": "Portevo borygoo45@gmail.com"}
KWARTALOW = 7                       # 7 portfeli → 6 różnic, półtora roku
MIN_ZMIANA = 1_000_000              # $
MIN_UDZIAL = 0.0005                 # 0,05% portfela
FIGI = "https://api.openfigi.com/v3/mapping"


def _get(url: str) -> requests.Response:
    time.sleep(0.2)                 # zasady SEC: poniżej 10 zapytań na sekundę
    return requests.get(url, headers=UA, timeout=40)


def _zgloszenia(cik: int) -> list[dict]:
    """Ostatnie 13F-HR funduszu — jedno na kwartał (przy dwóch bierzemy nowsze)."""
    d = _get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()
    r = d["filings"]["recent"]
    wg: dict[str, dict] = {}
    for i, f in enumerate(r["form"]):
        if f != "13F-HR":
            continue
        okres = r["reportDate"][i]
        z = {"acc": r["accessionNumber"][i], "okres": okres, "filed": r["filingDate"][i]}
        if okres not in wg or z["filed"] > wg[okres]["filed"]:
            wg[okres] = z
    return sorted(wg.values(), key=lambda z: z["okres"])[-KWARTALOW:], d.get("name", "")


def _portfel(cik: int, z: dict) -> dict[str, dict]:
    """{cusip: {sh, val, name}} — suma wszystkich wierszy tego samego papieru."""
    klucz = f"13f:portfel:{cik}:{z['okres']}"
    hit = store.kv_get(klucz)
    if hit is not None:
        return _jednostka(hit)
    acc = z["acc"].replace("-", "")
    j = _get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json").json()
    pliki = [x["name"] for x in j["directory"]["item"]]
    tabela = next((n for n in pliki if n.lower().endswith(".xml") and "primary" not in n.lower()), None)
    if not tabela:
        store.kv_set(klucz, {})
        return {}
    t = _get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{tabela}").content
    root = ET.fromstring(t)
    ns = {"n": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {}
    q = (lambda s: f"n:{s}") if ns else (lambda s: s)
    mnoznik = 1000 if z["okres"] < "2023-01-01" else 1   # przed 2023 wartości w tys. $
    out: dict[str, dict] = {}
    for it in root.findall(q("infoTable"), ns):
        if it.findtext(q("putCall"), "", ns):
            continue                                        # opcje to nie pozycja w akcjach
        typ = it.findtext(f"{q('shrsOrPrnAmt')}/{q('sshPrnamtType')}", "", ns)
        if typ and typ != "SH":
            continue
        cusip = (it.findtext(q("cusip"), "", ns) or "").upper()
        try:
            sh = float(it.findtext(f"{q('shrsOrPrnAmt')}/{q('sshPrnamt')}", "0", ns) or 0)
            val = float(it.findtext(q("value"), "0", ns) or 0) * mnoznik
        except ValueError:
            continue
        if not cusip or sh <= 0:
            continue
        p = out.setdefault(cusip, {"sh": 0.0, "val": 0.0, "name": it.findtext(q("nameOfIssuer"), "", ns)})
        p["sh"] += sh
        p["val"] += val
    store.kv_set(klucz, out)
    return _jednostka(out)


def _jednostka(portfel: dict) -> dict:
    """Część funduszy (Duquesne, Baupost) dalej podaje wartości w TYSIĄCACH dolarów,
    choć od 2023 roku przepis każe w dolarach. Poznać to po cenie: mediana
    „wartość / akcje" poniżej 2 $ przy portfelu dużych spółek to nie groszowe
    akcje, tylko zła jednostka."""
    ceny = sorted(p["val"] / p["sh"] for p in portfel.values() if p.get("sh"))
    if ceny and ceny[len(ceny) // 2] < 2:
        return {c: {**p, "val": p["val"] * 1000} for c, p in portfel.items()}
    return portfel


def _tickery(cusipy: list[str]) -> dict[str, str]:
    """CUSIP → ticker przez OpenFIGI, z trwałym zapisem (także „nie wiadomo")."""
    out, brak = {}, []
    for c in cusipy:
        hit = store.kv_get(f"figi:{c}")
        if hit is None:
            brak.append(c)
        else:
            out[c] = hit
    for i in range(0, len(brak), 10):
        part = brak[i:i + 10]
        try:
            r = requests.post(FIGI, json=[{"idType": "ID_CUSIP", "idValue": c} for c in part],
                              timeout=30)
            if r.status_code == 429:
                time.sleep(30)
                continue
            wyniki = r.json()
        except Exception as e:  # noqa: BLE001
            log.info("OpenFIGI: %s", e)
            break
        for c, w in zip(part, wyniki):
            dane = (w or {}).get("data") or []
            us = [x for x in dane if x.get("exchCode") == "US"] or dane
            tk = (us[0].get("ticker") if us else "") or ""
            tk = tk.upper().replace("/", "-").replace(".", "-").replace(" ", "-")
            if not re.fullmatch(r"[A-Z0-9\-]{1,10}", tk):
                tk = ""
            store.kv_set(f"figi:{c}", tk)
            out[c] = tk
        time.sleep(2.6)             # bez klucza: 25 zapytań na minutę
    return out


def wczytaj_fundusz(cik: int, pid: str) -> dict:
    zgl, nazwa_funduszu = _zgloszenia(cik)
    if len(zgl) < 2:
        return {"cik": cik, "kwartalow": len(zgl)}
    portfele = [(_portfel(cik, z), z) for z in zgl]
    wszystkie = sorted({c for p, _ in portfele for c in p})
    tick = _tickery(wszystkie)
    fundusz = people.skroc_spolke(nazwa_funduszu)
    trans = []
    for (poprz, _), (teraz, z) in zip(portfele, portfele[1:]):
        razem = sum(p["val"] for p in teraz.values()) or 1.0
        for c in set(poprz) | set(teraz):
            a, b = poprz.get(c), teraz.get(c)
            sh_a = a["sh"] if a else 0.0
            sh_b = b["sh"] if b else 0.0
            if abs(sh_b - sh_a) < 1:
                continue
            cena = (b["val"] / b["sh"]) if b and b["sh"] else (a["val"] / a["sh"] if a and a["sh"] else 0)
            kwota = abs(sh_b - sh_a) * cena
            if kwota < max(MIN_ZMIANA, MIN_UDZIAL * razem):
                continue
            t = tick.get(c) or ""
            if not t:
                continue
            side = "buy" if sh_b > sh_a else "sell"
            opis = ("nowa pozycja" if not a else "zamknięta pozycja" if not b
                    else ("dokupione" if side == "buy" else "zmniejszone")
                    + f" o {abs(sh_b - sh_a) / sh_a * 100:.0f}%")
            trans.append({
                "uid": f"13f:{cik}:{z['okres']}:{c}", "person": pid, "source": "f13",
                "ticker": t, "asset": ((b or a) or {}).get("name", "")[:120], "side": side,
                "date": z["okres"], "filed": z["filed"],
                "shares": round(abs(sh_b - sh_a), 2), "price": round(cena, 4) if cena else None,
                "amt_lo": round(kwota, 2), "amt_hi": round(kwota, 2),
                "owner": f"fundusz {fundusz}"[:80],
                "note": f"13F · zmiana w kwartale · {opis}",
                "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{z['acc'].replace('-', '')}/",
            })
    k = people.curated(pid) or {}
    # Buffett czy Ackman mają już wiersz z Form 4 (funkcja, spółka) — tego nie
    # nadpisujemy opisem funduszu; wiersz zakładamy tylko osobom spoza SEC.
    if not store.people_rows([pid]):
        store.upsert_people([{
            "id": pid, "name": k.get("name", fundusz), "cat": k.get("cat", "znani"),
            "role": f"Portfel funduszu {fundusz}", "org": fundusz, "source": "f13",
            "extra": {"short": people.nazwisko(k.get("name", fundusz)), "cik13f": cik},
        }])
    nowe = store.add_trades(trans)
    return {"cik": cik, "kwartalow": len(zgl), "transakcje": len(trans), "nowe": len(nowe),
            "nowe_uid": nowe}


def wczytaj(stop=None) -> dict:
    stat = {"fundusze": 0, "transakcje": 0, "nowe_uid": []}
    for p in people.KATALOG:
        for cik in p.get("f13", []):
            if stop is not None and stop.is_set():
                return stat
            try:
                w = wczytaj_fundusz(cik, p["id"])
            except Exception as e:  # noqa: BLE001 — jeden fundusz nie zatrzymuje reszty
                log.warning("13F %s: %s", cik, e)
                continue
            stat["fundusze"] += 1
            stat["transakcje"] += w.get("transakcje", 0)
            stat["nowe_uid"] += w.get("nowe_uid", [])
    log.info("13F: %s", {k: v for k, v in stat.items() if k != "nowe_uid"})
    return stat
