"""Katalog funduszy ETF dostępnych polskiemu inwestorowi.

Dlaczego lista jest wpisana ręcznie, a nie pobierana z jakiegoś API: żadne darmowe
źródło nie oddaje *filtrowalnego* uniwersum ETF-ów z podziałem na region i sektor.
Yahoo zna każdy fundusz z osobna, ale nie umie wylistować „wszystkie ETF-y na
biotechnologię w EUR". Dlatego etykiety trzymamy u siebie, a liczby — cenę, skład,
koszty, wyniki — dociągamy z Yahoo na żywo.

Wpis, którego Yahoo nie rozpozna, po prostu wypada z wyników (sprawdzane raz i
zapamiętywane), więc martwy ticker niczego nie psuje.

Pola:
  sym      — symbol w Yahoo (z sufiksem giełdy)
  name     — nazwa skrócona, taka jaką widzi użytkownik
  region   — jeden z REGIONS
  sector   — jeden z SECTORS
  asset    — equity | bond | commodity | crypto | mixed
  cur      — waluta notowania
  acc      — True = akumulujący (dywidendy zostają w funduszu), False = wypłacający
  note     — jedno zdanie po ludzku: co ten fundusz właściwie robi
"""

# --------------------------------------------------------------- słowniki

REGIONS = [
    {"id": "world", "label": "Cały świat", "desc": "Fundusz kupuje spółki z całego globu naraz — najszersza możliwa dywersyfikacja."},
    {"id": "usa", "label": "USA", "desc": "Rynek amerykański: największy i najbardziej płynny, ale też cała ekspozycja na dolara."},
    {"id": "europe", "label": "Europa", "desc": "Spółki europejskie — więcej przemysłu i banków, mniej wielkiej technologii niż w USA."},
    {"id": "poland", "label": "Polska", "desc": "GPW — brak ryzyka walutowego, ale rynek mały i mocno zależny od kilku spółek."},
    {"id": "em", "label": "Rynki wschodzące", "desc": "Chiny, Indie, Brazylia, Tajwan i podobne — wyższy potencjał i wyraźnie wyższe wahania."},
    {"id": "asia", "label": "Azja i Pacyfik", "desc": "Rozwinięta Azja: Japonia, Korea, Australia, Tajwan."},
    {"id": "exus", "label": "Świat bez USA", "desc": "Dla kogoś, kto ma już dużo Ameryki i chce dołożyć resztę świata."},
]

SECTORS = [
    {"id": "broad", "label": "Szeroki rynek", "desc": "Bez wybierania branż — fundusz kupuje po prostu cały rynek."},
    {"id": "tech", "label": "Technologia", "desc": "Oprogramowanie, sprzęt, internet. Rośnie szybciej niż rynek, ale i mocniej spada."},
    {"id": "semis", "label": "Półprzewodniki", "desc": "Producenci układów scalonych — najbardziej cykliczna część technologii."},
    {"id": "ai", "label": "Sztuczna inteligencja", "desc": "Spółki budujące i sprzedające AI. Wąski koszyk, bardzo zmienny."},
    {"id": "biotech", "label": "Biotechnologia", "desc": "Firmy pracujące nad lekami. Wynik zależy od wyników badań klinicznych, nie od gospodarki."},
    {"id": "health", "label": "Ochrona zdrowia", "desc": "Farmacja, sprzęt medyczny, ubezpieczyciele zdrowotni — defensywna branża."},
    {"id": "finance", "label": "Finanse", "desc": "Banki i ubezpieczyciele. Zarabiają na wysokich stopach procentowych."},
    {"id": "energy", "label": "Energia", "desc": "Ropa, gaz i usługi wydobywcze — chodzą za surowcem, nie za giełdą."},
    {"id": "clean", "label": "Zielona energia", "desc": "OZE i elektromobilność. Wrażliwe na stopy procentowe i politykę."},
    {"id": "defence", "label": "Obronność", "desc": "Zbrojeniówka i lotnictwo — napędzane budżetami państw."},
    {"id": "realestate", "label": "Nieruchomości", "desc": "Fundusze REIT: wynajem powierzchni, wysokie dywidendy, czułość na stopy."},
    {"id": "gold", "label": "Złoto i metale", "desc": "Zabezpieczenie na czasy, gdy giełdy i waluty tracą zaufanie."},
    {"id": "commodity", "label": "Surowce", "desc": "Koszyk towarów: energia, metale, rolnictwo. Zachowuje się inaczej niż akcje."},
    {"id": "dividend", "label": "Dywidendowe", "desc": "Spółki regularnie dzielące się zyskiem — spokojniejsze, wolniej rosnące."},
    {"id": "small", "label": "Małe spółki", "desc": "Mniejsze firmy: więcej miejsca na wzrost, więcej ryzyka bankructwa."},
    {"id": "bond", "label": "Obligacje", "desc": "Dług państw i firm — najspokojniejsza część portfela, hamuje spadki."},
    {"id": "crypto", "label": "Kryptowaluty", "desc": "Ekspozycja na bitcoina i ethereum przez giełdę. Skrajnie zmienne."},
]

ASSETS = [
    {"id": "equity", "label": "Akcje"},
    {"id": "bond", "label": "Obligacje"},
    {"id": "commodity", "label": "Surowce"},
    {"id": "crypto", "label": "Krypto"},
    {"id": "mixed", "label": "Mieszane"},
]

# ----------------------------------------------------------------- kraje
#
# Yahoo NIE podaje dla ETF-ów rozbicia geograficznego. Da się je jednak wyliczyć
# z samych pozycji: sufiks tickera mówi, na której giełdzie spółka jest notowana.
# „8035.T" to Tokio, „NVDA" bez sufiksu to USA. To nie jest to samo co kraj
# przychodów, ale dokładnie to, co widzi inwestor — i dlatego w aplikacji piszemy
# wprost, że liczymy z największych pozycji.

SUFFIX_COUNTRY = {
    "": "US", "T": "JP", "HK": "HK", "SS": "CN", "SZ": "CN", "TW": "TW",
    "KS": "KR", "KQ": "KR", "L": "GB", "IL": "GB", "DE": "DE", "F": "DE",
    "PA": "FR", "AS": "NL", "MI": "IT", "MC": "ES", "SW": "CH", "VX": "CH",
    "ST": "SE", "CO": "DK", "OL": "NO", "HE": "FI", "BR": "BE", "LS": "PT",
    "VI": "AT", "IR": "IE", "WA": "PL", "PR": "CZ", "BD": "HU", "AT": "GR",
    "TO": "CA", "V": "CA", "NE": "CA", "AX": "AU", "NZ": "NZ",
    "SA": "BR", "MX": "MX", "BA": "AR", "SN": "CL",
    "NS": "IN", "BO": "IN", "JK": "ID", "KL": "MY", "SI": "SG", "BK": "TH",
    "JO": "ZA", "TA": "IL", "SR": "SA", "IS": "TR", "CA": "EG", "QA": "QA",
}

COUNTRY = {
    "US": ("USA", "🇺🇸"), "JP": ("Japonia", "🇯🇵"), "GB": ("Wielka Brytania", "🇬🇧"),
    "DE": ("Niemcy", "🇩🇪"), "FR": ("Francja", "🇫🇷"), "NL": ("Holandia", "🇳🇱"),
    "CH": ("Szwajcaria", "🇨🇭"), "IT": ("Włochy", "🇮🇹"), "ES": ("Hiszpania", "🇪🇸"),
    "SE": ("Szwecja", "🇸🇪"), "DK": ("Dania", "🇩🇰"), "NO": ("Norwegia", "🇳🇴"),
    "FI": ("Finlandia", "🇫🇮"), "BE": ("Belgia", "🇧🇪"), "PT": ("Portugalia", "🇵🇹"),
    "AT": ("Austria", "🇦🇹"), "IE": ("Irlandia", "🇮🇪"), "PL": ("Polska", "🇵🇱"),
    "CZ": ("Czechy", "🇨🇿"), "HU": ("Węgry", "🇭🇺"), "GR": ("Grecja", "🇬🇷"),
    "CA": ("Kanada", "🇨🇦"), "AU": ("Australia", "🇦🇺"), "NZ": ("Nowa Zelandia", "🇳🇿"),
    "CN": ("Chiny", "🇨🇳"), "HK": ("Hongkong", "🇭🇰"), "TW": ("Tajwan", "🇹🇼"),
    "KR": ("Korea Płd.", "🇰🇷"), "IN": ("Indie", "🇮🇳"), "ID": ("Indonezja", "🇮🇩"),
    "MY": ("Malezja", "🇲🇾"), "SG": ("Singapur", "🇸🇬"), "TH": ("Tajlandia", "🇹🇭"),
    "BR": ("Brazylia", "🇧🇷"), "MX": ("Meksyk", "🇲🇽"), "AR": ("Argentyna", "🇦🇷"),
    "CL": ("Chile", "🇨🇱"), "ZA": ("RPA", "🇿🇦"), "IL": ("Izrael", "🇮🇱"),
    "SA": ("Arabia Saud.", "🇸🇦"), "TR": ("Turcja", "🇹🇷"), "EG": ("Egipt", "🇪🇬"),
    "QA": ("Katar", "🇶🇦"),
}


def country_of(symbol: str) -> str:
    """Kod kraju z sufiksu giełdowego. Pusty symbol albo nieznany sufiks → pusto."""
    s = (symbol or "").strip().upper()
    if not s:
        return ""
    suffix = s.rsplit(".", 1)[1] if "." in s else ""
    code = SUFFIX_COUNTRY.get(suffix)
    # brak sufiksu to notowanie w USA, ale tylko gdy symbol wygląda jak ticker
    return code or ""


def country_label(code: str) -> tuple:
    return COUNTRY.get(code, (code or "Nieznany", "🏳"))


# --------------------------------------------------------------- katalog

E = "equity"
B = "bond"
C = "commodity"
K = "crypto"

CATALOG: list[dict] = [
    # ---------------- świat, szeroki rynek
    {"sym": "VWCE.DE", "name": "Vanguard FTSE All-World", "region": "world", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Około 3600 spółek z całego świata w jednym zleceniu — najpopularniejszy „jeden fundusz na wszystko”."},
    {"sym": "IWDA.AS", "name": "iShares Core MSCI World", "region": "world", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Rynki rozwinięte, bez rynków wschodzących. Klasyk portfeli pasywnych."},
    {"sym": "SWRD.L", "name": "SPDR MSCI World", "region": "world", "sector": "broad",
     "asset": E, "cur": "USD", "acc": True,
     "note": "To samo co MSCI World, ale z niższą opłatą roczną."},
    {"sym": "EUNL.DE", "name": "iShares Core MSCI World (Xetra)", "region": "world", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Ten sam fundusz co IWDA, notowany we Frankfurcie — wygodniejszy przy rachunku w euro."},
    {"sym": "ISAC.L", "name": "iShares MSCI ACWI", "region": "world", "sector": "broad",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Rynki rozwinięte i wschodzące razem, w jednym koszyku."},
    {"sym": "IWMO.L", "name": "iShares Edge MSCI World Momentum", "region": "world", "sector": "broad",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Kupuje to, co ostatnio rosło najmocniej. Działa świetnie w trendzie, boleśnie przy zwrocie."},
    {"sym": "IWQU.L", "name": "iShares Edge MSCI World Quality", "region": "world", "sector": "broad",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Filtr jakości: stabilne zyski, niskie zadłużenie. Spokojniejszy przebieg niż szeroki rynek."},
    {"sym": "IUSN.DE", "name": "iShares MSCI World Small Cap", "region": "world", "sector": "small",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Małe spółki z całego świata — historycznie wyższy zwrot kosztem większych wahań."},

    # ---------------- USA
    {"sym": "CSPX.L", "name": "iShares Core S&P 500", "region": "usa", "sector": "broad",
     "asset": E, "cur": "USD", "acc": True,
     "note": "500 największych spółek amerykańskich. Punkt odniesienia dla całego rynku."},
    {"sym": "SXR8.DE", "name": "iShares Core S&P 500 (Xetra)", "region": "usa", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "S&P 500 kupowany za euro — waluta rozliczenia inna, ryzyko dolara to samo."},
    {"sym": "VUAA.L", "name": "Vanguard S&P 500", "region": "usa", "sector": "broad",
     "asset": E, "cur": "USD", "acc": True,
     "note": "S&P 500 od Vanguarda, akumulujący. Jedna z najniższych opłat na rynku."},
    {"sym": "CNDX.L", "name": "iShares Nasdaq 100", "region": "usa", "sector": "tech",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Sto największych spółek technologicznych z Nasdaq. Mocno skoncentrowany na kilku gigantach."},
    {"sym": "SXRV.DE", "name": "iShares Nasdaq 100 (Xetra)", "region": "usa", "sector": "tech",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Nasdaq 100 rozliczany w euro."},
    {"sym": "IUIT.L", "name": "iShares S&P 500 Technology", "region": "usa", "sector": "tech",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Wyłącznie sektor technologiczny z indeksu S&P 500."},
    {"sym": "IUHC.L", "name": "iShares S&P 500 Health Care", "region": "usa", "sector": "health",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Ochrona zdrowia z S&P 500 — branża, która najmniej reaguje na spowolnienie."},
    {"sym": "IUFS.L", "name": "iShares S&P 500 Financials", "region": "usa", "sector": "finance",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Amerykańskie banki i ubezpieczyciele."},
    {"sym": "IESU.L", "name": "iShares S&P 500 Energy", "region": "usa", "sector": "energy",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Sektor naftowo-gazowy z S&P 500."},
    {"sym": "IUVL.L", "name": "iShares MSCI USA Value Factor", "region": "usa", "sector": "broad",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Tańsza wycenowo część rynku USA — mniej technologii, więcej przemysłu i finansów."},
    {"sym": "R2US.L", "name": "SPDR Russell 2000 US Small Cap", "region": "usa", "sector": "small",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Dwa tysiące małych spółek amerykańskich."},
    {"sym": "IDVY.L", "name": "iShares Euro Dividend", "region": "europe", "sector": "dividend",
     "asset": E, "cur": "GBP", "acc": False,
     "note": "Trzydzieści europejskich spółek o najwyższej stopie dywidendy."},
    {"sym": "VHYL.L", "name": "Vanguard FTSE All-World High Dividend", "region": "world", "sector": "dividend",
     "asset": E, "cur": "GBP", "acc": False,
     "note": "Spółki dywidendowe z całego świata — regularna wypłata zamiast reinwestycji."},
    {"sym": "ISPA.DE", "name": "iShares STOXX Global Select Dividend 100", "region": "world", "sector": "dividend",
     "asset": E, "cur": "EUR", "acc": False,
     "note": "Setka najhojniej dzielących się zyskiem spółek świata."},
    {"sym": "XDWD.DE", "name": "Xtrackers MSCI World", "region": "world", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Alternatywa dla iShares Core MSCI World, ta sama ekspozycja u innego dostawcy."},
    {"sym": "DBXJ.DE", "name": "Xtrackers MSCI Japan", "region": "asia", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Japonia rozliczana w euro."},

    # ---------------- Europa
    {"sym": "MEUD.PA", "name": "Lyxor Core STOXX Europe 600", "region": "europe", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Sześćset największych spółek europejskich — odpowiednik S&P 500 dla Europy."},
    {"sym": "EXSA.DE", "name": "iShares STOXX Europe 600", "region": "europe", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": False,
     "note": "Szeroki rynek europejski z wypłatą dywidendy."},
    {"sym": "EXV1.DE", "name": "iShares STOXX Europe 600 Banks", "region": "europe", "sector": "finance",
     "asset": E, "cur": "EUR", "acc": False,
     "note": "Wyłącznie europejskie banki — bardzo cykliczne, mocno reagują na stopy."},
    {"sym": "ESIT.L", "name": "iShares MSCI Europe Information Technology", "region": "europe", "sector": "tech",
     "asset": E, "cur": "GBP", "acc": True,
     "note": "Europejska technologia — inny zestaw firm niż amerykańska, m.in. ASML i SAP."},

    # ---------------- Polska
    {"sym": "ETFBW20TR.WA", "name": "Beta ETF WIG20TR", "region": "poland", "sector": "broad",
     "asset": E, "cur": "PLN", "acc": True,
     "note": "Dwadzieścia największych spółek z GPW, z uwzględnieniem dywidend. Bez ryzyka walutowego."},
    {"sym": "ETFBM40TR.WA", "name": "Beta ETF mWIG40TR", "region": "poland", "sector": "broad",
     "asset": E, "cur": "PLN", "acc": True,
     "note": "Średnie spółki z GPW — historycznie lepszy wynik niż WIG20, przy większych wahaniach."},
    {"sym": "ETFBS80TR.WA", "name": "Beta ETF sWIG80TR", "region": "poland", "sector": "small",
     "asset": E, "cur": "PLN", "acc": True,
     "note": "Małe spółki warszawskiej giełdy."},
    {"sym": "ETFBTBSP.WA", "name": "Beta ETF TBSP (obligacje skarbowe)", "region": "poland", "sector": "bond",
     "asset": B, "cur": "PLN", "acc": True,
     "note": "Polskie obligacje skarbowe o stałym oprocentowaniu — najspokojniejsza pozycja w portfelu złotowym."},
    {"sym": "ETFBWTECH.WA", "name": "Beta ETF WIGtech", "region": "poland", "sector": "tech",
     "asset": E, "cur": "PLN", "acc": True,
     "note": "Polskie spółki technologiczne i gamingowe."},

    # ---------------- rynki wschodzące i Azja
    {"sym": "EIMI.L", "name": "iShares Core MSCI EM IMI", "region": "em", "sector": "broad",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Ponad trzy tysiące spółek z rynków wschodzących, łącznie z małymi."},
    {"sym": "IS3N.DE", "name": "iShares Core MSCI EM IMI (Xetra)", "region": "em", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Ten sam fundusz co EIMI, notowany we Frankfurcie."},
    {"sym": "FLXI.DE", "name": "Franklin FTSE India", "region": "em", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Wyłącznie Indie — najszybciej rosnąca duża gospodarka świata."},
    {"sym": "CNYA.L", "name": "iShares MSCI China A", "region": "em", "sector": "broad",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Chińskie spółki notowane na giełdach kontynentalnych."},
    {"sym": "IJPA.L", "name": "iShares Core MSCI Japan IMI", "region": "asia", "sector": "broad",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Szeroki rynek japoński."},
    {"sym": "IPRP.L", "name": "iShares European Property Yield", "region": "europe", "sector": "realestate",
     "asset": E, "cur": "GBP", "acc": False,
     "note": "Europejskie spółki nieruchomościowe wypłacające czynsze w formie dywidendy."},

    # ---------------- świat bez USA
    {"sym": "EXUS.L", "name": "Amundi Prime Global ex-US", "region": "exus", "sector": "broad",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Cały świat z pominięciem Ameryki — dla kogoś, kto ma już dużo USA."},
    {"sym": "IEUX.L", "name": "iShares MSCI Europe ex-UK", "region": "europe", "sector": "broad",
     "asset": E, "cur": "GBP", "acc": False,
     "note": "Europa kontynentalna bez Wielkiej Brytanii."},

    # ---------------- branże wąskie
    {"sym": "XAIX.DE", "name": "Xtrackers AI & Big Data", "region": "world", "sector": "ai",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Spółki zarabiające na sztucznej inteligencji i przetwarzaniu danych."},
    {"sym": "WTAI.L", "name": "WisdomTree AI & Innovation", "region": "world", "sector": "ai",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Wąski koszyk firm budujących modele i infrastrukturę AI."},
    {"sym": "SMH.L", "name": "VanEck Semiconductor", "region": "world", "sector": "semis",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Największe firmy półprzewodnikowe świata — sedno boomu na AI i najbardziej cykliczna branża technologii."},
    {"sym": "CHIP.L", "name": "iShares MSCI Global Semiconductors", "region": "world", "sector": "semis",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Szerszy koszyk producentów układów scalonych."},
    {"sym": "BTEC.L", "name": "iShares Nasdaq US Biotechnology", "region": "usa", "sector": "biotech",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Amerykańska biotechnologia — kursy chodzą za wynikami badań, nie za gospodarką."},
    {"sym": "WCBR.L", "name": "WisdomTree Cybersecurity", "region": "world", "sector": "tech",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Spółki od cyberbezpieczeństwa — wydatki na ochronę rosną niezależnie od koniunktury."},
    {"sym": "HEAL.L", "name": "iShares Healthcare Innovation", "region": "world", "sector": "health",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Firmy zmieniające sposób leczenia: genetyka, robotyka chirurgiczna, cyfrowa medycyna."},
    {"sym": "ASWC.DE", "name": "VanEck Defense", "region": "world", "sector": "defence",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Przemysł zbrojeniowy NATO — rośnie z budżetami obronnymi państw."},
    {"sym": "INRG.L", "name": "iShares Global Clean Energy", "region": "world", "sector": "clean",
     "asset": E, "cur": "GBP", "acc": True,
     "note": "Energia odnawialna. Bardzo wrażliwa na stopy procentowe i decyzje polityczne."},
    {"sym": "DH2O.L", "name": "iShares Global Water", "region": "world", "sector": "clean",
     "asset": E, "cur": "USD", "acc": False,
     "note": "Infrastruktura wodna — nudna, powtarzalna, słabo skorelowana z technologią."},
    {"sym": "LOCK.L", "name": "iShares Digital Security", "region": "world", "sector": "tech",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Cyberbezpieczeństwo i ochrona tożsamości cyfrowej."},
    {"sym": "IWDP.L", "name": "iShares Developed Markets Property", "region": "world", "sector": "realestate",
     "asset": E, "cur": "GBP", "acc": False,
     "note": "Nieruchomości komercyjne z rynków rozwiniętych, w formie REIT-ów."},

    # ---------------- surowce i złoto
    {"sym": "SGLN.L", "name": "iShares Physical Gold", "region": "world", "sector": "gold",
     "asset": C, "cur": "GBP", "acc": True,
     "note": "Fizyczne złoto w sztabach w skarbcu. Klasyczne zabezpieczenie portfela."},
    {"sym": "4GLD.DE", "name": "Xetra-Gold", "region": "europe", "sector": "gold",
     "asset": C, "cur": "EUR", "acc": True,
     "note": "Złoto rozliczane w euro, z prawem do fizycznej dostawy."},
    {"sym": "SSLN.L", "name": "iShares Physical Silver", "region": "world", "sector": "gold",
     "asset": C, "cur": "GBP", "acc": True,
     "note": "Srebro — bardziej przemysłowe i dużo bardziej zmienne niż złoto."},
    {"sym": "CMOD.L", "name": "iShares Diversified Commodity Swap", "region": "world", "sector": "commodity",
     "asset": C, "cur": "USD", "acc": True,
     "note": "Koszyk surowców: energia, metale, rolnictwo. Osłona przed inflacją."},

    # ---------------- obligacje
    {"sym": "IBTA.L", "name": "iShares $ Treasury Bond 1-3yr", "region": "usa", "sector": "bond",
     "asset": B, "cur": "USD", "acc": False,
     "note": "Krótkie obligacje skarbu USA — najbliższa gotówce forma inwestycji w dolarze."},
    {"sym": "IBTM.L", "name": "iShares $ Treasury Bond 7-10yr", "region": "usa", "sector": "bond",
     "asset": B, "cur": "GBP", "acc": False,
     "note": "Średnioterminowy dług USA. Rośnie, gdy rynek boi się recesji."},
    {"sym": "IEAC.L", "name": "iShares Core € Corp Bond", "region": "europe", "sector": "bond",
     "asset": B, "cur": "EUR", "acc": False,
     "note": "Obligacje dużych firm europejskich o wysokim ratingu."},
    {"sym": "AGGH.L", "name": "iShares Global Aggregate Bond", "region": "world", "sector": "bond",
     "asset": B, "cur": "USD", "acc": True,
     "note": "Cały światowy rynek długu w jednym funduszu, z zabezpieczeniem walutowym."},

    # ---------------- krypto
    {"sym": "BTCE.DE", "name": "ETC Group Physical Bitcoin", "region": "world", "sector": "crypto",
     "asset": K, "cur": "EUR", "acc": True,
     "note": "Bitcoin kupowany przez zwykły rachunek maklerski. Zmienność wielokrotnie wyższa niż akcji."},
    {"sym": "ZETH.DE", "name": "21Shares Ethereum", "region": "world", "sector": "crypto",
     "asset": K, "cur": "EUR", "acc": True,
     "note": "Ethereum w formie papieru wartościowego."},
]


# ------------------------------------------------------------------------
# Druga partia — dołożona po tym, jak katalog okazał się za wąski przy szukaniu
# konkretnego funduszu. Każdy ticker sprawdzony w Yahoo przed wpisaniem.
# ------------------------------------------------------------------------

CATALOG += [
    # ---------------- świat, szeroki rynek
    {"sym": "SPYY.DE", "name": "SPDR MSCI All Country World", "region": "world", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Rynki rozwinięte i wschodzące w jednym funduszu, taniej niż u konkurencji."},
    {"sym": "VWRL.L", "name": "Vanguard FTSE All-World (wypłacający)", "region": "world", "sector": "broad",
     "asset": E, "cur": "GBP", "acc": False,
     "note": "To samo co VWCE, ale dywidendy wypłaca na rachunek zamiast reinwestować."},
    {"sym": "VEVE.L", "name": "Vanguard FTSE Developed World", "region": "world", "sector": "broad",
     "asset": E, "cur": "GBP", "acc": False,
     "note": "Rynki rozwinięte od Vanguarda, z wypłatą dywidendy."},
    {"sym": "WSML.L", "name": "iShares MSCI World Small Cap", "region": "world", "sector": "small",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Małe spółki z rynków rozwiniętych — inne ryzyko i inny cykl niż wielkie koncerny."},
    {"sym": "XDEM.DE", "name": "Xtrackers MSCI World Momentum", "region": "world", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Stawia na spółki, które ostatnio rosły najszybciej. Świetne w trendzie, bolesne przy zwrocie."},
    {"sym": "XDEQ.DE", "name": "Xtrackers MSCI World Quality", "region": "world", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Filtr jakości: wysoka rentowność, niskie zadłużenie, stabilne zyski."},
    {"sym": "XDEV.DE", "name": "Xtrackers MSCI World Value", "region": "world", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Tania wycenowo połowa świata — mniej technologii, więcej przemysłu i banków."},
    {"sym": "JPGL.L", "name": "JPM Global Equity Multi-Factor", "region": "world", "sector": "broad",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Łączy kilka strategii naraz: wartość, jakość i momentum."},
    {"sym": "IWVL.L", "name": "iShares MSCI World Value Factor", "region": "world", "sector": "broad",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Spółki notowane poniżej wartości księgowej i z niskimi wskaźnikami wyceny."},

    # ---------------- USA
    {"sym": "VUSA.L", "name": "Vanguard S&P 500 (wypłacający)", "region": "usa", "sector": "broad",
     "asset": E, "cur": "GBP", "acc": False,
     "note": "S&P 500 z kwartalną wypłatą dywidendy."},
    {"sym": "SPY5.L", "name": "SPDR S&P 500", "region": "usa", "sector": "broad",
     "asset": E, "cur": "USD", "acc": True,
     "note": "S&P 500 od State Street, jeden z najtańszych na rynku."},
    {"sym": "IUSA.L", "name": "iShares Core S&P 500 (wypłacający)", "region": "usa", "sector": "broad",
     "asset": E, "cur": "GBP", "acc": False,
     "note": "Wersja S&P 500 wypłacająca dywidendę na rachunek."},
    {"sym": "EQQQ.L", "name": "Invesco EQQQ Nasdaq-100", "region": "usa", "sector": "tech",
     "asset": E, "cur": "GBP", "acc": False,
     "note": "Najstarszy europejski fundusz na Nasdaq 100."},
    {"sym": "QDVE.DE", "name": "iShares S&P 500 Technology (Xetra)", "region": "usa", "sector": "tech",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Sektor technologiczny z S&P 500, rozliczany w euro."},
    {"sym": "IUMO.L", "name": "iShares MSCI USA Momentum Factor", "region": "usa", "sector": "broad",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Amerykańskie spółki w najsilniejszym trendzie wzrostowym."},
    {"sym": "XMUS.DE", "name": "Xtrackers MSCI USA", "region": "usa", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Szeroki rynek amerykański, ponad 600 spółek."},
    {"sym": "MOAT.L", "name": "VanEck Morningstar Wide Moat", "region": "usa", "sector": "broad",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Spółki z trwałą przewagą konkurencyjną — takie, których nie da się łatwo podgryźć."},

    # ---------------- branże świata
    {"sym": "XDWT.DE", "name": "Xtrackers MSCI World Technology", "region": "world", "sector": "tech",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Technologia z całego świata, nie tylko amerykańska."},
    {"sym": "XDWH.DE", "name": "Xtrackers MSCI World Health Care", "region": "world", "sector": "health",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Globalna ochrona zdrowia — najbardziej defensywna branża świata."},
    {"sym": "XDWF.DE", "name": "Xtrackers MSCI World Financials", "region": "world", "sector": "finance",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Banki i ubezpieczyciele z rynków rozwiniętych."},
    {"sym": "XDWI.DE", "name": "Xtrackers MSCI World Industrials", "region": "world", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Przemysł: maszyny, lotnictwo, transport, budownictwo."},

    # ---------------- tematyczne
    {"sym": "RBOT.L", "name": "iShares Automation & Robotics", "region": "world", "sector": "ai",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Automatyzacja i robotyka — spółki zastępujące pracę ludzką maszynami."},
    {"sym": "ECAR.L", "name": "iShares Electric Vehicles", "region": "world", "sector": "clean",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Elektromobilność: producenci aut, baterii i surowców do nich."},
    {"sym": "DGTL.L", "name": "iShares Digitalisation", "region": "world", "sector": "tech",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Cyfryzacja gospodarki — chmura, płatności, e-commerce."},
    {"sym": "AGED.L", "name": "iShares Ageing Population", "region": "world", "sector": "health",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Spółki zarabiające na starzeniu się społeczeństw. Trend, którego nic nie odwróci."},
    {"sym": "ESPO.L", "name": "VanEck Video Gaming & eSports", "region": "world", "sector": "tech",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Gry i esport — producenci, wydawcy i twórcy sprzętu."},
    {"sym": "NUKL.DE", "name": "VanEck Uranium & Nuclear", "region": "world", "sector": "energy",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Uran i energetyka jądrowa — wraca do łask razem z zapotrzebowaniem centrów danych."},
    {"sym": "GDX.L", "name": "VanEck Gold Miners", "region": "world", "sector": "gold",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Kopalnie złota. Chodzą jak złoto, tylko mocniej — w obie strony."},
    {"sym": "INFR.L", "name": "iShares Global Infrastructure", "region": "world", "sector": "realestate",
     "asset": E, "cur": "GBP", "acc": False,
     "note": "Drogi, lotniska, sieci przesyłowe — przewidywalne przepływy i wysokie dywidendy."},
    {"sym": "IH2O.L", "name": "iShares Global Water", "region": "world", "sector": "clean",
     "asset": E, "cur": "GBP", "acc": False,
     "note": "Infrastruktura wodna: uzdatnianie, przesył, liczniki."},
    {"sym": "LIFE.L", "name": "Rize Environmental Impact 100", "region": "world", "sector": "clean",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Sto spółek o najniższym wpływie środowiskowym w swoich branżach."},

    # ---------------- rynki wschodzące i Azja
    {"sym": "VFEM.L", "name": "Vanguard FTSE Emerging Markets", "region": "em", "sector": "broad",
     "asset": E, "cur": "GBP", "acc": False,
     "note": "Rynki wschodzące od Vanguarda, z wypłatą dywidendy."},
    {"sym": "VDEM.L", "name": "Vanguard FTSE EM (USD)", "region": "em", "sector": "broad",
     "asset": E, "cur": "USD", "acc": False,
     "note": "Ten sam fundusz rozliczany w dolarze."},
    {"sym": "IEMA.L", "name": "iShares MSCI EM", "region": "em", "sector": "broad",
     "asset": E, "cur": "USD", "acc": True,
     "note": "Duże i średnie spółki rynków wschodzących, bez małych."},
    {"sym": "XMME.DE", "name": "Xtrackers MSCI Emerging Markets", "region": "em", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Rynki wschodzące rozliczane w euro."},
    {"sym": "FLXC.DE", "name": "Franklin FTSE China", "region": "em", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Chiny w najtańszej dostępnej formie."},
    {"sym": "FLXK.DE", "name": "Franklin FTSE Korea", "region": "asia", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Korea Południowa — Samsung, Hyundai, SK Hynix."},

    # ---------------- Europa
    {"sym": "CEU.L", "name": "iShares Core MSCI EMU", "region": "europe", "sector": "broad",
     "asset": E, "cur": "EUR", "acc": True,
     "note": "Strefa euro bez Wielkiej Brytanii i Szwajcarii — czysta ekspozycja na euro."},
    {"sym": "IEFM.L", "name": "iShares MSCI Europe Momentum", "region": "europe", "sector": "broad",
     "asset": E, "cur": "GBP", "acc": True,
     "note": "Europejskie spółki w najsilniejszym trendzie."},
    {"sym": "IEUR.L", "name": "iShares FTSEurofirst 80", "region": "europe", "sector": "broad",
     "asset": E, "cur": "GBP", "acc": False,
     "note": "Osiemdziesiąt największych spółek strefy euro."},

    # ---------------- obligacje
    {"sym": "IB01.L", "name": "iShares $ Treasury Bond 0-1yr", "region": "usa", "sector": "bond",
     "asset": B, "cur": "USD", "acc": True,
     "note": "Bony skarbowe USA — najbliżej gotówki, jak się da w dolarze."},
    {"sym": "IEGA.L", "name": "iShares Core € Govt Bond", "region": "europe", "sector": "bond",
     "asset": B, "cur": "EUR", "acc": False,
     "note": "Obligacje skarbowe państw strefy euro."},
    {"sym": "IHYG.L", "name": "iShares € High Yield Corp Bond", "region": "europe", "sector": "bond",
     "asset": B, "cur": "EUR", "acc": False,
     "note": "Dług firm o niższym ratingu — wyższe odsetki, realne ryzyko niewypłacalności."},
    {"sym": "ERNS.L", "name": "iShares £ Ultrashort Bond", "region": "europe", "sector": "bond",
     "asset": B, "cur": "GBP", "acc": False,
     "note": "Bardzo krótki dług w funtach — parking na gotówkę."},

    # ---------------- surowce
    {"sym": "SGLD.L", "name": "Invesco Physical Gold", "region": "world", "sector": "gold",
     "asset": C, "cur": "USD", "acc": True,
     "note": "Fizyczne złoto, jeden z najtańszych funduszy złota w Europie."},
    {"sym": "IGLN.L", "name": "iShares Physical Gold (USD)", "region": "world", "sector": "gold",
     "asset": C, "cur": "USD", "acc": True,
     "note": "Złoto w sztabach, notowanie w dolarze."},
    {"sym": "PHAU.L", "name": "WisdomTree Physical Gold", "region": "world", "sector": "gold",
     "asset": C, "cur": "USD", "acc": True,
     "note": "Kolejny fundusz na fizyczne złoto — warto porównać opłatę roczną."},
    {"sym": "SLVP.L", "name": "Invesco Physical Silver", "region": "world", "sector": "gold",
     "asset": C, "cur": "GBP", "acc": True,
     "note": "Srebro fizyczne. Bardziej przemysłowe i dużo bardziej zmienne niż złoto."},
    {"sym": "CRUD.L", "name": "WisdomTree WTI Crude Oil", "region": "world", "sector": "commodity",
     "asset": C, "cur": "USD", "acc": True,
     "note": "Ropa WTI przez kontrakty terminowe. Do krótkiej gry, nie do trzymania latami."},

    # ---------------- Polska
    {"sym": "ETFBSPXPL.WA", "name": "Beta ETF S&P 500 PLN-Hedged", "region": "poland", "sector": "broad",
     "asset": E, "cur": "PLN", "acc": True,
     "note": "S&P 500 z zabezpieczeniem walutowym — wynik zależy od giełdy, nie od kursu dolara."},
    {"sym": "ETFBNDXPL.WA", "name": "Beta ETF Nasdaq-100 PLN-Hedged", "region": "poland", "sector": "tech",
     "asset": E, "cur": "PLN", "acc": True,
     "note": "Nasdaq 100 bez ryzyka kursowego, kupowany za złotówki na GPW."},
]

BY_SYMBOL = {e["sym"]: e for e in CATALOG}

REGION_LABEL = {r["id"]: r["label"] for r in REGIONS}
SECTOR_LABEL = {s["id"]: s["label"] for s in SECTORS}
ASSET_LABEL = {a["id"]: a["label"] for a in ASSETS}


# ------------------------------------------------- polskie ETF-y (skład)
#
# Yahoo o funduszach z GPW nie wie NIC poza ceną: quoteSummary dla „ETFBW20TR.WA"
# oddaje wyłącznie `price` i `summaryDetail` — żadnego składu, sektorów, opłaty ani
# rodziny funduszy. Karta polskiego ETF-a była więc pusta dokładnie tam, gdzie jest
# najważniejsza: „co jest w środku".
#
# GPW i gpwbenchmark.pl zrywają połączenie z serwera (sprawdzone), a stooq blokuje
# nas od dawna — nie ma skąd wziąć oficjalnego portfela indeksu. Robimy więc to samo,
# co z całym katalogiem: skład indeksu trzymamy u siebie, a WAGI liczymy na żywo
# z kapitalizacji spółek (Yahoo je zna) z limitem udziału jednej spółki, tak jak
# robią to metodyki WIG. To szacunek, nie karta funduszu — i tak to podpisujemy
# w aplikacji.
#
# Fundusze na indeksy zagraniczne (S&P 500, Nasdaq) mają prościej: ich skład to
# skład indeksu, więc bierzemy go z dużego amerykańskiego ETF-a jako wzorca.

_FIN = "financial_services"
_TECH = "technology"
_COMM = "communication_services"
_IND = "industrials"
_MAT = "basic_materials"
_ENE = "energy"
_UTL = "utilities"
_CYC = "consumer_cyclical"
_DEF = "consumer_defensive"
_HLT = "healthcare"
_RE = "realestate"

PL_INDEX = {
    "WIG20": {
        "label": "WIG20",
        "cap": 0.15, "covers": 1.0,
        "members": [
            ("PKN.WA", "Orlen", _ENE), ("PKO.WA", "PKO BP", _FIN),
            ("PZU.WA", "PZU", _FIN), ("PEO.WA", "Pekao", _FIN),
            ("SPL.WA", "Santander Bank Polska", _FIN), ("DNP.WA", "Dino Polska", _DEF),
            ("ALE.WA", "Allegro", _CYC), ("KGH.WA", "KGHM", _MAT),
            ("LPP.WA", "LPP", _CYC), ("CDR.WA", "CD Projekt", _COMM),
            ("PGE.WA", "PGE", _UTL), ("MBK.WA", "mBank", _FIN),
            ("OPL.WA", "Orange Polska", _COMM), ("KRU.WA", "Kruk", _FIN),
            ("BDX.WA", "Budimex", _IND), ("CPS.WA", "Cyfrowy Polsat", _COMM),
            ("KTY.WA", "Grupa Kęty", _MAT), ("ZAB.WA", "Żabka", _DEF),
            ("ALR.WA", "Alior Bank", _FIN), ("JSW.WA", "JSW", _MAT),
        ],
    },
    "MWIG40": {
        "label": "mWIG40",
        "cap": 0.10, "covers": 0.90,
        "members": [
            ("ACP.WA", "Asseco Poland", _TECH), ("XTB.WA", "XTB", _FIN),
            ("ING.WA", "ING Bank Śląski", _FIN), ("MIL.WA", "Bank Millennium", _FIN),
            ("BHW.WA", "Bank Handlowy", _FIN), ("BNP.WA", "BNP Paribas BP", _FIN),
            ("GPW.WA", "GPW", _FIN), ("TXT.WA", "Text (LiveChat)", _TECH),
            ("BFT.WA", "Benefit Systems", _CYC), ("CAR.WA", "Inter Cars", _CYC),
            ("EUR.WA", "Eurocash", _DEF), ("NEU.WA", "Neuca", _HLT),
            ("11B.WA", "11 bit studios", _COMM), ("PLW.WA", "PlayWay", _COMM),
            ("WPL.WA", "Wirtualna Polska", _COMM), ("VRC.WA", "Vercom", _TECH),
            ("CBF.WA", "Cyber_Folks", _TECH), ("SNT.WA", "Synektik", _HLT),
            ("SLV.WA", "Selvita", _HLT), ("NWG.WA", "Newag", _IND),
            ("PKP.WA", "PKP Cargo", _IND), ("STP.WA", "Stalprodukt", _MAT),
            ("ATT.WA", "Grupa Azoty", _MAT), ("ENA.WA", "Enea", _UTL),
            ("TPE.WA", "Tauron", _UTL), ("PEP.WA", "Polenergia", _UTL),
            ("LWB.WA", "Bogdanka", _ENE), ("DVL.WA", "Develia", _RE),
            ("DOM.WA", "Dom Development", _CYC), ("AMC.WA", "Amica", _CYC),
        ],
    },
    "SWIG80": {
        "label": "sWIG80",
        "cap": 0.10, "covers": 0.65,
        "members": [
            ("MBR.WA", "Mo-BRUK", _IND), ("RBW.WA", "Rainbow Tours", _CYC),
            ("ABE.WA", "AB S.A.", _TECH), ("ASB.WA", "Asbis", _TECH),
            ("SPR.WA", "Spyrosoft", _TECH), ("DAT.WA", "DataWalk", _TECH),
            ("SHO.WA", "Shoper", _TECH), ("APR.WA", "Auto Partner", _CYC),
            ("VRG.WA", "VRG", _CYC), ("FTE.WA", "Forte", _CYC),
            ("AMB.WA", "Ambra", _DEF), ("CLN.WA", "Celon Pharma", _HLT),
            ("PCF.WA", "People Can Fly", _COMM), ("TEN.WA", "Ten Square Games", _COMM),
            ("CIG.WA", "CI Games", _COMM), ("ECH.WA", "Echo Investment", _RE),
            ("PBX.WA", "Pekabex", _IND), ("TOR.WA", "Torpol", _IND),
            ("OND.WA", "Onde", _IND), ("GRN.WA", "Grenevia", _IND),
            ("WLT.WA", "Wielton", _IND), ("UNT.WA", "Unimot", _ENE),
            ("KGN.WA", "Kogeneracja", _UTL), ("BOS.WA", "Bank Ochrony Środowiska", _FIN),
        ],
    },
    "WIGTECH": {
        "label": "WIGtech",
        "cap": 0.10, "covers": 0.90,
        "members": [
            ("CDR.WA", "CD Projekt", _COMM), ("ACP.WA", "Asseco Poland", _TECH),
            ("TXT.WA", "Text (LiveChat)", _TECH), ("VRC.WA", "Vercom", _TECH),
            ("CBF.WA", "Cyber_Folks", _TECH), ("ASE.WA", "Asseco South Eastern Europe", _TECH),
            ("ABE.WA", "AB S.A.", _TECH), ("ASB.WA", "Asbis", _TECH),
            ("SPR.WA", "Spyrosoft", _TECH), ("DAT.WA", "DataWalk", _TECH),
            ("SHO.WA", "Shoper", _TECH), ("AIL.WA", "Ailleron", _TECH),
            ("TLX.WA", "Talex", _TECH), ("11B.WA", "11 bit studios", _COMM),
            ("PLW.WA", "PlayWay", _COMM), ("TEN.WA", "Ten Square Games", _COMM),
            ("PCF.WA", "People Can Fly", _COMM), ("CIG.WA", "CI Games", _COMM),
            ("CRJ.WA", "Creepy Jar", _COMM), ("WPL.WA", "Wirtualna Polska", _COMM),
        ],
    },
}

#: Fundusz z GPW -> jak odtworzyć jego zawartość.
#:   index  — liczymy skład sami z PL_INDEX (wagi z kapitalizacji)
#:   proxy  — bierzemy skład z dużego ETF-a na ten sam indeks
#:   bonds  — fundusz obligacji, składu spółek nie ma z definicji
PL_FUND = {
    "ETFBW20TR.WA": {
        "index": "WIG20", "family": "Beta ETF (AgioFunds TFI)",
        "category": "Akcje polskie — duże spółki",
        "about": "Fundusz odwzorowuje WIG20TR, czyli te same dwadzieścia spółek co WIG20, "
                 "ale w wersji z dywidendami doliczanymi do wyniku.",
    },
    "ETFBM40TR.WA": {
        "index": "MWIG40", "family": "Beta ETF (AgioFunds TFI)",
        "category": "Akcje polskie — średnie spółki",
        "about": "mWIG40TR to czterdzieści spółek z drugiego szeregu GPW — za dużych na "
                 "„małe”, za małych na WIG20.",
    },
    "ETFBS80TR.WA": {
        "index": "SWIG80", "family": "Beta ETF (AgioFunds TFI)",
        "category": "Akcje polskie — małe spółki",
        "about": "sWIG80TR zbiera osiemdziesiąt małych spółek z GPW. Pojedyncza firma waży "
                 "tu niewiele, ale cały indeks potrafi się ruszać mocniej niż WIG20.",
    },
    "ETFBWTECH.WA": {
        "index": "WIGTECH", "family": "Beta ETF (AgioFunds TFI)",
        "category": "Akcje polskie — technologia i gry",
        "about": "WIGtech to polska technologia: producenci gier, software house'y "
                 "i firmy IT z GPW.",
    },
    "ETFBSPXPL.WA": {
        "proxy": "SPY", "proxy_label": "S&P 500", "family": "Beta ETF (AgioFunds TFI)",
        "category": "Akcje amerykańskie z zabezpieczeniem walutowym",
        "about": "W środku jest S&P 500 — te same spółki co w amerykańskim funduszu, tylko "
                 "kupowane za złotówki i z zabezpieczeniem kursu dolara.",
    },
    "ETFBNDXPL.WA": {
        "proxy": "QQQ", "proxy_label": "Nasdaq-100", "family": "Beta ETF (AgioFunds TFI)",
        "category": "Akcje amerykańskie (technologia) z zabezpieczeniem walutowym",
        "about": "W środku jest Nasdaq-100 — sto największych spółek niefinansowych z Nasdaq, "
                 "z zabezpieczeniem kursu dolara.",
    },
    "ETFBTBSP.WA": {
        "bonds": True, "family": "Beta ETF (AgioFunds TFI)",
        "category": "Obligacje skarbowe (PLN, stały kupon)",
        "about": "Fundusz idzie za indeksem TBSP, czyli koszykiem polskich obligacji skarbowych "
                 "o stałym oprocentowaniu. Nie ma tu żadnych spółek — jest dług Skarbu Państwa, "
                 "a o wyniku decydują stopy procentowe: gdy rynek oczekuje ich spadku, "
                 "wyceny obligacji rosną.",
    },
}
