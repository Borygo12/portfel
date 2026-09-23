"""Obserwowane persony i powiadomienia o ich transakcjach.

To jedyna część insiderów, która należy do konkretnego człowieka, więc jako
jedyna leży w Supabase (tabela `insider_follows`, migracja 0007, RLS jak
wszędzie: widzisz tylko swoje). Transakcje są wspólne i siedzą w SQLite.

Powiadomienie idzie przez ten sam silnik co newsy (`notify.engine.powiadom`):
skrzynka w aplikacji zawsze, push i e-mail według ustawień konta. Kluczem
przeciw duplikatom jest identyfikator transakcji — ta sama transakcja
przychodząca dwiema drogami (kanał bieżący SEC i dzienny indeks) dzwoni raz.

Czego NIE powiadamiamy:
* transakcji znalezionych przy pierwszym wypełnianiu bazy — to byłyby setki
  powiadomień o rzeczach sprzed miesięcy;
* transakcji ujawnionych dawniej niż `SWIEZOSC_DNI` temu — gdy spis Izby
  dosypie zaległy raport sprzed dwóch miesięcy, to już nie jest wiadomość.
"""

from __future__ import annotations

import datetime as dt
import logging

log = logging.getLogger("insiders.follow")

SWIEZOSC_DNI = 4
MAX_W_PACZCE = 3          # powyżej tylu transakcji jednej osoby — jedno zbiorcze


# ---------------------------------------------------------------- konto


def moje(user_id: str) -> list[str]:
    import db
    try:
        rows = db.query("select person_id from insider_follows order by created_at",
                        user_id=user_id)
    except Exception as e:  # noqa: BLE001 — brak tabeli (migracja) to pusta lista
        log.info("insider_follows niedostępne: %s", e)
        return []
    return [r["person_id"] for r in rows]


def ustaw(user_id: str, pid: str, nazwa: str, wlacz: bool) -> list[str]:
    import db
    if wlacz:
        db.execute("insert into insider_follows (user_id, person_id, person_name) "
                   "values (auth.uid(), %s, %s) on conflict (user_id, person_id) do update "
                   "set person_name = excluded.person_name",
                   (pid[:80], (nazwa or "")[:120]), user_id=user_id)
    else:
        db.execute("delete from insider_follows where person_id = %s", (pid,), user_id=user_id)
    return moje(user_id)


def obserwujacy(pids: list[str]) -> dict[str, list[str]]:
    """{persona: [konta]} — rolą serwisową, bo silnik chodzi bez zalogowanego."""
    import db
    if not pids:
        return {}
    try:
        rows = db.shared_query(
            "select user_id, person_id from insider_follows where person_id = any(%s)",
            (list(set(pids)),))
    except Exception as e:  # noqa: BLE001
        log.info("Obserwujący niedostępni: %s", e)
        return {}
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["person_id"], []).append(str(r["user_id"]))
    return out


# ----------------------------------------------------------- powiadomienia


def _liczba_txt(v: float) -> str:
    for prog, slowo in ((1e9, "mld"), (1e6, "mln"), (1e3, "tys.")):
        if v >= prog:
            x = f"{v / prog:.1f}".rstrip("0").rstrip(".").replace(".", ",")
            return f"{x} {slowo}"
    return f"{v:.0f}"


def _waluta(t: dict) -> str:
    # pusta kolumna `cur` = dolary (SEC, Kongres, OGE, 13F); GPW ma „PLN"
    return {"PLN": "zł", "EUR": "€", "": "$", "USD": "$"}.get(t.get("cur") or "", t.get("cur") or "$")


def _kwota_txt(t: dict) -> str:
    lo, hi = t.get("amt_lo"), t.get("amt_hi")
    w = _waluta(t)
    if lo and hi and abs(hi - lo) > 1:
        return f"{_liczba_txt(lo)}–{_liczba_txt(hi)} {w}"
    v = lo or hi
    return f"{_liczba_txt(v)} {w}" if v else ""


def _et(ticker: str) -> str:
    return ticker[:-3] if (ticker or "").upper().endswith(".WA") else ticker


def _data_pl(iso: str) -> str:
    try:
        d = dt.date.fromisoformat(iso[:10])
        return f"{d.day:02d}.{d.month:02d}"
    except ValueError:
        return iso


def powiadom(nowe: list[dict], nazwy: dict[str, str]) -> int:
    """Rozsyła powiadomienia o nowo zobaczonych transakcjach. Zwraca liczbę wysłanych."""
    if not nowe:
        return 0
    granica = (dt.date.today() - dt.timedelta(days=SWIEZOSC_DNI)).isoformat()
    swieze = [t for t in nowe if (t.get("filed") or "") >= granica and t.get("ticker")]
    if not swieze:
        return 0
    wg_osoby: dict[str, list[dict]] = {}
    for t in swieze:
        wg_osoby.setdefault(t["person"], []).append(t)
    kto = obserwujacy(list(wg_osoby))
    if not kto:
        return 0

    from notify import engine
    from notify import store as nstore
    wszyscy = {u for us in kto.values() for u in us}
    premium = nstore.tylko_premium(list(wszyscy))
    wyslane = 0
    for pid, trans in wg_osoby.items():
        odbiorcy = [u for u in kto.get(pid, []) if u in premium]
        if not odbiorcy:
            continue
        nazwa = nazwy.get(pid) or pid
        trans.sort(key=lambda t: (t.get("amt_hi") or t.get("amt_lo") or 0), reverse=True)
        if len(trans) > MAX_W_PACZCE:
            kupna = sum(1 for t in trans if t["side"] == "buy")
            tickery = ", ".join(dict.fromkeys(_et(t["ticker"]) for t in trans))
            paczki = [{
                "title": f"{nazwa}: {len(trans)} nowych transakcji",
                "body": (f"{kupna} kupna, {len(trans) - kupna} sprzedaży · {tickery[:120]}"),
                "symbol": trans[0]["ticker"],
                "dedup": "insider:batch:" + "|".join(sorted(t["uid"] for t in trans))[:180],
            }]
        else:
            paczki = []
            for t in trans:
                co = "kupno" if t["side"] == "buy" else "sprzedaż"
                szczegoly = [x for x in (_kwota_txt(t), "opcje" if t.get("options") else "",
                                         f"transakcja z {_data_pl(t['date'])}") if x]
                paczki.append({
                    "title": f"{nazwa}: {co} {_et(t['ticker'])}",
                    "body": " · ".join(szczegoly),
                    "symbol": t["ticker"],
                    "dedup": f"insider:{t['uid']}"[:200],
                })
        for u in odbiorcy:
            for p in paczki:
                if engine.powiadom(u, "insider", p["title"], p["body"], p["dedup"],
                                   symbol=p["symbol"], meta={"person": pid}):
                    wyslane += 1
    if wyslane:
        log.info("Powiadomienia o insiderach: %d", wyslane)
    return wyslane
