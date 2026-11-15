"""A saved recipe scaled to a number of portions and priced as a cart, in plain code (no model).

Usage: recipe_cart(shop, session_id, recipe_id, portions); POST /api/shop/sessions/{sid}/recipe calls it.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from trade_gate.engine.offers import TZ
from trade_gate.service import GateError
from trade_gate.shop.i18n import eur

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TEXT = {
    "ask": {"en": "{name} for {n} portions, from my saved recipe.",
            "fi": "{name} {n} annokselle tallennetusta reseptistäni."},
    "saved": {"en": "In your saved recipe", "fi": "Tallennetussa reseptissäsi"},
    "usual": {"en": "You buy this regularly", "fi": "Ostat tätä säännöllisesti"},
    "cheapest": {"en": "Lowest price that arrives on time", "fi": "Edullisin, joka ehtii ajoissa"},
    "other": {"en": "Alternative that arrives on time", "fi": "Vaihtoehto, joka ehtii ajoissa"},
    "scaled": {"en": "Recipe for {a} portions scaled to {b}; delivery {day}.",
               "fi": "{a} annoksen resepti skaalattu {b} annokselle; toimitus {day}."},
    "done": {"en": "Built in plain code, no AI: {total} excl. VAT, {per} per portion. Lines marked "
                   "“choose one” are yours to decide; confirming sends the cart to Valio's gate.",
             "fi": "Koottu tavallisella koodilla ilman tekoälyä: {total} alv 0 %, {per} / annos. "
                   "”Valitse yksi” -rivit ovat sinun päätettäviäsi; vahvistus lähettää korin Valion portille."},
}


def next_delivery_day(delivery_days: list[str], today: date) -> date:
    """The customer's first delivery weekday at least two days away, so order-by times are still open."""
    wanted = {WEEKDAYS.index(d) for d in delivery_days if d in WEEKDAYS} - {6} or {0, 1, 2, 3, 4}
    d = today + timedelta(days=2)
    while d.weekday() not in wanted:
        d += timedelta(days=1)
    return d


def recipe_lines(gate, buyer: dict, recipe: dict, portions: int, deliver_by: date, lang: str = "en") -> tuple[list, dict]:
    """Cart lines for the scaled recipe: the recipe's own product where it names one, else up to three
    deliverable candidates from the gate's shortlist (the customer's usual first, then the lowest price)."""
    scale = portions / recipe["portions"]
    agent = (buyer["mandate"] or {}).get("agent_id", "aimo-assistant")
    need = [{"key": f"i{n}", "query": ing["name"], "quantity": round(ing["quantity"] * scale, 3), "unit": ing["unit"]}
            for n, ing in enumerate(recipe["ingredients"]) if not ing.get("product_id")]
    found = gate.shortlist(buyer["id"], agent, need, deliver_by, per_item=6) if need else {"items": [], "summary": {}}
    picks = {it["key"]: sorted((c for c in it["candidates"] if c["delivery"]["on_time"]),
                               key=lambda c: (not c["usual"], c["total"] or 0))[:3] for it in found["items"]}
    lines = []
    for n, ing in enumerate(recipe["ingredients"]):
        if ing.get("product_id"):
            options = [{"product_id": ing["product_id"], "why": TEXT["saved"][lang]}]
        else:
            options = [{"product_id": c["product_id"],
                        "why": TEXT["usual" if c["usual"] else "cheapest" if i == 0 else "other"][lang]}
                       for i, c in enumerate(picks.get(f"i{n}", []))]
        lines.append({"key": f"i{n}", "need": ing["name"], "dish": recipe["name"],
                      "quantity": round(ing["quantity"] * scale, 3), "unit": ing["unit"], "options": options,
                      "decision_needed": len(options) > 1})
    return lines, found["summary"]


def recipe_cart(shop, sid: str, recipe_id: str, portions: int):
    s = shop.get(sid)
    if s.status in ("working", "ordering"):
        raise GateError("BUSY", "Wait for the current step to finish.", 409)
    buyer = shop.gate.buyer(s.customer_id)
    recipe = next((r for r in buyer["profile"].get("recipes", []) if r["id"] == recipe_id), None)
    if not recipe:
        raise GateError("UNKNOWN_RECIPE", f"No saved recipe {recipe_id}.", 404)
    if not 1 <= portions <= 5000:
        raise GateError("BAD_PORTIONS", "Portions must be between 1 and 5,000.")
    lang = s.lang if s.lang in ("en", "fi") else "en"
    day = next_delivery_day(buyer["profile"].get("delivery_days", []), datetime.now(TZ).date())
    shop._msg(s, "user", TEXT["ask"][lang].format(name=recipe["name"], n=portions), notify=False)
    lines, _ = recipe_lines(shop.gate, buyer, recipe, portions, day, lang)
    priced = shop._price_lines(s.customer_id, lines, day)
    s.cart = shop._cart_from(f"{recipe['name']} × {portions}", day, priced,
                             [TEXT["scaled"][lang].format(a=recipe["portions"], b=portions, day=day.isoformat())],
                             portions=portions, customer_id=s.customer_id, lang=lang)
    s.order, s.plan, s.question, s.pending, s.status = None, None, None, None, "cart"
    totals = s.cart["totals"]
    shop._msg(s, "assistant", TEXT["done"][lang].format(total=eur(totals["total"], lang),
                                                        per=eur(totals["per_portion"], lang)), notify=False)
    shop._notify(s)
    return s
