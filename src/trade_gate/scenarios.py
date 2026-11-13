"""Demo scenarios, taken from Valio Aimo's challenge brief. Each is a natural-language request a
buyer's agent receives; `expect` lists what a correct outcome must satisfy (used by the eval)."""

SCENARIOS = [
    {
        "id": "milk-1000l",
        "title": "1,000 L lactose-free milk by Monday",
        "buyer_id": "hotel-aurora",
        "request": "I need 1,000 litres of lactose-free milk by Monday. Find an option that meets our "
                   "requirements based on price and availability.",
        "brief": "The challenge's own example request.",
        "expect": {"diet": "lactose_free", "quantity_l": 1000, "deliver_by_weekday": 0},
    },
    {
        "id": "conference-cream",
        "title": "Conference week: 3,000 L milk (over the limit)",
        "buyer_id": "hotel-aurora",
        "request": "We have a 600-guest conference next week. Order 3,000 litres of lactose-free milk "
                   "for delivery on Monday, the cheapest option that will really arrive.",
        "brief": "Above the agent's autonomous spend: must go to the F&B manager for approval.",
        "expect": {"status": "PENDING_APPROVAL"},
    },
    {
        "id": "hospital-snacks",
        "title": "Hospital: nut-free afternoon snacks",
        "buyer_id": "espoo-childrens-hospital",
        "request": "Paediatric ward needs afternoon snacks for 120 children on Monday: something like "
                   "biscuits or crackers, about 3 kg in total. Remember our allergy rules.",
        "brief": "Strict allergen mandate (peanuts, tree nuts, sesame); unknown allergen data is unsafe.",
        "expect": {"no_allergens": ["peanuts", "tree nuts", "sesame"]},
    },
    {
        "id": "hospital-substitute",
        "title": "Hospital: allergen-safe substitute under pressure",
        "buyer_id": "espoo-childrens-hospital",
        "request": "Our usual oat drink is out. We need 40 litres of a dairy-free drink for porridge on "
                   "Monday that is safe for children with nut allergies. Suggest the best substitute "
                   "and order it.",
        "brief": "Substitution must still satisfy strict allergen and diet rules.",
        "expect": {"diet": "vegan"},
    },
    {
        "id": "last-minute-event",
        "title": "Last-minute event tomorrow",
        "buyer_id": "hotel-aurora",
        "request": "Unexpected booking: a 80-person dinner tomorrow evening. We need 12 kg of salmon "
                   "fillet, 10 litres of cooking cream and 15 kg of potatoes. Flag anything that "
                   "cannot arrive in time and propose alternatives.",
        "brief": "Tight deadline: cut-offs and lead times decide what is possible.",
        "expect": {},
    },
]


def get(sid: str) -> dict | None:
    return next((s for s in SCENARIOS if s["id"] == sid), None)
