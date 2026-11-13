"""Planner: turn a structured buyer need into ranked purchase options (good / better / best).

Pipeline: narrow candidates from the static catalog -> ONE batched price call + ONE batched
availability call -> offers -> single-product and split options -> rank with explicit reasons.
Rejected candidates are returned with their reasons too, so the decision is explainable.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from trade_gate.catalog.store import Catalog, Product
from trade_gate.engine.offers import TZ, Offer, build_offer

CERTAINTY = {"confirmed": 1.0, "untracked": 0.95, "unconfirmed": 0.7, "partial": 0.5, "none": 0.0, "unknown": 0.3}


@dataclass
class Need:
    query: str
    quantity: float
    unit: str  # 'l' | 'kg' | 'unit'
    deliver_by: date
    diets: list[str] = field(default_factory=list)
    avoid_allergens: list[str] = field(default_factory=list)
    require_allergen_data: bool = False
    preferred_labels: list[str] = field(default_factory=list)
    product_ids: list[str] = field(default_factory=list)  # explicit candidates (e.g. from a standing order)
    note: str = ""

    @staticmethod
    def from_dict(d: dict) -> "Need":
        d = dict(d)
        if isinstance(d.get("deliver_by"), str):
            d["deliver_by"] = date.fromisoformat(d["deliver_by"])
        known = {k: d[k] for k in Need.__dataclass_fields__ if k in d}
        return Need(**known)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["deliver_by"] = self.deliver_by.isoformat()
        return d


@dataclass
class Line:
    product_id: str
    name: str
    units: float
    sales_unit: str
    unit_price: float
    total_price: float
    delivered_qty: float | None
    stock_status: str
    earliest_delivery: str | None
    delivery_reliability: float | None


@dataclass
class Option:
    tier: str  # good | better | best | alternative
    title: str
    lines: list[Line]
    total_price: float
    total_price_with_tax: float | None
    delivered_qty: float | None
    overage_pct: float | None
    confidence: float  # 0..1: stock certainty x delivery reliability x deadline confirmation
    meets_deadline: bool
    earliest_delivery: str | None
    sustainability_labels: list[str]
    co2_kg: float | None
    reasons: list[str]
    warnings: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Plan:
    need: Need
    options: list[Option]
    rejected: list[dict]
    offers: list[Offer]
    exception: str | None
    created_at: str

    def to_dict(self, include_offers: bool = False) -> dict:
        d = {"need": self.need.to_dict(), "options": [o.to_dict() for o in self.options],
             "rejected": self.rejected, "exception": self.exception, "created_at": self.created_at}
        if include_offers:
            d["offers"] = [o.to_dict() for o in self.offers]
        return d


def _line(o: Offer, units: float | None = None) -> Line:
    u = units if units is not None else o.units_to_order
    delivered = round(u * o.content_per_sales_unit, 3) if o.content_per_sales_unit else None
    return Line(o.product_id, o.name, u, o.sales_unit, o.unit_price, round(u * o.unit_price, 2), delivered,
                o.stock_status, o.earliest_delivery, o.delivery_reliability)


def _single(o: Offer, need: Need) -> Option:
    conf = CERTAINTY.get(o.stock_status, 0.3) * (o.delivery_reliability or 0.97)
    if not o.earliest_delivery_confirmed:
        conf *= 0.8
    over = None
    if o.delivered_qty and need.unit != "unit":
        over = round(100 * (o.delivered_qty - need.quantity) / need.quantity, 1)
    return Option(
        tier="", title=o.name, lines=[_line(o)], total_price=o.total_price,
        total_price_with_tax=o.total_price_with_tax, delivered_qty=o.delivered_qty, overage_pct=over,
        confidence=round(conf, 3), meets_deadline=o.meets_deadline, earliest_delivery=o.earliest_delivery,
        sustainability_labels=o.sustainability_labels, co2_kg=o.co2_kg, reasons=[],
        warnings=[i.message for i in o.issues if i.severity == "warning"])


def _split(offers: list[Offer], need: Need) -> Option | None:
    """Cover the need from several in-stock products, cheapest per litre/kg first."""
    pool = [o for o in offers if o.meets_deadline and o.stock_status in ("confirmed", "partial", "untracked")
            and o.unit_price and (need.unit == "unit" or o.content_per_sales_unit)]
    pool.sort(key=lambda o: o.price_per_content_unit or o.unit_price)
    remaining, lines = need.quantity, []
    for o in pool:
        if remaining <= 1e-9:
            break
        per = 1.0 if need.unit == "unit" else o.content_per_sales_unit
        want_units = remaining / per
        cap = o.available_amount if o.stock_status in ("confirmed", "partial") else want_units
        units = min(want_units, cap or 0)
        lot = o.allowed_lot_size if o.allowed_lot_size and o.allowed_lot_size > 0.01 else 1.0
        units = (int(units / lot + (1 if units < cap - 1e-9 and units % lot else 0))) * lot
        if units <= 0:
            continue
        lines.append(_line(o, units))
        remaining -= units * per
    if len(lines) < 2 or remaining > 1e-6:
        return None
    total = round(sum(ln.total_price for ln in lines), 2)
    delivered = sum(ln.delivered_qty or 0 for ln in lines) if need.unit != "unit" else None
    by_id = {o.product_id: o for o in offers}
    conf = min(CERTAINTY.get(ln.stock_status, 0.3) * (ln.delivery_reliability or 0.97) for ln in lines)
    return Option(
        tier="", title=f"Split across {len(lines)} in-stock products", lines=lines, total_price=total,
        total_price_with_tax=round(sum(ln.units * (by_id[ln.product_id].unit_price_with_tax or 0) for ln in lines), 2),
        delivered_qty=round(delivered, 3) if delivered else None,
        overage_pct=round(100 * (delivered - need.quantity) / need.quantity, 1) if delivered else None,
        confidence=round(conf, 3), meets_deadline=True,
        earliest_delivery=max(ln.earliest_delivery or "" for ln in lines) or None,
        sustainability_labels=sorted({s for ln in lines for s in by_id[ln.product_id].sustainability_labels}),
        co2_kg=None, reasons=["No single product has confirmed stock for the full quantity by the deadline."],
        warnings=[])


def _rank(options: list[Option], need: Need) -> list[Option]:
    """Pick good (cheapest), better (best value-for-certainty), best (most certain + sustainable)."""
    if not options:
        return []
    cheapest = min(o.total_price for o in options)
    pref = set(need.preferred_labels)

    def value_score(o: Option) -> float:  # lower is better: expected cost of a failed/short delivery
        return o.total_price / cheapest + 2.0 * (1 - o.confidence) + 0.002 * max(o.overage_pct or 0, 0)

    def premium_score(o: Option) -> float:
        lbl = len(set(o.sustainability_labels) | (pref & set(o.sustainability_labels)))
        return -(o.confidence * 3 + 0.3 * lbl) + 0.25 * (o.total_price / cheapest)

    picked: list[Option] = []

    def take(o: Option, tier: str, reason: str) -> None:
        if any(o is p for p in picked):
            o.reasons.append(reason)
            return
        o.tier = tier
        o.reasons.insert(0, reason)
        picked.append(o)

    good = min(options, key=lambda o: (o.total_price, -o.confidence))
    take(good, "good", f"Lowest total price: €{good.total_price:,.2f} excl. VAT.")
    better = min(options, key=value_score)
    take(better, "better", f"Best value once delivery risk is priced in (confidence {better.confidence:.0%}).")
    best = min(options, key=premium_score)
    extra = f" Labels: {', '.join(best.sustainability_labels)}." if best.sustainability_labels else ""
    take(best, "best", f"Highest delivery certainty ({best.confidence:.0%}).{extra}")
    for o in options:
        if not any(o is p for p in picked) and len(picked) < 5:
            o.tier = "alternative"
            picked.append(o)
    return picked


def plan(need: Need, catalog: Catalog, valio, *, now: datetime | None = None, max_candidates: int = 40) -> Plan:
    now = now or datetime.now(TZ)
    dim = need.unit if need.unit in ("l", "kg") else None
    cands: list[Product] = catalog.search(need.query, diets=need.diets, avoid_allergens=need.avoid_allergens,
                                          require_allergen_data=need.require_allergen_data,
                                          content_dim=dim, limit=max_candidates) if need.query else []
    for pid in need.product_ids:
        if all(c.id != pid for c in cands) and (p := catalog.get(pid)):
            cands.append(p)
    if not cands:
        return Plan(need, [], [], [], "NO_CANDIDATES: nothing in the catalog matches the request and its "
                    "dietary/allergen constraints.", now.isoformat())

    ids = [c.id for c in cands]
    prices = valio.prices(ids, need.deliver_by)
    avail = valio.availability(ids, need.deliver_by)
    offers = [build_offer(c, prices.get(c.id), avail.get(c.id), need_qty=need.quantity, need_dim=need.unit,
                          deliver_by=need.deliver_by, now=now) for c in cands]

    singles = [_single(o, need) for o in offers
               if o.feasible and o.meets_deadline and o.stock_status in ("confirmed", "untracked", "unconfirmed")]
    split = _split(offers, need)
    options = singles + ([split] if split else [])
    rejected = [{"product_id": o.product_id, "name": o.name,
                 "reasons": [i.message for i in o.issues if i.severity == "blocking"]
                 or ([f"Only {o.available_amount:g} {o.sales_unit} in stock."] if o.stock_status == "partial" else [])}
                for o in offers if not any(o.product_id == ln.product_id for opt in options for ln in opt.lines)]

    exception = None
    if not options:
        late = [o for o in offers if o.feasible or (o.unit_price and o.units_to_order and not o.sales_block)]
        late = [o for o in late if o.earliest_delivery and o.stock_status != "none"]
        late.sort(key=lambda o: (o.earliest_delivery, o.total_price or 1e12))
        options = [_single(o, need) for o in late[:3]]
        for opt in options:
            opt.tier = "alternative"
            opt.reasons.append(f"Cannot meet {need.deliver_by}; earliest delivery {opt.earliest_delivery}.")
        exception = ("DEADLINE_UNREACHABLE: no option can be delivered by the requested date; "
                     "showing the earliest alternatives. A human must accept the later date.")
        return Plan(need, options, rejected, offers, exception, now.isoformat())

    ranked = _rank(options, need)
    return Plan(need, ranked, rejected, offers, exception, now.isoformat())
