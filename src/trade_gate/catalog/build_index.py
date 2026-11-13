"""Build the local catalog index (SQLite + FTS5) from Valio Aimo's static product files.

Static data (names, allergens, labels, pack sizes, reliability, CO2) is indexed locally so
agents can narrow down candidates without hammering the rate-limited price/availability APIs.

Usage:  uv run python -m trade_gate.catalog.build_index
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
from pathlib import Path

from trade_gate.catalog.codes import SUSTAINABILITY_LABELS, TEMPERATURE_LABELS
from trade_gate.config import DATA_DIR, DB_PATH

RAW = DATA_DIR / "raw"

# ---------------------------------------------------------------- content parsing
_UNIT = {"kg": ("kg", 1.0), "g": ("kg", 0.001), "l": ("l", 1.0), "dl": ("l", 0.1),
         "cl": ("l", 0.01), "ml": ("l", 0.001), "ltr": ("l", 1.0)}
_NUM = r"(\d+(?:[.,]\d+)?)"
_MULTI = re.compile(rf"(\d+)\s*[x×]\s*{_NUM}\s*(kg|g|ltr|l|dl|cl|ml)\b", re.I)
_SINGLE = re.compile(rf"{_NUM}\s*(kg|g|ltr|l|dl|cl|ml)\b", re.I)


def parse_content(name: str) -> tuple[float, str] | None:
    """Estimate net content of ONE base unit from its name, e.g. '10 l' -> (10.0, 'l')."""
    if not name:
        return None
    m = _MULTI.search(name)
    if m:
        count, qty, unit = int(m.group(1)), float(m.group(2).replace(",", ".")), m.group(3).lower()
        dim, factor = _UNIT[unit]
        return round(count * qty * factor, 6), dim
    m = _SINGLE.search(name)
    if m:
        qty, unit = float(m.group(1).replace(",", ".")), m.group(2).lower()
        dim, factor = _UNIT[unit]
        return round(qty * factor, 6), dim
    return None


def structured_content(sd: dict) -> tuple[float, str] | None:
    """Net content of the base unit from GS1 unitConversions, if present."""
    for u in sd.get("unitConversions") or []:
        if u.get("synkkaPackagingType") != "BASE_UNIT_OR_EACH":
            continue
        vol = u.get("volume") or {}
        if vol.get("unit") in ("LTR", "MLT") and vol.get("value"):
            return vol["value"] * (0.001 if vol["unit"] == "MLT" else 1.0), "l"
        nw = u.get("netWeight") or {}
        if nw.get("unit") in ("KGM", "GRM") and nw.get("value"):
            return nw["value"] * (0.001 if nw["unit"] == "GRM" else 1.0), "kg"
    return None


# ---------------------------------------------------------------- helpers
def _text(items: list | None, lang: str) -> str:
    for it in items or []:
        if it.get("language") == lang and it.get("value"):
            return it["value"]
    return ""


def _classif(sd: dict, name: str) -> list[dict]:
    for c in sd.get("classifications") or []:
        if c.get("name") == name:
            return c.get("values") or []
    return []


def _load_csv(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    with path.open(newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        next(r)
        for row in r:
            if len(row) >= 2 and row[1].strip():
                try:
                    out[row[0].strip()] = float(row[1])
                except ValueError:
                    pass
    return out


SCHEMA = """
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS products_fts;
DROP TABLE IF EXISTS substitutions;
CREATE TABLE products (
  id TEXT PRIMARY KEY,
  name_en TEXT, name_fi TEXT, brand TEXT, vendor TEXT, category TEXT,
  country TEXT, temperature_code INTEGER,
  sales_unit TEXT, base_unit TEXT, base_units_per_sales_unit REAL,
  allowed_lot_size REAL, variable_unit INTEGER, vat_code TEXT, gtin TEXT,
  content_per_base REAL, content_dim TEXT, content_source TEXT,
  content_per_sales_unit REAL,
  has_allergen_data INTEGER,
  allergens_contains TEXT, allergens_may_contain TEXT, free_from TEXT,
  claims TEXT, labels TEXT, sustainability_labels TEXT,
  key_ingredients_en TEXT, key_ingredients_fi TEXT, marketing_en TEXT,
  delivery_reliability REAL, co2_kg_per_kg REAL,
  raw_json TEXT
);
CREATE VIRTUAL TABLE products_fts USING fts5(
  id UNINDEXED, name_en, name_fi, brand, vendor, key_ingredients_en, key_ingredients_fi,
  marketing_en, tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TABLE substitutions (product TEXT, substitute TEXT, PRIMARY KEY (product, substitute));
CREATE INDEX idx_products_category ON products(category);
"""


def build(db_path: Path = DB_PATH) -> int:
    products = json.loads((RAW / "product_data.json").read_text(encoding="utf-8"))
    reliability = _load_csv(RAW / "delivery_reliability.csv")
    co2 = _load_csv(RAW / "carbon_footprint.csv")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)

    rows, fts, subs = [], [], []
    for p in products:
        sd = p.get("synkkaData") or {}
        name_en = _text(sd.get("names"), "en") or _text(sd.get("names"), "fi")
        name_fi = _text(sd.get("names"), "fi")
        units = {u["unitId"]: u.get("sizeInBaseUnits") or 1.0 for u in p.get("units") or []}
        per_sales = float(units.get(p["salesUnit"], 1.0))

        content = structured_content(sd)
        source = "gs1_structured" if content else None
        if not content:
            content = parse_content(name_en) or parse_content(name_fi)
            source = "parsed_from_name" if content else None
        content_base, dim = content if content else (None, None)

        allergen_vals = _classif(sd, "allergen")
        non_allergen = _classif(sd, "nonAllergen")
        contains = sorted({v["id"] for v in allergen_vals if v.get("unit") == "CONTAINS"})
        may_contain = sorted({v["id"] for v in allergen_vals if v.get("unit") == "MAY_CONTAIN"})
        free_from = sorted({v["id"] for v in non_allergen if v.get("unit") == "FREE_FROM"})
        claims = sorted({v["id"] for v in _classif(sd, "nutritionalClaim")})
        labels = sorted({v["id"] for v in _classif(sd, "packagingMarkedLabel")} - TEMPERATURE_LABELS)
        sust = sorted(set(labels) & SUSTAINABILITY_LABELS)

        rows.append((
            p["id"], name_en, name_fi, sd.get("brand"), p.get("vendorName"), p.get("category"),
            p.get("countryOfOrigin"), p.get("temperatureCondition"),
            p["salesUnit"], p.get("baseUnit"), per_sales,
            p.get("allowedLotSize"), int(bool(sd.get("variableUnit"))), sd.get("vatCode"),
            p.get("salesUnitGtin"),
            content_base, dim, source, (content_base * per_sales) if content_base else None,
            int(bool(allergen_vals or non_allergen)),
            json.dumps(contains), json.dumps(may_contain), json.dumps(free_from),
            json.dumps(claims), json.dumps(labels), json.dumps(sust),
            _text(sd.get("keyIngredients"), "en"), _text(sd.get("keyIngredients"), "fi"),
            _text(sd.get("marketingTexts"), "en"),
            reliability.get(p["id"]), co2.get(p["id"]),
            json.dumps(p, ensure_ascii=False),
        ))
        fts.append((p["id"], name_en, name_fi, sd.get("brand") or "", p.get("vendorName") or "",
                    _text(sd.get("keyIngredients"), "en"), _text(sd.get("keyIngredients"), "fi"),
                    _text(sd.get("marketingTexts"), "en")))
        for s in p.get("substitutions") or []:
            subs.append((s["product"], s["substituteProduct"]))

    con.executemany(f"INSERT INTO products VALUES ({','.join('?' * len(rows[0]))})", rows)
    con.executemany("INSERT INTO products_fts VALUES (?,?,?,?,?,?,?,?)", fts)
    con.executemany("INSERT OR IGNORE INTO substitutions VALUES (?,?)", subs)
    con.commit()
    con.close()
    return len(rows)


if __name__ == "__main__":
    n = build()
    print(f"indexed {n} products -> {DB_PATH}")
