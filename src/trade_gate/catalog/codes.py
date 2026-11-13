"""Human-readable names for GS1 / Synkka codes used in the Valio Aimo product data.

The dataset ships codes only. Allergen codes follow the GS1 AllergenTypeCode list;
labels and claims are GS1 code-list values. Unknown codes fall back to the raw code.
"""

ALLERGENS: dict[str, str] = {
    "AC": "crustaceans",
    "AE": "eggs",
    "AF": "fish",
    "AM": "milk",
    "AN": "tree nuts",
    "AP": "peanuts",
    "AS": "sesame",
    "AU": "sulphites",
    "AW": "gluten cereals",
    "AY": "soy",
    "BC": "celery",
    "BM": "mustard",
    "GB": "barley",
    "GK": "kamut",
    "GO": "oats",
    "GS": "spelt",
    "ML": "lactose",
    "NL": "lupin",
    "NR": "rye",
    "SA": "almonds",
    "SC": "cashews",
    "SH": "hazelnuts",
    "SP": "pecans",
    "SM": "macadamia nuts",
    "SQ": "macadamia nuts",
    "X99": "no declarable allergens",
    "SR": "brazil nuts",
    "ST": "pistachios",
    "SW": "walnuts",
    "UM": "molluscs",
    "UW": "wheat",
}

# Allergen families: asking to avoid the family must also avoid its members.
ALLERGEN_FAMILIES: dict[str, set[str]] = {
    "AW": {"AW", "UW", "GB", "GO", "NR", "GK", "GS"},  # gluten cereals
    "AN": {"AN", "SA", "SC", "SH", "SM", "SP", "SQ", "SR", "ST", "SW"},  # tree nuts
    "AM": {"AM", "ML"},  # milk includes lactose
}

# Friendly aliases a buyer (or LLM) may use -> GS1 code.
ALLERGEN_ALIASES: dict[str, str] = {
    **{v: k for k, v in ALLERGENS.items()},
    "gluten": "AW",
    "nuts": "AN",
    "nut": "AN",
    "dairy": "AM",
    "egg": "AE",
    "soya": "AY",
    "shellfish": "AC",
    "sulphur dioxide": "AU",
    "sulfites": "AU",
}

LABELS: dict[str, str] = {
    "GOODS_FROM_FINLAND_BLUE_SWAN": "Goods from Finland (Blue Swan)",
    "MADE_IN_FINLAND_FLAG_WITH_KEY": "Made in Finland (Key Flag)",
    "FINNISH_HEART_SYMBOL": "Finnish Heart Symbol",
    "EU_ORGANIC_FARMING": "EU Organic",
    "SVANEN": "Nordic Swan Ecolabel",
    "RAINFOREST_ALLIANCE": "Rainforest Alliance",
    "EU_ECO_LABEL": "EU Ecolabel",
    "MARINE_STEWARDSHIP_COUNCIL_LABEL": "MSC certified",
    "FAIR_TRADE_MARK": "Fairtrade",
    "AQUACULTURE_STEWARDSHIP_COUNCIL": "ASC certified",
    "KRAV_MARK": "KRAV",
    "OFFICIAL_ECO_LABEL_SUN": "Finnish organic (Sun label)",
    "SOIL_ASSOCIATION_ORGANIC_SYMBOL": "Soil Association Organic",
    "PUHTAASTI_KOTIMAINEN": "Puhtaasti kotimainen",
    "DOLPHIN_SAFE": "Dolphin Safe",
    "UTZ_CERTIFIED": "UTZ Certified",
}

# Temperature labels in packagingMarkedLabel are storage hints, not certificates.
TEMPERATURE_LABELS = {"warmTemperature", "coolTemperature", "freezeTemperature"}

SUSTAINABILITY_LABELS = {
    "EU_ORGANIC_FARMING", "SVANEN", "RAINFOREST_ALLIANCE", "EU_ECO_LABEL",
    "MARINE_STEWARDSHIP_COUNCIL_LABEL", "FAIR_TRADE_MARK", "AQUACULTURE_STEWARDSHIP_COUNCIL",
    "KRAV_MARK", "OFFICIAL_ECO_LABEL_SUN", "SOIL_ASSOCIATION_ORGANIC_SYMBOL", "UTZ_CERTIFIED",
    "DOLPHIN_SAFE",
}


def allergen_name(code: str) -> str:
    return ALLERGENS.get(code, code)


def resolve_allergen(term: str) -> str | None:
    """Map a code or friendly name ('milk', 'AM', 'gluten') to a GS1 code."""
    t = term.strip()
    if t.upper() in ALLERGENS:
        return t.upper()
    return ALLERGEN_ALIASES.get(t.lower())


def expand_allergen(code: str) -> set[str]:
    return ALLERGEN_FAMILIES.get(code, {code})
