"""Guardrails: decide whether an order may proceed autonomously.

Three outcomes, each with machine-readable rule ids and plain-language reasons:
  AUTO      — within the mandate; the gate confirms the order immediately.
  APPROVAL  — allowed, but a named human must sign off first.
  BLOCKED   — never allowed (safety or hard limits), even with approval.

Rules are evaluated by the gate (Valio side), independent of what the agent claims.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from trade_gate.catalog.codes import allergen_name, expand_allergen, resolve_allergen
from trade_gate.catalog.store import Catalog
from trade_gate.trust.mandate import Mandate

AUTO, APPROVAL, BLOCKED = "AUTO", "APPROVAL", "BLOCKED"
_RANK = {AUTO: 0, APPROVAL: 1, BLOCKED: 2}


@dataclass
class Finding:
    rule: str
    outcome: str
    message: str
    product_id: str | None = None


@dataclass
class Decision:
    outcome: str
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"outcome": self.outcome, "findings": [asdict(f) for f in self.findings]}

    @property
    def reasons(self) -> list[str]:
        return [f.message for f in self.findings if f.outcome != AUTO]


def evaluate(quote: dict, mandate: Mandate, catalog: Catalog, *, week_spend_eur: float = 0.0,
             reference_prices: dict[str, float] | None = None, related_recent_eur: float = 0.0) -> Decision:
    """Evaluate a signed-and-verified quote against the buyer's mandate."""
    findings: list[Finding] = []

    def add(rule: str, outcome: str, msg: str, pid: str | None = None) -> None:
        findings.append(Finding(rule, outcome, msg, pid))

    total = float(quote["total_price"])
    lim = mandate.limits
    # ------------------------------------------------------------ spend
    if total > lim.hard_max_order_eur:
        add("spend.hard_max", BLOCKED, f"Order total €{total:,.2f} exceeds the hard limit of "
            f"€{lim.hard_max_order_eur:,.0f} set by {mandate.buyer_name}.")
    elif total > lim.auto_approve_max_order_eur:
        add("spend.auto_limit", APPROVAL, f"Order total €{total:,.2f} is above the agent's autonomous limit "
            f"of €{lim.auto_approve_max_order_eur:,.0f}.")
    else:
        add("spend.auto_limit", AUTO, f"Order total €{total:,.2f} is within the autonomous limit "
            f"of €{lim.auto_approve_max_order_eur:,.0f}.")
    if total <= lim.auto_approve_max_order_eur < total + related_recent_eur:
        add("spend.split_order", APPROVAL, f"Orders for the same products in the last 24 h already total "
            f"€{related_recent_eur:,.2f}; together with this one they exceed the autonomous limit, so this "
            f"looks like one purchase split into smaller orders.")
    if week_spend_eur + total > lim.weekly_budget_eur:
        add("spend.weekly_budget", APPROVAL, f"This order would bring this week's spend to "
            f"€{week_spend_eur + total:,.2f}, over the weekly budget of €{lim.weekly_budget_eur:,.0f}.")

    # ------------------------------------------------------------ per line
    avoid: set[str] = set()
    for a in mandate.dietary.avoid_allergens:
        code = resolve_allergen(a)
        if code:
            avoid |= expand_allergen(code)
    ref = reference_prices or {}
    for line in quote["lines"]:
        pid = line["product_id"]
        p = catalog.get(pid)
        name = line.get("name") or pid
        if p is None:
            add("catalog.unknown", BLOCKED, f"{pid} is not in Valio's catalog.", pid)
            continue
        if p.category in mandate.blocked_categories:
            add("category.blocked", BLOCKED, f"{name}: category {p.category} is not allowed for this agent.", pid)
        hit = (set(p.allergens_contains) | set(p.allergens_may_contain)) & avoid
        if hit:
            add("allergen.conflict", BLOCKED, f"{name} contains or may contain "
                f"{', '.join(allergen_name(h) for h in sorted(hit))}, which {mandate.buyer_name} must avoid.", pid)
        elif avoid and not p.has_allergen_data:
            add("allergen.unverified", APPROVAL if mandate.dietary.require_allergen_data else AUTO,
                f"{name} has no allergen declaration; safety cannot be verified automatically.", pid)
        if line.get("stock_status") == "unconfirmed" and mandate.delivery.unconfirmed_stock_needs_approval:
            add("delivery.unconfirmed_stock", APPROVAL,
                f"{name} ships from a supplier warehouse with unknown stock (not guaranteed).", pid)
        if not line.get("earliest_delivery_confirmed", True) and mandate.delivery.estimated_dates_need_approval:
            add("delivery.estimated_date", APPROVAL,
                f"{name}: delivery date {line.get('earliest_delivery')} is our estimate after a passed "
                f"cut-off, not confirmed by Valio.", pid)
        if not line.get("meets_deadline", True):
            add("delivery.late", APPROVAL, f"{name} arrives {line.get('earliest_delivery')}, after the requested "
                f"date {quote.get('deliver_by')}.", pid)
        if line.get("is_substitute"):
            if not mandate.substitution.allowed:
                add("substitution.forbidden", BLOCKED, f"{name} is a substitute; this agent may not substitute.", pid)
            elif line.get("outside_preferences") and mandate.substitution.approval_outside_preferences:
                add("substitution.outside_preferences", APPROVAL,
                    f"{name} replaces {line.get('replaces')} and falls outside stated preferences.", pid)
        if pid in ref and line.get("unit_price"):
            inc = 100 * (line["unit_price"] - ref[pid]) / ref[pid]
            if inc > lim.max_unit_price_increase_pct:
                add("price.increase", APPROVAL, f"{name} costs {inc:.0f}% more than the reference price "
                    f"(€{ref[pid]:.2f} → €{line['unit_price']:.2f}).", pid)

    outcome = max((f.outcome for f in findings), key=_RANK.get, default=AUTO)
    return Decision(outcome, findings)
