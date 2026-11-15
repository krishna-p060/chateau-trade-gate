"""Read-side catalog: full-text search with hard dietary/allergen filters.

Allergen safety rule: a product is only 'verified safe' for an allergen if the manufacturer data
explicitly covers allergens and the product neither CONTAINS nor MAY_CONTAIN it. Products with no
allergen data are never silently treated as safe; they come back with allergen_status='unknown'.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from trade_gate.catalog.codes import (LABELS, SUSTAINABILITY_LABELS, allergen_name, expand_allergen,
                                      resolve_allergen)
from trade_gate.config import DB_PATH

# Diet / claim requirements a buyer can state -> GS1 nutritionalClaim codes.
DIET_CLAIMS: dict[str, str] = {
    "lactose_free": "FREE_FROM_LACTOSE",
    "gluten_free": "FREE_FROM_GLUTEN",
    "vegan": "VEGAN",
    "vegetarian": "VEGETARIAN",
}


@dataclass
class Product:
    id: str
    name: str
    name_fi: str
    brand: str | None
    vendor: str | None
    category: str | None
    country: str | None
    sales_unit: str
    base_unit: str | None
    base_units_per_sales_unit: float
    allowed_lot_size: float | None
    content_per_sales_unit: float | None
    content_dim: str | None
    content_source: str | None
    has_allergen_data: bool
    allergens_contains: list[str]
    allergens_may_contain: list[str]
    free_from: list[str]
    claims: list[str]
    labels: list[str]
    sustainability_labels: list[str]
    delivery_reliability: float | None
    co2_kg_per_kg: float | None
    key_ingredients: str
    substitutes: list[str] = field(default_factory=list)
    allergen_status: str = "not_checked"  # verified_safe | unknown | not_checked
    match_score: float = 0.0

    def public(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        d["allergens_contains"] = [allergen_name(a) for a in self.allergens_contains]
        d["allergens_may_contain"] = [allergen_name(a) for a in self.allergens_may_contain]
        d["labels"] = [LABELS.get(lbl, lbl) for lbl in self.labels]
        d["sustainability_labels"] = [LABELS.get(lbl, lbl) for lbl in self.sustainability_labels]
        d["free_from"] = [allergen_name(a) for a in self.free_from]
        return d


def _row_to_product(r: sqlite3.Row) -> Product:
    j = lambda s: json.loads(s) if s else []  # noqa: E731
    return Product(
        id=r["id"], name=r["name_en"] or r["name_fi"] or r["id"], name_fi=r["name_fi"] or "",
        brand=r["brand"], vendor=r["vendor"], category=r["category"], country=r["country"],
        sales_unit=r["sales_unit"], base_unit=r["base_unit"],
        base_units_per_sales_unit=r["base_units_per_sales_unit"] or 1.0,
        allowed_lot_size=r["allowed_lot_size"],
        content_per_sales_unit=r["content_per_sales_unit"], content_dim=r["content_dim"],
        content_source=r["content_source"], has_allergen_data=bool(r["has_allergen_data"]),
        allergens_contains=j(r["allergens_contains"]), allergens_may_contain=j(r["allergens_may_contain"]),
        free_from=j(r["free_from"]), claims=j(r["claims"]), labels=j(r["labels"]),
        sustainability_labels=j(r["sustainability_labels"]),
        delivery_reliability=r["delivery_reliability"], co2_kg_per_kg=r["co2_kg_per_kg"],
        key_ingredients=r["key_ingredients_en"] or r["key_ingredients_fi"] or "",
    )


# Words that carry no product meaning in a buyer request.
_STOP = {"i", "need", "we", "want", "some", "for", "by", "of", "the", "a", "an", "and", "with", "free",
         "litres", "liters", "litre", "liter", "kg", "kilos", "pcs", "pieces", "monday", "tuesday",
         "wednesday", "thursday", "friday", "saturday", "sunday", "tomorrow", "please", "find", "option"}

# Words the FTS index needs to match in EN or FI (buyer may write either).
_SYNONYMS = {"milk": ["milk", "maito", "milkdrink", "maitojuoma"],
             "cream": ["cream", "kerma"], "butter": ["butter", "voi"], "cheese": ["cheese", "juusto"],
             "yoghurt": ["yoghurt", "yogurt", "jogurtti"], "yogurt": ["yoghurt", "yogurt", "jogurtti"],
             "potato": ["potato", "peruna", "potatoes"], "potatoes": ["potato", "peruna", "potatoes"],
             "chicken": ["chicken", "broiler", "kana"], "beef": ["beef", "nauta"],
             "salmon": ["salmon", "lohi"], "egg": ["egg", "eggs", "kananmuna"], "eggs": ["egg", "eggs", "kananmuna"],
             "oat": ["oat", "kaura"], "rice": ["rice", "riisi"], "flour": ["flour", "jauho", "vehnäjauho"]}


def _query_words(text: str) -> list[str]:
    words = [w for w in re.findall(r"[\wåäöÅÄÖ]+", text.lower()) if w not in _STOP and not w.isdigit()]
    return [w for w in words if len(w) > 1]


# Words that turn a product into a different product type ("milk" vs "milk chocolate drink").
# A name containing one the buyer did not ask for ranks lower.
_TYPE_MODIFIERS = {"coffee", "kahvi", "latte", "cappuccino", "mocca", "mocha", "espresso", "chocolate", "suklaa",
                   "cocoa", "kaakao", "vanilla", "vanilja", "sour", "piimä", "condensed", "powder", "jauhe",
                   "ice", "jäätelö", "quark", "rahka", "yoghurt", "yogurt", "jogurtti", "cheese", "juusto",
                   "flavor", "flavour", "mint", "strawberry", "smoothie", "protein", "shake", "dessert",
                   "pudding", "vanukas", "sauce", "kastike", "soup", "keitto", "bar", "candy", "snack",
                   "cake", "kakku", "pie", "piirakka", "mix", "seos", "spread", "levite",
                   # measured by search_eval.py: snacks, ready meals and processed forms that share a word
                   "chips", "sipsi", "crisps", "tortilla", "caramel", "karamelli", "jellies", "mashed", "muusi",
                   "sose", "pizza", "salad", "salaatti", "pastasalad", "meal", "ateria", "ketchup", "ketsuppi",
                   "marinated", "marinoitu", "dried", "kuivattu", "spreader", "brush"}


def _type_penalty(words: list[str], name: str) -> int:
    toks = set(re.findall(r"[\wåäöÅÄÖ]+", name.lower()))
    return len((toks & _TYPE_MODIFIERS) - set(words))


def _name_hits(words: list[str], name: str) -> int:
    n = name.lower()
    toks = set(re.findall(r"[\wåäöÅÄÖ]+", n))
    # short words ("voi" = butter) must be whole words, or "voi" matches "Voima"
    return sum(1 for w in words if any((a in toks) if len(a) <= 3 else (a in n) for a in _SYNONYMS.get(w, [w])))


def _coherent(rows: list, nk) -> list:
    """Category coherence: the strongest matches (every word in the name, no other-product word) mostly share
    one product category; products from other categories that merely contain the word move down
    ("milk" should not surface milk chocolate or a milk-based sauce)."""
    if not rows:
        return rows
    best = nk(rows[0])
    strong = [r for r in rows[:40] if nk(r) == best and best[1] == 0][:12]
    counts: dict[str, int] = {}
    for r in strong:
        counts[r["category"]] = counts.get(r["category"], 0) + 1
    if not counts:
        return rows
    top, n = max(counts.items(), key=lambda kv: kv[1])
    if n < 2 or n < 0.4 * len(strong):
        return rows
    return sorted(rows, key=lambda r: (nk(r)[0], nk(r)[1] + (r["category"] != top), r["score"]))


def _fts_query(text: str) -> str | None:
    words = _query_words(text)
    if not words:
        return None
    groups = []
    for w in words:
        alts = _SYNONYMS.get(w, [w])
        groups.append("(" + " OR ".join(f'"{a}"' if len(a) <= 3 else f'"{a}"*' for a in alts) + ")")
    return " AND ".join(groups)


class Catalog:
    def __init__(self, db_path: Path = DB_PATH):
        self.con = sqlite3.connect(db_path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row

    @lru_cache(maxsize=50_000)
    def _subs(self, pid: str) -> tuple[str, ...]:
        return tuple(r[0] for r in self.con.execute("SELECT substitute FROM substitutions WHERE product=?", (pid,)))

    def get(self, pid: str) -> Product | None:
        r = self.con.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        if not r:
            return None
        p = _row_to_product(r)
        p.substitutes = list(self._subs(pid))
        return p

    def get_many(self, ids: list[str]) -> list[Product]:
        return [p for p in (self.get(i) for i in ids) if p]

    def raw(self, pid: str) -> dict | None:
        r = self.con.execute("SELECT raw_json FROM products WHERE id=?", (pid,)).fetchone()
        return json.loads(r[0]) if r else None

    def search(self, query: str = "", *, diets: list[str] | None = None, avoid_allergens: list[str] | None = None,
               require_allergen_data: bool = False, labels: list[str] | None = None,
               category: str | None = None, content_dim: str | None = None, limit: int = 25,
               rank: str = "names") -> list[Product]:
        """Search the catalog. Hard filters are applied in Python after FTS for transparency.
        rank: "bm25" keyword score only; "names" products whose name carries the words first, other product types
        demoted; "coherent" also keeps the product kind most strong matches share (search_eval.py measures all three)."""
        fq = _fts_query(query) if query else None
        if fq:
            rows = self.con.execute(
                "SELECT p.*, bm25(products_fts, 0, 10.0, 8.0, 3.0, 1.0, 2.0, 2.0, 0.5) AS score "
                "FROM products_fts JOIN products p ON p.id = products_fts.id "
                "WHERE products_fts MATCH ? ORDER BY score LIMIT 600", (fq,)).fetchall()
        else:
            sql, args = "SELECT p.*, 0 AS score FROM products p", []
            if category:
                sql += " WHERE p.category = ?"
                args.append(category)
            rows = self.con.execute(sql + " LIMIT 2000", args).fetchall()

        claim_codes = [DIET_CLAIMS[d] for d in (diets or []) if d in DIET_CLAIMS]
        avoid: set[str] = set()
        for a in avoid_allergens or []:
            code = resolve_allergen(a)
            if code:
                avoid |= expand_allergen(code)
        want_labels = set(labels or [])

        words = _query_words(query) if query else []
        if words and rank != "bm25":  # products whose NAME carries the query words beat ingredient-only matches
            def nk(r):
                n = f"{r['name_en']} {r['name_fi']}"
                return -_name_hits(words, n), _type_penalty(words, n)
            rows = sorted(rows, key=lambda r: (*nk(r), r["score"]))
            if rank == "coherent":
                rows = _coherent(rows, nk)

        out: list[Product] = []
        for r in rows:
            p = _row_to_product(r)
            if category and p.category != category:
                continue
            if content_dim and p.content_dim not in (content_dim, None):
                continue
            if claim_codes and not all(self._meets_claim(p, c) for c in claim_codes):
                continue
            if want_labels and not want_labels <= set(p.labels):
                continue
            if avoid:
                if set(p.allergens_contains) & avoid or set(p.allergens_may_contain) & avoid:
                    continue
                p.allergen_status = "verified_safe" if p.has_allergen_data else "unknown"
                if require_allergen_data and not p.has_allergen_data:
                    continue
            p.match_score = round(-float(r["score"]), 3)
            if p.content_per_sales_unit:
                p.content_per_sales_unit = round(p.content_per_sales_unit, 4)
            p.substitutes = list(self._subs(p.id))
            out.append(p)
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _meets_claim(p: Product, claim: str) -> bool:
        if claim in p.claims:
            return True
        # 'lactose free' is also proven by an explicit FREE_FROM lactose declaration.
        if claim == "FREE_FROM_LACTOSE" and "ML" in p.free_from:
            return True
        if claim == "FREE_FROM_GLUTEN" and "AW" in p.free_from:
            return True
        return False

    def sustainability_codes(self) -> set[str]:
        return set(SUSTAINABILITY_LABELS)
