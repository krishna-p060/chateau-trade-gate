"""Demo customers of Valio Aimo: profile, preferences, signed mandate, standing orders, saved recipes.

Each customer has its own signing key and a buyer-signed purchasing mandate. Preferences and rules are
editable in the webshop (PUT /api/shop/customers/{id}/settings); every change re-signs the mandate.

Usage: uv run python -m trade_gate.seed
Writes data/state/buyers/<id>.pem (buyer private key) and data/state/mandates/<id>.jwt (credential).
Synthetic purchase history (8 weeks) is generated into the gate database on first start.
"""
from __future__ import annotations

import copy

from trade_gate.config import STATE_DIR
from trade_gate.trust.keys import KeyPair
from trade_gate.trust.mandate import DeliveryRules, DietaryRules, Limits, Mandate, SubstitutionRules, issue

# Product ids refer to Valio Aimo's challenge catalog (names are read from the catalog at runtime).
BUYERS = [
    {
        "id": "kultakeittio-catering",
        "name": "Kultakeittiö Catering",
        "profile": {
            "segment": "Catering company in Espoo — weddings, company parties and events for 20–400 guests",
            "customer_number": "123", "delivery_address": "Kultakeittiö kitchen, Tekniikantie 3, Espoo",
            "contact": {"name": "Mikko Laine", "role": "Chef-owner"},
            "delivery_days": ["Tuesday", "Friday"],
            "priorities": ["Good price matters most — margins are tight on events",
                           "Must arrive on time: an event cannot move",
                           "Prefer Finnish products when the price is close",
                           "Uses lactose-free dairy by default (guests rarely tell in advance)"],
            "preferences": {"labels": [], "brands": ["Valio"]}, "reference_prices": {},
            "settings": {"auto_confirm_standing_orders": True},
            "standing_orders": [{
                "id": "so-tue-fri", "name": "Tuesday & Friday basics", "weekdays": ["Tuesday", "Friday"],
                "lines": [{"product_id": "475479", "units": 2}, {"product_id": "464249", "units": 12},
                          {"product_id": "469363", "units": 20}, {"product_id": "469440", "units": 2},
                          {"product_id": "463010", "units": 1}, {"product_id": "463982", "units": 1},
                          {"product_id": "466203", "units": 2}, {"product_id": "460198", "units": 2}]}],
            "recipes": [
                {"id": "r-salmon-pasta", "name": "Creamy salmon pasta", "portions": 10, "ingredients": [
                    {"name": "spaghetti", "quantity": 1.0, "unit": "kg", "product_id": "475479"},
                    {"name": "salmon fillet", "quantity": 1.3, "unit": "kg"},
                    {"name": "cooking cream 15% lactose-free", "quantity": 1.2, "unit": "l", "product_id": "464249"},
                    {"name": "dill", "quantity": 0.05, "unit": "kg"},
                    {"name": "grated parmesan", "quantity": 0.1, "unit": "kg", "product_id": "469440"}]},
                {"id": "r-pasta-pesto", "name": "Pasta pesto", "portions": 10, "ingredients": [
                    {"name": "penne pasta", "quantity": 1.2, "unit": "kg"},
                    {"name": "basil pesto", "quantity": 0.4, "unit": "kg"},
                    {"name": "grated parmesan", "quantity": 0.15, "unit": "kg", "product_id": "469440"},
                    {"name": "cherry tomatoes", "quantity": 0.6, "unit": "kg"}]},
                {"id": "r-green-salad", "name": "Green salad", "portions": 10, "ingredients": [
                    {"name": "iceberg lettuce", "quantity": 0.8, "unit": "kg", "product_id": "460198"},
                    {"name": "cucumber", "quantity": 0.4, "unit": "kg"},
                    {"name": "tomato", "quantity": 0.5, "unit": "kg"}]}],
        },
        "mandate": Mandate(buyer_id="kultakeittio-catering", buyer_name="Kultakeittiö Catering",
                           agent_id="aimo-assistant",
                           limits=Limits(auto_approve_max_order_eur=3000, hard_max_order_eur=15000,
                                         weekly_budget_eur=9000, max_unit_price_increase_pct=15),
                           dietary=DietaryRules(),
                           substitution=SubstitutionRules(allowed=True, approval_outside_preferences=True,
                                                          max_price_increase_pct=15),
                           delivery=DeliveryRules(unconfirmed_stock_needs_approval=True,
                                                  estimated_dates_need_approval=True),
                           approvers=["Mikko Laine (Chef-owner)"]),
    },
    {
        "id": "hotel-aurora",
        "name": "Hotel Aurora Group",
        "profile": {
            "segment": "Hotel chain, 4 properties in Helsinki — breakfast buffet, restaurant, conferences",
            "customer_number": "124", "delivery_address": "Aurora Helsinki Central, Mannerheimintie 1",
            "contact": {"name": "Jari Nieminen", "role": "Head chef"},
            "delivery_days": ["Monday", "Wednesday", "Friday"],
            "priorities": ["Quality and Finnish origin first — guests notice",
                           "We report our carbon footprint: prefer lower CO₂ when quality is equal",
                           "Price matters, but not at the cost of quality"],
            "preferences": {"labels": ["GOODS_FROM_FINLAND_BLUE_SWAN"], "brands": ["Valio"]},
            "reference_prices": {},
            "settings": {"auto_confirm_standing_orders": False},
            "standing_orders": [{
                "id": "so-breakfast", "name": "Breakfast buffet (Mon/Wed/Fri)",
                "weekdays": ["Monday", "Wednesday", "Friday"],
                "lines": [{"product_id": "469363", "units": 60}, {"product_id": "464194", "units": 20},
                          {"product_id": "463982", "units": 2}, {"product_id": "477032", "units": 40},
                          {"product_id": "472291", "units": 30}, {"product_id": "461063", "units": 20},
                          {"product_id": "460825", "units": 24}]}],
            "recipes": [
                {"id": "r-skagen", "name": "Toast Skagen", "portions": 10, "ingredients": [
                    {"name": "shrimps", "quantity": 0.8, "unit": "kg"},
                    {"name": "mayonnaise", "quantity": 0.25, "unit": "kg"},
                    {"name": "dill", "quantity": 0.03, "unit": "kg"},
                    {"name": "butter", "quantity": 0.1, "unit": "kg"}]}],
        },
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
        "profile": {
            "segment": "Hospital central kitchen, 600 meals/day, paediatric wards",
            "customer_number": "456", "delivery_address": "Hospital kitchen dock B, Espoo",
            "contact": {"name": "Sanna Korhonen", "role": "Kitchen manager"},
            "delivery_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            "priorities": ["Allergen safety is absolute: no peanuts, tree nuts or sesame — and no products "
                           "without an allergen declaration",
                           "Child-friendly, nutritious food", "Public budget: price matters"],
            "preferences": {"labels": [], "brands": []}, "reference_prices": {},
            "settings": {"auto_confirm_standing_orders": True},
            "standing_orders": [{
                "id": "so-weekday", "name": "Weekday dairy & vegetables", "weekdays": ["Monday", "Wednesday"],
                "lines": [{"product_id": "469363", "units": 80}, {"product_id": "470863", "units": 40},
                          {"product_id": "470952", "units": 30}, {"product_id": "471416", "units": 20}]}],
            "recipes": [
                {"id": "r-porridge", "name": "Oat porridge (dairy-free)", "portions": 100, "ingredients": [
                    {"name": "oat flakes", "quantity": 6.0, "unit": "kg"},
                    {"name": "oat drink", "quantity": 20.0, "unit": "l", "product_id": "470863"}]}],
        },
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


def _key(buyer_id: str, state_dir=STATE_DIR) -> KeyPair:
    return KeyPair.load_or_create(state_dir / "buyers" / f"{buyer_id}.pem", kid=f"{buyer_id}-key-1")


def sign_mandate(m: Mandate, state_dir=STATE_DIR) -> str:
    """Buyer signs its mandate (demo: the buyer's key lives in data/state/buyers; in production it stays
    in the buyer's browser or key store and only the public key is registered with Valio)."""
    token = issue(m, _key(m.buyer_id, state_dir))
    path = state_dir / "mandates" / f"{m.buyer_id}.jwt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token)
    return token


def seed(gate) -> dict[str, str]:
    """Register demo customers with the gate (keeping settings already edited); return {id: mandate_jwt}."""
    out = {}
    sd = getattr(gate, "state_dir", STATE_DIR)
    for b in BUYERS:
        existing = gate.buyer_or_none(b["id"]) if hasattr(gate, "buyer_or_none") else None
        profile = copy.deepcopy(b["profile"])
        mandate = copy.deepcopy(b["mandate"])
        if existing and existing.get("mandate"):  # keep what the customer changed in the webshop
            profile.update({k: existing["profile"][k] for k in ("priorities", "settings", "standing_orders", "recipes") if k in existing["profile"]})
            mandate = Mandate.from_credential_subject(existing["mandate"])
        gate.register_buyer(b["id"], b["name"], _key(b["id"], sd).jwk(), profile, mandate.to_credential_subject())
        out[b["id"]] = sign_mandate(mandate, sd)
    if hasattr(gate, "ensure_history"):
        gate.ensure_history(BUYERS)
    return out


def load_mandate(buyer_id: str, state_dir=STATE_DIR) -> str:
    return (state_dir / "mandates" / f"{buyer_id}.jwt").read_text().strip()


if __name__ == "__main__":
    from trade_gate.service import TradeGate
    from trade_gate.valio_client import ValioClient

    tokens = seed(TradeGate(ValioClient()))
    for k, v in tokens.items():
        print(f"{k}: mandate issued ({len(v)} chars) -> data/state/mandates/{k}.jwt")
