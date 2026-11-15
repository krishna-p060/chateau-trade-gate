"""Offers: one product, priced and checked for availability, translated into buyer terms.

An Offer answers: can I get N litres/kg of this product by date D, how many sales units is that,
what does it cost, and how sure are we? Every judgement carries an issue code and a plain-language
explanation so agents and humans see the same reasoning.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from trade_gate.catalog.store import Product
from trade_gate.config import TIMEZONE

TZ = ZoneInfo(TIMEZONE)
# Valio (Discord, 14 Nov): any availableAmount >= 999999 means "stock unknown, any quantity can be
# ordered" (typically Terminal products from supplier warehouses). Empty schedule = not available.
UNKNOWN_STOCK_THRESHOLD = 999_999
TERMINAL_PLACEHOLDER = UNKNOWN_STOCK_THRESHOLD
DEFAULT_RELIABILITY = 0.97               # used when Valio has no history for a product (flagged)


@dataclass
class Issue:
    code: str
    severity: str  # info | warning | blocking
    message: str


@dataclass
class Offer:
    product_id: str
    name: str
    brand: str | None
    sales_unit: str
    content_per_sales_unit: float | None
    content_dim: str | None
    content_source: str | None
    # price (per sales unit)
    unit_price: float | None = None
    unit_price_with_tax: float | None = None
    list_price: float | None = None
    vat_rate: float | None = None
    comparison_price: float | None = None
    comparison_unit: str | None = None
    currency: str = "EUR"
    price_valid_to: str | None = None
    # availability
    logistic_model: str | None = None
    stock_status: str = "unknown"  # confirmed | partial | unconfirmed | untracked | none
    available_amount: float | None = None
    available_date: str | None = None
    closing_time: str | None = None
    cutoff_passed: bool = False
    earliest_delivery: str | None = None
    earliest_delivery_confirmed: bool = False
    sales_block: bool = False
    # quantities for the requested need
    requested_qty: float | None = None
    units_to_order: float | None = None
    delivered_qty: float | None = None
    allowed_lot_size: float | None = None
    total_price: float | None = None
    total_price_with_tax: float | None = None
    price_per_content_unit: float | None = None
    # quality signals
    delivery_reliability: float | None = None
    reliability_known: bool = False
    sustainability_labels: list[str] = field(default_factory=list)
    co2_kg: float | None = None
    allergen_status: str = "not_checked"
    feasible: bool = False
    meets_deadline: bool = False
    issues: list[Issue] = field(default_factory=list)

    def add(self, code: str, severity: str, message: str) -> None:
        self.issues.append(Issue(code, severity, message))

    @property
    def blocking(self) -> bool:
        return any(i.severity == "blocking" for i in self.issues)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["issues"] = [asdict(i) for i in self.issues]
        return d


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def round_up_to_lot(units: float, lot: float | None) -> float:
    lot = lot or 1.0
    if lot <= 0.01:  # effectively any quantity; but sales units are whole packs
        lot = 1.0
    n = math.ceil(units / lot - 1e-9)
    return round(n * lot, 4)


def build_offer(p: Product, price: dict | None, avail: dict | None, *, need_qty: float | None,
                need_dim: str | None, deliver_by: date, now: datetime | None = None) -> Offer:
    """Combine static product data with live Valio price/availability for one buyer need.

    need_dim: 'l' | 'kg' | 'unit' (sales units). need_qty in that dimension.
    """
    now = now or datetime.now(TZ)
    o = Offer(product_id=p.id, name=p.name, brand=p.brand, sales_unit=p.sales_unit,
              content_per_sales_unit=p.content_per_sales_unit, content_dim=p.content_dim,
              content_source=p.content_source, allowed_lot_size=p.allowed_lot_size,
              sustainability_labels=p.sustainability_labels, allergen_status=p.allergen_status)

    # ---------------------------------------------------------------- price
    if not price or price.get("error"):
        o.add("NO_PRICE", "blocking", "Valio returned no price for this product.")
    else:
        cp = price.get("catalogPrice") or {}
        o.unit_price = cp.get("value")
        o.unit_price_with_tax = cp.get("valueWithTax")
        o.list_price = (price.get("listPrice") or {}).get("value")
        o.vat_rate = (price.get("tax") or {}).get("taxRate")
        o.currency = cp.get("currency", "EUR")
        o.price_valid_to = cp.get("validTo")
        comp = price.get("comparisonPrice") or {}
        o.comparison_price = comp.get("value")
        o.comparison_unit = price.get("comparisonUnit")
        # Verify pack content from Valio's own unit price: content = pack price / price per L|KG.
        if o.unit_price and o.comparison_price and o.comparison_unit in ("L", "KG"):
            verified = round(o.unit_price / o.comparison_price, 3)
            dim = o.comparison_unit.lower()
            if p.content_per_sales_unit and p.content_dim == dim:
                drift = abs(verified - p.content_per_sales_unit) / max(verified, 1e-9)
                if drift > 0.08:
                    o.add("CONTENT_MISMATCH", "info",
                          f"Pack content from product name ({p.content_per_sales_unit:g} {dim}) differs from "
                          f"Valio's unit price ({verified:g} {dim}); using Valio's figure.")
                    o.content_per_sales_unit, o.content_dim, o.content_source = verified, dim, "valio_unit_price"
                else:
                    o.content_per_sales_unit, o.content_dim, o.content_source = (
                        p.content_per_sales_unit, dim, "catalog_verified")
            else:
                o.content_per_sales_unit, o.content_dim, o.content_source = verified, dim, "valio_unit_price"

    # ---------------------------------------------------------------- availability
    if not avail:
        o.add("NO_AVAILABILITY", "blocking", "Valio returned no availability for this product.")
    else:
        o.logistic_model = avail.get("logisticModel")
        o.sales_block = bool(avail.get("salesBlock"))
        o.closing_time = avail.get("closingTime")
        lines = avail.get("scheduleLines") or []
        if o.sales_block or any(sl.get("salesBlock") for sl in lines):
            o.sales_block = True
            o.add("SALES_BLOCK", "blocking", "Product is currently blocked from sale.")
        if not lines:
            o.stock_status = "none"
            o.add("NOT_DELIVERABLE", "blocking", "Valio cannot currently deliver this product on any date.")
        else:
            sl = lines[0]
            amount = sl.get("availableAmount") or 0
            o.available_date = sl.get("availableDate")
            if o.logistic_model == "Terminal" or amount >= UNKNOWN_STOCK_THRESHOLD:
                o.stock_status = "unconfirmed"
                o.add("STOCK_UNCONFIRMED", "warning",
                      ("Delivered from a supplier warehouse: " if o.logistic_model == "Terminal" else "")
                      + "Valio does not know the real stock for this product (placeholder quantity), "
                      "so any quantity can be ordered but delivery is not guaranteed.")
            elif amount <= 0:
                o.stock_status = "none"
                o.add("OUT_OF_STOCK", "blocking", "Valio stock is 0.")
            else:
                o.available_amount = amount
                o.stock_status = "confirmed"

        # Order cut-off: after closingTime the goods can no longer arrive on availableDate.
        cut = _parse_dt(o.closing_time)
        avail_d = date.fromisoformat(o.available_date) if o.available_date else None
        earliest = avail_d
        if cut and avail_d:
            if now > cut:
                o.cutoff_passed = True
                lead = max(1, (avail_d - cut.date()).days)
                cand = now.date() + timedelta(days=lead)
                if now.time() > cut.time():
                    cand += timedelta(days=1)
                while cand.weekday() == 6:  # no Sunday deliveries (assumption, documented)
                    cand += timedelta(days=1)
                earliest = max(cand, avail_d)
                o.add("CUTOFF_PASSED", "warning",
                      f"Order cut-off for delivery on {avail_d} was {cut:%a %d %b %H:%M}. "
                      f"Estimated earliest delivery now {earliest} ({lead}-day lead time) — an estimate, "
                      f"not confirmed by Valio.")
            else:
                o.earliest_delivery_confirmed = True
        o.earliest_delivery = earliest.isoformat() if earliest else None
        o.meets_deadline = bool(earliest and earliest <= deliver_by)
        if earliest and not o.meets_deadline:
            o.add("LATE", "blocking" if o.earliest_delivery_confirmed or o.cutoff_passed else "warning",
                  f"Earliest delivery {earliest} is after the requested date {deliver_by}.")

    # ---------------------------------------------------------------- quantity math
    if need_qty is not None:
        o.requested_qty = need_qty
        if need_dim == "unit":
            units = need_qty
        elif o.content_per_sales_unit and o.content_dim == need_dim:
            units = need_qty / o.content_per_sales_unit
        else:
            units = None
            o.add("UNIT_UNKNOWN", "blocking",
                  f"Cannot convert {need_qty:g} {need_dim} into {p.sales_unit} packs: pack content unknown.")
        if units is not None:
            o.units_to_order = round_up_to_lot(units, p.allowed_lot_size)
            if p.allowed_lot_size and p.allowed_lot_size > 1:
                o.add("LOT_SIZE", "info", f"Must be ordered in multiples of {p.allowed_lot_size:g} {p.sales_unit}.")
            if o.content_per_sales_unit and need_dim != "unit":
                o.delivered_qty = round(o.units_to_order * o.content_per_sales_unit, 3)
            if o.stock_status == "confirmed" and o.available_amount is not None \
                    and o.available_amount < o.units_to_order:
                o.stock_status = "partial"
                o.add("PARTIAL_STOCK", "warning",
                      f"Only {o.available_amount:g} {p.sales_unit} in stock; {o.units_to_order:g} needed.")
            if o.unit_price is not None:
                o.total_price = round(o.units_to_order * o.unit_price, 2)
                if o.unit_price_with_tax is not None:
                    o.total_price_with_tax = round(o.units_to_order * o.unit_price_with_tax, 2)
                if o.delivered_qty:
                    o.price_per_content_unit = round(o.total_price / o.delivered_qty, 4)
            # CO2 estimate (product-group average, kg CO2e per kg; litres approximated as kg)
            if p.co2_kg_per_kg and o.delivered_qty and need_dim in ("kg", "l"):
                o.co2_kg = round(p.co2_kg_per_kg * o.delivered_qty, 1)

    # ---------------------------------------------------------------- reliability
    o.reliability_known = p.delivery_reliability is not None
    o.delivery_reliability = p.delivery_reliability if o.reliability_known else DEFAULT_RELIABILITY
    if o.reliability_known and o.delivery_reliability < 0.9:
        o.add("LOW_RELIABILITY", "warning",
              f"Historically only {o.delivery_reliability:.0%} of ordered quantities were delivered.")

    if p.allergen_status == "unknown":
        o.add("ALLERGEN_DATA_MISSING", "warning",
              "Manufacturer has not declared allergens: safety cannot be verified automatically.")

    o.feasible = not o.blocking and o.unit_price is not None and o.units_to_order is not None
    return o
