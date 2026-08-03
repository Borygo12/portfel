"""Import raportów historii konta XTB (xlsx lub zip z xlsx-ami).

Format pliku: dwie zakładki — 'Cash Operations' i 'Closed Positions'.
Nazwa pliku niesie walutę i numer konta: USD_55145637_2006-01-01_2026-07-27.xlsx
(zip może zawierać katalogi per konto). Waluta z nazwy pliku; gdy jej brak,
próbujemy wywnioskować z komentarzy 'Currency conversion, USD to PLN from TA: X to: Y'.

Format rozpoznajemy po ZAWARTOŚCI, nie po rozszerzeniu — nazwa z telefonu bywa
przypadkowa (`document.bin`, `raport (1).zip`), a xlsx i zip mają identyczny
nagłówek `PK`. Rozróżnia je dopiero to, co jest w środku archiwum.
"""

import datetime
import io
import re
import string
import zipfile

import openpyxl

from . import store

_FNAME_RE = re.compile(r"(?:^|[/\\])([A-Z]{3})_(\d{5,12})_.*\.xlsx$", re.IGNORECASE)
_FNAME_NOCUR_RE = re.compile(r"(?:^|[/\\])(\d{5,12})_.*\.xlsx$")
_CONV_RE = re.compile(
    r"Currency conversion,\s*([A-Z]{3}) to ([A-Z]{3}) from TA:\s*(\d+)\s*to:\s*(\d+)")


def _iso(v) -> str:
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%dT%H:%M:%S")
    return str(v or "")


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _pad(row: tuple, n: int) -> tuple:
    """read_only=True potrafi zwracać krótsze krotki — dopełniamy None-ami."""
    return row + (None,) * (n - len(row)) if len(row) < n else row


def _header_map(row: tuple) -> dict:
    """{nazwa kolumny (małe litery): indeks} z wiersza nagłówka.

    XTB przestawia kolumny między wersjami raportu: w lipcu 2026 'Ticker' i
    'Instrument' zamieniły się miejscami, doszła też kolumna 'Category'. Czytanie
    po POZYCJI wpisywało wtedy do bazy nazwę spółki jako ticker, a klasę aktywa
    jako datę — i cała wycena się sypała. Dlatego kolumny bierzemy po nazwie.
    """
    out = {}
    for i, cell in enumerate(row):
        key = str(cell or "").strip().lower().replace(" (utc)", "")
        if key and key not in out:
            out[key] = i
    return out


def _find_header(ws, first_cell: str) -> tuple:
    """(numer wiersza 1-based, mapa kolumn) tabeli, której kolumna A == first_cell."""
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=15, values_only=True), start=1):
        if str(row[0]).strip() == first_cell:
            return i, _header_map(row)
    raise ValueError(f"Nie znaleziono nagłówka '{first_cell}' — to nie wygląda na raport XTB")


def _picker(cols: dict, required: set, what: str):
    """Funkcja odczytu komórki po nazwie kolumny, z aliasami: pick(row, 'ticker', 'symbol').

    Brak kolumny, bez której nie da się zbudować wiersza, kończy import błędem —
    lepiej powiedzieć „nie znam tego układu" niż po cichu zapisać przesunięte dane.
    """
    missing = sorted(required - set(cols))
    if missing:
        raise ValueError(f"{what}: brakuje kolumn {', '.join(missing)} — "
                         "raport ma nieznany układ, zgłoś to razem z nazwą pliku")

    def pick(row: tuple, *names, default=None):
        for n in names:
            i = cols.get(n)
            if i is not None and i < len(row):
                return row[i]
        return default

    return pick


def _meta(ws) -> dict:
    """Nagłówek raportu: numer konta + zakres dat (pierwsze 4 wiersze)."""
    meta = {}
    for row in ws.iter_rows(min_row=1, max_row=4, max_col=2, values_only=True):
        key = str(row[0] or "").strip().lower()
        if key in ("account number", "account"):
            meta["account"] = str(row[1] or "").strip()
        elif key.startswith("date from"):
            meta["date_from"] = _iso(row[1])[:10]
        elif key.startswith("date to"):
            meta["date_to"] = _iso(row[1])[:10]
    return meta


def _guess_currency(account: str, ops: list) -> str:
    """Waluta konta z komentarzy o przewalutowaniach (konto 'from' ma walutę 'from')."""
    for op in ops:
        m = _CONV_RE.search(op[7] or "")     # op[7] = comment
        if not m:
            continue
        cur_from, cur_to, ta_from, ta_to = m.groups()
        if ta_from == account:
            return cur_from.upper()
        if ta_to == account:
            return cur_to.upper()
    return "PLN"


def detect_broker(wb, filename: str) -> str:
    """Broker rozpoznany po budowie raportu. Pusty string = nie wiadomo.

    Rozpoznanie zapisujemy przy koncie, bo od brokera zależą prowizje. Gdy nie
    umiemy rozpoznać, użytkownik wybiera brokera ręcznie w aplikacji — dlatego
    tutaj wolimy zwrócić pustkę niż zgadywać.
    """
    sheets = {s.strip().lower() for s in wb.sheetnames}
    if {"cash operations", "closed positions"} <= sheets or "open positions" in sheets:
        return "XTB"
    if "transactions" in sheets and "account statement" in sheets:
        return "BOSSA"
    return ""


def _parse_xlsx(data: bytes, filename: str) -> dict:
    """Parsuje jeden raport xlsx. Zwraca statystyki importu."""
    # UWAGA: bez read_only=True — raporty XTB nie mają metadanych wymiarów
    # i w trybie read_only openpyxl zwraca tylko pierwszą kolumnę wierszy.
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)

    if "Cash Operations" not in wb.sheetnames:
        raise ValueError(f"{filename}: brak zakładki 'Cash Operations' — to nie raport historii XTB")
    broker = detect_broker(wb, filename)

    ws = wb["Cash Operations"]
    meta = _meta(ws)
    account = meta.get("account") or ""

    m = _FNAME_RE.search(filename)
    currency = m.group(1).upper() if m else ""
    if m and not account:
        account = m.group(2)
    if not account:
        m2 = _FNAME_NOCUR_RE.search(filename)
        if m2:
            account = m2.group(1)
    if not account:
        raise ValueError(f"{filename}: nie udało się ustalić numeru konta")

    header_row, cols = _find_header(ws, "Type")
    pick = _picker(cols, {"type", "time", "amount", "id"},
                   f"{filename}: zakładka 'Cash Operations'")
    width = max(cols.values()) + 1
    ops = []
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        row = _pad(row, width)
        typ = str(pick(row, "type") or "").strip()
        if not typ or typ == "Total":
            continue
        op_id = str(pick(row, "id") or "").strip()
        if not op_id:   # wiersz podsumowania / śmieć
            continue
        ops.append((
            account, op_id, typ,
            str(pick(row, "ticker", "symbol") or "").strip(),
            str(pick(row, "instrument", "name") or "").strip(),
            _iso(pick(row, "time", "date")), _num(pick(row, "amount")),
            str(pick(row, "comment") or "").strip(),
            str(pick(row, "product") or "").strip(),
        ))

    if not currency:
        currency = _guess_currency(account, ops)

    closed = []
    if "Closed Positions" in wb.sheetnames:
        ws2 = wb["Closed Positions"]
        try:
            h2, cols2 = _find_header(ws2, "Instrument")
            pick2 = _picker(cols2, {"instrument", "volume", "close time", "position id"},
                            f"{filename}: zakładka 'Closed Positions'")
        except ValueError:
            h2 = None
        if h2:
            width2 = max(cols2.values()) + 1
            for row in ws2.iter_rows(min_row=h2 + 1, values_only=True):
                row = _pad(row, width2)
                instr = str(pick2(row, "instrument") or "").strip()
                if not instr or instr == "Profit/loss":
                    continue
                pos_id = str(pick2(row, "position id") or "").strip()
                volume, close_time = _num(pick2(row, "volume")), _iso(pick2(row, "close time"))
                key = f"{account}|{pos_id}|{close_time}|{volume}"
                closed.append((
                    key, account, instr,
                    str(pick2(row, "category") or "").strip(),
                    str(pick2(row, "ticker", "symbol") or "").strip(),
                    str(pick2(row, "type") or "").strip(),
                    volume, _num(pick2(row, "open price")), _iso(pick2(row, "open time")),
                    _num(pick2(row, "close price")), close_time,
                    _num(pick2(row, "profit/loss")), _num(pick2(row, "gross profit")),
                    _num(pick2(row, "purchase value")), _num(pick2(row, "sale value")),
                    _num(pick2(row, "commission")), _num(pick2(row, "swap")),
                    _num(pick2(row, "rollover")),
                    str(pick2(row, "close origin") or "").strip(), pos_id,
                ))

    wb.close()

    store.init()
    new_ops = store.insert_cash_ops(ops)
    new_closed = store.insert_closed_positions(closed)
    store.upsert_account(
        account, currency,
        meta.get("date_from", ""), meta.get("date_to", ""),
        datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        broker,
    )
    return {
        "file": filename.split("/")[-1].split("\\")[-1],
        "account": account, "currency": currency, "broker": broker,
        "ops_total": len(ops), "ops_new": new_ops,
        "closed_total": len(closed), "closed_new": new_closed,
    }


# ---------------- rozpoznawanie formatu ----------------

_ZIP_SIGS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OLE_SIG = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"          # stary .xls / .doc
_B64_ALPHABET = frozenset((string.ascii_letters + string.digits + "+/=-_").encode())
# Pliki, których nigdy nie ma sensu otwierać jako raportu.
_JUNK_PREFIXES = ("__macosx/", ".", "~$")
_KNOWN_EXT = (".xlsx", ".xlsm", ".zip", ".xls", ".csv", "")


def _is_zip(data: bytes) -> bool:
    return data[:4] in _ZIP_SIGS


def _looks_xlsx(names) -> bool:
    """Czy to archiwum JEST skoroszytem, a nie paczką z plikami?

    xlsx to też zip — poznajemy go po wewnętrznej strukturze OOXML.
    """
    s = set(names)
    return ("xl/workbook.xml" in s or "xl/workbook.bin" in s
            or ("[Content_Types].xml" in s and any(n.startswith("xl/") for n in s)))


def looks_base64(data: bytes) -> bool:
    """Czy bajty to w rzeczywistości tekst base64 (a nie sam plik)?

    Zdarza się, gdy klient zapomni oznaczyć `encoding=base64` albo pośrednik
    potraktuje ciało żądania jak tekst. Taniej to wykryć niż zwrócić „to nie zip".
    """
    head = data[:1024]
    if head[:5].lower() == b"data:":
        head = head.partition(b",")[2]
    head = bytes(c for c in head if c not in b" \t\r\n")   # łamanie linii co 76 znaków
    return len(head) >= 16 and set(head) <= _B64_ALPHABET


def decode_base64(data: bytes) -> bytes:
    """Base64 wyrozumiały: białe znaki, prefiks `data:`, wariant URL, brak paddingu."""
    import base64 as _b64
    txt = data.strip()
    if txt[:5].lower() == b"data:":
        txt = txt.partition(b",")[2]
    txt = bytes(c for c in txt if c in _B64_ALPHABET)
    txt = txt.replace(b"-", b"+").replace(b"_", b"/")
    txt += b"=" * (-len(txt) % 4)
    return _b64.b64decode(txt, validate=False)


def _sniff_label(data: bytes) -> str:
    """Krótki opis tego, co faktycznie przyszło — do sensownego komunikatu błędu."""
    head = data[:24]
    txt = head.decode("utf-8", "replace").strip()
    printable = all(32 <= b < 127 or b in (9, 10, 13) for b in head)
    kind = f'tekst „{txt[:20]}…"' if printable else f"bajty {head[:8].hex(' ')}"
    return f"{len(data)} B, {kind}"


def _useful_member(name: str) -> bool:
    base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    low = name.lower()
    if name.endswith("/") or not base:
        return False
    if low.startswith("__macosx/") or base.startswith(_JUNK_PREFIXES[1:]):
        return False
    return True


def _collect(data: bytes, filename: str, out: list, errors: list, depth: int = 0) -> None:
    """Rozpakowuje co się da i importuje każdy znaleziony skoroszyt.

    Błąd pojedynczego pliku nie przerywa całości — paczka z brokera potrafi
    zawierać dodatki (regulamin, csv), a raporty i tak mają być zaimportowane.
    """
    if depth > 4 or not data:
        return

    data = data.lstrip(b"\r\n\t \x00").lstrip(b"\xef\xbb\xbf")

    if _is_zip(data):
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            errors.append(f"{filename}: archiwum jest uszkodzone lub niekompletne")
            return
        with zf:
            names = zf.namelist()
            if _looks_xlsx(names):
                try:
                    out.append(_parse_xlsx(data, filename))
                except Exception as e:                       # noqa: BLE001
                    errors.append(str(e))
                return
            members = [n for n in names if _useful_member(n)]
            if not members:
                errors.append(f"{filename}: archiwum jest puste")
                return
            for n in sorted(members):
                try:
                    inner = zf.read(n)
                except Exception as e:                       # noqa: BLE001
                    errors.append(f"{n}: nie udało się rozpakować ({e})")
                    continue
                _collect(inner, n, out, errors, depth + 1)
        return

    if data[:8] == _OLE_SIG:
        errors.append(f"{filename}: to stary format .xls — w XTB wybierz eksport do .xlsx")
        return

    # Ostatnia deska ratunku: ciało przyszło jako tekst base64 zamiast bajtów.
    if looks_base64(data):
        try:
            decoded = decode_base64(data)
        except Exception:                                    # noqa: BLE001
            decoded = b""
        if _is_zip(decoded):
            _collect(decoded, filename, out, errors, depth + 1)
            return

    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if depth and ext not in _KNOWN_EXT:
        return          # zwykły dodatek w paczce (pdf, obrazek) — cicho pomijamy
    errors.append(f"{filename}: nierozpoznany format ({_sniff_label(data)})")


def import_report(data: bytes, filename: str) -> tuple:
    """Importuje wszystko, co da się wyłuskać z przysłanych bajtów.

    Zwraca (wyniki, ostrzeżenia). Rzuca dopiero wtedy, gdy nie udało się
    zaimportować ani jednego raportu — wtedy komunikat mówi, co przyszło.
    """
    results, errors = [], []
    _collect(data, filename or "raport", results, errors)
    if not results:
        raise ValueError(" · ".join(errors[:3])
                         or f"{filename}: nie znaleziono raportu ({_sniff_label(data)})")
    return results, errors


def import_file(data: bytes, filename: str) -> list:
    """Zgodność wstecz: sama lista wyników (używa panel w przeglądarce)."""
    return import_report(data, filename)[0]
