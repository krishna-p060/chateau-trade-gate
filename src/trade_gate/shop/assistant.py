"""Aimo Assistant: the AI ordering assistant inside Valio Aimo's webshop.

The customer (a chef, a caterer, a hospital kitchen) describes a need in their own words: a menu and
portions, an event, a change to a standing order. The assistant does the busy work — ingredients,
quantities, finding the right products — and hands back a cart the customer confirms. It never orders
on its own; the person in the webshop confirms, and the gate's guardrails still apply (spend limits go
to the named approver, allergen conflicts are blocked).

Architecture (as Valio's mentors suggested): the assistant is surfaced in Valio's own channel, but it
talks to Valio's systems only through the Trade Gate's MCP tools — the same open interface a
customer's own agent would use later. Two UI tools stay local: ask_customer and show_cart.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import anthropic
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from trade_gate.catalog.codes import expand_allergen, resolve_allergen
from trade_gate.agent.buyer_agent import GATE_MCP_URL, _attr, _tool_result_text
from trade_gate.config import AGENT_MODEL, TIMEZONE
from trade_gate.engine.offers import TZ, build_offer
from trade_gate.seed import load_mandate
from trade_gate.service import GateError, TradeGate, _candidate

log = logging.getLogger("trade_gate.shop")
GATE_TOOLS = {"find_products", "check_offers", "get_product"}  # context is loaded by the app itself
MAX_STEPS = 14
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

SYSTEM = """You are Aimo Assistant, the ordering assistant inside Valio Aimo's webshop for professional
kitchens. Today is {today}. You are helping {contact} ({role}) at {customer}.

The customer decides WHAT to serve. You do the busy work: ingredients, quantities, finding the right
products. You never place orders; the customer checks and confirms every step on screen. The customer
context (priorities, rules, usual products, saved recipes, order templates) comes with the first message:
use it instead of asking for things it already answers.

You work through on-screen tools. Keep every text short; the screen shows the details.

PATH A - broad request (a dish, a menu, an event, "food for N people"):
 1. If the number of portions, the delivery or event date, or a dietary need that changes the ingredients
    is not stated, call ask_customer ONCE with all open questions (max 3), each with 2-4 tap-able
    options. Never guess these three things.
 2. Call propose_ingredients: the ingredient list with quantities, for the customer to check and edit.
    - If a saved recipe matches a dish, use it scaled by portions (source "recipe", with its recipe_id).
    - If no saved recipe matches, use professional kitchen quantities per portion (source "estimate").
    - Only what must be bought. Leave out salt, pepper, water and frying oil unless a recipe lists them.
      Round sensibly. Units: kg, l or pcs.
    - Never search products before the customer has approved the list.
 3. The tool returns the customer's final list. It is authoritative: use exactly their items and
    quantities, including rows they added or removed. Then call find_products ONCE for all items, then
    show_cart.

PATH B - specific list (the customer names items with quantities, e.g. "5 kg onions, 2 kg penne"):
 Skip propose_ingredients. If an item is ambiguous in a way that changes the product (type, fat %,
 fresh or frozen, lactose-free) and the customer's history does not settle it, call ask_customer once.
 Then find_products ONCE for all items, then show_cart.

PATH C - a message starting with [Order template check ...]: follow its instructions.

Changing an existing cart: call show_cart again with the complete updated cart.

find_products: short English queries of 1-3 words ("cooking cream", "salmon fillet", "penne"); unit is
'kg', 'l' or 'unit' (pieces/packs). deliver_by is the day before the event unless told otherwise;
delivery days are Monday-Saturday. Call it a second time only for items whose results were thin.

show_cart: per line, option 1 is your recommendation. Add up to 2 alternatives ONLY when they differ in
a way this customer may care about (cheaper, their usual product, lower CO2, Finnish, fresh vs frozen).
Weigh options by the customer's own stated priorities; there is no fixed formula. Prefer what they
usually buy when it fits. Set decision_needed=true when the right choice depends on the customer's
taste or plans: do not decide for them. "why" is at most 8 words and concrete. Reuse the keys of the
ingredient list as line keys. "message" is what you say with the cart: at most 2 short sentences, only
what needs their attention.

Rules: never invent products, prices or stock; use only tool results. Call a product "your usual" only
when its candidate has usual=true. Allergen rules are absolute. If
something cannot arrive in time, say so and offer the closest alternative. Valio Aimo calls recurring
orders "order templates". Do not write text outside the tools unless you are answering a question.
Write in the customer's language (English unless they write Finnish)."""

UI_TOOLS = [
    {
        "name": "ask_customer",
        "description": "Ask the customer up to 3 short questions at once; each is answered with one tap. "
                       "The conversation pauses until they answer. Use it instead of assuming.",
        "input_schema": {
            "type": "object",
            "properties": {"questions": {"type": "array", "minItems": 1, "maxItems": 3, "items": {
                "type": "object",
                "properties": {"id": {"type": "string"},
                               "question": {"type": "string", "description": "Max 12 words."},
                               "options": {"type": "array", "items": {"type": "string"},
                                           "minItems": 2, "maxItems": 4}},
                "required": ["id", "question", "options"]}}},
            "required": ["questions"],
        },
    },
    {
        "name": "propose_ingredients",
        "description": "Show the ingredient list for the customer to check, edit and approve BEFORE any "
                       "product search. The conversation pauses; the tool returns their final list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "e.g. 'Pasta pesto for 40 - Fri 20 Nov'"},
                "deliver_by": {"type": "string", "description": "YYYY-MM-DD"},
                "message": {"type": "string", "description": "One short sentence shown with the list."},
                "dishes": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "portions": {"type": "integer"},
                                   "source": {"type": "string", "enum": ["recipe", "estimate"]},
                                   "recipe_id": {"type": "string"}},
                    "required": ["name", "portions", "source"]}},
                "items": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}, "name": {"type": "string"},
                                   "quantity": {"type": "number"},
                                   "unit": {"type": "string", "enum": ["kg", "l", "pcs"]},
                                   "dish": {"type": "string", "description": "Name of the dish it belongs to."}},
                    "required": ["key", "name", "quantity", "unit", "dish"]}},
            },
            "required": ["title", "deliver_by", "dishes", "items"],
        },
    },
    {
        "name": "show_cart",
        "description": "Show (or replace) the cart in the webshop for the customer to review and confirm. "
                       "Valio prices every option live for the line's quantity (packs are calculated for you).",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "e.g. 'Party for 80 — Sat 21 Nov'"},
                "deliver_by": {"type": "string", "description": "YYYY-MM-DD"},
                "message": {"type": "string", "description": "Max 2 short sentences said with the cart."},
                "assumptions": {"type": "array", "items": {"type": "string"},
                                "description": "Short assumptions the customer should know (max 4)."},
                "portions": {"type": "integer", "description": "Total servings this cart feeds, if it is "
                                                                "for a menu/event (shows cost per portion)."},
                "lines": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "need": {"type": "string", "description": "e.g. 'Cooking cream — salmon pasta'"},
                        "dish": {"type": "string"},
                        "quantity": {"type": "number"},
                        "unit": {"type": "string", "enum": ["kg", "l", "unit"]},
                        "decision_needed": {"type": "boolean"},
                        "replaces": {"type": "string", "description": "product_id this line substitutes"},
                        "options": {"type": "array", "minItems": 1, "maxItems": 3, "items": {
                            "type": "object",
                            "properties": {"product_id": {"type": "string"}, "why": {"type": "string"}},
                            "required": ["product_id", "why"]}},
                    },
                    "required": ["key", "need", "quantity", "unit", "options"]}},
            },
            "required": ["title", "deliver_by", "message", "lines"],
        },
    },
]


def _now() -> datetime:
    return datetime.now(TZ)


def _mid() -> str:
    return secrets.token_hex(4)


@dataclass
class Session:
    id: str
    customer_id: str
    status: str = "idle"  # idle | working | waiting (questions) | review (ingredients) | cart | ordering | ordered
    messages: list[dict] = field(default_factory=list)
    cart: dict | None = None
    order: dict | None = None
    question: dict | None = None
    plan: dict | None = None
    ctx_loaded: bool = False
    system: str | None = None
    llm: list[dict] = field(default_factory=list)
    pending: dict | None = None  # {"kind": "question"|"plan", "tool_use_id": ..., "other_results": [...]}
    listeners: set = field(default_factory=set)
    task: asyncio.Task | None = None

    def snapshot(self) -> dict:
        step = ("order" if self.order else "products" if self.cart
                else "ingredients" if self.plan else "request")
        return {"id": self.id, "customer_id": self.customer_id, "status": self.status, "step": step,
                "busy": self.status in ("working", "ordering"), "messages": self.messages,
                "question": self.question, "plan": self.plan, "cart": self.cart, "order": self.order}


class Shop:
    def __init__(self, gate: TradeGate, model: str = AGENT_MODEL, gate_url: str = GATE_MCP_URL):
        self.gate, self.model, self.gate_url = gate, model, gate_url
        self.sessions: dict[str, Session] = {}

    # ------------------------------------------------------------------ session plumbing
    def create(self, customer_id: str) -> Session:
        b = self.gate.buyer(customer_id)
        s = Session(id=f"s_{uuid.uuid4().hex[:10]}", customer_id=b["id"])
        contact = b["profile"].get("contact") or {}
        self._msg(s, "assistant", f"Hi {contact.get('name', '').split(' ')[0] or 'there'}! Tell me what you're "
                  f"cooking, or give me a shopping list. You approve every step before anything is ordered.", notify=False)
        self.sessions[s.id] = s
        return s

    def get(self, sid: str) -> Session:
        if sid not in self.sessions:
            raise GateError("UNKNOWN_SESSION", "No such session.", 404)
        return self.sessions[sid]

    def _notify(self, s: Session) -> None:
        snap = s.snapshot()
        for q in list(s.listeners):
            q.put_nowait(snap)

    def _msg(self, s: Session, role: str, text: str, notify: bool = True, **extra) -> dict:
        m = {"id": _mid(), "role": role, "text": text, "ts": _now().isoformat(timespec="seconds"), **extra}
        s.messages.append(m)
        if notify:
            self._notify(s)
        return m

    def _start(self, s: Session, coro) -> None:
        if s.status in ("working", "ordering"):
            raise GateError("BUSY", "The assistant is still working on your previous message.", 409)
        s.status = "working"
        self._notify(s)

        async def runner():
            try:
                await coro
            except Exception as e:  # show the problem instead of hanging
                root = e
                while isinstance(root, BaseExceptionGroup) and root.exceptions:
                    root = root.exceptions[0]
                log.exception("assistant run failed in session %s", s.id, exc_info=root)
                self._msg(s, "error", f"Something went wrong: {type(root).__name__}: {str(root)[:300]}",
                          notify=False)
                s.status = "cart" if s.cart else "idle"
            self._notify(s)
        s.task = asyncio.create_task(runner())

    # ------------------------------------------------------------------ customer actions
    @staticmethod
    def _user_turn(s: Session, text: str) -> None:
        """Add customer text to the model history (after a finished tool turn it joins that user turn)."""
        if s.llm and s.llm[-1]["role"] == "user" and isinstance(s.llm[-1]["content"], list):
            s.llm[-1]["content"].append({"type": "text", "text": text})
        else:
            s.llm.append({"role": "user", "content": text})

    def _resume(self, s: Session, result: str) -> None:
        """Hand the customer's on-screen answer back to the model as the paused tool's result."""
        results = s.pending["other_results"] + [{"type": "tool_result", "tool_use_id": s.pending["tool_use_id"],
                                                 "content": result}]
        s.pending, s.question = None, None
        s.llm.append({"role": "user", "content": results})
        self._start(s, self._run(s))

    def send(self, sid: str, text: str) -> Session:
        s = self.get(sid)
        text = text.strip()
        if not text:
            raise GateError("EMPTY", "Message is empty.")
        if s.status in ("working", "ordering"):
            raise GateError("BUSY", "The assistant is still working on your previous message.", 409)
        self._msg(s, "user", text, notify=False)
        if s.pending and s.pending["kind"] == "plan":
            s.plan["status"] = "revising"
            self._resume(s, f"The customer has NOT approved the list yet. They wrote: “{text}”. "
                            f"Update the list and call propose_ingredients again.")
        elif s.pending:
            self._resume(s, f"Customer answered in their own words: {text}")
        else:
            prefix = ""
            if s.order and s.order.get("status") in ("CONFIRMED", "PENDING_APPROVAL"):
                prefix = "(The previous cart was already ordered; this is a new request.) "
                s.cart, s.order, s.plan = None, None, None
            self._user_turn(s, prefix + text)
            self._start(s, self._run(s))
        return s

    def answer(self, sid: str, answers: dict[str, str]) -> Session:
        s = self.get(sid)
        if not s.pending or s.pending["kind"] != "question" or not s.question:
            raise GateError("NO_QUESTION", "There is no open question.", 409)
        qs = s.question["questions"]
        missing = [q["text"] for q in qs if not (answers.get(q["id"]) or "").strip()]
        if missing:
            raise GateError("ANSWER_ALL", "Please answer: " + "; ".join(missing), 409)
        self._msg(s, "user", " · ".join(answers[q["id"]].strip() for q in qs), notify=False)
        self._resume(s, "Customer answered:\n" + "\n".join(f"- {q['text']} -> {answers[q['id']].strip()}" for q in qs))
        return s

    def approve_plan(self, sid: str, items: list[dict], save_recipes: list[str] | None = None) -> Session:
        s = self.get(sid)
        if not s.pending or s.pending["kind"] != "plan" or not s.plan:
            raise GateError("NO_PLAN", "There is no ingredient list waiting for approval.", 409)
        b = self.gate.buyer(s.customer_id)
        who = (b["profile"].get("contact") or {}).get("name", "Customer")
        before = {it["key"]: it for it in s.plan["items"]}
        final, changes, seen = [], [], set()
        for n, it in enumerate(items):
            name = (it.get("name") or "").strip()
            qty = float(it.get("quantity") or 0)
            if not name or qty <= 0:
                continue
            unit = it.get("unit") if it.get("unit") in ("kg", "l", "pcs") else "kg"
            old = before.get(it.get("key") or "")
            key = old["key"] if old else f"x{n}"
            seen.add(key)
            final.append({"key": key, "name": name, "quantity": qty, "unit": unit,
                          "dish": it.get("dish") or (old or {}).get("dish"),
                          "source": (old or {}).get("source", "added"), "edited": False})
            if not old:
                changes.append(f"added {name} {qty:g} {unit}")
                final[-1]["edited"] = True
            elif (old["quantity"], old["unit"], old["name"]) != (qty, unit, name):
                changes.append(f"{old['name']}: {old['quantity']:g} {old['unit']} → "
                               + (f"{name} " if name != old["name"] else "") + f"{qty:g} {unit}")
                final[-1]["edited"] = True
        changes += [f"removed {it['name']}" for k, it in before.items() if k not in seen]
        if not final:
            raise GateError("EMPTY_PLAN", "The list is empty.", 409)
        s.plan.update(items=final, status="approved", changes=changes)
        self.gate.audit.append(
            buyer_id=s.customer_id, actor=f"human:{who}", event="plan.approved",
            summary=f"{who} approved the ingredient list “{s.plan['title']}” ({len(final)} items"
                    + (f"; changes: {'; '.join(changes)}" if changes else ", unchanged") + ").",
            data={"items": final, "changes": changes, "dishes": s.plan["dishes"]})
        saved = []
        for d in s.plan["dishes"]:
            if d["name"] in (save_recipes or []) and d["source"] == "estimate":
                ing = [{"name": it["name"], "quantity": it["quantity"], "unit": it["unit"]}
                       for it in final if it.get("dish") == d["name"]]
                if ing:
                    self.gate.add_recipe(s.customer_id, d["name"], d["portions"], ing, by=who)
                    d["saved"] = True
                    saved.append(d["name"])
        self._msg(s, "user", "Ingredients approved" + (f" ({len(changes)} change{'s' if len(changes) != 1 else ''})"
                                                       if changes else ""), notify=False)
        if saved:
            self._msg(s, "progress", "Saved as your recipe: " + ", ".join(saved), notify=False)
        self._resume(s, json.dumps({
            "approved": True, "by": who, "changes": changes,
            "items": [{k: it[k] for k in ("key", "name", "quantity", "unit", "dish")} for it in final],
            "note": "Use exactly these items and quantities. Unit 'pcs' is 'unit' in find_products/show_cart.",
        }, ensure_ascii=False))
        return s

    def select(self, sid: str, key: str, option: int) -> Session:
        s = self.get(sid)
        line = self._line(s, key)
        if not 0 <= option < len(line["options"]):
            raise GateError("BAD_OPTION", "No such option.")
        line["selected"] = option
        line["decision_needed"] = False
        self._totals(s.cart)
        self._notify(s)
        return s

    def remove(self, sid: str, key: str) -> Session:
        s = self.get(sid)
        self._line(s, key)
        s.cart["lines"] = [ln for ln in s.cart["lines"] if ln["key"] != key]
        self._totals(s.cart)
        self._notify(s)
        return s

    def set_reference(self, sid: str, reference: str) -> Session:
        s = self.get(sid)
        if not s.cart:
            raise GateError("NO_CART", "There is no cart yet.", 409)
        s.cart["reference"] = reference.strip()[:80]
        self._notify(s)
        return s

    def save_template(self, sid: str, name: str) -> Session:
        s = self.get(sid)
        if not s.cart or not s.cart["lines"]:
            raise GateError("NO_CART", "There is nothing to save.", 409)
        b = self.gate.buyer(s.customer_id)
        who = (b["profile"].get("contact") or {}).get("name", "Customer")
        lines = [{"product_id": ln["options"][ln["selected"]]["product_id"],
                  "units": ln["options"][ln["selected"]]["units"]} for ln in s.cart["lines"] if ln["options"]]
        wd = [WEEKDAYS[date.fromisoformat(s.cart["deliver_by"]).weekday()]]
        tpl = self.gate.add_order_template(s.customer_id, name or s.cart["title"], lines, wd, by=who)
        s.cart["saved_template"] = tpl["name"]
        self._msg(s, "notice", f"Saved as order template “{tpl['name']}” ({len(lines)} products). "
                  f"You'll find it under your order templates.", notify=False)
        self._notify(s)
        return s

    def notify_when_back(self, sid: str, key: str) -> Session:
        s = self.get(sid)
        ln = self._line(s, key)
        if not ln.get("replaces"):
            raise GateError("NOT_REPLACED", "This line is not a substitute.", 409)
        b = self.gate.buyer(s.customer_id)
        self.gate.signal(s.customer_id, "notify",
                         f"{b['name']} wants to be notified when {ln['replaces']['name']} is available again.",
                         {"product": ln["replaces"]})
        ln["notify"] = True
        self._notify(s)
        return s

    def _line(self, s: Session, key: str) -> dict:
        if not s.cart:
            raise GateError("NO_CART", "There is no cart yet.", 409)
        for ln in s.cart["lines"]:
            if ln["key"] == key:
                return ln
        raise GateError("UNKNOWN_LINE", f"No cart line {key}.", 404)

    async def confirm(self, sid: str) -> Session:
        s = self.get(sid)
        if not s.cart or not s.cart["lines"]:
            raise GateError("NO_CART", "There is nothing to order.", 409)
        if s.status in ("working", "ordering"):
            raise GateError("BUSY", "Please wait a moment.", 409)
        undecided = [ln["need"] for ln in s.cart["lines"] if ln.get("decision_needed")]
        if undecided:
            raise GateError("CHOICE_NEEDED", "Please choose a product for: " + ", ".join(undecided), 409)
        s.status = "ordering"
        self._notify(s)
        try:
            order = await asyncio.to_thread(self._place, s)
        except GateError as e:
            s.status = "cart"
            self._msg(s, "error", f"Valio could not take this order yet: {e.message}")
            return s
        s.order = order
        s.status = "ordered"
        if order["status"] == "CONFIRMED":
            text = (f"Order {order['order_id']} is confirmed — €{order['total']:,.2f} excl. VAT, delivery "
                    f"{_day(order['delivery'])}. Valio has signed the confirmation.")
        elif order["status"] == "PENDING_APPROVAL":
            text = (f"Sent to {order['approver'] or 'your approver'} for approval: " + " ".join(order["reasons"][:2]))
        else:
            text = "Valio could not accept this order: " + " ".join(order["reasons"][:2])
        self._msg(s, "notice", text, notify=False, order_id=order["order_id"], status=order["status"])
        self._notify(s)
        return s

    def _place(self, s: Session, auto: bool = False) -> dict:
        b = self.gate.buyer(s.customer_id)
        contact = b["profile"].get("contact") or {}
        who = f"{contact.get('name', 'Customer')} ({contact.get('role', 'buyer')})"
        token = load_mandate(s.customer_id, self.gate.state_dir)
        m = self.gate.verify_mandate(s.customer_id, token)
        cart = s.cart
        lines = []
        for ln in cart["lines"]:
            opt = ln["options"][ln["selected"]]
            lines.append({"product_id": opt["product_id"], "units": opt["units"],
                          **({"is_substitute": True, "replaces": ln["replaces"]["product_id"]}
                             if ln.get("replaces") else {})})
        q = self.gate.create_quote(s.customer_id, m.agent_id, lines, date.fromisoformat(cart["deliver_by"]),
                                   note=" · ".join(x for x in (cart.get("reference"), cart.get("title")) if x))
        o = self.gate.place_order(s.customer_id, m.agent_id, q["quote"]["quote_id"], token, str(uuid.uuid4()),
                                  rationale=f"Cart prepared by Aimo Assistant: {cart.get('title', '')}",
                                  confirmed_by=None if auto else who)
        # signals for Valio Aimo: substitutions and preferences the customer expressed in the cart
        for ln in cart["lines"]:
            opt = ln["options"][ln["selected"]]
            if ln.get("replaces"):
                self.gate.signal(s.customer_id, "substitution",
                                 f"{b['name']} accepted {opt['name']} instead of {ln['replaces']['name']} "
                                 f"(unavailable).",
                                 {"from": ln["replaces"], "to": {"product_id": opt["product_id"], "name": opt["name"]},
                                  "order_id": o["id"], "option_rank": ln["selected"] + 1})
            elif ln["selected"] > 0:
                first = ln["options"][0]
                self.gate.signal(s.customer_id, "preference",
                                 f"{b['name']} chose {opt['name']} over the suggested {first['name']} "
                                 f"for “{ln['need']}”.",
                                 {"suggested": first["product_id"], "chosen": opt["product_id"], "need": ln["need"],
                                  "order_id": o["id"]})
        approver = (o.get("approval") or {}).get("approver") or (m.approvers[0] if m.approvers else None)
        return {"order_id": o["id"], "status": o["status"], "total": o["total"],
                "total_with_tax": o["quote"]["total_price_with_tax"],
                "delivery": (cart["deliver_by"] if all(ln.get("meets_deadline", True) for ln in o["quote"]["lines"])
                             else max(ln["earliest_delivery"] or "" for ln in o["quote"]["lines"])),
                "reasons": [f["message"] for f in (o.get("decision") or {}).get("findings", [])
                            if f["outcome"] != "AUTO"],
                "accepted": [f["message"] for f in (o.get("decision") or {}).get("findings", [])
                             if "accepted by" in f["message"]],
                "approver": approver if o["status"] == "PENDING_APPROVAL" else None,
                "confirmed_by": None if auto else who, "signed": bool(o.get("confirmation_jws")),
                "reference": cart.get("reference") or None,
                "quote_signed": True}

    def refresh_order(self, s: Session) -> None:
        if s.order and s.order["status"] == "PENDING_APPROVAL":
            o = self.gate.get_order(s.order["order_id"])
            if o["status"] != "PENDING_APPROVAL":
                s.order.update(status=o["status"], signed=bool(o.get("confirmation_jws")),
                               approver=(o.get("approval") or {}).get("approver") or s.order.get("approver"),
                               note=(o.get("approval") or {}).get("note"))
                verb = "approved" if o["status"] == "CONFIRMED" else "rejected"
                self._msg(s, "notice", f"{s.order['approver']} {verb} order {o['id']}."
                          + (f" Note: “{s.order['note']}”" if s.order.get("note") else ""),
                          order_id=o["id"], status=o["status"])

    # ------------------------------------------------------------------ standing order check
    def standing_order(self, sid: str, so_id: str) -> Session:
        s = self.get(sid)
        b = self.gate.buyer(s.customer_id)
        so = next((x for x in b["profile"].get("standing_orders", []) if x["id"] == so_id), None)
        if not so:
            raise GateError("UNKNOWN_STANDING_ORDER", f"No standing order {so_id}.", 404)
        self._msg(s, "user", f"Check my order template “{so['name']}” for the next delivery.", notify=False)
        s.cart, s.order, s.plan = None, None, None
        self._start(s, self._run_standing(s, b, so))
        return s

    async def _run_standing(self, s: Session, b: dict, so: dict) -> None:
        today = _now().date()
        wd = {WEEKDAYS.index(w) for w in so["weekdays"]}
        d = today + timedelta(days=1)
        while d.weekday() not in wd:
            d += timedelta(days=1)
        lines = await asyncio.to_thread(self._price_lines, s.customer_id,
                                        [{"key": f"so{i}", "need": "", "quantity": ln["units"], "unit": "unit",
                                          "options": [{"product_id": ln["product_id"], "why": "From your order template"}]}
                                         for i, ln in enumerate(so["lines"])], d)
        ok, bad = [], []
        for ln, src in zip(lines, so["lines"]):
            opt = ln["options"][0] if ln["options"] else None
            name = (opt or {}).get("name") or (self.gate.catalog.get(src["product_id"]).name
                                               if self.gate.catalog.get(src["product_id"]) else src["product_id"])
            ln["need"] = name
            if opt and opt["delivery"]["on_time"] and "not available" not in opt["stock"]:
                ok.append(ln)
            else:
                why = ln.get("problem") or ((opt or {}).get("notes") or ["not available"])[0]
                bad.append((ln, src, name, why))
        self._msg(s, "progress", f"Checked {len(lines)} order-template items for {_day(d.isoformat())}: "
                  f"{len(ok)} available, {len(bad)} with problems.", notify=False)
        auto = (b["profile"].get("settings") or {}).get("auto_confirm_standing_orders")
        if not bad:
            s.cart = self._cart_from(f"{so['name']} — {_day(d.isoformat())}", d, ok, [],
                                     customer_id=s.customer_id)
            if auto:
                s.status = "ordering"
                self._notify(s)
                s.order = await asyncio.to_thread(self._place, s, True)
                s.status = "ordered"
                self._msg(s, "notice", f"Everything in “{so['name']}” is available, so I confirmed it automatically "
                          f"as your settings allow: €{s.order['total']:,.2f}, delivery {_day(d.isoformat())}.",
                          notify=False, order_id=s.order["order_id"], status=s.order["status"])
            else:
                s.status = "cart"
                self._msg(s, "assistant", "Everything is available. Review the cart and confirm when ready.",
                          notify=False)
            return
        problems = "\n".join(
            f"- key so{lines.index(ln)}: {name} (product {src['product_id']}), usual {src['units']:g} "
            f"{(ln['options'][0]['sales_unit'] if ln['options'] else 'units')}"
            f"{_content_hint(self.gate, src['product_id'], src['units'])} — problem: {why}"
            for ln, src, name, why in bad)
        keep = "\n".join(f"- key {ln['key']}: {ln['need']} — {ln['options'][0]['units']:g} "
                         f"{ln['options'][0]['sales_unit']} (product {ln['options'][0]['product_id']}) OK"
                         for ln in ok)
        self._user_turn(s, (
                      f"[Order template check by Valio for delivery {d.isoformat()} — '{so['name']}']\n"
                      f"Available:\n{keep}\nProblems:\n{problems}\n\n"
                      f"Find substitutes for the problem items (find_products with replaces=<product_id>, "
                      f"quantity in kg/l when the pack content is known), then show_cart with ALL lines: "
                      f"available lines unchanged as a single option with quantity in 'unit' (packs), and each "
                      f"substitute line with replaces set and up to 3 options, decision_needed=true. In the "
                      f"cart message say in one or two sentences what changed."))
        await self._run(s)

    # ------------------------------------------------------------------ cart building
    def _price_lines(self, customer_id: str, lines: list[dict], deliver_by: date) -> list[dict]:
        """Price every option of every line live (one batched call per endpoint) for its quantity."""
        ids = list(dict.fromkeys(o["product_id"] for ln in lines for o in ln.get("options", [])))
        prods = {p.id: p for p in self.gate.catalog.get_many(ids)}
        prices = self.gate.valio.prices(list(prods), deliver_by) if prods else {}
        avail = self.gate.valio.availability(list(prods), deliver_by) if prods else {}
        usual = {u["product_id"]: u for u in self.gate.usual_products(customer_id, 200)}
        out = []
        for i, ln in enumerate(lines):
            unit = (ln.get("unit") or "unit").lower()
            opts, problem = [], None
            rp0 = self.gate.catalog.get(ln["replaces"]) if ln.get("replaces") else None
            rep_subs = set(rp0.substitutes) if rp0 else set()
            for o in ln.get("options", [])[:3]:
                p = prods.get(o["product_id"])
                if not p:
                    problem = f"Unknown product {o['product_id']}"
                    continue
                off = build_offer(p, prices.get(p.id), avail.get(p.id), need_qty=float(ln["quantity"]),
                                  need_dim=unit, deliver_by=deliver_by)
                hard = [x for x in off.issues if x.severity == "blocking" and x.code != "LATE"]
                if hard:
                    problem = f"{p.name}: {hard[0].message}"
                    continue
                c = _candidate(p, off, usual.get(p.id), bool(rep_subs and p.id in rep_subs), deliver_by)
                c["why"] = o.get("why", "")
                opts.append(c)
            rep = None
            if ln.get("replaces"):
                rp = self.gate.catalog.get(ln["replaces"])
                rep = {"product_id": ln["replaces"], "name": rp.name if rp else ln["replaces"]}
            out.append({"key": ln.get("key") or f"l{i}", "need": ln.get("need", ""), "dish": ln.get("dish"),
                        "quantity": ln["quantity"], "unit": unit, "decision_needed": bool(ln.get("decision_needed"))
                        and len(opts) > 1, "replaces": rep, "selected": 0, "options": opts, "problem": problem})
        return out

    def _cart_from(self, title: str, deliver_by: date, lines: list[dict], assumptions: list[str],
                   portions: int | None = None, customer_id: str | None = None) -> dict:
        cart = {"customer_id": customer_id, "title": title, "deliver_by": deliver_by.isoformat(), "assumptions": assumptions[:4],
                "lines": lines, "portions": portions or None, "reference": "",
                "updated": _now().isoformat(timespec="seconds")}
        self._totals(cart)
        return cart

    def _checks(self, cart: dict) -> list[dict]:
        """Guardrails shown before the customer confirms (the gate enforces them again on the order)."""
        if not cart.get("customer_id"):
            return []
        m = self.gate.buyer(cart["customer_id"])["mandate"] or {}
        lim, diet = m.get("limits") or {}, m.get("dietary") or {}
        approver = (m.get("approvers") or ["your approver"])[0].split(" (")[0]
        sel = [ln["options"][ln["selected"]] for ln in cart["lines"] if ln["options"]]
        total, out = cart["totals"]["total"], []
        auto, hard = lim.get("auto_approve_max_order_eur"), lim.get("hard_max_order_eur")
        if hard and total > hard:
            out.append({"id": "spend", "level": "block", "label": f"Above the €{hard:,.0f} maximum for one order"})
        elif auto and total > auto:
            out.append({"id": "spend", "level": "warn", "label": f"Above your €{auto:,.0f} limit: {approver} approves"})
        elif auto:
            out.append({"id": "spend", "level": "ok", "label": f"Within your €{auto:,.0f} order limit"})
        avoid = diet.get("avoid_allergens") or []
        if avoid:
            codes: set[str] = set()
            for a in avoid:
                c = resolve_allergen(a)
                if c:
                    codes |= expand_allergen(c)
            bad = nodata = 0
            for o in sel:
                p = self.gate.catalog.get(o["product_id"])
                if p and (set(p.allergens_contains) | set(p.allergens_may_contain)) & codes:
                    bad += 1
                elif p and not p.has_allergen_data:
                    nodata += 1
            if bad:
                out.append({"id": "allergens", "level": "block",
                            "label": f"{bad} product{'s' if bad > 1 else ''} conflict with your allergen rules"})
            elif nodata and diet.get("require_allergen_data"):
                out.append({"id": "allergens", "level": "warn",
                            "label": f"{nodata} without allergen data: {approver} approves"})
            else:
                out.append({"id": "allergens", "level": "ok", "label": "Allergen rules met: no " + ", ".join(avoid)})
        late = cart["totals"]["late"]
        if late:
            out.append({"id": "delivery", "level": "warn",
                        "label": f"{late} item{'s' if late > 1 else ''} arrive after {_day(cart['deliver_by'])}"})
        else:
            out.append({"id": "delivery", "level": "ok", "label": f"Everything arrives by {_day(cart['deliver_by'])}"})
        return out

    def _totals(self, cart: dict) -> None:
        sel = [ln["options"][ln["selected"]] for ln in cart["lines"] if ln["options"]]
        total = round(sum(o["total"] or 0 for o in sel), 2)
        order_bys = [o["order_by"] for o in sel if o.get("order_by")]
        cart["totals"] = {
            "total": total,
            "total_with_tax": round(sum(o.get("total_with_tax") or 0 for o in sel), 2),
            "per_portion": round(total / cart["portions"], 2) if cart.get("portions") else None,
            "order_by": min(order_bys) if order_bys else None,
            "co2_kg": round(sum(o["co2_kg"] or 0 for o in sel), 1),
            "lines": len(cart["lines"]),
            "late": sum(1 for o in sel if not o["delivery"]["on_time"]),
            "choices_open": sum(1 for ln in cart["lines"] if ln.get("decision_needed")),
            "delivery": (cart["deliver_by"] if all(o["delivery"]["on_time"] for o in sel)
                         else max((o["delivery"]["date"] or "" for o in sel), default=None)),
        }
        cart["checks"] = self._checks(cart)

    # ------------------------------------------------------------------ the agent loop
    async def _run(self, s: Session) -> None:
        b = self.gate.buyer(s.customer_id)
        contact = b["profile"].get("contact") or {}
        if s.system is None:
            # Built once per conversation: the model's earlier reasoning is bound to the exact prompt, so
            # the prompt must not change between turns (a clock in it would change every minute).
            today = _now()
            s.system = SYSTEM.format(today=f"{today:%A %d %B %Y} ({TIMEZONE})",
                                     contact=contact.get("name", "the customer"),
                                     role=contact.get("role", "buyer"), customer=b["name"])
        system = s.system
        client = anthropic.AsyncAnthropic()
        http = create_mcp_http_client(headers={"Authorization": f"Bearer {load_mandate(s.customer_id, self.gate.state_dir)}"})
        async with http, streamable_http_client(self.gate_url, http_client=http) as (read, write):
            async with ClientSession(read, write) as mcp:
                await mcp.initialize()
                listed = await mcp.list_tools()
                tools = [{"name": t.name, "description": t.description or "",
                          "input_schema": _attr(t, "input_schema", "inputSchema")}
                         for t in listed.tools if t.name in GATE_TOOLS] + UI_TOOLS
                if not s.ctx_loaded:  # customer context comes from the gate, not from the model's memory
                    ctx = await self._tool(s, mcp, "get_customer_context", {})
                    first = s.llm[0]["content"]
                    s.llm[0]["content"] = f"[Customer context from Valio's Trade Gate]\n{ctx}\n\n[Customer]\n{first}"
                    s.ctx_loaded = True
                for _ in range(MAX_STEPS):
                    resp = await client.beta.messages.create(
                        model=self.model, max_tokens=12000, system=system, tools=tools, messages=s.llm,
                        thinking={"type": "adaptive"}, output_config={"effort": "medium"},
                        betas=["server-side-fallback-2026-07-01"], fallbacks="default")
                    s.llm.append({"role": "assistant", "content": resp.content})
                    texts = [bl.text for bl in resp.content if bl.type == "text" and bl.text.strip()]
                    if resp.stop_reason != "tool_use":
                        if texts:
                            self._msg(s, "assistant", "\n\n".join(texts), notify=False)
                        s.status = "cart" if s.cart else "idle"
                        return
                    results, pause, cart_msg = [], None, None
                    for bl in resp.content:
                        if bl.type != "tool_use":
                            continue
                        if bl.name in ("ask_customer", "propose_ingredients"):
                            if pause is None:
                                pause = bl
                            else:
                                results.append({"type": "tool_result", "tool_use_id": bl.id,
                                                "content": "Ignored: one on-screen step at a time."})
                            continue
                        content = await self._tool(s, mcp, bl.name, bl.input)
                        results.append({"type": "tool_result", "tool_use_id": bl.id, "content": content})
                        if (bl.name == "show_cart" and '"shown": true' in content and s.cart
                                and all(ln["options"] for ln in s.cart["lines"])):
                            cart_msg = (bl.input.get("message") or "").strip() or "Your cart is ready to review."
                    if pause is not None and pause.name == "ask_customer":
                        raw = pause.input.get("questions") or []
                        qs = [{"id": str(q.get("id") or f"q{n + 1}"), "text": str(q.get("question", "")),
                               "options": [str(o) for o in (q.get("options") or [])][:4]}
                              for n, q in enumerate(raw[:3]) if q.get("question")]
                        s.question = {"questions": qs}
                        self._msg(s, "question", qs[0]["text"] if len(qs) == 1 else "A few quick questions",
                                  notify=False, questions=qs, options=qs[0]["options"] if qs else [])
                        s.pending = {"kind": "question", "tool_use_id": pause.id, "other_results": results}
                        s.status = "waiting"
                        return
                    if pause is not None:
                        self._propose(s, pause.input)
                        s.pending = {"kind": "plan", "tool_use_id": pause.id, "other_results": results}
                        s.status = "review"
                        return
                    s.llm.append({"role": "user", "content": results})
                    if cart_msg:  # the cart is on screen: end the turn here, the customer takes over
                        self._msg(s, "assistant", cart_msg, notify=False)
                        s.status = "cart"
                        return
                    self._notify(s)
                self._msg(s, "error", "I couldn't finish this request in a reasonable number of steps.",
                          notify=False)
                s.status = "cart" if s.cart else "idle"

    def _propose(self, s: Session, args: dict) -> None:
        """Put the model's ingredient list on screen for the customer to edit and approve."""
        recipes = {r["id"]: r for r in self.gate.buyer(s.customer_id)["profile"].get("recipes", [])}
        dishes, src = [], {}
        for d in args.get("dishes") or []:
            r = recipes.get(d.get("recipe_id") or "") if d.get("source") == "recipe" else None
            dishes.append({"name": d.get("name", ""), "portions": d.get("portions"),
                           "source": "recipe" if r else "estimate",
                           "recipe_name": r["name"] if r else None, "recipe_portions": r["portions"] if r else None})
            src[d.get("name", "")] = dishes[-1]["source"]
        items = []
        for n, it in enumerate(args.get("items") or []):
            try:
                qty = float(it.get("quantity") or 0)
            except (TypeError, ValueError):
                qty = 0
            if not it.get("name") or qty <= 0:
                continue
            items.append({"key": str(it.get("key") or f"i{n}"), "name": str(it["name"]), "quantity": qty,
                          "unit": it.get("unit") if it.get("unit") in ("kg", "l", "pcs") else "kg",
                          "dish": it.get("dish"), "source": src.get(it.get("dish"), "estimate"), "edited": False})
        s.plan = {"title": args.get("title", "Ingredients"), "deliver_by": args.get("deliver_by"),
                  "dishes": dishes, "items": items, "status": "proposed", "changes": []}
        from_recipe = [d["recipe_name"] for d in dishes if d["source"] == "recipe"]
        est = [d["name"] for d in dishes if d["source"] == "estimate"]
        how = " · ".join(x for x in (
            ("from your saved recipe" + ("s" if len(from_recipe) > 1 else "") + " " + ", ".join(from_recipe))
            if from_recipe else "",
            ("my estimate for " + ", ".join(est)) if est else "") if x)
        self._msg(s, "progress", f"Drafted {len(items)} ingredients ({how})" if how
                  else f"Drafted {len(items)} ingredients", notify=False)
        self._msg(s, "assistant", (args.get("message") or "").strip()
                  or "Check the quantities, change anything, then I'll find the products.", notify=False)

    async def _tool(self, s: Session, mcp: ClientSession, name: str, args: dict) -> str:
        if name == "show_cart":
            try:
                d = date.fromisoformat(args["deliver_by"])
            except (KeyError, ValueError):
                return json.dumps({"error": "deliver_by must be YYYY-MM-DD"})
            lines = await asyncio.to_thread(self._price_lines, s.customer_id, args.get("lines") or [], d)
            ref = (s.cart or {}).get("reference", "")
            s.cart = self._cart_from(args.get("title", "Your cart"), d, lines, args.get("assumptions") or [],
                                     portions=args.get("portions"), customer_id=s.customer_id)
            s.cart["reference"] = ref
            self._msg(s, "progress", f"Built the cart: {len(lines)} lines, prices and stock checked live",
                      notify=False)
            self._notify(s)
            summary = [{"key": ln["key"], "need": ln["need"],
                        "options": [{"product_id": o["product_id"], "name": o["name"], "units": o["units"],
                                     "total": o["total"], "delivery": o["delivery"], "notes": o["notes"]}
                                    for o in ln["options"]],
                        **({"problem": ln["problem"]} if ln["problem"] else {})} for ln in lines]
            return json.dumps({"shown": True, "totals": s.cart["totals"], "lines": summary}, ensure_ascii=False)
        label = {"get_customer_context": "Read your profile, order history and saved recipes",
                 "find_products": "Searching Valio Aimo's catalog", "check_offers": "Checking live price and stock",
                 "get_product": "Reading product details"}.get(name, name)
        prog = self._msg(s, "progress", label + "…", notify=True)
        try:
            out = await mcp.call_tool(name, args)
            text = _tool_result_text(out)
        except Exception as e:
            text = json.dumps({"error": "TOOL_FAILED", "message": str(e)})
        if name == "find_products":
            try:
                sm = json.loads(text)["summary"]
                prog["text"] = (f"Searched {sm['catalog_size']:,} products → {sm['checked_live']} checked "
                                f"live → {sm['shortlisted']} candidates")
                prog["funnel"] = sm
            except (KeyError, ValueError, TypeError):
                prog["text"] = label
        elif name == "get_customer_context":
            try:
                c = json.loads(text)
                prog["text"] = (f"Read your profile: {len(c['saved_recipes'])} recipes, "
                                f"{len(c['usual_products'])} usual products")
            except (KeyError, ValueError, TypeError):
                prog["text"] = label
        else:
            prog["text"] = label
        self._notify(s)
        return text


def _day(iso: str | None) -> str:
    if not iso:
        return "—"
    d = date.fromisoformat(iso[:10])
    return f"{d:%a} {d.day} {d:%b}"


def _content_hint(gate: TradeGate, pid: str, units: float) -> str:
    p = gate.catalog.get(pid)
    if p and p.content_per_sales_unit and p.content_dim:
        return f" = {units * p.content_per_sales_unit:g} {p.content_dim}"
    return ""
