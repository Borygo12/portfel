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
                wartosci_kont[p.get("account", "")] = (
                    wartosci_kont.get(p.get("account", ""), 0.0) + p["value_pln"])
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


@router.post("/api/wealth/ai-report")
async def ai_report(request: Request, v=Depends(require_login)):
    """Odczytuje raport z nieznanego brokera modelem językowym.

    **Limit zużywa się dopiero po udanym odczycie.** Nieudana próba nie może go
    zjadać: człowiek nie dostał nic w zamian, a pierwszy raport ucięty przez
    timeout zamykałby drogę na zawsze i zostawiał wrażenie oszustwa.

    Zwracamy pozycje DO ZATWIERDZENIA, a nie wrzucamy ich do portfela. To jest
    odczyt maszynowy z niepewnego źródła — wpuszczenie go prosto do liczb, na
    których ktoś opiera decyzje, byłoby proszeniem się o cichy błąd.
    """
    import base64

    import db
    import report_ai

    premium = bool(getattr(v, "premium", False))
    if not premium and _zuzyte_odczyty() >= DARMOWE_ODCZYTY:
        raise HTTPException(402, {
            "error": "premium_required", "feature": "tools.ai_report",
            "message": "Darmowy odczyt AI został już wykorzystany"})

    body = await request.json()
    nazwa = (body.get("nazwa") or "raport").strip()
    surowe = body.get("plik_b64") or ""
    tekst = body.get("tekst") or ""

    if surowe:
        try:
            tekst = report_ai.do_tekstu(base64.b64decode(surowe), nazwa)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, str(e))
    if not tekst.strip():
        raise HTTPException(400, "Pusty plik — nie ma czego odczytywać")

    try:
        wynik = report_ai.czytaj(tekst)
    except Exception as e:  # noqa: BLE001
        # Świadomie 503, a nie 500: to nie jest błąd naszego kodu, tylko brak
        # odpowiedzi od modelu. Front pokazuje wtedy „spróbuj jeszcze raz",
        # a nie „coś się zepsuło".
        raise HTTPException(503, str(e))

    try:
        db.execute(
            "INSERT INTO ai_report_usage (model, positions) VALUES (%s, %s)",
            (wynik.get("model") or "", len(wynik.get("pozycje") or [])))
    except Exception as e:  # noqa: BLE001
        log.warning("Zapis zużycia odczytu AI: %s", e)

    wynik["premium"] = premium
    wynik["zostalo"] = None if premium else max(0, DARMOWE_ODCZYTY - _zuzyte_odczyty())
    return wynik
