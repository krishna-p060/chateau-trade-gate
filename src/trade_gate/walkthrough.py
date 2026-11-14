"""Walkthrough on the bundled sample catalog: a saved recipe priced per portion, ten attempts to get an order
past the gate, then the challenge's own request and six exception cases.

Usage: uv run python -m trade_gate.walkthrough   (no keys, no LLM, no server; exits 1 if any outcome differs)
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from trade_gate import scenarios
from trade_gate.attacks import Attacks, eur, monday_after
from trade_gate.demo import DEMO_NOTE, demo_gate
from trade_gate.engine.offers import TZ
from trade_gate.engine.planner import Need
from trade_gate.seed import seed
from trade_gate.service import GateError, TradeGate
from trade_gate.trust.audit import AuditLog
from trade_gate.trust.keys import KeyPair, verify
from trade_gate.trust.mandate import Mandate, issue

HOTEL, HOSPITAL, CATERER = "hotel-aurora", "espoo-childrens-hospital", "kultakeittio-catering"
SHORT_MILK, NUT_BAR, CRACKERS, CREAM = "462775", "481120", "481212", "464249"


def refusal(fn) -> GateError | None:
    try:
        fn()
    except GateError as e:
        return e
    return None


class Walkthrough:
    def __init__(self, gate: TradeGate, tokens: dict[str, str], work_dir: Path):
        self.gate, self.tokens, self.work_dir = gate, tokens, work_dir
        self.monday = monday_after(datetime.now(TZ).date())
        self.mandates = {b: gate.verify_mandate(b, tokens[b]) for b in (HOTEL, HOSPITAL)}
        self.failed: list[str] = []
        self.passed = 0
        self.blocked_order_id = ""

    def step(self, title: str) -> None:
        print(f"\n{title}")

    def say(self, text: str) -> None:
        print(f"  {text}")

    def check(self, claim: str, ok: bool) -> None:
        print(f"  [{'ok' if ok else 'FAIL'}] {claim}")
        self.passed += ok
        if not ok:
            self.failed.append(claim)

    def plan_milk(self, scenario_id: str, litres: float) -> dict:
        sc = scenarios.get(scenario_id)
        m = self.mandates[HOTEL]
        self.say(f"{m.buyer_name} tells its agent {m.agent_id}: “{sc['request']}”")
        self.say(f"The agent sends the gate a structured need: lactose-free milk, {litres:g} l, "
                 f"by {self.monday:%A %d %b %Y}.")
        before = len(self.gate.valio.calls)
        plan = self.gate.plan(HOTEL, m.agent_id, Need(query="lactose-free milk", quantity=litres, unit="l",
                                                      deliver_by=self.monday, diets=["lactose_free"]))
        calls = [c["endpoint"] for c in self.gate.valio.calls[before:]]
        self.say(f"Plan: {len(plan['options'])} options, {len(plan['rejected'])} products ruled out, "
                 f"from {len(calls)} batched Valio calls ({', '.join(calls)}).")
        for o in plan["options"]:
            ln = o["lines"][0]
            self.say(f"  {o['tier']:<11} {o['title']}: {ln['units']:g} {ln['sales_unit']} × {eur(ln['unit_price'])} "
                     f"= {eur(o['total_price'])}, delivery {o['earliest_delivery']}, confidence {o['confidence']:.0%}")
            for why in o["reasons"] + o["warnings"]:
                self.say(f"              {why}")
        for r in plan["rejected"]:
            self.say(f"  ruled out   {r['name']}: {' '.join(r['reasons'])}")
        self.check("the plan took one price call and one availability call", calls == ["/price", "/availability"])
        self.check("the first option is the cheapest and arrives by Monday",
                   bool(plan["options"]) and plan["options"][0]["tier"] == "good"
                   and all(o["meets_deadline"] for o in plan["options"]))
        return plan

    def quote_and_order(self, buyer: str, lines: list[dict], rationale: str, token: str | None = None,
                        key: str | None = None) -> dict:
        m = self.mandates[buyer]
        q = self.gate.create_quote(buyer, m.agent_id, lines, self.monday)
        body = q["quote"]
        for ln in body["lines"]:
            self.say(f"Quote {body['quote_id']}: {ln['units']:g} {ln['sales_unit']} × {ln['name']} at "
                     f"{eur(ln['unit_price'])} = {eur(ln['line_total'])} excl. VAT, held until "
                     f"{body['expires_at'][11:16]}, signed by the gate.")
        return self.gate.place_order(buyer, m.agent_id, body["quote_id"], token or self.tokens[buyer],
                                     key or str(uuid.uuid4()), rationale)

    def confirmation(self, order: dict) -> dict:
        return verify(order["confirmation_jws"], self.gate.key.jwk())["order"]

    def a_challenge_example(self) -> None:
        self.step("(a) The challenge's own example: 1,000 L lactose-free milk by Monday")
        plan = self.plan_milk("milk-1000l", 1000)
        rejected = {r["product_id"]: " ".join(r["reasons"]) for r in plan["rejected"]}
        self.check("the product with 51 packs in stock is ruled out with that number",
                   "51" in rejected.get(SHORT_MILK, ""))
        best = plan["options"][0]
        m = self.mandates[HOTEL]
        order = self.quote_and_order(HOTEL, [{"product_id": ln["product_id"], "units": ln["units"]}
                                             for ln in best["lines"]], best["reasons"][0])
        self.check("the quote's signature verifies against the gate's public key",
                   self.gate.verify_quote(self.gate.get_quote(order["quote_id"])["signature"])["total_price"]
                   == best["total_price"])
        self.say(f"Order {order['id']}: {order['status']}. {eur(order['total'])} is within the "
                 f"{eur(m.limits.auto_approve_max_order_eur)} the mandate lets the agent spend alone.")
        self.check("the order is CONFIRMED without a human", order["status"] == "CONFIRMED")
        self.check("the signed confirmation verifies and names policy:auto as approver",
                   self.confirmation(order)["approved_by"] == "policy:auto")

    def b_over_the_limit(self) -> None:
        self.step("(b) Above the autonomous limit: 3,000 L goes to the named approver")
        plan = self.plan_milk("conference-cream", 3000)
        best = plan["options"][0]
        m = self.mandates[HOTEL]
        order = self.quote_and_order(HOTEL, [{"product_id": ln["product_id"], "units": ln["units"]}
                                             for ln in best["lines"]], "Cheapest option with confirmed stock.")
        self.say(f"Order {order['id']}: {order['status']}. {' '.join(order['approval']['reasons'])}")
        self.check("the order is PENDING_APPROVAL, not confirmed", order["status"] == "PENDING_APPROVAL"
                   and not order["confirmation_jws"])
        approver = m.approvers[0]
        decided = self.gate.decide(order["approval"]["id"], approver, True, "Conference week, go ahead.")
        self.say(f"{approver} approves in the console: order {decided['id']} is {decided['status']}.")
        self.check("after approval the order is CONFIRMED", decided["status"] == "CONFIRMED")
        self.check("the signed confirmation names the human approver",
                   self.confirmation(decided)["approved_by"] == f"human:{approver}")

    def c_forbidden_allergen(self) -> None:
        self.step("(c) A forbidden allergen: the hospital's agent orders a hazelnut bar")
        m = self.mandates[HOSPITAL]
        p = self.gate.catalog.get(NUT_BAR)
        self.say(f"{m.buyer_name} must avoid {', '.join(m.dietary.avoid_allergens)}. "
                 f"Its agent asks for 1 × {p.name}.")
        order = self.quote_and_order(HOSPITAL, [{"product_id": NUT_BAR, "units": 1}], "Afternoon snack.")
        conflicts = [f["message"] for f in order["decision"]["findings"] if f["rule"] == "allergen.conflict"]
        self.say(f"Order {order['id']}: {order['status']} ({order['decision']['outcome']}). {' '.join(conflicts)}")
        self.check("the order is REJECTED with outcome BLOCKED",
                   order["status"] == "REJECTED" and order["decision"]["outcome"] == "BLOCKED")
        self.check("the reason is the allergen rule", bool(conflicts))
        self.check("nothing was sent for approval: a human cannot override it", self.gate.approvals(HOSPITAL) == [])
        self.blocked_order_id = order["id"]

    def d_wrong_mandate(self) -> None:
        self.step("(d) A foreign mandate and a forged mandate")
        hospital, hotel = self.mandates[HOSPITAL], self.mandates[HOTEL]
        orders_before = len(self.gate.orders())
        q = self.gate.create_quote(HOSPITAL, hospital.agent_id, [{"product_id": CRACKERS, "units": 10}], self.monday)
        foreign = refusal(lambda: self.gate.place_order(HOSPITAL, hospital.agent_id, q["quote"]["quote_id"],
                                                        self.tokens[HOTEL], str(uuid.uuid4()), "foreign mandate"))
        self.say(f"Hospital order presented with {hotel.buyer_name}'s mandate: "
                 f"{foreign.code if foreign else 'accepted'}. {foreign.message if foreign else ''}")
        self.check("the foreign mandate is refused with MANDATE_INVALID",
                   bool(foreign) and foreign.code == "MANDATE_INVALID")

        raised = Mandate.from_credential_subject(self.gate.buyer(HOTEL)["mandate"])
        raised.limits.auto_approve_max_order_eur = raised.limits.hard_max_order_eur = 1_000_000
        forged = issue(raised, KeyPair("attacker-key-1", Ed25519PrivateKey.generate()))
        q = self.gate.create_quote(HOTEL, hotel.agent_id, [{"product_id": "464306", "units": 3000}], self.monday)
        forgery = refusal(lambda: self.gate.place_order(HOTEL, hotel.agent_id, q["quote"]["quote_id"], forged,
                                                        str(uuid.uuid4()), "forged mandate"))
        self.say(f"Hotel mandate rewritten to a {eur(1_000_000)} limit and signed with a key the hotel never "
                 f"registered: {forgery.code if forgery else 'accepted'}. {forgery.message if forgery else ''}")
        self.check("the forged mandate is refused with MANDATE_INVALID",
                   bool(forgery) and forgery.code == "MANDATE_INVALID")
        self.check("neither attempt created an order", len(self.gate.orders()) == orders_before)

    def e_partial_stock(self) -> None:
        self.step("(e) Partial stock: 200 packs asked, 51 in stock")
        p = self.gate.catalog.get(SHORT_MILK)
        e = refusal(lambda: self.gate.create_quote(HOTEL, self.mandates[HOTEL].agent_id,
                                                   [{"product_id": SHORT_MILK, "units": 200}], self.monday))
        self.say(f"Quote for 200 × {p.name}: {e.code if e else 'issued'}. {e.message if e else ''}")
        self.check("the quote is refused with QUOTE_REFUSED", bool(e) and e.code == "QUOTE_REFUSED")
        self.check("the refusal states the exact stock, 51, and the 200 requested",
                   bool(e) and "only 51 ST in stock, 200 requested" in e.message)

    def f_idempotency(self) -> None:
        self.step("(f) The same idempotency key twice")
        m = self.mandates[HOTEL]
        key = str(uuid.uuid4())
        orders_before = len(self.gate.orders(HOTEL))
        first = self.quote_and_order(HOTEL, [{"product_id": CREAM, "units": 10}], "Weekly cream.", key=key)
        again = self.gate.place_order(HOTEL, m.agent_id, first["quote_id"], self.tokens[HOTEL], key, "Weekly cream.")
        self.say(f"First call: order {first['id']} {first['status']}. Retry with key {key[:8]}…: order {again['id']}.")
        self.check("both calls return the same order", first["id"] == again["id"])
        self.check("the hotel has exactly one more order", len(self.gate.orders(HOTEL)) == orders_before + 1)

    def g_audit_chain(self) -> None:
        self.step("(g) The audit trail: intact, and tampering is detected")
        intact = self.gate.audit.verify_chain()
        self.say(f"verify_chain on the gate's log: {intact['checked']} entries, valid={intact['valid']}, "
                 f"head {intact.get('head', '')[:12]}…")
        self.check("the audit chain verifies", intact["valid"])
        entry = next(e for e in self.gate.audit.entries(ref=self.blocked_order_id) if e["event"] == "policy.decision")
        copy = sqlite3.connect(self.work_dir / "audit-copy.sqlite")
        self.gate.con.backup(copy)
        copy.execute("UPDATE audit SET summary=? WHERE seq=?",
                     (entry["summary"].replace("blocked", "within the mandate — confirmed automatically"), entry["seq"]))
        copy.commit()
        tampered = AuditLog(copy, threading.RLock()).verify_chain()
        copy.close()
        self.say(f"On a copy, entry {entry['seq']} (the blocked hazelnut order) is rewritten to read as confirmed: "
                 f"valid={tampered['valid']}, broken at entry {tampered.get('broken_at_seq')}.")
        self.check("the rewritten entry is detected at its own sequence number",
                   not tampered["valid"] and tampered.get("broken_at_seq") == entry["seq"])
        self.check("the gate's own log is untouched", self.gate.audit.verify_chain() == intact)

    def kitchen(self) -> None:
        from trade_gate.shop.assistant import Shop
        from trade_gate.shop.recipe_cart import recipe_cart

        self.step("A kitchen's saved recipe becomes a cart, in plain code: creamy salmon pasta for 80")
        shop = Shop(self.gate)
        s = shop.create(CATERER)
        recipe_cart(shop, s.id, "r-salmon-pasta", 80)
        cart, totals = s.cart, s.cart["totals"]
        self.say(cart["assumptions"][0])
        for ln in cart["lines"]:
            o = ln["options"][0]
            self.say(f"  {ln['quantity']:g} {ln['unit']} {ln['need']}: {o['units']:g} × {o['name']} = {eur(o['total'])} "
                     f"({o['why'].lower()}"
                     + (f"; the chef chooses, {len(ln['options']) - 1} more on screen)" if ln["decision_needed"] else ")"))
        self.say(f"Cart: {eur(totals['total'])} excl. VAT, {eur(totals['per_portion'])} per portion, "
                 f"{totals['co2_kg']:g} kg CO₂, order by {totals['order_by'][:16].replace('T', ' ')}.")
        self.check("every ingredient of the recipe has a deliverable product",
                   all(ln["options"] for ln in cart["lines"]))
        self.check("cost per portion is the cart total divided by 80 portions",
                   totals["per_portion"] == round(totals["total"] / 80, 2) and totals["per_portion"] > 0)
        order = shop._place(s)
        self.say(f"{order['confirmed_by']} confirms: order {order['order_id']} is {order['status']}, signed by the gate.")
        self.check("the chef's confirmed cart is within the mandate and CONFIRMED",
                   order["status"] == "CONFIRMED" and order["signed"])

    def attempts(self) -> None:
        self.step("Ten attempts to get an order past the gate, each on a scratch gate with its own order book")
        attacks = Attacks(self.gate.valio, self.gate.catalog)
        results = [attacks.run(a["id"]) for a in attacks.listing()]
        for n, r in enumerate(results, 1):
            self.say(f"{n}. {r['title']}.")
            for line in r["steps"]:
                self.say(f"    {line}")
            self.say(f"    Gate: {r['verdict']} ({r['code']}). {r['message']}")
            self.check(f"{r['verdict'].lower()} with {r['code']}; {len(r['audit'])} audit entries, {r['ms']} ms",
                       r["stopped"])
        stopped = sum(r["stopped"] for r in results)
        self.say(f"{stopped} of {len(results)} attempts stopped, the slowest in {max(r['ms'] for r in results)} ms.")
        self.say("Staged, in both modes: the 20% price rise and the product that stops being deliverable are "
                 "injected between the gate and its Valio client; everything else is the gate's own answer.")

    def run(self) -> int:
        print(f"Trade Gate walkthrough. {DEMO_NOTE}")
        steps = (self.kitchen, self.attempts, self.a_challenge_example, self.b_over_the_limit, self.c_forbidden_allergen,
                 self.d_wrong_mandate, self.e_partial_stock, self.f_idempotency, self.g_audit_chain)
        for run_step in steps:
            run_step()
        if self.failed:
            print(f"\n{len(self.failed)} outcome(s) differ from what the walkthrough states:")
            for claim in self.failed:
                print(f"  - {claim}")
            return 1
        print(f"\nAll {self.passed} checks hold: every case ended as stated.")
        return 0


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="trade-gate-walkthrough-") as tmp:
        gate = demo_gate(Path(tmp))
        code = Walkthrough(gate, seed(gate), Path(tmp)).run()
        gate.con.close()
        gate.catalog.con.close()
        return code


if __name__ == "__main__":
    sys.exit(main())
