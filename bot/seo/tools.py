"""Kalkulatory — `/kalkulator-podatku-belki`.

„Podatek Belki kalkulator" to jedna z największych i najstabilniejszych fraz
w polskim inwestowaniu (co roku szczyt przed 30 kwietnia, termin PIT-38).
Narzędzie ma jednoznaczną intencję, więc rankuje lepiej niż tekst — i prowadzi
prosto do produktu: Portevo liczy wynik po kosztach z raportu brokera sam.

Kalkulator działa w przeglądarce (kilkadziesiąt linijek JS w stronie, bez
zewnętrznych skryptów), ale PRZYKŁADY są policzone po stronie serwera i stoją
w HTML-u — robot i czytnik bez JavaScriptu widzą konkretne liczby, a nie
pusty formularz.

Zasady podatkowe (stan na 2026, PIT-38, art. 30a i 30b ustawy o PIT):
* 19% od dochodu ze sprzedaży papierów (przychód − koszty), strata z lat
  ubiegłych do 50% rocznie przez 5 lat albo jednorazowo do 5 mln zł;
* dywidendy z Polski — 19% pobiera płatnik, bez dalszych rozliczeń;
* dywidendy z USA z W-8BEN — 15% u źródła, w Polsce dopłata 4%;
  bez W-8BEN — 30% u źródła i nic do dopłaty (nadwyżki się nie odzyska);
* odsetki z lokat — 19% pobiera bank.
Podstawę i podatek z PIT-38 zaokrągla się do pełnych złotych.
"""

from __future__ import annotations

from . import dates, jsonld, render, site

SCIEZKA = "/kalkulator-podatku-belki"
ZMIENIONO = "2026-09-22"
STAWKA = 0.19


def _zl(v: float) -> str:
    return render.liczba(v, 2) + " zł"


def podatek_od_zysku(przychod: float, koszty: float, strata: float = 0.0) -> dict:
    dochod = max(0.0, przychod - koszty)
    odliczenie = min(strata, dochod)
    podstawa = round(dochod - odliczenie)
    pod = round(podstawa * STAWKA)
    return {"dochod": dochod, "podstawa": podstawa, "podatek": pod,
            "netto": przychod - koszty - pod}


def podatek_od_dywidendy(brutto: float, zrodlo: float) -> dict:
    """`zrodlo` — stawka pobrana za granicą (0,15 przy W-8BEN, 0,30 bez niego)."""
    u_zrodla = brutto * zrodlo
    doplata = max(0.0, brutto * STAWKA - u_zrodla)
    return {"u_zrodla": u_zrodla, "doplata": doplata, "razem": u_zrodla + doplata,
            "netto": brutto - u_zrodla - doplata}


FORMULARZ = """
<div class="calc" id="kalkulator">
  <div class="tabs" role="tablist">
    <button type="button" class="on" data-t="zysk" role="tab">Sprzedaż akcji / ETF</button>
    <button type="button" data-t="dyw" role="tab">Dywidenda</button>
    <button type="button" data-t="lok" role="tab">Lokata i obligacje</button>
  </div>
  <div class="pane on" data-p="zysk">
    <label>Przychód ze sprzedaży<input inputmode="decimal" id="z_p" value="25000"><em>zł</em></label>
    <label>Koszt zakupu z prowizjami<input inputmode="decimal" id="z_k" value="15000"><em>zł</em></label>
    <label>Strata z poprzednich lat do odliczenia<input inputmode="decimal" id="z_s" value="0"><em>zł</em></label>
  </div>
  <div class="pane" data-p="dyw">
    <label>Dywidenda brutto<input inputmode="decimal" id="d_b" value="1000"><em>zł</em></label>
    <label>Skąd spółka
      <select id="d_k">
        <option value="0.19">Polska (GPW) — 19% pobiera broker</option>
        <option value="0.15" selected>USA z formularzem W-8BEN — 15% w USA</option>
        <option value="0.30">USA bez W-8BEN — 30% w USA</option>
        <option value="0">Kraj bez podatku u źródła</option>
      </select></label>
  </div>
  <div class="pane" data-p="lok">
    <label>Odsetki brutto<input inputmode="decimal" id="l_o" value="800"><em>zł</em></label>
  </div>
  <div class="out" aria-live="polite">
    <div><span>Podatek do zapłaty</span><b id="o_pod">{pod}</b></div>
    <div><span>Zostaje dla Ciebie</span><b id="o_net" class="up">{net}</b></div>
    <p id="o_opis">{opis}</p>
  </div>
</div>
<script>
(function(){
  var $=function(i){return document.getElementById(i)};
  var liczba=function(i){var v=parseFloat(($(i).value||'0').replace(/\\s/g,'').replace(',','.'));return isFinite(v)&&v>0?v:0};
  var zl=function(v){return v.toLocaleString('pl-PL',{minimumFractionDigits:2,maximumFractionDigits:2})+' zł'};
  var tryb='zysk';
  function licz(){
    var pod=0,net=0,opis='';
    if(tryb==='zysk'){
      var p=liczba('z_p'),k=liczba('z_k'),s=liczba('z_s');
      var doch=Math.max(0,p-k),podst=Math.round(doch-Math.min(s,doch));
      pod=Math.round(podst*0.19);net=p-k-pod;
      opis=doch>0?'Dochód '+zl(doch)+(s>0?', po odliczeniu straty podstawa '+zl(podst):'')+' × 19%. Rozliczasz w PIT-38 do 30 kwietnia.'
                 :'Strata '+zl(k-p)+' — podatku nie ma, a stratę odliczysz w kolejnych 5 latach.';
    }else if(tryb==='dyw'){
      var b=liczba('d_b'),z=parseFloat($('d_k').value);
      var u=b*z,d=Math.max(0,b*0.19-u);pod=u+d;net=b-pod;
      opis=z===0.19?'19% pobiera broker przy wypłacie — nic więcej nie robisz.'
          :z===0.30?'30% zabiera USA, w Polsce nic nie dopłacasz — ale 11% nadwyżki przepada. Podpisz W-8BEN.'
          :'Za granicą '+zl(u)+', w Polsce dopłata '+zl(d)+' w PIT-38.';
    }else{
      var o=liczba('l_o');pod=o*0.19;net=o-pod;opis='19% pobiera bank przy wypłacie odsetek.';
    }
    $('o_pod').textContent=zl(pod);$('o_net').textContent=zl(net);$('o_opis').textContent=opis;
  }
  document.querySelectorAll('#kalkulator .tabs button').forEach(function(b){
    b.addEventListener('click',function(){
      tryb=b.dataset.t;
      document.querySelectorAll('#kalkulator .tabs button').forEach(function(x){x.classList.toggle('on',x===b)});
      document.querySelectorAll('#kalkulator .pane').forEach(function(x){x.classList.toggle('on',x.dataset.p===tryb)});
      licz();
    });
  });
  document.querySelectorAll('#kalkulator input,#kalkulator select').forEach(function(i){i.addEventListener('input',licz)});
  licz();
})();
</script>
"""

CSS = """
.calc{margin-top:26px;background:var(--card);border:1px solid var(--border-2);border-radius:20px;padding:20px;
  box-shadow:0 24px 70px rgba(0,0,0,.35)}
.calc .tabs{display:flex;gap:6px;background:var(--elev);border:1px solid var(--border);border-radius:13px;padding:4px;
  flex-wrap:wrap}
.calc .tabs button{flex:1 1 auto;border:0;background:transparent;color:var(--muted);font:inherit;font-size:14px;
  font-weight:700;padding:9px 12px;border-radius:10px;cursor:pointer}
.calc .tabs button.on{background:var(--card-hi);color:var(--text);box-shadow:inset 0 0 0 1px var(--border-2)}
.calc .pane{display:none;margin-top:16px;gap:12px}
.calc .pane.on{display:grid}
.calc label{display:grid;gap:6px;font-size:13px;font-weight:700;color:var(--muted);position:relative}
.calc input,.calc select{background:var(--elev);border:1px solid var(--border-2);border-radius:11px;color:var(--text);
  font:inherit;font-size:17px;font-weight:700;padding:11px 44px 11px 13px;width:100%}
.calc select{font-size:15px;padding-right:13px}
.calc input:focus,.calc select:focus{outline:2px solid var(--green);outline-offset:1px}
.calc label em{position:absolute;right:14px;bottom:12px;font-style:normal;color:var(--dim);font-size:14px}
.calc .out{margin-top:18px;display:grid;grid-template-columns:1fr 1fr;gap:10px}
.calc .out div{background:var(--elev);border:1px solid var(--border);border-radius:13px;padding:14px}
.calc .out span{display:block;font-size:11.5px;font-weight:800;letter-spacing:.7px;text-transform:uppercase;color:var(--dim)}
.calc .out b{display:block;font-size:24px;font-weight:800;letter-spacing:-.6px;margin-top:6px}
.calc .out p{grid-column:1/-1;margin:0;font-size:13.5px;color:var(--muted)}
@media (max-width:560px){.calc .out{grid-template-columns:1fr}}
"""


def zbuduj() -> str:
    domyslny = podatek_od_zysku(25000, 15000)
    formularz = (FORMULARZ.replace("{pod}", _zl(domyslny["podatek"]))
                 .replace("{net}", _zl(domyslny["netto"]))
                 .replace("{opis}", "Dochód 10 000,00 zł × 19%. Rozliczasz w PIT-38 do 30 kwietnia."))

    przyklady = []
    for opis, p, k in (("Zysk 1 000 zł", 6000, 5000), ("Zysk 10 000 zł", 25000, 15000),
                       ("Zysk 50 000 zł", 150000, 100000), ("Strata 3 000 zł", 7000, 10000)):
        w = podatek_od_zysku(p, k)
        przyklady.append((opis, (_zl(p), "num"), (_zl(k), "num"),
                          (_zl(w["podatek"]), "down" if w["podatek"] else "num"),
                          (_zl(w["netto"]), "up" if w["netto"] >= 0 else "down")))
    dyw = []
    for opis, stawka in (("Spółka z GPW", 0.19), ("Spółka z USA, z W-8BEN", 0.15),
                         ("Spółka z USA, bez W-8BEN", 0.30)):
        w = podatek_od_dywidendy(1000, stawka)
        dyw.append((opis, (_zl(w["u_zrodla"]), "num"), (_zl(w["doplata"]), "num"),
                    (_zl(w["netto"]), "up")))

    bloki = [
        f"<section>{formularz}</section>",
        render.sekcja(
            "Ile wynosi podatek Belki w 2026 roku",
            "<strong>19% od zysku</strong> — tyle samo od zysku ze sprzedaży akcji, ETF-ów "
            "i obligacji, od dywidend i od odsetek z lokat. Zmienia się tylko to, kto go "
            "pobiera: przy dywidendzie z GPW i przy lokacie robi to broker albo bank, przy "
            "sprzedaży akcji rozliczasz się sam w zeznaniu PIT-38 do 30 kwietnia kolejnego roku.",
            "Podatek liczy się od <strong>dochodu</strong>, nie od przychodu: od ceny "
            "sprzedaży odejmujesz cenę zakupu i prowizje. Podstawę i sam podatek w PIT-38 "
            "zaokrągla się do pełnych złotych."),
        render.sekcja(
            "Przykłady: sprzedaż akcji",
            html_dodatkowy=render.tabela(
                ["Sytuacja", ("Przychód", True), ("Koszt", True), ("Podatek", True), ("Zostaje", True)],
                przyklady, "Podatek 19% od dochodu, bez straty z lat ubiegłych")),
        render.sekcja(
            "Przykłady: dywidenda 1000 zł",
            "Przy spółkach z USA broker pobiera podatek za granicą, a w Polsce dopłacasz "
            "różnicę do 19%. Bez formularza W-8BEN tracisz 11% dywidendy bezpowrotnie.",
            html_dodatkowy=render.tabela(
                ["Spółka", ("Podatek za granicą", True), ("Dopłata w PL", True), ("Zostaje", True)],
                dyw)),
        render.sekcja(
            "Jak odliczyć stratę z giełdy",
            "Stratę ze sprzedaży papierów wartościowych odliczasz od dochodu w kolejnych "
            "pięciu latach: co roku najwyżej połowę straty albo jednorazowo do 5 mln zł, "
            "a resztę na tej samej zasadzie połowy. Straty nie łączy się z dywidendami — "
            "te opodatkowane są osobno i odliczenie ich nie obniża.",
            lista=["<b>IKE</b> — zysk zwolniony z podatku Belki, jeśli wypłacasz po 60. roku życia.",
                   "<b>IKZE</b> — przy wypłacie po 65. roku życia 10% zryczałtowanego podatku zamiast 19%.",
                   "<b>PIT-8C</b> — polski broker wystawia go do końca lutego; zagraniczny "
                   "(np. Interactive Brokers) nie, wtedy liczysz sam z raportu rocznego."]),
    ]
    pary = [
        ("Ile wynosi podatek Belki?",
         "19% od zysku kapitałowego: ze sprzedaży akcji, ETF-ów i obligacji, z dywidend i z odsetek."),
        ("Do kiedy trzeba rozliczyć podatek od zysków z giełdy?",
         "Do 30 kwietnia roku następującego po sprzedaży, w zeznaniu PIT-38."),
        ("Jak liczy się podatek od sprzedaży akcji?",
         "Od dochodu: przychód ze sprzedaży minus koszt zakupu i prowizje. Od wyniku 19%, "
         "zaokrąglone do pełnych złotych."),
        ("Ile podatku od dywidendy z USA?",
         "Z formularzem W-8BEN 15% pobiera USA, a w Polsce dopłacasz 4%. Bez W-8BEN USA "
         "pobiera 30% i tej nadwyżki nie odzyskasz w polskim zeznaniu."),
        ("Czy można odliczyć stratę z giełdy?",
         "Tak, w kolejnych pięciu latach — do połowy straty rocznie albo jednorazowo do 5 mln zł."),
        ("Czy podatek Belki trzeba płacić na IKE?",
         "Nie, jeśli wypłacasz środki po 60. roku życia (lub po 55., gdy nabyłeś prawa emerytalne) "
         "i spełniasz warunki wpłat."),
    ]
    bloki.append(render.sekcja("Najczęstsze pytania", kotwica="pytania",
                               html_dodatkowy=render.faq(pary)))
    bloki.append(render.zacheta(
        "Niech Portevo policzy to za Ciebie",
        "Wgraj raport z XTB — Portevo policzy wynik każdej pozycji po prowizjach, spreadach "
        "i przewalutowaniu, a kalkulator dywidend pokaże, ile zostanie po podatku z każdej "
        "spółki w portfelu.",
        adres="/?zaloguj=1", etykieta="Załóż darmowe konto",
        drugi=("/", "Zobacz portfel pokazowy"),
        trzeci=("/dywidendy", "Dywidendy spółek")))
    bloki.append(render.sekcja(
        "Powiązane",
        html_dodatkowy=render.chipsy([
            ("/slownik/podatek-belki", "Podatek Belki — słownik"),
            ("/dywidendy/najwyzsze-stopy", "Najwyższe stopy dywidendy"),
            ("/portfel-inwestycyjny", "Portfel inwestycyjny"),
            ("/poradniki", "Poradniki"),
        ])))
    bloki.append('<div class="disclaimer"><p>Wyliczenie orientacyjne według zasad z 2026 r. '
                 'Portevo nie jest doradcą podatkowym — przy nietypowej sytuacji (kilku '
                 'brokerów, kryptowaluty, działalność) sprawdź zasady z doradcą.</p></div>')

    tytul = "Kalkulator podatku Belki 2026 — akcje, dywidendy, lokaty"
    opis = ("Policz podatek Belki od sprzedaży akcji i ETF, dywidendy z Polski i USA "
            "(W-8BEN) oraz odsetek. 19%, PIT-38, odliczanie straty — z przykładami.")
    okruchy = [("", "Kalkulator podatku Belki")]
    app = {"@context": "https://schema.org", "@type": "WebApplication",
           "name": "Kalkulator podatku Belki", "applicationCategory": "FinanceApplication",
           "operatingSystem": "Web", "inLanguage": "pl-PL",
           "offers": {"@type": "Offer", "price": "0", "priceCurrency": "PLN"},
           "url": site.absolute(SCIEZKA)}
    return render.strona(
        sciezka=SCIEZKA, tytul="Kalkulator podatku Belki 2026 — akcje i dywidendy | Portevo",
        opis=opis, h1="Kalkulator podatku Belki 2026",
        lead="Ile podatku zapłacisz od zysku z akcji, dywidendy albo lokaty — i ile zostanie "
             "dla Ciebie. Wpisz kwoty, wynik liczy się od razu.",
        nadtytul="Kalkulator · za darmo", okruchy=okruchy,
        aktualizacja=dates.dlugo(ZMIENIONO),
        bloki=bloki,
        jsonld=[jsonld.strona(SCIEZKA, tytul, opis), app, jsonld.okruchy(okruchy),
                jsonld.pytania(pary)])
