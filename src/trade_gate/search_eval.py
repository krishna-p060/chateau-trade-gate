"""Search quality, measured: kitchen-style requests (English and Finnish) against the full catalog.

Each case says what a chef asks for and what counts as the right product (name pattern, words that make it a
different product, a required diet claim). The cases were written from how kitchens order, before tuning, and
are judged by rules, not by hand-picked product ids, so the same rules apply to every ranking method.

Usage: uv run python -m trade_gate.search_eval            (prints the table, writes docs/search-eval.json)
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from trade_gate.catalog.store import Catalog
from trade_gate.config import DB_PATH, ROOT

D = r"(?<![\wåäö])"  # word start


@dataclass
class Case:
    ask: str                       # what the chef types
    ok: str                        # regex the product name (EN + FI) must match
    bad: str = r"$^"               # regex that makes it a different product
    diets: tuple[str, ...] = ()    # hard diet requirement

    def accepts(self, p) -> bool:
        n = f"{p.name} {p.name_fi}".lower()
        return bool(re.search(self.ok, n)) and not re.search(self.bad, n)


FLAVOURED = r"kahvi|coffee|latte|cappuccino|suklaa|chocolate|kaakao|cocoa|vanil|mansikka|strawberr|banaani|banana|mustikka|blueberr|vadelma|raspberr|mango|persik|peach|kirsik|cherry|marja|berry|hedelmä|fruit"

CASES = [
    # dairy
    Case("milk", rf"{D}(maito|milk)", rf"{FLAVOURED}|jäätelö|ice cream|jauhe|powder|kondensoi|condensed|rahka|quark|jogurt|yog|piimä|buttermilk|juusto|cheese|kaura|oat|soija|soy|manteli|almond|kookos|coconut|riisi|rice|vanukas|pudding|leipä|bread|suklaa|keksi|biscuit"),
    Case("lactose-free milk", rf"{D}(maito|milk)", rf"{FLAVOURED}|jäätelö|ice cream|jauhe|powder|rahka|quark|jogurt|yog|juusto|cheese|kaura|oat|soija|soy|manteli|almond|vanukas|pudding", ("lactose_free",)),
    Case("maito", rf"{D}(maito|milk)", rf"{FLAVOURED}|jäätelö|ice cream|jauhe|powder|rahka|quark|jogurt|yog|piimä|juusto|cheese|kaura|oat|soija|soy|manteli|almond|kookos|coconut|vanukas|pudding|suklaa|keksi"),
    Case("cooking cream", r"(ruokakerma|cooking cream|kerma|cream)", rf"{FLAVOURED}|jäätelö|ice cream|vispi|whipping|kermaviili|sour cream|juusto|cheese|levite|spread|keksi|leivos|kakku|cake|kastike|sauce"),
    Case("whipping cream", r"(vispikerma|whipping cream|kuohukerma|whipped cream)", rf"{FLAVOURED}|jäätelö|ice cream|kakku|cake|leivos"),
    Case("butter", rf"{D}(voi|butter)\b", r"spreader|brush|maapähkinä|peanut|keksi|biscuit|cookie|croissant|kastike|sauce|leipä|bread|pulla|bun|kakku|cake|piirakka|pie|suklaa|chocolate|kaakao|cocoa|shea|kookos|coconut|omena|apple|seesam|sesame"),
    Case("voi", rf"{D}(voi|butter)\b", r"spreader|brush|maapähkinä|peanut|keksi|biscuit|cookie|croissant|kastike|sauce|leipä|bread|pulla|kakku|cake|piirakka|pie|suklaa|chocolate|kaakao|shea|kookos|coconut|seesam|sesame"),
    Case("grated cheese", r"(raaste|grated|shredded|juustoraaste)", r"kastike|sauce|pizza|leipä|bread|piirakka|pie|keksi|snack"),
    Case("parmesan", r"(parmesan|parmigiano|grana padano)", r"kastike|sauce|pesto|keksi|cracker|snack"),
    Case("feta cheese", r"(feta|salaattijuusto|salad cheese)", r"kastike|sauce|pizza|piirakka|pie|salaatti\b(?!juusto)"),
    Case("natural yoghurt", r"(jogurt|yoghurt|yogurt)", rf"{FLAVOURED}|jäätelö|ice cream|jauhe|powder|keksi|kastike|sauce|juoma|drink|smoothie|myslit|muesli|granola|lime|sitruuna|lemon"),
    Case("eggs", r"(kananmun|munat|\begg)", r"pasta|nuudel|noodle|majonees|mayonnaise|kastike|sauce|suklaa|chocolate|pääsiäi|easter|liköör|keksi|munkki|donut|salaatti|salad|leipä|sandwich|voileipä"),
    # plant drinks
    Case("oat drink", r"(kaura|oat)", rf"{FLAVOURED}|jogurt|yog|jäätelö|ice cream|hiutale|flake|keksi|biscuit|leipä|bread|puuro|porridge|myslit|muesli|granola|patukka|bar|jauho|flour|kuitu|fibre|fiber|ruokakerma|cooking|vispi|whip|rahka|levite|spread"),
    Case("soy drink", r"(soija|soy)", rf"{FLAVOURED}|kastike|sauce|jogurt|yog|rouhe|mince|nugget|papu|bean|rahka|jäätelö"),
    # dry goods
    Case("spaghetti", r"spag", r"kastike|sauce|bolognese|valmis|ready|ateria|meal|säilyke|tin"),
    Case("penne pasta", r"penne", r"kastike|sauce|valmis|ready|ateria|meal|salaatti|salad"),
    Case("gluten-free pasta", r"(pasta|spag|penne|fusilli|makaroni|macaroni|tagliatelle|lasagne|nuudel|noodle)", r"kastike|sauce|valmis|ready|ateria|meal", ("gluten_free",)),
    Case("macaroni", r"(makaroni|macaroni)", r"laatikko|casserole|valmis|ready|ateria|meal|juusto|cheese"),
    Case("basmati rice", r"basmati", r"valmis|ready|ateria|meal|kastike|sauce|curry"),
    Case("jasmine rice", r"(jasmin|jasmine)", r"valmis|ready|ateria|meal|tee\b|tea"),
    Case("riisi", r"(riisi|rice)", r"puuro|porridge|kakku|cake|keksi|cracker|valmis|ready|ateria|meal|juoma|drink|piirakka|pie|nuudel|noodle|jauho|flour|etikka|vinegar|paperi|paper|vanukas|pudding|kastike|sauce|sushi"),
    Case("wheat flour", r"(vehnäjauho|wheat flour|vehnä.*jauho|jauho.*vehnä)", r"leipä|bread|pulla|bun|keksi|biscuit|pizza|piirakka|pie|seos|mix|tortilla|ohukai|crepe"),
    Case("oat flakes", r"(kaurahiutale|oat flake|rolled oat|kaura.*hiutale|hiutale.*kaura|porridge oat)", r"keksi|biscuit|myslit|muesli|granola|patukka|bar|leipä|bread|juoma|drink|valmis|ready|pikapuuro|instant"),
    Case("sugar", r"(sokeri|sugar)", r"keksi|biscuit|leivos|pastry|siirappi|syrup|suklaa|chocolate|karkki|candy|makeinen|sweet|juoma|drink|sokeriton|sugar free|sugar-free|vähemmän|less|kakku|cake|pulla|bun|munkki|donut|vohveli|waffle|jäätelö|ice|kastike|sauce|hillo|jam|mehu|juice|limonadi|soda|dressing"),
    Case("olive oil", r"(oliiviöljy|olive oil|oliivi.*öljy)", r"säilyke|tin|in oil|öljyssä|tonnikala|tuna|sardiini|sardine|aurinkokuivat|sun-dried|majonees|mayonnaise|kastike|sauce|dressing|leipä|bread|sipsi|chips|oliivit\b|olives\b"),
    Case("rapeseed oil", r"(rypsiöljy|rapeseed oil|rypsi.*öljy|kasviöljy|vegetable oil)", r"säilyke|tin|öljyssä|in oil|majonees|mayonnaise|kastike|sauce|dressing|levite|spread|margariini|margarine|sipsi|chips|kala|fish"),
    Case("salt", rf"{D}(suola|salt)\b", r"suolattu|salted|suolakurk|pickle|keksi|cracker|sipsi|chips|pähkinä|nut|kala|fish|liha|meat|voi\b|butter|lakritsi|liquorice|karkki|candy|popcorn|pretzel|perun|potato|kurkku|cucumber|vähäsuola|low salt|maapähkinä|peanut"),
    Case("black pepper", r"(mustapippuri|black pepper|pippuri|pepper)", r"kastike|sauce|pihvi|steak|makkara|sausage|salami|keksi|cracker|sipsi|chips|juusto|cheese|paprika|chili|jalapeño|bell|liha|meat|kana|chicken|maustesekoitus|blend"),
    Case("canned tomatoes", r"(tomaatti|tomato).*(murska|säilyke|crushed|chopped|tin|can|pilkottu|kuorittu|peeled)|(murska|crushed|chopped|pilkottu|kuorittu|peeled).*(tomaatti|tomato)", r"kastike|sauce|ketsuppi|ketchup|keitto|soup|pizza|salsa|pyree|purée|puree|aurinkokuivat|sun-dried|semi|dried|kuivat|kirsikka|cherry|mehu|juice"),
    Case("tomato purée", r"(tomaattipyree|tomato pur|tomato paste|tomaattisose|tomaattitiiviste|tomato concentrate|pyree|purée|puree|passata)", r"ketsuppi|ketchup|keitto|soup|pizza|salsa|kastike|sauce(?! base)"),
    Case("canned tuna", r"(tonnikala|tuna)", r"salaatti|salad|pizza|leipä|bread|sandwich|voileipä|pasta|ateria|meal|tahna|spread|piirakka|pie"),
    Case("chickpeas", r"(kikherne|chickpea)", r"jauho|flour|hummus|tahna|spread|sipsi|chips|snack|keitto|soup|ateria|meal|curry|pihvi|burger|pyörykä|falafel|pasta"),
    Case("coconut milk", r"(kookosmaito|coconut milk|kookoskerma|coconut cream)", rf"{FLAVOURED}|jäätelö|ice cream|jogurt|yog|juoma|drink|keitto|soup|curry|kastike|sauce|suklaa|karkki"),
    Case("basil pesto", r"pesto", r"pasta(?!.*pesto)|leipä|bread|sandwich|ateria|meal|kana|chicken|juusto(?!.*pesto)|sipsi|chips|keksi"),
    # fresh produce
    Case("yellow onion", r"(keltasipuli|yellow onion|sipuli|onion)", r"punasipuli|red onion|kevätsipuli|spring onion|ruohosipuli|chive|valkosipuli|garlic|jauhe|powder|rengas|ring|paistettu|fried|crispy|rapea|kastike|sauce|keitto|soup|pikkelöity|pickled|sipsi|chips|kuivattu|dried|hilloke|chutney|marmelad|salotti|shallot|purjo|leek"),
    Case("red onion", r"(punasipuli|red onion)", r"jauhe|powder|pikkelöity|pickled|hilloke|chutney|marmelad|kastike|sauce|salaatti|salad|paistettu|fried|kuivattu|dried"),
    Case("garlic", r"(valkosipuli|garlic)", r"jauhe|powder|rouhe|granul|kastike|sauce|leipä|bread|patonki|baguette|voi\b|butter|majonees|mayonnaise|aioli|dip|tahna|paste|sipsi|chips|öljy|oil|marinadi|marinade|mauste|seasoning|suola|salt|kuivattu|dried|juusto|cheese|makkara|sausage|krutonki|crouton|pikkelöity|pickled|tuorejuusto"),
    Case("potatoes", r"(peruna|potato)", r"sipsi|chips|crisps|lastu|ranskalai|fries|french|muusi|mash|jauho|flour|kroketti|croquette|lohko|wedge|rösti|gratiini|gratin|salaatti|salad|kermaperuna|valmis|ready|ateria|meal|keitto|soup|lettu|pancake|tärkkelys|starch\\b|hiutale|flake|smash|paistinperuna|bataatti|sweet potato"),
    Case("carrots", r"(porkkana|carrot)", r"mehu|juice|kakku|cake|raaste(?! porkkana)|salaatti|salad|keitto|soup|sose|puree|pyree|purée|lastu|chips|smoothie|sekoitus|mix|hernerokka|peas and|herne|pea"),
    Case("cucumber", r"(kurkku|cucumber)", r"suola|salt|pikkel|pickle|etikka|vinegar|maustekurkku|tzatziki|salaatti|salad|kastike|sauce|dip|hillo|relish"),
    Case("cherry tomatoes", r"(kirsikkatomaat|cherry tomato|tomaatti.*kirsikka|kirsikka.*tomaatti)", r"säilyke|tin|can|murska|crushed|kastike|sauce|aurinkokuivat|sun-dried|kuivattu|dried|pyree|puree|purée|pizza"),
    Case("iceberg lettuce", r"(jäävuori|iceberg|jääsalaatti)", r"sekoitus|mix|kastike|sauce|dressing"),
    Case("fresh dill", r"(tilli|dill)", r"perunat|potatoes|kurkku|cucumber|silli|herring|kastike|sauce|siemen|seed|kuivattu|dried|pakaste|frozen|maustekurkku|majonees|dip|lohi|salmon|kala|fish|perunasalaatti"),
    Case("strawberries", r"(mansikka|strawberr)", r"jogurt|yog|jäätelö|ice cream|hillo|jam|mehu|juice|kiisseli|keksi|biscuit|kakku|cake|leivos|smoothie|rahka|quark|vanukas|pudding|juoma|drink|karkki|candy|suklaa|chocolate|tee\b|tea\b|sekoitus|mix|kastike|sauce|soppa|soup|maito|milk|kerma|cream|marmelad|aromi|siirappi|syrup|piirakka|pie|myslit|muesli|granola|kuivattu|dried|patukka|bar|limonadi|soda|vesi|water|sima"),
    # fish and meat
    Case("salmon fillet", r"(lohi|salmon)", r"savu|smoked|graavi|cured|kylmäsavu|lohikeitto|keitto|soup|pizza|leipä|bread|sandwich|voileipä|tahna|spread|salaatti|salad|piirakka|pie|kiusaus|laatikko|casserole|pyörykä|ball|pihvi|burger|sushi|kastike|sauce|säilyke|tin|rapea|crispy|wrap|kääre|pasta|ateria|meal|mäti|roe|kulho|bowl"),
    Case("chicken breast", r"(broilerin.*rinta|kananrinta|chicken breast|rintafilee|broiler breast|broilerin fileepihvi|fileesuikale|broileri.*filee|kana.*filee|chicken fillet)", r"leike|schnitzel|nugget|pyörykä|ball|pihvi|burger|makkara|sausage|leikkele|cold cut|salaatti|salad|wrap|kääre|pizza|keitto|soup|ateria|meal|kastike|sauce|piirakka|pie|rapea|crispy|paneroitu|breaded|leivitetty|sandwich|voileipä|kebab|kulho|bowl|curry|tikka|teriyaki"),
    Case("minced beef", r"(naudan jauheliha|jauheliha.*nauta|nauta.*jauheliha|minced beef|beef mince|ground beef|naudan.*jauhe)", r"pyörykä|ball|pihvi|burger|patty|kastike|sauce|lasagne|lasagna|piirakka|pie|laatikko|casserole|ateria|meal|keitto|soup|pizza|makkara|sausage|kebab|wrap|lihapulla|meatball|rapea|valmis|ready"),
    Case("bacon", r"(pekoni|bacon)", r"juusto|cheese|keitto|soup|pizza|piirakka|pie|kastike|sauce|sipsi|chips|kääre|wrap|ateria|meal|salaatti|salad|leipä|bread|makkara|sausage|perunat|potato"),
    # bakery
    Case("rye bread", r"(ruisleipä|rye bread|ruis.*leipä|ruisvuoka|ruispala|ruisreikä|ruislimppu|ruisrieska|ruispuikula|puikula|jälkiuuni|reikäleipä)", r"jauho|flour|keksi|cracker|näkkileipä|crispbread|sipsi|chips|lastu|croutons|krutonki|voileipä|sandwich|kakku|cake|piirakka|pie|vanukas"),
    Case("hamburger buns", r"(hampurilais|burger bun|hamburger bun|hampurilaissämpylä|burger.*sämpylä|sämpylä.*burger|briossisämpylä|brioche bun)", r"pihvi|patty|ateria|meal|valmis|ready|kastike|sauce|liha|meat|juusto|cheese"),
]


# Held out: written before any tuning on CASES and never used to tune; reported separately.
HELD_OUT = [
    Case("sour cream", r"(kermaviili|sour cream|smetana|ranskankerma|crème fraîche|creme fraiche)", rf"{FLAVOURED}|dip|kastike|sauce|sipsi|chips|keitto|soup|salaatti|salad"),
    Case("mozzarella", r"mozzarell", r"pizza|leipä|bread|sandwich|salaatti|salad|tikku|stick|paneroitu|breaded|ateria|meal|piirakka|pie"),
    Case("lasagne sheets", r"(lasagne|lasagna)", r"valmis|ready|ateria|meal|kastike|sauce|pakaste.*lasagne|frozen lasagne|liha|meat|kasvis|vegetable|bolognese|juusto|cheese|lohi|salmon|kana|chicken|pinaatti|spinach"),
    Case("brown lentils", r"(linssi|lentil)", r"keitto|soup|ateria|meal|pihvi|burger|pasta|curry|kastike|sauce|sipsi|chips|jauho|flour|dal|pyörykä|ball|valmis|ready"),
    Case("honey", r"(hunaja|honey)", r"keksi|biscuit|myslit|muesli|granola|kastike|sauce|sinappi|mustard|kinkku|ham|kana|chicken|jogurt|yog|tee|tea|juoma|drink|patukka|bar|karkki|candy|hiutale|flake|meloni|melon|siipi|wing|marinadi|marinade|kakku|cake|leipä|bread|vohveli|waffle|sauna|sima|dressing|pähkinä|nut|mantel|almond|cereal|rengas|ring|pops|loops"),
    Case("frozen peas", r"(herne|peas?\b)", r"keitto|soup|rokka|kikherne|chickpea|maapähkinä|peanut|proteiini|protein|sipsi|chips|snack|jauho|flour|ateria|meal|riisi|rice|sekoitus|mix|maissi|corn|porkkana|carrot|pyree|purée|puree|sose|hummus|wasabi|valmis|ready|kastike|sauce"),
    Case("lemons", r"(sitruuna|lemon)", r"mehu|juice|limonadi|lemonade|soda|juoma|drink|tee|tea|jogurt|yog|keksi|biscuit|kakku|cake|aromi|flavour|pippuri|pepper|ruoho|grass|tiiviste|concentrate|marmelad|curd|karkki|candy|kastike|sauce|vesi|water|siirappi|syrup|piirakka|pie|muffin|suklaa|liköör|rahka|quark|timjami|thyme|melissa|balm|öljy|oil|suola|salt|mauste|seasoning|leivos|tart|jäätelö|ice|sorbet|tonic|lime|limetti|kuori|zest|peel"),
    Case("frozen spinach", r"(pinaatti|spinach)", r"lettu|pancake|keitto|soup|piirakka|pie|lasagne|ohukai|crepe|kastike|sauce|pasta|ravioli|tortellini|juusto|cheese|ateria|meal|pyörykä|ball|pizza|smoothie|sipsi|chips|munakas|omelet|leipä|bread|feta|valmis|ready|wrap|kääre"),
    Case("cod fillet", r"(turska|cod)", r"paneroitu|breaded|leivitetty|kalapuikko|fish stick|fish finger|pihvi|burger|pyörykä|ball|keitto|soup|ateria|meal|kastike|sauce|maksa|liver|öljy|oil|mäti|roe|kiusaus|laatikko|casserole|valmis|ready|savu|smoked|suolattu|salted|kuivattu|dried|lipeä"),
    Case("pork tenderloin", r"(porsaan sisäfilee|pork tenderloin|sisäfilee.*porsa|porsa.*sisäfilee|porsaan ulkofilee|pork loin|porsaan filee|pork fillet)", r"pihvi(?!.*filee)|leike|schnitzel|marinoitu|marinated|makkara|sausage|leikkele|cold cut|kinkku|ham|ateria|meal|kastike|sauce|savu|smoked|valmis|ready|kebab|suikale(?!.*filee)|nugget|pekoni|bacon"),
    Case("white wine vinegar", r"(viinietikka|wine vinegar|valkoviinietikka|white wine vinegar)", r"kastike|sauce|dressing|majonees|mayonnaise|sipsi|chips|kurkku|cucumber|pikkel|pickle|punaviini|red wine|balsami|balsamic"),
    Case("cinnamon", r"(kaneli|cinnamon)", r"pulla|bun|korvapuusti|roll|keksi|biscuit|kakku|cake|myslit|muesli|granola|tee|tea|jogurt|yog|puuro|porridge|omena|apple|piirakka|pie|leivos|pastry|karkki|candy|suklaa|chocolate|siirappi|syrup|kahvi|coffee|sokeri|sugar|munkki|donut|vohveli|waffle|rinkeli|pretzel|sekoitus|mix|patukka|bar|jäätelö|ice|rahka|quark|vanukas|pudding|hiutale|flake|pähkinä|nut|mantel|almond|leipä|bread|toast|rusina|raisin|croissant|danish|wiener|jouluinen|christmas|glögi|mulled|rengas|ring|pops|loops|crunch"),
    Case("kaurajuoma", r"(kaura|oat)", rf"{FLAVOURED}|jogurt|yog|jäätelö|ice cream|hiutale|flake|keksi|biscuit|leipä|bread|puuro|porridge|myslit|muesli|granola|patukka|bar|jauho|flour|kuitu|fibre|ruokakerma|cooking|vispi|whip|rahka|levite|spread"),
    Case("perunat", r"(peruna|potato)", r"sipsi|chips|crisps|lastu|ranskalai|fries|french|muusi|mash|jauho|flour|kroketti|croquette|lohko|wedge|rösti|gratiini|gratin|salaatti|salad|kermaperuna|valmis|ready|ateria|meal|keitto|soup|lettu|pancake|tärkkelys|starch\\b|hiutale|flake|smash|bataatti|sweet potato"),
    Case("smetana", r"(smetana|kermaviili|sour cream|ranskankerma|crème fraîche)", rf"{FLAVOURED}|dip|kastike|sauce|sipsi|chips|keitto|soup|salaatti|salad"),
    Case("broccoli", r"(parsakaali|broccoli)", r"keitto|soup|sekoitus|mix|piirakka|pie|gratiini|gratin|ateria|meal|kastike|sauce|pihvi|burger|pyörykä|ball|riisi|rice|kukkakaali.*sekoitus|wok|valmis|ready|pasta|smoothie|salaatti|salad|lasagne|quiche"),
]


def _rank_variants(cat: Catalog, case: Case, method: str, k: int = 3):
    diets = list(case.diets)
    return cat.search(case.ask, diets=diets, limit=k, rank=method)


def run(methods=("bm25", "names", "coherent"), verbose: bool = False, cases=None) -> dict:
    cases = CASES if cases is None else cases
    cat = Catalog(DB_PATH)
    res = {m: {"top1": 0, "top3": 0, "fails": []} for m in methods}
    for c in cases:
        for m in methods:
            got = _rank_variants(cat, c, m)
            ok = [c.accepts(p) for p in got]
            if ok[:1] == [True]:
                res[m]["top1"] += 1
            if any(ok[:3]):
                res[m]["top3"] += 1
            if ok[:1] != [True]:
                res[m]["fails"].append(c.ask)
            if verbose and m == methods[-1] and ok[:1] != [True]:
                print(f"  ✗ {c.ask!r}: " + " | ".join(f"{'✓' if o else '·'} {p.name}" for p, o in zip(got, ok)))
    n = len(cases)
    for m in methods:
        res[m]["top1_pct"] = round(100 * res[m]["top1"] / n)
        res[m]["top3_pct"] = round(100 * res[m]["top3"] / n)
    return {"cases": n, "catalog_size": cat.con.execute("SELECT count(*) FROM products").fetchone()[0], "methods": res}


LABELS = {"bm25": "Keyword search only (SQLite FTS5, BM25)",
          "names": "Aimo search: name match first, other product kinds demoted, Finnish/English synonyms",
          "coherent": "Tried and rejected: also keep the category most matches share"}
# main at commit 3fac816, measured with the same cases and rules before this change
BEFORE = {"tuning": 88, "held_out": 88, "all": 88}


def main(argv: list[str]) -> int:
    report = {"catalog_size": None, "sets": {}, "labels": LABELS, "before_main_3fac816_top1_pct": BEFORE}
    for name, cases in (("tuning", CASES), ("held_out", HELD_OUT)):
        out = run(verbose="-v" in argv, cases=cases)
        report["catalog_size"] = out["catalog_size"]
        report["sets"][name] = {"cases": out["cases"], **{m: {k: v for k, v in r.items() if k != "fails"}
                                                          for m, r in out["methods"].items()}}
    t, h = report["sets"]["tuning"], report["sets"]["held_out"]
    n = t["cases"] + h["cases"]
    report["all"] = {m: {"top1": t[m]["top1"] + h[m]["top1"], "top3": t[m]["top3"] + h[m]["top3"], "cases": n,
                         "top1_pct": round(100 * (t[m]["top1"] + h[m]["top1"]) / n),
                         "top3_pct": round(100 * (t[m]["top3"] + h[m]["top3"]) / n)} for m in LABELS}
    print(f"Search quality: {n} kitchen requests (English + Finnish) over {report['catalog_size']:,} products")
    print(f"{t['cases']} used while tuning, {h['cases']} held out (written before tuning, never tuned on)\n")
    print(f"{'method':<84} {'tuning':>7} {'held out':>9} {'all: first / top 3':>20}")
    for m, lab in LABELS.items():
        a = report["all"][m]
        print(f"{lab:<84} {t[m]['top1_pct']:>6}% {h[m]['top1_pct']:>8}%   {a['top1_pct']:>6}% / {a['top3_pct']}%")
    print(f"{'Before this change (main 3fac816)':<84} {BEFORE['tuning']:>6}% {BEFORE['held_out']:>8}%   {BEFORE['all']:>6}%")
    path = ROOT / "docs" / "search-eval.json"
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print(f"\nwritten {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
