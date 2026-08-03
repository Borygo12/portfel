"""Prowizje brokerskie — koszty faktycznie zapłacone i koszt wyjścia z portfela.

ZASADA NADRZĘDNA: nic nie liczymy dwa razy.

  - Kwoty operacji w raporcie to realny ruch gotówki. Jeśli broker potrącił prowizję
    przy transakcji, ona JUŻ siedzi w saldzie i w wycenie portfela. Takich kosztów
    nie dodajemy — tylko je MIERZYMY, żeby pokazać, ile poszło na opłaty.
  - Spread przewalutowania też jest już w saldzie: broker przelicza po swoim kursie,
    więc na koncie wylądowała mniejsza kwota. Mierzymy go, porównując kurs zapisany
    w komentarzu operacji z kursem NBP z tego dnia — różnica to marża brokera.
  - Jedynym kosztem, którego w danych NIE MA, jest koszt PRZYSZŁY: sprzedaż pozycji
    i zamiana walut na złotówki. Ten liczymy z profilu prowizji i pokazujemy osobno,
    jako „wartość po kosztach". Nie zmienia to wyceny — zmienia odpowiedź na pytanie
    „ile realnie zostałoby mi w kieszeni".

Profile są edytowalne z aplikacji: `verified: False` znaczy „wartość domyślna,
sprawdź w tabeli opłat brokera" — nie zmyślamy cudzych cenników jako pewnika.
"""

import json
import logging
import re

log = logging.getLogger("portfolio.fees")

# operacje, które SĄ kosztem brokera (już zapłaconym)
FEE_TYPES = {"SEC fee", "Commission", "Swap", "Rollover", "Custody fee",
             "Transaction fee", "Stamp duty", "Exchange fee"}
# operacje podatkowe — osobna kategoria, to nie jest opłata brokera
TAX_TYPES = {"Withholding tax", "Free funds interest tax", "Tax", "Capital gains tax"}

_RATE_RE = re.compile(r"Exchange rate:\s*([\d.]+)")
_CONV_RE = re.compile(r"Currency conversion,\s*([A-Z]{3}) to ([A-Z]{3}) from TA:\s*(\d+)\s*to:\s*(\d+)")

FIELDS = ("stock_pct", "stock_min", "min_currency", "free_turnover_eur",
          "fx_pct", "custody_pct", "spread_pct")

BROKERS = {
    "XTB": {
        "label": "XTB",
        "stock_pct": 0.2, "stock_min": 10.0, "min_currency": "EUR",
        "free_turnover_eur": 100000, "fx_pct": 0.5, "custody_pct": 0.0, "spread_pct": 0.0,
        "verified": True,
        "note": "Akcje bez prowizji do 100 000 EUR obrotu miesięcznie, powyżej 0,2% (min 10 EUR). "
                "Przewalutowanie 0,5%.",
    },
    "BOSSA": {
        "label": "DM BOŚ (bossa)",
        "stock_pct": 0.38, "stock_min": 5.0, "min_currency": "PLN",
        "free_turnover_eur": 0, "fx_pct": 0.2, "custody_pct": 0.0, "spread_pct": 0.0,
        "verified": False,
    },
    "MBANK": {
        "label": "mBank / Biuro maklerskie",
        "stock_pct": 0.39, "stock_min": 5.0, "min_currency": "PLN",
        "free_turnover_eur": 0, "fx_pct": 0.2, "custody_pct": 0.0, "spread_pct": 0.0,
        "verified": False,
    },
    "ING": {
        "label": "ING / BM",
        "stock_pct": 0.38, "stock_min": 5.0, "min_currency": "PLN",
        "free_turnover_eur": 0, "fx_pct": 0.2, "custody_pct": 0.0, "spread_pct": 0.0,
        "verified": False,
    },
    "PKO": {
        "label": "PKO BP / BM",
        "stock_pct": 0.39, "stock_min": 5.0, "min_currency": "PLN",
        "free_turnover_eur": 0, "fx_pct": 0.2, "custody_pct": 0.0, "spread_pct": 0.0,
        "verified": False,
    },
    "REVOLUT": {
        "label": "Revolut",
        "stock_pct": 0.25, "stock_min": 0.0, "min_currency": "PLN",
        "free_turnover_eur": 0, "fx_pct": 0.5, "custody_pct": 0.0, "spread_pct": 0.0,
        "verified": False,
    },
    "TRADING212": {
        "label": "Trading 212",
        "stock_pct": 0.0, "stock_min": 0.0, "min_currency": "PLN",
        "free_turnover_eur": 0, "fx_pct": 0.15, "custody_pct": 0.0, "spread_pct": 0.0,
        "verified": False,
    },
    "IBKR": {
        "label": "Interactive Brokers",
        "stock_pct": 0.05, "stock_min": 1.0, "min_currency": "USD",
        "free_turnover_eur": 0, "fx_pct": 0.02, "custody_pct": 0.0, "spread_pct": 0.0,
        "verified": False,
    },
    "SAXO": {
        "label": "Saxo Bank",
        "stock_pct": 0.08, "stock_min": 1.0, "min_currency": "USD",
        "free_turnover_eur": 0, "fx_pct": 0.25, "custody_pct": 0.12, "spread_pct": 0.0,
        "verified": False,
    },
    "DEGIRO": {
        "label": "DEGIRO",
        "stock_pct": 0.0, "stock_min": 2.0, "min_currency": "EUR",
        "free_turnover_eur": 0, "fx_pct": 0.25, "custody_pct": 0.0, "spread_pct": 0.0,
        "verified": False,
    },
    "OTHER": {
        "label": "Inny broker",
        "stock_pct": 0.0, "stock_min": 0.0, "min_currency": "PLN",
        "free_turnover_eur": 0, "fx_pct": 0.0, "custody_pct": 0.0, "spread_pct": 0.0,
        "verified": False,
        "note": "Wpisz stawki ze swojej tabeli opłat.",
    },
}

DEFAULT_BROKER = "OTHER"


def catalog() -> list:
    """Lista profili do wyboru w formularzu."""
    return [{"id": k, **v} for k, v in BROKERS.items()]


def profile(broker: str, overrides=None) -> dict:
    """Profil prowizji: baza brokera + ręczne nadpisania z konta."""
    base = dict(BROKERS.get((broker or "").upper(), BROKERS[DEFAULT_BROKER]))
    base["broker"] = (broker or DEFAULT_BROKER).upper()
    if isinstance(overrides, str) and overrides.strip():
        try:
            overrides = json.loads(overrides)
        except ValueError:
            overrides = None
    if isinstance(overrides, dict):
        changed = False
        for k in FIELDS:
            if overrides.get(k) is not None and overrides[k] != base.get(k):
                base[k] = overrides[k]
                changed = True
        if overrides.get("label") and overrides["label"] != base["label"]:
            base["label"] = overrides["label"]
            changed = True
        # „własne stawki" tylko wtedy, gdy naprawdę różnią się od profilu brokera —
        # samo kliknięcie Zapisz bez zmian nie powinno zmieniać opisu konta
        base["custom"] = changed
    return base


# ---------------- koszty JUŻ zapłacone (mierzone z historii) ----------------

def measure(ops: list, accounts: dict, to_pln) -> dict:
    """Ile realnie poszło na opłaty i spready — policzone z operacji, nie z profilu.

    `to_pln(kwota, waluta, data)` — ten sam przelicznik, którego używa wycena.
    """
    fees_pln, taxes_pln = 0.0, 0.0
    by_type: dict = {}
    conv_cost, conv_volume, conv_count = 0.0, 0.0, 0

    for op in ops:
        typ, amt = op["type"], op["amount"]
        day = (op["time"] or "")[:10]
        ccy = accounts.get(op["account"], "PLN")

        if typ in FEE_TYPES or typ in TAX_TYPES:
            pln = to_pln(abs(amt), ccy, day)
            if typ in FEE_TYPES:
                fees_pln += pln
            else:
                taxes_pln += pln
            by_type[typ] = round(by_type.get(typ, 0.0) + pln, 2)
            continue

        # przewalutowanie: liczymy TYLKO nogę źródłową, żeby nie policzyć dwa razy
        m = _CONV_RE.search(op["comment"] or "")
        r = _RATE_RE.search(op["comment"] or "")
        if not m or not r or op["account"] != m.group(3) or amt >= 0:
            continue
        cur_from, cur_to = m.group(1).upper(), m.group(2).upper()
        rate = float(r.group(1))
        if rate <= 0:
            continue
        src_pln = to_pln(1.0, cur_from, day)      # ile PLN za 1 jednostkę waluty źródłowej
        dst_pln = to_pln(1.0, cur_to, day)
        if src_pln <= 0 or dst_pln <= 0:
            continue
        fair = src_pln / dst_pln                  # kurs rynkowy (NBP) tej pary
        amount_pln = abs(amt) * src_pln
        conv_cost += amount_pln * (1.0 - rate / fair)
        conv_volume += amount_pln
        conv_count += 1

    return {
        "fees_pln": round(fees_pln, 2),
        "taxes_pln": round(taxes_pln, 2),
        "by_type": by_type,
        "fx_spread_pln": round(conv_cost, 2),
        "fx_volume_pln": round(conv_volume, 2),
        "fx_conversions": conv_count,
        "fx_spread_pct": round(conv_cost / conv_volume * 100, 3) if conv_volume > 1e-9 else 0.0,
        "total_pln": round(fees_pln + conv_cost, 2),
    }


# ---------------- koszt WYJŚCIA (jedyny, którego w danych nie ma) ----------------

def exit_costs(positions: list, cash: list, pos_account: dict, cfg: dict, fx_rate) -> dict:
    """Ile kosztowałoby dziś spieniężenie portfela i zamiana wszystkiego na złotówki.

    positions — otwarte pozycje z wyceną w PLN; cash — [(konto, waluta, saldo)];
    pos_account — {ticker: konto}; cfg — {konto: profil}; fx_rate(waluta) -> PLN.
    """
    per_broker: dict = {}
    per_position: dict = {}
    sell_total, fx_total, spread_total = 0.0, 0.0, 0.0

    # obrót per konto — darmowy limit brokera jest miesięczny i dotyczy sumy zleceń
    turnover: dict = {}
    for p in positions:
        acct = pos_account.get(p["ticker"], "")
        turnover[acct] = turnover.get(acct, 0.0) + p["value_pln"]

    for p in positions:
        acct = pos_account.get(p["ticker"], "")
        prof = cfg.get(acct) or profile(DEFAULT_BROKER)
        value = p["value_pln"]

        free_pln = (prof.get("free_turnover_eur") or 0) * fx_rate("EUR")
        if free_pln > 0 and turnover.get(acct, 0.0) <= free_pln:
            commission = 0.0                       # mieścimy się w darmowym limicie
        else:
            pct = value * (prof.get("stock_pct") or 0.0) / 100.0
            min_pln = (prof.get("stock_min") or 0.0) * fx_rate(prof.get("min_currency") or "PLN")
            commission = max(pct, min_pln) if (pct > 0 or min_pln > 0) else 0.0

        spread = value * (prof.get("spread_pct") or 0.0) / 100.0
        # przewalutowanie płacimy tylko od tego, co nie jest w złotówkach
        fx = value * (prof.get("fx_pct") or 0.0) / 100.0 if p["currency"] != "PLN" else 0.0

        sell_total += commission
        spread_total += spread
        fx_total += fx
        per_position[p["ticker"]] = round(commission + spread + fx, 2)
        b = per_broker.setdefault(prof["broker"], {
            "broker": prof["broker"], "label": prof["label"], "accounts": [],
            "sell_pln": 0.0, "fx_pln": 0.0, "spread_pln": 0.0, "value_pln": 0.0})
        b["sell_pln"] += commission
        b["fx_pln"] += fx
        b["spread_pln"] += spread
        b["value_pln"] += value
        if acct and acct not in b["accounts"]:
            b["accounts"].append(acct)

    for acct, ccy, amount in cash:
        if ccy == "PLN" or abs(amount) < 1e-9:
            continue
        prof = cfg.get(acct) or profile(DEFAULT_BROKER)
        fx = amount * fx_rate(ccy) * (prof.get("fx_pct") or 0.0) / 100.0
        fx_total += fx
        b = per_broker.setdefault(prof["broker"], {
            "broker": prof["broker"], "label": prof["label"], "accounts": [],
            "sell_pln": 0.0, "fx_pln": 0.0, "spread_pln": 0.0, "value_pln": 0.0})
        b["fx_pln"] += fx

    for b in per_broker.values():
        for k in ("sell_pln", "fx_pln", "spread_pln", "value_pln"):
            b[k] = round(b[k], 2)

    return {
        "sell_pln": round(sell_total, 2),
        "fx_pln": round(fx_total, 2),
        "spread_pln": round(spread_total, 2),
        "total_pln": round(sell_total + fx_total + spread_total, 2),
        "by_broker": sorted(per_broker.values(), key=lambda b: -b["value_pln"]),
        "by_position": per_position,
    }
