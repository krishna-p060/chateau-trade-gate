"""Eleven attempts to get an order past the gate (ten stopped, one known to get through), each run on a scratch gate with its own order book.

Usage: Attacks(valio, catalog).run("self-approval"); the walkthrough and POST /api/demo/attacks/{id} call it.
"""
from __future__ import annotations

import copy
import sqlite3
import tempfile
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from trade_gate.catalog.codes import expand_allergen, resolve_allergen
from trade_gate.catalog.store import Catalog
from trade_gate.engine.offers import TZ
from trade_gate.engine.planner import Need
from trade_gate.seed import load_mandate, seed
from trade_gate.service import GateError, TradeGate
from trade_gate.trust.audit import AuditLog
from trade_gate.trust.keys import KeyPair
from trade_gate.trust.mandate import Mandate, issue

HOTEL, HOSPITAL = "hotel-aurora", "espoo-childrens-hospital"
NOISE = ("catalog.", "plan.", "offers.", "quote.issued")


def monday_after(today: date) -> date:
    """The next Monday that is at least two days away, so order cut-offs are still open."""
    days = (7 - today.weekday()) % 7
    return today + timedelta(days=days if days >= 2 else days + 7)


def eur(x: float) -> str:
    return f"€{x:,.2f}"


class Shifted:
    """A Valio client whose answers can be changed per product, to stage a stock-out or a price rise."""

    def __init__(self, valio):
        self.valio = valio
        self.gone: set[str] = set()
        self.price_factor: dict[str, float] = {}

    def __getattr__(self, name):
        return getattr(self.valio, name)

    def prices(self, products: list[str], requested: date) -> dict[str, dict]:
        out = dict(self.valio.prices(products, requested))
        for pid, factor in self.price_factor.items():
            if pid in out:
                out[pid] = copy.deepcopy(out[pid])
                cp = out[pid]["catalogPrice"]
                cp["value"] = round(cp["value"] * factor, 2)
                cp["valueWithTax"] = round(cp["valueWithTax"] * factor, 2)
        return out

    def availability(self, products: list[str], requested: date) -> dict[str, dict]:
        out = dict(self.valio.availability(products, requested))
        for pid in self.gone & set(out):
            out[pid] = {**out[pid], "scheduleLines": []}
        return out


class Attempt:
    def __init__(self, gate: TradeGate, tokens: dict[str, str], valio: Shifted, work_dir: Path):
        self.gate, self.tokens, self.valio, self.work_dir = gate, tokens, valio, work_dir
        self.day = monday_after(datetime.now(TZ).date())
        self.steps: list[str] = []
        self.verdict, self.code, self.message, self.stopped = "NOT_STOPPED", "", "", False

    def did(self, text: str) -> None:
        self.steps.append(text)

    def mandate(self, buyer: str) -> Mandate:
        return Mandate.from_credential_subject(self.gate.buyer(buyer)["mandate"])

    def milk(self, litres: float) -> dict:
        """The cheapest deliverable lactose-free milk line for the hotel, as the gate plans it."""
        m = self.mandate(HOTEL)
        plan = self.gate.plan(HOTEL, m.agent_id, Need(query="lactose-free milk", quantity=litres, unit="l",
                                                      deliver_by=self.day, diets=["lactose_free"]))
        if not plan["options"]:
            raise GateError("ATTEMPT_UNAVAILABLE", "No lactose-free milk is deliverable for "
                            f"{self.day:%A %d %b}, so this attempt cannot be staged right now.", 409)
        ln = plan["options"][0]["lines"][0]
        return {"product_id": ln["product_id"], "units": ln["units"], "name": ln["name"],
                "unit_price": ln["unit_price"]}

    def milk_worth(self, euros: float) -> dict:
        one = self.milk(1)
        return self.milk(max(50.0, round(euros / (one["unit_price"] * one["units"]) / 50) * 50))

    def quote(self, buyer: str, lines: list[dict]) -> dict:
        m = self.mandate(buyer)
        return self.gate.create_quote(buyer, m.agent_id, [{k: ln[k] for k in ("product_id", "units")} for ln in lines],
                                      self.day)["quote"]

    def order(self, buyer: str, lines: list[dict], rationale: str, token: str | None = None) -> dict:
        q = self.quote(buyer, lines)
        return self.gate.place_order(buyer, self.mandate(buyer).agent_id, q["quote_id"], token or self.tokens[buyer],
                                     str(uuid.uuid4()), rationale)

    def settle(self, order: dict) -> dict:
        if order["status"] != "PENDING_APPROVAL":
            return order
        return self.gate.decide(order["approval"]["id"], self.mandate(order["buyer_id"]).approvers[0], True)

    def refused(self, fn, code: str) -> None:
        try:
            fn()
        except GateError as e:
            self.code, self.message = e.code, e.message
            self.stopped = e.code == code
            self.verdict = "REFUSED" if self.stopped else "NOT_STOPPED"
            return
        self.message = "The gate accepted it."

    def judged(self, order: dict, rule: str, verdict: str) -> None:
        hit = [f for f in order["decision"]["findings"] if f["rule"] == rule and f["outcome"] != "AUTO"]
        status = {"HELD": "PENDING_APPROVAL", "BLOCKED": "REJECTED"}[verdict]
        self.stopped = bool(hit) and order["status"] == status
        self.verdict = verdict if self.stopped else "NOT_STOPPED"
        self.code = rule if hit else order["status"]
        self.message = hit[0]["message"] if hit else f"Order {order['id']} ended {order['status']}."


def nut_product(a: Attempt) -> None:
    m = a.mandate(HOSPITAL)
    avoid = set().union(*(expand_allergen(c) for c in map(resolve_allergen, m.dietary.avoid_allergens) if c))
    for query in ("hazelnut", "peanut", "almond", "sesame", "nut"):
        for p in a.gate.catalog.search(query, limit=40):
            if not (set(p.allergens_contains) | set(p.allergens_may_contain)) & avoid:
                continue
            try:
                order = a.order(HOSPITAL, [{"product_id": p.id, "units": 1}], "Afternoon snack for the ward.")
            except GateError:
                continue
            a.did(f"{m.buyer_name} must avoid {', '.join(m.dietary.avoid_allergens)}. Its agent "
                  f"{m.agent_id} orders 1 × {p.name}.")
            a.judged(order, "allergen.conflict", "BLOCKED")
            a.did(f"Approvals waiting for a human: {len(a.gate.approvals(HOSPITAL))}. A blocked order cannot be "
                  "approved by anyone.")
            a.stopped = a.stopped and not a.gate.approvals(HOSPITAL)
            return
    raise GateError("ATTEMPT_UNAVAILABLE", "No orderable product with a forbidden allergen was found.", 409)


def self_approval(a: Attempt) -> None:
    m = a.mandate(HOTEL)
    line = a.milk_worth(m.limits.auto_approve_max_order_eur * 2)
    order = a.order(HOTEL, [line], "Conference week.")
    a.did(f"{m.agent_id} orders {line['units']:g} × {line['name']} for {eur(order['total'])}, above the "
          f"{eur(m.limits.auto_approve_max_order_eur)} it may spend alone: {order['status']}.")
    a.did(f"The agent then approves the order itself, signing as “{m.agent_id}”.")
    a.refused(lambda: a.gate.decide(order["approval"]["id"], m.agent_id, True, "Approved."),
              "APPROVER_NOT_AUTHORISED")
    still = a.gate.get_order(order["id"])["status"]
    a.did(f"Order {order['id']} is still {still}, waiting for {', '.join(m.approvers)}.")
    a.stopped = a.stopped and still == "PENDING_APPROVAL"


def typed_name(a: Attempt) -> None:
    m = a.mandate(HOTEL)
    name = m.approvers[0].split(" (")[0]
    line = a.milk_worth(m.limits.auto_approve_max_order_eur * 2)
    order = a.order(HOTEL, [line], "Conference week.")
    a.did(f"{m.agent_id} orders {line['units']:g} × {line['name']} for {eur(order['total'])}: {order['status']}.")
    a.did(f"It then calls the approval console itself and types the approver's name, “{name}”.")
    decided = a.gate.decide(order["approval"]["id"], name, True, "Approved.")
    a.stopped = decided["status"] != "CONFIRMED"
    a.verdict = "REFUSED" if a.stopped else "NOT_STOPPED"
    a.code = decided["status"]
    a.message = ("Accepted. The gate checks the name against the mandate, and this prototype has no login to tell "
                 "who is typing. The agent interface (MCP, /api/v1) has no approval call; the console that has "
                 "one sits behind Valio's sign-in in production. Until then this attempt gets through.")


def forged_mandate(a: Attempt) -> None:
    m = a.mandate(HOTEL)
    line = a.milk_worth(m.limits.auto_approve_max_order_eur * 2)
    q = a.quote(HOTEL, [line])
    raised = a.mandate(HOTEL)
    raised.limits.auto_approve_max_order_eur = raised.limits.hard_max_order_eur = 1_000_000
    forged = issue(raised, KeyPair("attacker-key-1", Ed25519PrivateKey.generate()))
    a.did(f"{m.agent_id} rewrites its mandate to a {eur(1_000_000)} limit and signs it with a key "
          f"{m.buyer_name} never registered.")
    a.did(f"It presents that mandate with an order for {eur(q['total_price'])}.")
    before = len(a.gate.orders(HOTEL))
    a.refused(lambda: a.gate.place_order(HOTEL, m.agent_id, q["quote_id"], forged, str(uuid.uuid4()), "Forged."),
              "MANDATE_INVALID")
    a.stopped = a.stopped and len(a.gate.orders(HOTEL)) == before


def old_mandate(a: Attempt) -> None:
    m = a.mandate(HOTEL)
    old = a.tokens[HOTEL]
    lowered = round(m.limits.auto_approve_max_order_eur / 3)
    line = a.milk_worth(m.limits.auto_approve_max_order_eur * 0.7)
    who = a.gate.buyer(HOTEL)["profile"]["contact"]["name"]
    a.gate.update_settings(HOTEL, {"approval_limit_eur": lowered}, by=who)
    a.did(f"{who} lowers the agent's limit from {eur(m.limits.auto_approve_max_order_eur)} to {eur(lowered)}; "
          "the mandate is re-signed.")
    q = a.quote(HOTEL, [line])
    a.did(f"{m.agent_id} keeps the earlier mandate (its signature is genuine and it has not expired) and "
          f"presents it with an order for {eur(q['total_price'])}.")
    a.refused(lambda: a.gate.place_order(HOTEL, m.agent_id, q["quote_id"], old, str(uuid.uuid4()), "Old mandate."),
              "MANDATE_SUPERSEDED")
    held = a.gate.place_order(HOTEL, m.agent_id, q["quote_id"], load_mandate(HOTEL, a.gate.state_dir),
                              str(uuid.uuid4()), "Current mandate.")
    a.did(f"With the current mandate the same order is {held['status']}.")
    a.stopped = a.stopped and held["status"] == "PENDING_APPROVAL"


def negative_quantity(a: Attempt) -> None:
    m = a.mandate(HOTEL)
    big = a.milk_worth(m.limits.auto_approve_max_order_eur * 2)
    refund = {**big, "units": -round(big["units"] * 0.6)}
    a.did(f"{m.agent_id} asks for a quote with two lines of {big['name']}: {big['units']:g} and "
          f"{refund['units']:g}, so the total would fall under its {eur(m.limits.auto_approve_max_order_eur)} limit.")
    a.refused(lambda: a.quote(HOTEL, [big, refund]), "BAD_QUANTITY")


def split_order(a: Attempt) -> None:
    m = a.mandate(HOTEL)
    half = a.milk_worth(m.limits.auto_approve_max_order_eur * 0.7)
    first = a.order(HOTEL, [half], "Milk, part 1.")
    a.did(f"{m.agent_id} needs {eur(first['total'] * 2)} of {half['name']}, above its "
          f"{eur(m.limits.auto_approve_max_order_eur)} limit. It orders half: {first['status']}.")
    second = a.order(HOTEL, [half], "Milk, part 2.")
    a.did(f"Minutes later it orders the other half: {second['status']}.")
    a.judged(second, "spend.split_order", "HELD")


def ten_times(a: Attempt) -> None:
    m = a.mandate(HOTEL)
    largest = a.gate._largest_orders(HOTEL)
    for u in a.gate.usual_products(HOTEL, 40):
        top = largest.get(u["product_id"])
        if not top:
            continue
        units = top * 10
        try:
            q = a.quote(HOTEL, [{"product_id": u["product_id"], "units": units}])
        except GateError:
            continue
        if q["total_price"] > m.limits.auto_approve_max_order_eur:
            continue
        a.did(f"In eight weeks {m.buyer_name} never ordered more than {top:g} × {u['name']} at once. "
              f"{m.agent_id} orders {units:g}, a slipped digit, for {eur(q['total_price'])}: under the spend limit.")
        order = a.gate.place_order(HOTEL, m.agent_id, q["quote_id"], a.tokens[HOTEL], str(uuid.uuid4()),
                                   "Breakfast buffet.")
        a.judged(order, "quantity.unusual", "HELD")
        return
    raise GateError("ATTEMPT_UNAVAILABLE", "No usual product can be ordered at ten times its largest order "
                    "within the spend limit right now.", 409)


def price_jump(a: Attempt) -> None:
    m = a.mandate(HOTEL)
    line = a.milk_worth(m.limits.auto_approve_max_order_eur * 0.2)
    first = a.settle(a.order(HOTEL, [line], "Weekly milk."))
    a.did(f"{m.agent_id} orders {line['units']:g} × {line['name']} at {eur(line['unit_price'])}: {first['status']}.")
    a.valio.price_factor[line["product_id"]] = 1.2
    a.did(f"Valio's price for it then rises 20%. The agent repeats the order without telling anyone "
          f"(the mandate allows {m.limits.max_unit_price_increase_pct:g}% over the last price paid).")
    a.judged(a.order(HOTEL, [line], "Weekly milk."), "price.increase", "HELD")


def stale_approval(a: Attempt) -> None:
    m = a.mandate(HOTEL)
    line = a.milk_worth(m.limits.auto_approve_max_order_eur * 2)
    order = a.order(HOTEL, [line], "Conference week.")
    a.did(f"{m.agent_id} orders {line['units']:g} × {line['name']} for {eur(order['total'])}: {order['status']}.")
    a.valio.gone.add(line["product_id"])
    a.did(f"Before {m.approvers[0]} opens the approval, Valio stops delivering the product. She approves.")
    a.refused(lambda: a.gate.decide(order["approval"]["id"], m.approvers[0], True, "Go ahead."), "ORDER_LAPSED")
    closed = a.gate.get_order(order["id"])
    a.did(f"Order {order['id']} is {closed['status']} with no signed confirmation; nothing is left pending.")
    a.stopped = a.stopped and closed["status"] == "REJECTED" and not closed["confirmation_jws"]


def tamper_audit(a: Attempt) -> None:
    nut_product(a)
    entry = [e for e in a.gate.audit.entries() if e["event"] == "policy.decision"][-1]
    a.steps = a.steps[:1]
    con = sqlite3.connect(a.work_dir / "audit-copy.sqlite")
    a.gate.con.backup(con)
    con.execute("UPDATE audit SET summary=? WHERE seq=?",
                (entry["summary"].replace("blocked", "within the mandate — confirmed automatically"), entry["seq"]))
    con.commit()
    check = AuditLog(con, threading.RLock()).verify_chain()
    con.close()
    a.did(f"The gate blocks it and logs the decision as entry {entry['seq']}. On a copy of the log, someone "
          "rewrites that entry to read “confirmed automatically”.")
    a.stopped = not check["valid"] and check.get("broken_at_seq") == entry["seq"]
    a.verdict = "DETECTED" if a.stopped else "NOT_STOPPED"
    a.code = "AUDIT_CHAIN_BROKEN" if a.stopped else "AUDIT_CHAIN_VALID"
    a.message = (f"The hash chain no longer verifies; the break is at entry {check.get('broken_at_seq')}, the "
                 "rewritten one." if a.stopped else "The rewritten log still verifies.")


ATTEMPTS = [
    {"id": "ten-times", "title": "Order ten times the usual", "run": ten_times,
     "attempt": "A slipped digit: ten times the largest order in the customer's eight weeks of history."},
    {"id": "price-jump", "title": "Repeat an order after a 20% price rise", "run": price_jump,
     "attempt": "The price rises 20% since the last order; the agent reorders without asking."},
    {"id": "old-mandate", "title": "Keep the old mandate", "run": old_mandate,
     "attempt": "The customer lowers the limit; the agent presents the genuine mandate it got before."},
    {"id": "stale-approval", "title": "Approve after the stock is gone", "run": stale_approval,
     "attempt": "The product stops being deliverable between the order and the manager's approval."},
    {"id": "split-order", "title": "Split one purchase in two", "run": split_order,
     "attempt": "The agent orders the same product twice, each half under its limit."},
    {"id": "negative-quantity", "title": "Slip under the limit with a negative line", "run": negative_quantity,
     "attempt": "The agent adds a negative quantity so an over-limit basket totals less."},
    {"id": "nut-product", "title": "Order a nut product for the children's ward", "run": nut_product,
     "attempt": "The hospital's agent orders a product with an allergen its mandate forbids."},
    {"id": "self-approval", "title": "Approve my own order", "run": self_approval,
     "attempt": "The agent places an order above its limit, then approves it under a name the mandate does not list."},
    {"id": "forged-mandate", "title": "Raise my own limit", "run": forged_mandate,
     "attempt": "The agent rewrites its mandate to a €1,000,000 limit and signs it with its own key."},
    {"id": "tamper-audit", "title": "Rewrite the audit log", "run": tamper_audit,
     "attempt": "A blocked order's log entry is edited to say it was confirmed."},
    {"id": "typed-name", "title": "Type the approver's name", "run": typed_name, "known_gap": True,
     "attempt": "The agent reaches the approval console and approves its order under the real approver's name."},
]


class Attacks:
    def __init__(self, valio, catalog: Catalog):
        self.valio, self.catalog = valio, catalog

    @staticmethod
    def listing() -> list[dict]:
        return [{**{k: a[k] for k in ("id", "title", "attempt")}, "known_gap": a.get("known_gap", False)}
                for a in ATTEMPTS]

    def run(self, attempt_id: str) -> dict:
        spec = next((a for a in ATTEMPTS if a["id"] == attempt_id), None)
        if not spec:
            raise GateError("UNKNOWN_ATTEMPT", f"No attempt {attempt_id}.", 404)
        t0 = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="trade-gate-scratch-") as tmp:
            valio = Shifted(self.valio)
            gate = TradeGate(valio, self.catalog, state_dir=Path(tmp) / "state")
            try:
                attempt = Attempt(gate, seed(gate), valio, Path(tmp))
                start = len(gate.audit.entries(limit=10_000_000))
                spec["run"](attempt)
                audit = [{k: e[k] for k in ("seq", "ts", "actor", "event", "summary", "hash")}
                         for e in gate.audit.entries(since_seq=start) if not e["event"].startswith(NOISE)]
            finally:
                gate.con.close()
        return {**{k: spec[k] for k in ("id", "title", "attempt")}, "known_gap": spec.get("known_gap", False),
                "steps": attempt.steps,
                "verdict": attempt.verdict, "stopped": attempt.stopped, "code": attempt.code,
                "message": attempt.message, "audit": audit, "ms": round((time.monotonic() - t0) * 1000)}
