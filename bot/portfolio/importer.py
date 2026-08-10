"""Import raportów historii konta (XTB i pokrewne) — xlsx, csv albo zip z nimi.

Raport XTB ma dwie tabele: operacje gotówkowe i pozycje zamknięte. Nazwa pliku
niesie walutę i numer konta: USD_55145637_2006-01-01_2026-07-27.xlsx (zip może
zawierać katalogi per konto). Gdy waluty w nazwie nie ma, próbujemy wywnioskować
ją z komentarzy 'Currency conversion, USD to PLN from TA: X to: Y'.

Trzy założenia, które ten moduł świadomie ODRZUCA — bo każde z nich wywalało
import na prawdziwym pliku użytkownika:

* że format poznamy po rozszerzeniu — nazwa z telefonu bywa przypadkowa
  (`document.bin`, `raport (1).zip`), a xlsx i zip mają identyczny nagłówek `PK`;
  rozstrzyga dopiero zawartość archiwum;
* że tabele siedzą w zakładkach o znanych nazwach — przeszukujemy WSZYSTKIE
  zakładki i rozpoznajemy tabelę po jej kolumnach;
* że nagłówek stoi w kolumnie A w pierwszych kilku wierszach — szukamy go
  w pierwszych 60 wierszach, w dowolnej kolumnie.

Dzięki temu ten sam kod czyta xlsx, csv i eksport z innej wersji panelu brokera.
"""

import csv
import datetime
import hashlib
import io
import re
import string
import zipfile

import openpyxl

from . import store

_FNAME_RE = re.compile(r"(?:^|[/\\])([A-Z]{3})_(\d{5,12})_", re.IGNORECASE)
_FNAME_NOCUR_RE = re.compile(r"(?:^|[/\\])(\d{5,12})_")
_CONV_RE = re.compile(
    r"Currency conversion,\s*([A-Z]{3}) to ([A-Z]{3}) from TA:\s*(\d+)\s*to:\s*(\d+)")

# Ile wierszy od góry przeszukujemy w poszukiwaniu nagłówka tabeli. XTB wkleja
# nad tabelą metryczkę raportu, a jej wysokość zmienia się między wersjami.
_HEADER_SCAN = 60

# Wymagane kolumny jako grupy synonimów: każda grupa musi mieć swojego
# przedstawiciela w nagłówku. Po nich POZNAJEMY tabelę — nie po nazwie zakładki.
_OPS_COLS = (("type", "typ", "operation", "operacja"),
             ("time", "date", "data", "czas"),
             ("amount", "kwota", "value"))
_CLOSED_COLS = (("instrument", "symbol", "ticker"),
                ("volume", "wolumen", "quantity"),
                ("close time", "close date", "data zamknięcia"))


def _iso(v) -> str:
    """Data/czas w postaci ISO. Przyjmuje i obiekty z xlsx, i teksty z csv."""
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(v, datetime.date):
        return v.strftime("%Y-%m-%d")
    s = str(v or "").strip()
    if not s:
        return ""
    # 2026-07-27 10:31:12 / 2026-07-27T10:31 → jedna postać
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}:\d{2})(:\d{2})?)?", s)
    if m:
        return (f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                + (f"T{m.group(4)}{m.group(5) or ':00'}" if m.group(4) else ""))
    # 27.07.2026 10:31:12 albo 27/07/2026 — układ dzień-miesiąc-rok
    m = re.match(r"(\d{2})[./](\d{2})[./](\d{4})(?:[ T](\d{2}:\d{2})(:\d{2})?)?", s)
    if m:
        return (f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
                + (f"T{m.group(4)}{m.group(5) or ':00'}" if m.group(4) else ""))
    return s


def _num(v) -> float:
    """Liczba z komórki. Radzi sobie z zapisem z csv: '1 234,56', '−12,00 PLN'."""
    if isinstance(v, bool):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").strip()
    if not s:
        return 0.0
    # minus typograficzny i spacje nierozdzielające trafiają tu z eksportów webowych
    s = s.replace("−", "-").replace(" ", "").replace(" ", "").replace("+", "")
    s = re.sub(r"[^0-9,.\-]", "", s)
    if "," in s and "." in s:
        # ostatni separator jest dziesiętny, wcześniejsze to grupowanie tysięcy
        s = (s.replace(",", "") if s.rfind(".") > s.rfind(",")
             else s.replace(".", "").replace(",", "."))
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _header_map(row: tuple) -> dict:
    """{nazwa kolumny (małe litery): indeks} z wiersza nagłówka.

    XTB przestawia kolumny między wersjami raportu: w lipcu 2026 'Ticker' i
    'Instrument' zamieniły się miejscami, doszła też kolumna 'Category'. Czytanie
    po POZYCJI wpisywało wtedy do bazy nazwę spółki jako ticker, a klasę aktywa
    jako datę — i cała wycena się sypała. Dlatego kolumny bierzemy po nazwie.
    """
    out = {}
    for i, cell in enumerate(row):
        key = str(cell if cell is not None else "").strip().lower()
        key = re.sub(r"\s*\(utc\)\s*", "", key)
        key = re.sub(r"\s+", " ", key)
        if key and key not in out:
            out[key] = i
    return out


def _find_table(rows: list, groups: tuple) -> tuple:
    """(indeks wiersza nagłówka, mapa kolumn) pierwszej tabeli o tych kolumnach.

    Nagłówka szukamy po ZAWARTOŚCI, a nie po pozycji — inaczej każdy dodatkowy
    wiersz opisu wklejony nad tabelą kończyłby import komunikatem „to nie raport".
    """
    for i, row in enumerate(rows[:_HEADER_SCAN]):
        cols = _header_map(row)
        if not cols:
            continue
        if all(any(n in cols for n in grp) for grp in groups):
            return i, cols
    return -1, {}


def _pick(cols: dict, row: tuple):
    """Funkcja odczytu komórki po nazwie kolumny, z aliasami: pick(row, 'ticker', 'symbol')."""
    def pick(*names, default=None):
        for n in names:
            i = cols.get(n)
            if i is not None and i < len(row):
                return row[i]
        return default
    return pick


def _meta(rows: list, header_i: int) -> dict:
    """Metryczka nad tabelą: numer konta + zakres dat."""
    meta = {}
    for row in rows[:max(header_i, 0) or 8]:
        if not row:
            continue
        key = str(row[0] or "").strip().lower().rstrip(":")
        val = row[1] if len(row) > 1 else ""
        if key in ("account number", "account", "numer rachunku", "rachunek"):
            meta["account"] = str(val or "").strip()
        elif key.startswith(("date from", "data od")):
            meta["date_from"] = _iso(val)[:10]
        elif key.startswith(("date to", "data do")):
            meta["date_to"] = _iso(val)[:10]
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


def detect_broker(sheet_names, cols_seen: set) -> str:
    """Broker rozpoznany po budowie raportu. Pusty string = nie wiadomo.

    Rozpoznanie zapisujemy przy koncie, bo od brokera zależą prowizje. Gdy nie
    umiemy rozpoznać, użytkownik wybiera brokera ręcznie w aplikacji — dlatego
    tutaj wolimy zwrócić pustkę niż zgadywać.
    """
    sheets = {str(s).strip().lower() for s in sheet_names}
    if {"cash operations", "closed positions"} & sheets or "open positions" in sheets:
        return "XTB"
    if "transactions" in sheets and "account statement" in sheets:
        return "BOSSA"
    # Kolumna 'position id' obok 'close origin' to podpis raportu XTB, niezależny
    # od tego, jak nazwano zakładki (albo czy w ogóle jakieś są — csv).
    if {"position id", "close origin"} <= cols_seen:
        return "XTB"
    return ""


# ---------------- odczyt tabel ----------------

def _rows_of_sheet(ws) -> list:
    """Zakładka jako lista krotek. Raporty mają tysiące wierszy — mieści się w pamięci.

    UWAGA: workbook wczytujemy bez read_only=True — raporty XTB nie mają metadanych
    wymiarów i w trybie read_only openpyxl zwraca tylko pierwszą kolumnę wierszy.
    """
    return [tuple(r) for r in ws.iter_rows(values_only=True)]


_ID_COLS = ("id", "operation id", "transaction id", "order id", "nr", "numer")


def _read_ops(rows: list, cols: dict, header_i: int, account: str) -> list:
    # Raport bez kolumny z numerem operacji (zdarza się w eksportach csv) i tak ma
    # się dać wgrać dwa razy bez dublowania — więc budujemy numer z treści wiersza.
    # Skutek uboczny: dwie operacje identyczne co do sekundy, kwoty i opisu zlewają
    # się w jedną. To rzadkie i mniej szkodliwe niż odrzucenie całego pliku.
    ma_id = any(n in cols for n in _ID_COLS)
    ops = []
    for row in rows[header_i + 1:]:
        pick = _pick(cols, row)
        typ = str(pick("type", "typ", "operation", "operacja") or "").strip()
        if not typ or typ.lower() in ("total", "razem", "suma"):
            continue
        czas = _iso(pick("time", "date", "data", "czas"))
        kwota = _num(pick("amount", "kwota", "value"))
        op_id = str(pick(*_ID_COLS) or "").strip()
        if not op_id and ma_id:
            continue   # kolumna jest, ale pusta → wiersz podsumowania / śmieć
        if not op_id:
            if not czas:
                continue
            surowe = f"{czas}|{typ}|{kwota}|{pick('comment', 'komentarz') or ''}"
            op_id = "auto:" + hashlib.blake2s(surowe.encode("utf-8"),
                                              digest_size=8).hexdigest()
        ops.append((
            account, op_id, typ,
            str(pick("ticker", "symbol") or "").strip(),
            str(pick("instrument", "name", "nazwa") or "").strip(),
            czas, kwota,
            str(pick("comment", "komentarz") or "").strip(),
            str(pick("product", "produkt") or "").strip(),
        ))
    return ops


def _read_closed(rows: list, cols: dict, header_i: int, account: str) -> list:
    closed = []
    for row in rows[header_i + 1:]:
        pick = _pick(cols, row)
        instr = str(pick("instrument", "symbol", "ticker") or "").strip()
        if not instr or instr.lower() in ("profit/loss", "total", "razem"):
            continue
        pos_id = str(pick("position id", "position", "id") or "").strip()
        volume = _num(pick("volume", "wolumen", "quantity"))
        close_time = _iso(pick("close time", "close date", "data zamknięcia"))
        key = f"{account}|{pos_id}|{close_time}|{volume}"
        closed.append((
            key, account, instr,
            str(pick("category", "kategoria") or "").strip(),
            str(pick("ticker", "symbol") or "").strip(),
            str(pick("type", "typ") or "").strip(),
            volume, _num(pick("open price", "cena otwarcia")),
            _iso(pick("open time", "open date", "data otwarcia")),
            _num(pick("close price", "cena zamknięcia")), close_time,
            _num(pick("profit/loss", "profit", "wynik")),
            _num(pick("gross profit", "gross p/l")),
            _num(pick("purchase value", "wartość zakupu")),
            _num(pick("sale value", "wartość sprzedaży")),
            _num(pick("commission", "prowizja")),
            _num(pick("swap", "punkty swap")),
            _num(pick("rollover")),
            str(pick("close origin") or "").strip(), pos_id,
        ))
    return closed


def _sheets_from_xlsx(data: bytes) -> list:
    """[(nazwa zakładki, wiersze)] — wszystkie zakładki skoroszytu."""
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    try:
        return [(ws.title, _rows_of_sheet(ws)) for ws in wb.worksheets]
    finally:
        wb.close()


def _sheets_from_csv(data: bytes, filename: str) -> list:
    """[(nazwa pliku, wiersze)] — csv traktujemy jak skoroszyt z jedną zakładką."""
    for enc in ("utf-8-sig", "cp1250", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", "replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
        delim = dialect.delimiter
    except csv.Error:
        # Bez podpowiedzi zgadujemy po tym, czego jest więcej w próbce.
        delim = max(";,\t|", key=sample.count)
    return [(filename, [tuple(r) for r in csv.reader(io.StringIO(text), delimiter=delim)])]


def _parse_sheets(sheets: list, filename: str) -> dict:
    """Wspólny rdzeń importu: z listy zakładek robi zapis w bazie i statystyki.

    Tabele znajdujemy przeszukując KAŻDĄ zakładkę — nazwa zakładki służy już tylko
    do rozstrzygnięcia remisu, gdy pasujących tabel jest kilka.
    """
    ops_hit = closed_hit = None
    cols_seen = set()
    for name, rows in sheets:
        low = str(name).strip().lower()
        i, cols = _find_table(rows, _OPS_COLS)
        if i >= 0:
            cols_seen |= set(cols)
            if ops_hit is None or "cash" in low or "gotów" in low:
                ops_hit = (name, rows, i, cols)
        j, cols2 = _find_table(rows, _CLOSED_COLS)
        if j >= 0:
            cols_seen |= set(cols2)
            if closed_hit is None or "closed" in low or "zamkni" in low:
                closed_hit = (name, rows, j, cols2)

    if ops_hit is None and closed_hit is None:
        widok = ", ".join(str(n) for n, _ in sheets[:6]) or "brak zakładek"
        raise ValueError(
            f"{filename}: nie znalazłem w tym pliku tabeli operacji ani pozycji "
            f"zamkniętych (zakładki: {widok}). W XTB wybierz Historia → eksport "
            "do Excela i wgraj plik bez zmian.")

    broker = detect_broker([n for n, _ in sheets], cols_seen)

    # Numer konta: metryczka nad tabelą, a gdy jej nie ma — nazwa pliku.
    base_rows, base_i = (ops_hit or closed_hit)[1], (ops_hit or closed_hit)[2]
    meta = _meta(base_rows, base_i)
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
        raise ValueError(
            f"{filename}: nie udało się ustalić numeru konta. Wgraj raport pod "
            "oryginalną nazwą z XTB (zawiera numer rachunku) albo dodaj konto ręcznie.")

    ops = _read_ops(ops_hit[1], ops_hit[3], ops_hit[2], account) if ops_hit else []
    closed = (_read_closed(closed_hit[1], closed_hit[3], closed_hit[2], account)
              if closed_hit else [])

    if not ops and not closed:
        raise ValueError(f"{filename}: tabela jest pusta — raport nie zawiera "
                         "żadnych operacji w wybranym okresie")

    if not currency:
        currency = _guess_currency(account, ops)

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


def _parse_xlsx(data: bytes, filename: str) -> dict:
    return _parse_sheets(_sheets_from_xlsx(data), filename)


def _parse_csv(data: bytes, filename: str) -> dict:
    return _parse_sheets(_sheets_from_csv(data, filename), filename)


# ---------------- rozpoznawanie formatu ----------------

_ZIP_SIGS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OLE_SIG = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"          # stary .xls / .doc
_PDF_SIG = b"%PDF"
_B64_ALPHABET = frozenset((string.ascii_letters + string.digits + "+/=-_").encode())
# Pliki, których nigdy nie ma sensu otwierać jako raportu.
_JUNK_PREFIXES = ("__macosx/", ".", "~$")
_KNOWN_EXT = (".xlsx", ".xlsm", ".zip", ".xls", ".csv", ".txt", ".tsv", ".bin", "")


def _is_zip(data: bytes) -> bool:
    return data[:4] in _ZIP_SIGS


def _looks_xlsx(names) -> bool:
    """Czy to archiwum JEST skoroszytem, a nie paczką z plikami?

    xlsx to też zip — poznajemy go po wewnętrznej strukturze OOXML.
    """
    s = set(names)
    return ("xl/workbook.xml" in s or "xl/workbook.bin" in s
            or ("[Content_Types].xml" in s and any(n.startswith("xl/") for n in s)))


def _looks_text_table(data: bytes) -> bool:
    """Czy bajty wyglądają na tabelę tekstową (csv/tsv), a nie na plik binarny?"""
    head = data[:4096]
    if b"\x00" in head:
        return False
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = head.decode("cp1250")
        except UnicodeDecodeError:
            return False
    first = text.splitlines()[0] if text.splitlines() else ""
    return any(sep in first for sep in (";", ",", "\t", "|"))


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
    """Rozpakowuje co się da i importuje każdy znaleziony raport.

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

    if data[:4] == _PDF_SIG:
        if not depth:
            errors.append(f"{filename}: to PDF, a nie arkusz — w XTB wybierz "
                          "eksport do Excela (.xlsx), nie wydruk do PDF")
        return

    # Ostatnia deska ratunku: ciało przyszło jako tekst base64 zamiast bajtów.
    if looks_base64(data):
        decoded = b""
        try:
            decoded = decode_base64(data)
        except Exception:                                    # noqa: BLE001
            decoded = b""
        if _is_zip(decoded) or decoded[:8] == _OLE_SIG:
            _collect(decoded, filename, out, errors, depth + 1)
            return

    if _looks_text_table(data):
        try:
            out.append(_parse_csv(data, filename))
            return
        except Exception as e:                               # noqa: BLE001
            errors.append(str(e))
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
    _collect(data, filename, results, errors)
    if not results:
        raise ValueError(" · ".join(errors[:3])
                         or f"{filename}: nie znaleziono raportu ({_sniff_label(data)})")
    return results, errors


def import_file(data: bytes, filename: str) -> list:
    """Zgodność wstecz: sama lista wyników (używa panel w przeglądarce)."""
    return import_report(data, filename)[0]
