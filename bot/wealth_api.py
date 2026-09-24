"""API portfeli i majątku — `/api/wealth/…`.

Całość za bramką logowania: to są prywatne dane majątkowe, więc gość nie ma tu
czego szukać. Świadomie NIE ma tu kłódki premium — możliwość dopisania własnego
mieszkania to nie funkcja płatna, tylko podstawa tego, żeby liczby w apce się
zgadzały. Płatne jest to, co z tymi liczbami dalej robimy.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

import wealth
from account_api import require_login

log = logging.getLogger("wealth_api")

router = APIRouter()


@router.get("/api/wealth/meta")
def meta(_v=Depends(require_login)):
    """Słowniki do formularzy: kategorie i podpowiedzi symboli."""
    return {
        "kategorie": [{"id": k, **v} for k, v in wealth.KATEGORIE.items()],
        "symbole": wealth.SYMBOLE,
    }


@router.get("/api/wealth/spot")
def spot(symbol: str, _v=Depends(require_login)):
    """Cena jednej uncji/sztuki w PLN — formularz przelicza z niej gramy i kwoty.

    Osobno od `/api/wealth/overview`, bo pytamy o to w trakcie WPISYWANIA, przy
    każdej zmianie metalu — a przeliczanie całego majątku przy okazji byłoby
    kilkuset milisekundami czekania na liczbę, która ma pojawić się od razu.
    """
    try:
        return wealth.spot(symbol)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/wealth/overview")
def overview(_v=Depends(require_login)):
    """Portfele, majątek i przypisanie rachunków — wszystko do jednego ekranu.

    Jeden endpoint zamiast trzech, bo ekran „Portfele" i tak potrzebuje
    wszystkich trzech rzeczy naraz, a trzy żądania to trzy okazje, żeby jedno
    z nich przyszło później i widok mrugnął.
    """
    import db

    portfele = wealth.portfele()
    maj = wealth.majatek()

    konta = db.query(
        "SELECT account, currency, broker, label, portfolio_id FROM accounts "
        "ORDER BY account")
    konta = [{"konto": r["account"], "waluta": r["currency"],
              "broker": r["broker"] or "", "etykieta": r["label"] or "",
              "portfel_id": str(r["portfolio_id"]) if r["portfolio_id"] else None}
             for r in konta]

    # Wartość rachunków bierzemy z silnika portfela. Gdy nie ma czego liczyć
    # (nikt nic nie wgrał), po prostu jej nie ma — majątek ręczny ma działać
    # także dla kogoś, kto nie ma żadnego rachunku maklerskiego.
    wartosci_kont: dict[str, float] = {}
    try:
        from portfolio import engine as pf_engine
        d = pf_engine.compute()
        if not d.get("empty"):
            for p in d.get("positions", []):
                if p.get("no_price"):
                    continue
                konto = p.get("account") or ""
                wartosci_kont[konto] = wartosci_kont.get(konto, 0.0) + p["value_pln"]
            # Gotówka na rachunku to też majątek — pominięta sprawiałaby, że suma
            # tutaj nie zgadza się z kwotą nad wykresem u kogoś, kto właśnie
            # sprzedał i jeszcze nie kupił.
            kursy = wealth._przeliczniki([a.get("currency") for a in d.get("accounts", [])])
            for a in d.get("accounts", []):
                got = float(a.get("cash") or 0)
                if got:
                    wartosci_kont[a["account"]] = (
                        wartosci_kont.get(a["account"], 0.0)
                        + got * kursy.get((a.get("currency") or "PLN").upper(), 1.0))
    except Exception as e:  # noqa: BLE001
        log.warning("Wartość rachunków dla portfeli: %s", e)

    for k in konta:
        k["wartosc"] = round(wartosci_kont.get(k["konto"], 0.0), 2)

    # Zestawienie per portfel: rachunki plus majątek do niego przypisany.
    # Rachunki i aktywa bez portfela trafiają do pozycji „bez przypisania",
    # żeby suma zawsze się zgadzała z majątkiem całkowitym.
    zestaw = []
    for p in portfele:
        moje_konta = [k for k in konta if k["portfel_id"] == p["id"]]
        moje_aktywa = [a for a in maj["aktywa"] if a["portfel_id"] == p["id"]]
        zestaw.append({
            **p,
            "konta": moje_konta,
            "aktywa": moje_aktywa,
            "wartosc": round(sum(k["wartosc"] for k in moje_konta)
                             + sum(a["wartosc"] for a in moje_aktywa), 2),
        })

    luzem_konta = [k for k in konta if not k["portfel_id"]]
    luzem_aktywa = [a for a in maj["aktywa"] if not a["portfel_id"]]

    return {
        "portfele": zestaw,
        "bez_przypisania": {
            "konta": luzem_konta,
            "aktywa": luzem_aktywa,
            "wartosc": round(sum(k["wartosc"] for k in luzem_konta)
                             + sum(a["wartosc"] for a in luzem_aktywa), 2),
        },
        "majatek_razem": maj["razem"],
        "rachunki_razem": round(sum(k["wartosc"] for k in konta), 2),
        "razem": round(sum(k["wartosc"] for k in konta) + maj["razem"], 2),
    }


# --------------------------------------------------------------- portfele


@router.post("/api/wealth/portfolios")
async def portfel_dodaj(request: Request, _v=Depends(require_login)):
    b = await request.json()
    try:
        return wealth.dodaj_portfel(b.get("nazwa") or "", b.get("kolor") or "",
                                    b.get("ikona") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.patch("/api/wealth/portfolios/{pid}")
async def portfel_zmien(pid: str, request: Request, _v=Depends(require_login)):
    b = await request.json()
    wealth.zmien_portfel(pid, b.get("nazwa"), b.get("kolor"), b.get("ikona"))
    return {"ok": True}


@router.delete("/api/wealth/portfolios/{pid}")
def portfel_usun(pid: str, _v=Depends(require_login)):
    wealth.usun_portfel(pid)
    return {"ok": True}


@router.post("/api/wealth/accounts/{account}/portfolio")
async def konto_przypisz(account: str, request: Request, _v=Depends(require_login)):
    b = await request.json()
    wealth.przypisz_konto(account, b.get("portfel_id"))
    return {"ok": True}


# --------------------------------------------------------------- majątek


@router.post("/api/wealth/assets")
async def aktywo_dodaj(request: Request, _v=Depends(require_login)):
    try:
        return wealth.dodaj_aktywo(await request.json())
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.patch("/api/wealth/assets/{aid}")
async def aktywo_zmien(aid: str, request: Request, _v=Depends(require_login)):
    wealth.zmien_aktywo(aid, await request.json())
    return {"ok": True}


@router.delete("/api/wealth/assets/{aid}")
def aktywo_usun(aid: str, _v=Depends(require_login)):
    wealth.usun_aktywo(aid)
    return {"ok": True}


@router.post("/api/wealth/assets/{aid}/valuations")
async def wycena_dodaj(aid: str, request: Request, _v=Depends(require_login)):
    b = await request.json()
    try:
        wartosc = float(b.get("wartosc"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Podaj wartość liczbowo")
    wealth.dodaj_wycene(aid, wartosc, b.get("data") or "", b.get("notatka") or "")
    return {"ok": True}


@router.delete("/api/wealth/assets/{aid}/valuations/{data}")
def wycena_usun(aid: str, data: str, _v=Depends(require_login)):
    wealth.usun_wycene(aid, data)
    return {"ok": True}


# --------------------------------------------------------------- raport AI


#: Ile odczytów AI dostaje konto bez premium. Jeden wystarcza, żeby zobaczyć,
#: czy to w ogóle działa na TWOIM raporcie — a o to chodzi w wersji darmowej.
DARMOWE_ODCZYTY = 1


def _zuzyte_odczyty() -> int:
    import db
    rows = db.query("SELECT COUNT(*) AS ile FROM ai_report_usage")
    return int(rows[0]["ile"]) if rows else 0


@router.get("/api/wealth/ai-report/limit")
def ai_limit(v=Depends(require_login)):
    """Ile odczytów AI zostało. Front pyta o to PRZED pokazaniem przycisku."""
    if getattr(v, "premium", False):
        return {"premium": True, "zostalo": None, "limit": None, "zuzyte": 0}
    zuzyte = _zuzyte_odczyty()
    return {"premium": False, "limit": DARMOWE_ODCZYTY, "zuzyte": zuzyte,
            "zostalo": max(0, DARMOWE_ODCZYTY - zuzyte)}


def _wczytaj_wejscie(body: dict) -> dict:
    """Z ciała żądania: {"tekst": …} albo {"obraz": bytes, "mime": …}. Rzuca 400."""
    import base64

    import report_ai

    nazwa = (body.get("nazwa") or "raport").strip()
    surowe = body.get("plik_b64") or ""
    tekst = body.get("tekst") or ""
    if surowe:
        try:
            dane = base64.b64decode(surowe)
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "Plik przyszedł uszkodzony")
        mime = report_ai.rodzaj_obrazu(dane)
        if mime:
            return {"obraz": dane, "mime": mime}
        try:
            tekst = report_ai.do_tekstu(dane, nazwa)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, str(e))
    if not tekst.strip():
        raise HTTPException(400, "Pusty plik — nie ma czego odczytywać")
    return {"tekst": tekst}


def _odczytaj(wejscie: dict) -> dict:
    import report_ai
    if "obraz" in wejscie:
        return report_ai.czytaj_obraz(wejscie["obraz"], wejscie["mime"])
    return report_ai.czytaj(wejscie["tekst"])


def _zapisz_zuzycie(wynik: dict) -> None:
    import db
    try:
        db.execute(
            "INSERT INTO ai_report_usage (model, positions) VALUES (%s, %s)",
            (wynik.get("model") or "", len(wynik.get("pozycje") or [])))
    except Exception as e:  # noqa: BLE001
        log.warning("Zapis zużycia odczytu AI: %s", e)


def _porownaj(wynik: dict) -> list[dict]:
    """Odczytane pozycje zliczone netto i porównane z tym, co konto już ma.

    `stan`: „nowa" (nie masz tego waloru), „masz" (ta sama liczba sztuk),
    „inna_ilosc" (masz, ale inną liczbę), „sprzedana" (w raporcie netto zero).
    Porównujemy z pozycjami z raportów brokera ORAZ z majątkiem dodanym ręcznie —
    inaczej drugi odczyt tego samego pliku zdublowałby wszystko jako nowe."""
    import report_ai

    posiadane: dict[str, float] = {}
    try:
        from portfolio import engine as pf_engine
        d = pf_engine.compute()
        for p in (d.get("positions") or []) if not d.get("empty") else []:
            k = report_ai._rdzen(p.get("ticker") or "")
            posiadane[k] = posiadane.get(k, 0.0) + float(p.get("shares") or 0)
    except Exception as e:  # noqa: BLE001
        log.info("Porównanie z portfelem: %s", e)
    try:
        for a in wealth.aktywa():
            if a.get("symbol"):
                k = report_ai._rdzen(a["symbol"])
                posiadane[k] = posiadane.get(k, 0.0) + float(a.get("ilosc") or 0)
    except Exception as e:  # noqa: BLE001
        log.info("Porównanie z majątkiem: %s", e)

    out = []
    for g in report_ai.zbierz(wynik.get("pozycje") or []):
        mam = posiadane.get(g["klucz"])
        if g["ilosc"] <= 1e-9:
            stan = "sprzedana"
        elif mam is None:
            stan = "nowa"
        elif abs(mam - g["ilosc"]) <= max(1e-6, g["ilosc"] * 0.001):
            stan = "masz"
        else:
            stan = "inna_ilosc"
        out.append({**g, "stan": stan, "mam": mam})
    return out


# Zadania odczytu w tle. Odczyt trwa do dwóch minut, a telefon w tym czasie
# potrafi wygasić ekran — iOS zrywa wtedy połączenie i długie żądanie kończyło
# się „network error", choć serwer dalej czytał. Teraz żądanie od razu zwraca
# numer zadania, model pracuje w wątku, a aplikacja co kilka sekund pyta
# o wynik; zerwane pytanie po prostu się ponawia. Jeden proces serwera, więc
# słownik w pamięci wystarcza; po restarcie aplikacja dostaje „nie ma zadania".
_ZADANIA: dict[str, dict] = {}
_ZADANIA_ZYJA_S = 3600


def _sprzataj_zadania() -> None:
    import time
    granica = time.time() - _ZADANIA_ZYJA_S
    for k in [k for k, z in _ZADANIA.items() if z["t"] < granica]:
        _ZADANIA.pop(k, None)


@router.post("/api/wealth/ai-report")
async def ai_report(request: Request, v=Depends(require_login)):
    """Odczytuje raport (plik albo zdjęcie) z nieznanego brokera modelem językowym.

    `w_tle: true` (nowa aplikacja) — zwraca od razu {zadanie}, wynik pod
    `/api/wealth/ai-report/zadanie/{id}`. Bez tego pola — stara, synchroniczna
    droga dla aplikacji, które jeszcze nie dostały aktualizacji.

    **Limit zużywa się dopiero po udanym odczycie.** Nieudana próba nie może go
    zjadać: człowiek nie dostał nic w zamian.

    Zwracamy pozycje DO ZATWIERDZENIA, a nie wrzucamy ich do portfela.
    """
    import threading
    import time
    import uuid

    premium = bool(getattr(v, "premium", False))
    if not premium and _zuzyte_odczyty() >= DARMOWE_ODCZYTY:
        raise HTTPException(402, {
            "error": "premium_required", "feature": "tools.ai_report",
            "message": "Darmowy odczyt AI został już wykorzystany"})

    body = await request.json()
    wejscie = _wczytaj_wejscie(body)

    if body.get("w_tle"):
        _sprzataj_zadania()
        jid = uuid.uuid4().hex
        zad = {"uid": getattr(v, "user_id", "") or "", "stan": "liczy", "t": time.time(),
               "wynik": None, "blad": "", "zapisane": False, "premium": premium}
        _ZADANIA[jid] = zad

        def praca():
            try:
                zad["wynik"] = _odczytaj(wejscie)
                zad["stan"] = "gotowe"
            except Exception as e:  # noqa: BLE001
                zad["blad"] = str(e)[:400]
                zad["stan"] = "blad"

        threading.Thread(target=praca, daemon=True, name="ai-report").start()
        return {"zadanie": jid}

    try:
        wynik = _odczytaj(wejscie)
    except Exception as e:  # noqa: BLE001
        # 503, nie 500: to brak odpowiedzi od modelu, a nie błąd naszego kodu.
        raise HTTPException(503, str(e))
    _zapisz_zuzycie(wynik)
    wynik["premium"] = premium
    wynik["zostalo"] = None if premium else max(0, DARMOWE_ODCZYTY - _zuzyte_odczyty())
    wynik["zbiorczo"] = _porownaj(wynik)
    return wynik


@router.get("/api/wealth/ai-report/zadanie/{jid}")
def ai_report_zadanie(jid: str, v=Depends(require_login)):
    """Stan zadania odczytu. Zużycie limitu i porównanie z portfelem liczymy TU,
    a nie w wątku: tylko w żądaniu wiadomo, czyje to konto (baza z RLS)."""
    zad = _ZADANIA.get(jid)
    if not zad or zad["uid"] != (getattr(v, "user_id", "") or ""):
        raise HTTPException(404, "Nie ma takiego odczytu — mógł wygasnąć po restarcie serwera. "
                                 "Wgraj plik jeszcze raz.")
    if zad["stan"] == "liczy":
        import time
        return {"stan": "liczy", "sekund": int(time.time() - zad["t"])}
    if zad["stan"] == "blad":
        return {"stan": "blad", "blad": zad["blad"]}
    wynik = dict(zad["wynik"])
    if not zad["zapisane"]:
        zad["zapisane"] = True
        _zapisz_zuzycie(wynik)
    wynik["premium"] = zad["premium"]
    wynik["zostalo"] = None if zad["premium"] else max(0, DARMOWE_ODCZYTY - _zuzyte_odczyty())
    # porównanie z portfelem przelicza cały portfel — raz na zadanie wystarczy,
    # a kolejne pytania (np. po zerwanym połączeniu) dostają gotową listę
    if zad.get("zbiorczo") is None:
        zad["zbiorczo"] = _porownaj(wynik)
    wynik["zbiorczo"] = zad["zbiorczo"]
    return {"stan": "gotowe", "wynik": wynik}


@router.post("/api/wealth/ai-report/symbol")
async def ai_report_symbol(request: Request, _v=Depends(require_login)):
    """Symbole notowań dla odczytanych pozycji — osobno, bo to kilka zapytań
    do Yahoo na pozycję, a lista potrafi mieć sto walorów."""
    import concurrent.futures as cf

    import report_ai

    pozycje = ((await request.json()) or {}).get("pozycje") or []
    pozycje = pozycje[:150]
    with cf.ThreadPoolExecutor(8) as ex:
        symbole = list(ex.map(report_ai.symbol_rynkowy, pozycje))
    return {"symbole": symbole}


@router.post("/api/wealth/ai-report/dodaj")
async def ai_report_dodaj(request: Request, _v=Depends(require_login)):
    """Dodaje zatwierdzone pozycje do majątku — jedną albo sto naraz.

    Każda pozycja z symbolem staje się aktywem wycenianym z rynku (ilość × kurs,
    jak złoto czy krypto), z kosztem zakupu = ilość × średnia cena z raportu.
    Pozycja bez symbolu nie ma skąd wziąć kursu, więc trafia jako wycena ręczna
    po cenie zakupu — lepsze to niż zero."""
    body = (await request.json()) or {}
    dodane, bledy = [], []
    for p in (body.get("pozycje") or [])[:200]:
        try:
            ilosc = float(p.get("ilosc") or 0)
            if ilosc <= 0:
                raise ValueError("liczba sztuk musi być większa od zera")
            typ = p.get("typ") or "inne"
            kategoria = typ if typ in ("akcje", "etf", "krypto", "obligacje") else "inne"
            symbol = (p.get("symbol") or "").strip().upper()
            cena = float(p.get("cena") or 0)
            waluta = (p.get("waluta") or "PLN").upper()
            dane = {
                "nazwa": (p.get("walor") or symbol or "Pozycja z raportu")[:80],
                "kategoria": kategoria, "portfel_id": body.get("portfel_id") or None,
                "wycena": "auto" if symbol else "manual", "symbol": symbol,
                "ilosc": ilosc, "waluta": waluta,
                "koszt": round(ilosc * cena, 2) if cena else 0,
                "koszt_data": (p.get("data") or "")[:10],
                "notatka": "z odczytu raportu przez AI",
            }
            if not symbol and cena:
                dane["wartosc"] = round(ilosc * cena, 2)
            dodane.append(wealth.dodaj_aktywo(dane)["id"])
        except Exception as e:  # noqa: BLE001
            bledy.append({"walor": p.get("walor"), "blad": str(e)[:160]})
    return {"dodane": len(dodane), "bledy": bledy}
