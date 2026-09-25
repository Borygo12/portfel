"""Zegar insiderów — jeden wątek tła, który wypełnia bazę i trzyma ją świeżą.

Kolejność pierwszego wypełnienia jest ułożona pod to, co człowiek zobaczy
najpierw po wdrożeniu:
1. OGE (prezydent, gabinet) — minuta, jeden plik na osobę;
2. Izba Reprezentantów — kilka minut, kilkaset PDF-ów;
3. paczki kwartalne SEC — dwa lata historii prezesów i udziałowców;
4. wyniki (% za rok) najważniejszych person, żeby lista w panelu miała liczby;
5. dzienne indeksy SEC od końca ostatniej paczki — najdłużej (około godziny),
   więc idzie małymi porcjami przeplatanymi ze świeżymi zgłoszeniami.

Potem w kółko: kanał bieżący SEC co 10 minut, Izba co 3 godziny, OGE dwa razy
na dobę, nowa paczka kwartalna i przeliczenie wyników raz na dobę.

Wyłącznik: zmienna `INSIDERS_INGEST`. Domyślnie włączone w chmurze
(`PORTEVO_CLOUD`), wyłączone na komputerze — lokalny panel nie musi mielić
tysięcy formularzy, skoro aplikacja i tak łączy się z produkcją.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from . import follow, moje_spolki, people, store

log = logging.getLogger("insiders.jobs")

CO_BIEZACE = 10 * 60
CO_GPW = 5 * 60              # w godzinach publikacji ESPI; poza nimi `_co_gpw`
CO_GPW_NOC = 30 * 60
CO_IZBA = 3 * 3600
CO_OGE = 12 * 3600
CO_DOBA = 24 * 3600

_watek: threading.Thread | None = None
_stop = threading.Event()
STAN: dict = {"etap": "nieuruchomiony", "bledy": [], "ostatnie": {}}


def wlaczone() -> bool:
    v = os.environ.get("INSIDERS_INGEST")
    if v is not None:
        return v.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(os.environ.get("PORTEVO_CLOUD"))


def _co_gpw() -> int:
    """Spółki z GPW publikują powiadomienia MAR w dni robocze, zwykle 7–22.
    Wtedy sprawdzamy co 5 minut (jedna strona Bankiera), w nocy i weekend
    rzadko — GPW to rdzeń aplikacji, zakup prezesa ma przyjść tego samego dnia."""
    import datetime as dt
    try:
        from zoneinfo import ZoneInfo
        teraz = dt.datetime.now(ZoneInfo("Europe/Warsaw"))
    except Exception:  # noqa: BLE001 — brak bazy stref czasowych: licz jak w dzień
        return CO_GPW
    return CO_GPW if teraz.weekday() < 5 and 7 <= teraz.hour < 22 else CO_GPW_NOC


def _blad(gdzie: str, e: Exception) -> None:
    log.warning("Insiderzy / %s: %s", gdzie, e)
    STAN["bledy"] = (STAN["bledy"] + [{"gdzie": gdzie, "blad": str(e)[:300],
                                       "at": time.time()}])[-12:]


def _nazwy(pids: set[str]) -> dict[str, str]:
    wiersze = store.people_rows(list(pids))
    out = {}
    for pid in pids:
        k = people.curated(pid)
        out[pid] = (k or {}).get("name") or (wiersze.get(pid) or {}).get("name") or pid
    return out


def _po_przyroscie(uidy: list[str]) -> None:
    """Nowe transakcje → powiadomienia obserwującym. Nie przy pierwszym wypełnieniu."""
    if not uidy or not store.kv_get("init_done"):
        return
    try:
        wiersze = store.trades_by_uids(uidy)
        nazwy = _nazwy({t["person"] for t in wiersze})
    except Exception as e:  # noqa: BLE001
        _blad("powiadomienia", e)
        return
    # najpierw obserwowane osoby, potem spółki z portfela — wspólny klucz
    # `insider:{uid}` sprawia, że kto ma jedno i drugie, dostaje jedno powiadomienie
    for nazwa, funkcja in (("powiadomienia", follow.powiadom),
                           ("powiadomienia_spolki", moje_spolki.powiadom)):
        try:
            funkcja(wiersze, nazwy)
        except Exception as e:  # noqa: BLE001
            _blad(nazwa, e)


def _zrob(nazwa: str, funkcja):
    STAN["etap"] = nazwa
    t0 = time.time()
    try:
        wynik = funkcja()
    except Exception as e:  # noqa: BLE001 — jedno źródło nie może zatrzymać reszty
        from . import sec
        if isinstance(e, sec.Zablokowane):
            _blad(nazwa, e)
            STAN["ostatnie"][nazwa] = {"at": time.time(), "blokada": True}
            _stop.wait(15 * 60)
            return None
        _blad(nazwa, e)
        return None
    STAN["ostatnie"][nazwa] = {"at": time.time(), "s": round(time.time() - t0, 1),
                               "wynik": {k: v for k, v in (wynik or {}).items()
                                         if k != "nowe_uid"} if isinstance(wynik, dict) else None}
    if isinstance(wynik, dict):
        _po_przyroscie(wynik.get("nowe_uid") or [])
    return wynik


def ranking_do_przeliczenia(limit: int = 90) -> list[str]:
    """Kogo warto mieć policzonego zawczasu: katalog + najaktywniejsi."""
    import datetime as dt
    od = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    akt = store.activity(od)
    pids = [p["id"] for p in people.KATALOG]
    polityka = sorted((a for a in akt if a["person"].startswith(("house-", "oge-", "senat-"))),
                      key=lambda a: -(a["buys"] + a["sells"]))[:40]
    pids += [a["person"] for a in polityka]
    od90 = (dt.date.today() - dt.timedelta(days=90)).isoformat()
    kupujacy = sorted((a for a in store.activity(od90, ("sec",)) if a["person"].startswith("sec-")),
                      key=lambda a: -(a["bought"] or 0))[:30]
    pids += [a["person"] for a in kupujacy]
    polscy = sorted((a for a in store.activity(od90, ("gpw",)) if a["person"].startswith("gpw-")),
                    key=lambda a: -(a["bought"] or 0))[:20]
    pids += [a["person"] for a in polscy]
    return list(dict.fromkeys(pids))[:limit]


def przelicz_wyniki(wymus: bool = False) -> dict:
    from . import perf
    n = 0
    znane = store.person_counts([p for p in ranking_do_przeliczenia()])
    for pid in znane:
        if _stop.is_set():
            break
        try:
            perf.statystyki(pid, max_wiek=0 if wymus else 20 * 3600)
            n += 1
        except Exception as e:  # noqa: BLE001
            log.debug("Wynik %s: %s", pid, e)
    return {"przeliczone": n}


def _petla() -> None:
    from . import f13, gpw, house, kongres, oge, sec, senat

    log.info("Insiderzy: zegar wystartował (baza: %s)", store.path())
    if not store.kv_get("init_done"):
        STAN["etap"] = "pierwsze wypełnienie"
        _zrob("oge", oge.wczytaj)
        _zrob("izba", lambda: house.wczytaj(stop=_stop))
        _zrob("senat", lambda: senat.wczytaj(stop=_stop))
        _zrob("kongres", lambda: kongres.uzupelnij(stop=_stop))
        _zrob("sec_kwartaly", sec.historia)
        _zrob("f13", lambda: f13.wczytaj(stop=_stop))
        _zrob("wyniki", przelicz_wyniki)
        # GPW na końcu: ~740 spółek po jednej stronie, około 20 minut. Przerwane
        # przez wdrożenie — ruszy od miejsca, w którym stanęło (`seen`).
        _zrob("gpw_historia", lambda: gpw.historia(stop=_stop))
        if not _stop.is_set():
            store.kv_set("init_done", time.time())
            log.info("Insiderzy: pierwsze wypełnienie gotowe — %s", store.counts())

    ost = {"biezace": 0.0, "gpw": 0.0, "izba": time.time(), "oge": time.time(),
           "doba": time.time()}
    while not _stop.is_set():
        teraz = time.time()
        if teraz - ost["biezace"] >= CO_BIEZACE:
            ost["biezace"] = teraz
            _zrob("sec_biezace", sec.biezace)
        if teraz - ost["gpw"] >= _co_gpw():
            ost["gpw"] = teraz
            _zrob("gpw_biezace", gpw.biezace)
        if teraz - ost["izba"] >= CO_IZBA:
            ost["izba"] = teraz
            _zrob("izba", lambda: house.wczytaj(stop=_stop))
            _zrob("senat", lambda: senat.wczytaj(stop=_stop))
        if teraz - ost["oge"] >= CO_OGE:
            ost["oge"] = teraz
            _zrob("oge", oge.wczytaj)
        if teraz - ost["doba"] >= CO_DOBA:
            ost["doba"] = teraz
            _zrob("sec_kwartaly", sec.historia)
            _zrob("gpw_historia", lambda: gpw.historia(stop=_stop))   # nowe spółki na GPW
            _zrob("f13", lambda: f13.wczytaj(stop=_stop))             # nowe kwartały 13F
            _zrob("kongres", lambda: kongres.uzupelnij(stop=_stop))
            _zrob("wyniki", przelicz_wyniki)

        # Zaległe dni SEC po jednym na obrót pętli — między nimi zdąży przejść
        # kanał bieżący, więc świeże zgłoszenia nie czekają na koniec nadrabiania.
        dni = sec.dni_do_uzupelnienia()
        STAN["zalegle_dni_sec"] = len(dni)
        if dni:
            if _zrob("sec_dzien", lambda: sec.wczytaj_dzien(dni[0], stop=_stop)) is None:
                _stop.wait(120)           # błąd sieci — bez tego pętla kręciłaby się w miejscu
            continue
        STAN["etap"] = "czeka"
        _stop.wait(60)
    log.info("Insiderzy: zegar zatrzymany")


AI_CO = 3600                # co godzinę sprawdzamy, komu minęła doba — pisze się najwyżej raz na 24 h


def _ranking_ids() -> list[str]:
    """Osoby, które aplikacja pokazuje w rankingu — ze wspólnego panelu.
    Bez panelu (pierwszy start) bierzemy katalog, żeby najważniejsi mieli tekst."""
    try:
        import insiders_api                       # leniwie: moduł API importuje nasz pakiet
        liderzy = (insiders_api._wspolny_panel() or {}).get("leaders") or []
        ids = [p["id"] for p in liderzy
               if (p.get("activity") or {}).get("buys", 0) + (p.get("activity") or {}).get("sells", 0) > 0]
        if ids:
            return ids
    except Exception as e:  # noqa: BLE001
        log.debug("Ranking do podsumowań: %s", e)
    return [k["id"] for k in people.KATALOG]


def podsumowania_zawczasu() -> dict:
    """Podsumowania AI piszemy w tle WYŁĄCZNIE dla osób z rankingu i najwyżej raz
    na dobę na osobę. Wejście w profil niczego nie pisze (patrz `insiders_api`),
    a osoby spoza rankingu dostają tekst tylko po kliknięciu przycisku.

    Dodatkowo: gdy od ostatniego tekstu nie przyszła ŻADNA nowa transakcja, nie
    pytamy modelu wcale — stary tekst dalej jest prawdziwy. Politycy zgłaszają
    transakcje raz na kilka tygodni, więc to ścina większość zapytań."""
    from . import ai, perf
    n = pominiete = bez_zmian = 0
    for pid in _ranking_ids():
        if _stop.is_set():
            break
        stare = ai.zapisane(pid)
        if stare and time.time() - float(stare.get("at") or 0) < ai.WAZNE_S:
            pominiete += 1
            continue
        trans = store.trades_for_person(pid, limit=60)
        if not trans:
            continue
        if stare and stare.get("sig") == ai.podpis(trans):
            bez_zmian += 1
            continue
        w = store.people_rows([pid]).get(pid) or {}
        k = people.BY_ID.get(pid) or {}
        rola = " · ".join(x for x in (w.get("role"), people.skroc_spolke(w.get("org") or "")) if x)
        try:
            if ai.podsumowanie(pid, k.get("name") or w.get("name") or pid, rola, trans,
                               perf.statystyki(pid), ponownie=True):
                n += 1
        except Exception as e:  # noqa: BLE001
            log.debug("Podsumowanie %s: %s", pid, e)
    return {"napisane": n, "aktualne": pominiete, "bez_nowych_transakcji": bez_zmian}


def _petla_ai() -> None:
    # osobny wątek: kilkadziesiąt minut rozmyślań modeli nie może wstrzymać
    # kanału bieżącego SEC w głównej pętli
    _stop.wait(5 * 60)                      # po starcie najpierw dane, potem teksty
    while not _stop.is_set():
        try:
            STAN["ostatnie"]["ai_zawczasu"] = {"at": time.time(), "wynik": podsumowania_zawczasu()}
        except Exception as e:  # noqa: BLE001
            _blad("ai_zawczasu", e)
        _stop.wait(AI_CO)


WYROZNIONE_CO = 30 * 60


def wyroznione_i_narracje() -> dict:
    """Pasek „Najciekawsze zagrania": przeliczenie listy i notki AI dla nowych pozycji.
    Notka pisze się RAZ na pozycję (pozycja się nie zmienia), więc przy ~16
    pozycjach i kilku nowych dziennie to kilka zapytań na dobę."""
    from . import ai, wyroznione
    stat = wyroznione.zbuduj(stop=_stop)
    napisane = 0
    for p in wyroznione.lista().get("items") or []:
        if _stop.is_set():
            break
        if ai.zapisana_narracja(p["id"]):
            continue
        w = store.people_rows([p["person"]]).get(p["person"]) or {}
        k = people.BY_ID.get(p["person"]) or {}
        rola = " · ".join(x for x in (w.get("role"), people.skroc_spolke(w.get("org") or ""))
                          if x and x != "Kongres USA")
        try:
            if ai.narracja_wyroznienia(p, k.get("name") or w.get("name") or p["person"], rola):
                napisane += 1
        except Exception as e:  # noqa: BLE001 — zostaje narracja z szablonu
            log.debug("Narracja %s: %s", p["id"], e)
    return {**stat, "narracje": napisane}


def _petla_wyroznione() -> None:
    _stop.wait(3 * 60)
    while not _stop.is_set():
        if store.kv_get("init_done"):
            try:
                STAN["ostatnie"]["wyroznione"] = {"at": time.time(), "wynik": wyroznione_i_narracje()}
            except Exception as e:  # noqa: BLE001
                _blad("wyroznione", e)
        _stop.wait(WYROZNIONE_CO)


def start() -> bool:
    global _watek
    if not wlaczone():
        STAN["etap"] = "wyłączone (INSIDERS_INGEST)"
        return False
    if _watek and _watek.is_alive():
        return False
    _stop.clear()
    _watek = threading.Thread(target=_petla, name="insiders-clock", daemon=True)
    _watek.start()
    threading.Thread(target=_petla_ai, name="insiders-ai", daemon=True).start()
    threading.Thread(target=_petla_wyroznione, name="insiders-wyroznione", daemon=True).start()
    return True


def stop() -> None:
    _stop.set()


def stan() -> dict:
    return {**STAN, "alive": bool(_watek and _watek.is_alive()), "wlaczone": wlaczone(),
            "baza": store.counts(), "init_done": store.kv_get("init_done")}
