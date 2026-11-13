"""Seed demo buyers: each has its own signing key and a signed purchasing mandate for its agent.

Usage: uv run python -m trade_gate.seed
Writes data/state/buyers/<id>.pem (buyer private key, stays with the buyer) and
data/state/mandates/<id>.jwt (the credential the buyer hands to its agent).
"""
from __future__ import annotations

from trade_gate.config import STATE_DIR
from trade_gate.trust.keys import KeyPair
from trade_gate.trust.mandate import DeliveryRules, DietaryRules, Limits, Mandate, SubstitutionRules, issue

BUYERS = [
    {
        "id": "hotel-aurora",
        "name": "Hotel Aurora Group",
        "profile": {"segment": "Hotel chain, 4 properties in Helsinki", "customer_number": "123",
                    "delivery_address": "Aurora Helsinki Central, Mannerheimintie 1",
                    "preferences": {"labels": ["GOODS_FROM_FINLAND_BLUE_SWAN"], "brands": ["Valio"]},
                    "reference_prices": {}},
        "mandate": Mandate(buyer_id="hotel-aurora", buyer_name="Hotel Aurora Group", agent_id="aurora-procure-bot",
                           limits=Limits(auto_approve_max_order_eur=1500, hard_max_order_eur=20000,
                                         weekly_budget_eur=12000, max_unit_price_increase_pct=15),
                           dietary=DietaryRules(),
                           substitution=SubstitutionRules(allowed=True, approval_outside_preferences=True,
                                                          max_price_increase_pct=10),
                           delivery=DeliveryRules(unconfirmed_stock_needs_approval=True,
                                                  estimated_dates_need_approval=True),
                           approvers=["Laura Mäkinen (F&B Manager)"]),
    },
    {
        "id": "espoo-childrens-hospital",
        "name": "Espoo Children's Hospital Kitchen",
        "profile": {"segment": "Hospital central kitchen, 600 meals/day, paediatric wards", "customer_number": "456",
                    "delivery_address": "Hospital kitchen dock B, Espoo",
                    "preferences": {"labels": [], "brands": []}, "reference_prices": {}},
        "mandate": Mandate(buyer_id="espoo-childrens-hospital", buyer_name="Espoo Children's Hospital Kitchen",
                           agent_id="hospital-kitchen-agent",
                           limits=Limits(auto_approve_max_order_eur=800, hard_max_order_eur=8000,
                                         weekly_budget_eur=6000, max_unit_price_increase_pct=10),
                           dietary=DietaryRules(avoid_allergens=["peanuts", "tree nuts", "sesame"],
                                                require_allergen_data=True),
                           substitution=SubstitutionRules(allowed=True, approval_outside_preferences=True,
                                                          max_price_increase_pct=5),
                           delivery=DeliveryRules(unconfirmed_stock_needs_approval=True,
                                                  estimated_dates_need_approval=True),
                           approvers=["Anna Virtanen (Clinical Dietitian)"]),
    },
]


def seed(gate) -> dict[str, str]:
    """Register demo buyers with the gate; return {buyer_id: mandate_jwt}."""
    out = {}
    for b in BUYERS:
        key = KeyPair.load_or_create(STATE_DIR / "buyers" / f"{b['id']}.pem", kid=f"{b['id']}-key-1")
        gate.register_buyer(b["id"], b["name"], key.jwk(), b["profile"])
        token = issue(b["mandate"], key)
        path = STATE_DIR / "mandates" / f"{b['id']}.jwt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token)
        out[b["id"]] = token
    return out


def load_mandate(buyer_id: str) -> str:
    return (STATE_DIR / "mandates" / f"{buyer_id}.jwt").read_text().strip()


if __name__ == "__main__":
    from trade_gate.service import TradeGate
    from trade_gate.valio_client import ValioClient

    tokens = seed(TradeGate(ValioClient()))
    for k, v in tokens.items():
        print(f"{k}: mandate issued ({len(v)} chars) -> data/state/mandates/{k}.jwt")
