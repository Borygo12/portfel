"""Zdjęcia person z Wikimedia Commons — tylko na wolnych licencjach, z autorem.

Uruchamiane RĘCZNIE na komputerze (Pillow jest tu, nie na serwerze):

    python bot/insiders/zdjecia_wiki.py            # osoby z katalogu bez zdjęcia
    python bot/insiders/zdjecia_wiki.py --od-nowa  # także te, które już mają

Skąd: zdjęcie z artykułu w Wikipedii (angielskiej; dla osób z GPW — polskiej),
ALE wyłącznie wtedy, gdy plik leży w Wikimedia Commons. Zdjęcia „fair use"
trzymane lokalnie w Wikipedii nie są wolne — takie pomijamy.

Licencje: domena publiczna (w tym oficjalne portrety rządu USA), CC0, CC BY,
CC BY-SA. CC BY i CC BY-SA wymagają podania autora i licencji — dlatego każdy
plik trafia do `static/insiders/zrodla.json`, a z niego powstaje strona
`static/insiders/autorzy.html`, podlinkowana w stopce panelu Insajderów.
Kadr i miniaturę robi `photos.zapisz` (ten sam, co dla zdjęć właściciela) —
CC BY-SA obejmuje też tę przyciętą wersję, co strona autorów mówi wprost.

Zdjęcia właściciela (`zdjecia.py`) mają pierwszeństwo: ten skrypt nie nadpisuje
pliku, którego nie ma w `zrodla.json` (czyli który nie pochodzi z Commons).
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.parse

import requests

TU = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TU))

from insiders import people, photos  # noqa: E402

CEL = os.path.join(os.path.dirname(TU), "static", "insiders")
ZRODLA = os.path.join(CEL, "zrodla.json")
AUTORZY = os.path.join(CEL, "autorzy.html")
UA = {"User-Agent": "PortevoBot/1.0 (https://www.portevo.pl; borygoo45@gmail.com) zdjecia insiderow"}

WOLNE = re.compile(r"^(public domain|pd\b|pd-|cc0|cc[ -]by(-sa)?[ -]\d|ogl\b)", re.I)

# Artykuł ma inny tytuł niż nazwa w katalogu (ujednoznacznienia, pełne imię)
TYTULY = {
    "tom-kean": "Tom Kean Jr.", "dan-loeb": "Daniel S. Loeb", "chase-coleman": "Chase Coleman III",
    "steve-cohen": "Steve Cohen (politician)", "mike-kelly": "Mike Kelly (Pennsylvania politician)",
    "tim-moore": "Tim Moore (North Carolina politician)", "rick-allen": "Rick W. Allen",
    "scott-peters": "Scott Peters (politician)", "max-miller": "Max Miller (politician)",
    "dave-taylor": "Dave Taylor (Ohio politician)", "julie-johnson": "Julie Johnson (politician)",
    "jonathan-jackson": "Jonathan Jackson (politician)", "dave-mccormick": "David McCormick",
}
# Ręczny kadr dla zdjęć, na których twarz jest mała albo z boku (środek x, środek y,
# bok kwadratu — wszystko jako ułamek szerokości/wysokości oryginału). Ustalone
# na oko 28.09.2026; bez tego Solorz był małą postacią na scenie.
KADRY = {
    "zygmunt-solorz": (0.46, 0.26, 0.62),
    "howard-lutnick": (0.55, 0.25, 0.50),
    "larry-ellison": (0.49, 0.36, 0.62),
    "seth-klarman": (0.55, 0.25, 0.50),
}

POLSKIE = {"marcin-iwinski", "michal-kicinski", "tomasz-biernacki", "dariusz-milek", "adam-goral",
           "zygmunt-solorz", "michal-solowow", "leszek-czarnecki"}

_ses = requests.Session()
_ses.headers.update(UA)


def _get(url: str, **params):
    for proba in range(3):
        try:
            r = _ses.get(url, params=params or None, timeout=30)
            if r.status_code == 429:
                time.sleep(5 * (proba + 1))
                continue
            return r
        except requests.RequestException:
            time.sleep(2)
    return None


def plik_z_artykulu(tytul: str, jezyk: str) -> str | None:
    """Nazwa pliku ze zdjęciem głównym artykułu (bez „File:")."""
    r = _get(f"https://{jezyk}.wikipedia.org/w/api.php", action="query", format="json",
             prop="pageimages", piprop="name", redirects=1, titles=tytul)
    if not r or r.status_code != 200:
        return None
    for strona in (r.json().get("query") or {}).get("pages", {}).values():
        if strona.get("pageimage"):
            return strona["pageimage"]
    return None


def z_commons(plik: str) -> dict | None:
    """Metadane pliku z Commons. None = pliku nie ma w Commons (np. fair use)."""
    r = _get("https://commons.wikimedia.org/w/api.php", action="query", format="json",
             prop="imageinfo", iiprop="url|extmetadata", iiurlwidth=900, titles=f"File:{plik}")
    if not r or r.status_code != 200:
        return None
    for strona in (r.json().get("query") or {}).get("pages", {}).values():
        if "missing" in strona or not strona.get("imageinfo"):
            return None
        ii = strona["imageinfo"][0]
        meta = ii.get("extmetadata") or {}
        licencja = (meta.get("LicenseShortName") or {}).get("value", "")
        autor = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip()
        return {
            "plik": plik, "licencja": licencja, "autor": html.unescape(autor)[:160] or "nieznany",
            "url_licencji": (meta.get("LicenseUrl") or {}).get("value", ""),
            "strona": ii.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/File:{urllib.parse.quote(plik)}",
            "obraz": ii.get("thumburl") or ii.get("url"),
        }
    return None


def _przytnij(dane: bytes, kadr: tuple[float, float, float]) -> bytes:
    import io
    from PIL import Image
    with Image.open(io.BytesIO(dane)) as im:
        im = im.convert("RGB")
        w, h = im.size
        bok = int(kadr[2] * w)
        x = min(max(0, int(kadr[0] * w - bok / 2)), w - bok)
        y = min(max(0, int(kadr[1] * h - bok / 2)), h - bok)
        out = io.BytesIO()
        im.crop((x, y, x + bok, y + bok)).save(out, "JPEG", quality=92)
        return out.getvalue()


def main() -> int:
    od_nowa = "--od-nowa" in sys.argv
    tylko = [a for a in sys.argv[1:] if not a.startswith("--")]
    try:
        with open(ZRODLA, encoding="utf-8") as f:
            zrodla = json.load(f)
    except (OSError, ValueError):
        zrodla = {}
    os.makedirs(os.path.join(CEL, "b"), exist_ok=True)

    ok, pominiete, brak = [], [], []
    for p in people.KATALOG:
        pid = p["id"]
        if tylko and pid not in tylko:
            continue
        # Kongres ma oficjalne portrety pobierane przez serwer (photos.py) — jednolite
        # i w domenie publicznej; plik stąd by je przesłonił
        if (p.get("house") or p.get("senat")) and not p.get("oge") and not tylko:
            continue
        jest = os.path.isfile(os.path.join(CEL, f"{pid}.jpg"))
        if jest and pid not in zrodla:
            pominiete.append(pid)                 # zdjęcie właściciela — nie ruszamy
            continue
        if jest and not od_nowa and not tylko:
            continue
        jezyk = "pl" if pid in POLSKIE else "en"
        tytul = TYTULY.get(pid, p["name"])
        plik = plik_z_artykulu(tytul, jezyk)
        if not plik and jezyk == "pl":
            plik = plik_z_artykulu(tytul, "en")
        meta = z_commons(plik) if plik else None
        if not meta or not WOLNE.search(meta["licencja"]) or not meta.get("obraz"):
            brak.append(f"{pid} ({plik or 'brak zdjęcia w artykule'}"
                        f"{'; licencja ' + meta['licencja'] if meta else ''})")
            continue
        r = _get(meta["obraz"])
        dane = _przytnij(r.content, KADRY[pid]) if r and r.status_code == 200 and pid in KADRY else (
            r.content if r else b"")
        if not r or r.status_code != 200 or not photos.zapisz(pid, dane, CEL):
            brak.append(f"{pid} (nie udało się pobrać)")
            continue
        zrodla[pid] = {k: v for k, v in meta.items() if k != "obraz"} | {"osoba": p["name"]}
        ok.append(f"{pid}: {meta['licencja']} — {meta['autor'][:50]}")
        time.sleep(0.4)

    with open(ZRODLA, "w", encoding="utf-8") as f:
        json.dump(zrodla, f, ensure_ascii=False, indent=1, sort_keys=True)
    _strona_autorow(zrodla)
    print(f"Pobrane: {len(ok)}")
    for x in ok:
        print("  +", x)
    if pominiete:
        print(f"Zdjęcia właściciela (nietknięte): {', '.join(pominiete)}")
    if brak:
        print(f"Bez wolnego zdjęcia ({len(brak)}):")
        for x in brak:
            print("  ?", x)
    return 0


def _strona_autorow(zrodla: dict) -> None:
    wiersze = []
    for pid, z in sorted(zrodla.items(), key=lambda kv: kv[1].get("osoba", kv[0])):
        lic = html.escape(z["licencja"])
        if z.get("url_licencji"):
            lic = f'<a href="{html.escape(z["url_licencji"])}">{lic}</a>'
        wiersze.append(
            f'<tr><td><img src="/static/insiders/{pid}.jpg" alt=""></td>'
            f'<td><b>{html.escape(z.get("osoba", pid))}</b><br>'
            f'<a href="{html.escape(z["strona"])}">{html.escape(z["plik"])}</a></td>'
            f'<td>{html.escape(z["autor"])}</td><td>{lic}</td></tr>')
    tresc = f"""<!doctype html><html lang="pl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Autorzy zdjęć — Insajderzy · Portevo</title>
<style>
body{{background:#080b11;color:#eef1f7;font:14px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px}}
main{{max-width:900px;margin:0 auto}} h1{{font-size:22px}} p{{color:#8b93a7}}
a{{color:#5b8cff}} table{{width:100%;border-collapse:collapse;margin-top:16px}}
td{{padding:8px;border-bottom:1px solid #212938;vertical-align:middle;font-size:13px}}
img{{width:44px;height:44px;border-radius:50%;display:block}}
@media(max-width:600px){{td:nth-child(3){{display:none}}}}
</style></head><body><main>
<h1>Autorzy zdjęć w narzędziu „Insajderzy"</h1>
<p>Zdjęcia pochodzą z Wikimedia Commons i są udostępnione na wolnych licencjach
(domena publiczna, CC0, CC BY, CC BY-SA). W aplikacji pokazujemy je przycięte do
kwadratu i pomniejszone; przycięte wersje zdjęć na licencji CC BY-SA udostępniamy
na tej samej licencji. Portrety członków Kongresu to oficjalne zdjęcia Kongresu USA
(domena publiczna, zbiór unitedstates/images). Kliknij nazwę pliku, żeby zobaczyć oryginał.</p>
<table>{''.join(wiersze)}</table>
</main></body></html>"""
    with open(AUTORZY, "w", encoding="utf-8") as f:
        f.write(tresc)


if __name__ == "__main__":
    sys.exit(main())
