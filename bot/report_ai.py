"""Odczyt raportu maklerskiego przez model językowy — dla brokerów, których nie znamy.

Parser w `portfolio/importer.py` czyta raporty XTB i robi to dobrze, bo zna ich
układ co do kolumny. Dla każdego innego brokera trzeba by napisać osobny parser,
a do tego potrzeba przykładowego pliku — których nikt nie publikuje. Ten moduł
jest odpowiedzią na tę blokadę: **model dostaje surową treść pliku i ma z niej
wypisać pozycje w jednym, znanym nam formacie.**

Trzy zasady, które rządzą tym kodem:

1. **Najpierw tanio, potem drogo.** Raport z trzema pozycjami czyta darmowy
   model w kilka sekund. Dopiero gdy plik jest długi albo darmowy model
   zawiedzie, sięgamy po płatny. Odwrotna kolejność działałaby tak samo,
   tylko rachunek rósłby przy każdym wgraniu.
2. **Model nie liczy — model czyta.** Prosimy wyłącznie o przepisanie tego, co
   w pliku jest: walor, liczba sztuk, cena, data, waluta. Wyceny, przewalutowania
   i stopy zwrotu liczy ten sam kod, co dla XTB. Model, który sam liczy wartość
   portfela, prędzej czy później pomyli się w mnożeniu i nikt tego nie zauważy.
3. **Nic nie wchodzi do portfela bez potwierdzenia.** Zwracamy odczytane pozycje
   do zatwierdzenia przez człowieka. To jest odczyt maszynowy z niepewnego
   źródła — wpuszczenie go prosto do portfela byłoby proszeniem się o cichy błąd
   w liczbach, na których ktoś opiera decyzje.
"""

from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("report_ai")

#: Powyżej tylu znaków uznajemy raport za duży i od razu bierzemy mocniejszy
#: model. Próg z pomiaru: raport na kilkanaście pozycji to około 6–8 tys. znaków,
#: a darmowe modele zaczynają gubić wiersze mniej więcej od dziesięciu tysięcy.
PROG_DUZY = 9000

#: Ile pozycji uznajemy za „prosty raport". Liczymy z grubsza po liniach.
PROG_PROSTY_LINII = 40

#: Limit znaków wysyłanych do modelu. Raporty bywają na tysiąc wierszy, a okno
#: kontekstowe darmowych modeli jest skromne — obcinamy i mówimy o tym wprost,
#: zamiast wysyłać wszystko i dostać ucięty wynik bez ostrzeżenia.
LIMIT_ZNAKOW = 60000

SYSTEM = """Jesteś parserem raportów maklerskich. Dostajesz surową treść pliku
z dowolnego biura maklerskiego (CSV, arkusz, wyciąg) w dowolnym języku.

Twoje jedyne zadanie: wypisać pozycje i operacje, które w tym pliku widzisz.
NIE licz wartości portfela, NIE przeliczaj walut, NIE zgaduj cen, których nie ma.
Jeśli czegoś nie ma w pliku, zostaw null.

Odpowiedz WYŁĄCZNIE obiektem JSON o dokładnie takiej budowie:
{
  "broker": "nazwa biura maklerskiego, jeśli da się rozpoznać, inaczej null",
  "waluta_konta": "kod waluty rachunku, np. PLN, jeśli widoczna, inaczej null",
  "pozycje": [
    {
      "walor": "nazwa lub ticker instrumentu, dokładnie jak w pliku",
      "ticker": "sam ticker, jeśli da się wydzielić, inaczej null",
      "typ": "akcje | etf | obligacje | krypto | inne",
      "ilosc": liczba sztuk jako liczba,
      "cena": cena jednostkowa jako liczba albo null,
      "waluta": "kod waluty ceny albo null",
      "data": "RRRR-MM-DD daty zakupu albo null",
      "kierunek": "kupno | sprzedaz"
    }
  ],
  "gotowka": [{"waluta": "PLN", "kwota": liczba}],
  "uwagi": "jednym zdaniem po polsku: czego nie udało się odczytać i dlaczego",
  "pewnosc": liczba od 0 do 1 mówiąca, na ile ufasz temu odczytowi
}

Zasady:
- Liczby podawaj jako liczby, nie napisy. Przecinek dziesiętny zamień na kropkę.
- Spacje w liczbach (1 234,56) usuń.
- Daty przepisz do formatu RRRR-MM-DD niezależnie od tego, jak są w pliku.
- Jeśli plik zawiera zarówno kupna, jak i sprzedaże, wypisz jedno i drugie.
- Jeśli plik w ogóle nie wygląda na raport maklerski, zwróć pustą listę pozycji
  i napisz to w polu "uwagi"."""


def _wyczysc(tekst: str) -> tuple:
    """(treść do wysłania, czy obcięta). Usuwa puste linie i przycina długość."""
    linie = [l.rstrip() for l in (tekst or "").splitlines()]
    linie = [l for l in linie if l.strip()]
    zlaczone = "\n".join(linie)
    if len(zlaczone) <= LIMIT_ZNAKOW:
        return zlaczone, False
    return zlaczone[:LIMIT_ZNAKOW], True


def ocen_trudnosc(tekst: str) -> dict:
    """Czy to prosty raport, czy taki, przy którym darmowy model polegnie.

    Ocena jest z grubsza i taka ma być: chodzi o wybór modelu, a nie o naukową
    klasyfikację. Dwa sygnały wystarczą — długość pliku i liczba wierszy.
    """
    tekst = tekst or ""
    linie = [l for l in tekst.splitlines() if l.strip()]
    duzy = len(tekst) > PROG_DUZY or len(linie) > PROG_PROSTY_LINII
    return {
        "znakow": len(tekst),
        "linii": len(linie),
        "trudny": duzy,
        "opis": "duży raport — od razu mocniejszy model" if duzy
                else "prosty raport — wystarczy darmowy model",
    }


def _sciezka_modeli(trudny: bool) -> list[str]:
    """Kolejność prób. Pierwszy, który odpowie sensownie, wygrywa.

    Przy prostym raporcie zaczynamy od darmowego i schodzimy w dół tej listy
    dopiero po niepowodzeniu. Przy trudnym pomijamy darmowe od razu — nie po to,
    żeby wydać więcej, tylko dlatego, że i tak by nie dały rady, a każda nieudana
    próba to kilkanaście sekund, przez które człowiek patrzy na kręcące się kółko.
    """
    import analyzer

    darmowe = analyzer.free_models()
    platny = analyzer.paid_fast_model()
    mocny = analyzer.verify_model()
    if trudny:
        return [platny, mocny]
    return (darmowe[:2] or []) + [platny, mocny]


def _liczba(v):
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    czysty = re.sub(r"[^\d,.\-]", "", v).replace(",", ".")
    # Po zamianie przecinka mogą zostać dwie kropki („1.234.56") — zostawiamy ostatnią.
    if czysty.count(".") > 1:
        glowa, _, ogon = czysty.rpartition(".")
        czysty = glowa.replace(".", "") + "." + ogon
    try:
        return float(czysty)
    except ValueError:
        return None


def _uporzadkuj(surowe: dict) -> dict:
    """Sprowadza odpowiedź modelu do kształtu, na którym można polegać.

    Model bywa twórczy mimo instrukcji: wstawi liczbę jako napis, pominie pole,
    doda swoje. Ten krok jest tańszy niż obrona przed tym w dziesięciu miejscach
    dalej — i sprawia, że reszta kodu może zakładać poprawne typy.
    """
    poz = []
    for p in (surowe.get("pozycje") or []):
        if not isinstance(p, dict):
            continue
        walor = (p.get("walor") or p.get("ticker") or "").strip()
        ilosc = _liczba(p.get("ilosc"))
        if not walor or not ilosc:
            continue
        poz.append({
            "walor": walor[:80],
            "ticker": ((p.get("ticker") or "").strip() or None),
            "typ": p.get("typ") if p.get("typ") in
                   ("akcje", "etf", "obligacje", "krypto", "inne") else "inne",
            "ilosc": ilosc,
            "cena": _liczba(p.get("cena")),
            "waluta": ((p.get("waluta") or "").strip().upper() or None),
            "data": (p.get("data") or "")[:10] or None,
            "kierunek": "sprzedaz" if p.get("kierunek") == "sprzedaz" else "kupno",
        })

    gotowka = []
    for g in (surowe.get("gotowka") or []):
        if not isinstance(g, dict):
            continue
        kwota = _liczba(g.get("kwota"))
        if kwota is None:
            continue
        gotowka.append({"waluta": (g.get("waluta") or "PLN").upper()[:5], "kwota": kwota})

    pewnosc = _liczba(surowe.get("pewnosc"))
    return {
        "broker": (surowe.get("broker") or "").strip()[:60] or None,
        "waluta_konta": ((surowe.get("waluta_konta") or "").strip().upper() or None),
        "pozycje": poz,
        "gotowka": gotowka,
        "uwagi": (surowe.get("uwagi") or "").strip()[:400],
        "pewnosc": max(0.0, min(1.0, pewnosc)) if pewnosc is not None else None,
        "model": surowe.get("_model") or "",
    }


def czytaj(tekst: str) -> dict:
    """Odczytuje raport modelem językowym. Rzuca RuntimeError, gdy nic nie wyszło.

    Zwraca też `proby` — listę tego, co poszło nie tak po drodze. To nie jest
    ozdobnik: gdy odczyt wyjdzie słabo, chcemy wiedzieć, czy darmowy model padł
    na formacie, czy po prostu nie odpowiedział w czasie.
    """
    import analyzer

    tresc, obcieta = _wyczysc(tekst)
    if len(tresc) < 40:
        raise RuntimeError("Plik jest pusty albo nie zawiera tekstu do odczytania")

    trudnosc = ocen_trudnosc(tresc)
    proby = []

    for model in _sciezka_modeli(trudnosc["trudny"]):
        try:
            # Dłuższy budżet czasu niż przy analizie newsów: tam liczy się
            # sekunda, tu człowiek patrzy na kółko i woli poczekać, niż dostać
            # komunikat o błędzie przy raporcie, który dało się odczytać.
            surowe = analyzer._call(
                model, SYSTEM, tresc,
                max_tokens=4000,
                req_timeout=75 if trudnosc["trudny"] else 45,
            )
            wynik = _uporzadkuj(surowe if isinstance(surowe, dict) else {})
            if not wynik["pozycje"] and not wynik["gotowka"]:
                proby.append({"model": model, "blad": "model nie znalazł żadnych pozycji"})
                continue
            wynik["proby"] = proby
            wynik["trudnosc"] = trudnosc
            wynik["obciete"] = obcieta
            return wynik
        except Exception as e:  # noqa: BLE001
            log.warning("Odczyt raportu przez %s: %s", model, e)
            proby.append({"model": model, "blad": str(e)[:200]})

    raise RuntimeError(
        "Żaden z modeli nie odczytał tego pliku. "
        + (proby[-1]["blad"] if proby else "Brak szczegółów."))


def do_tekstu(dane: bytes, nazwa: str) -> str:
    """Wyciąga tekst z pliku dowolnego formatu, żeby dało się go pokazać modelowi.

    CSV i TXT idą wprost. Arkusze rozkładamy tym samym czytnikiem, co parser XTB —
    nie ma powodu wozić drugiej biblioteki tylko po to, żeby zamienić xlsx na tekst.
    """
    niska = (nazwa or "").lower()
    if niska.endswith((".csv", ".txt", ".tsv")):
        for kod in ("utf-8-sig", "utf-8", "cp1250", "latin-1"):
            try:
                return dane.decode(kod)
            except UnicodeDecodeError:
                continue
        return dane.decode("utf-8", errors="replace")

    try:
        import io

        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(dane), data_only=True)
        czesci = []
        for ws in wb.worksheets:
            czesci.append(f"### Arkusz: {ws.title}")
            for wiersz in ws.iter_rows(values_only=True):
                komorki = ["" if k is None else str(k) for k in wiersz]
                if any(k.strip() for k in komorki):
                    czesci.append(" | ".join(komorki))
        return "\n".join(czesci)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Nie udało się otworzyć pliku: {e}")
