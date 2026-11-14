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
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import anthropic
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from trade_gate.agent.buyer_agent import GATE_MCP_URL, _attr, _tool_result_text
from trade_gate.config import AGENT_MODEL, TIMEZONE
from trade_gate.engine.offers import TZ, build_offer
from trade_gate.seed import load_mandate
from trade_gate.service import GateError, TradeGate, _candidate

GATE_TOOLS = {"get_customer_context", "find_products", "check_offers", "get_product"}
MAX_STEPS = 14
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

SYSTEM = """You are Aimo Assistant, the ordering assistant inside Valio Aimo's webshop for professional
kitchens. Today is {today}. You are helping {contact} ({role}) at {customer}.

The customer owns the decisions about WHAT to serve. You do the busy work after that: break dishes into
ingredients and quantities, find the right products in Valio Aimo's catalog, check price and delivery,
and prepare a cart. The customer reviews and confirms the cart; you never place orders.

How to work:
1. Call get_customer_context once at the start of a conversation. Use what it tells you (priorities,
   rules, usual products, saved recipes, order templates) instead of asking.
2. If something essential is missing that would change products or quantities (number of portions, the
   date, a dietary need), ask ONE short question with ask_customer and 2-4 tap-able answers. Ask at most
   two questions in a whole conversation. Otherwise make a sensible professional assumption and state it.
   If the customer asks you to suggest a menu, propose one in the cart title and assumptions; they decide.
3. Quantities: use the customer's saved recipe when a dish matches (scale by portions). Otherwise use
   professional kitchen quantities per portion. Work in kg or l.
4. Call find_products ONCE for all ingredients (short English queries of 1-3 words, e.g. "cooking cream",
   "salmon fillet", "penne"). deliver_by = the day before the event unless told otherwise. Delivery days
   are Monday-Saturday. If a result is thin, you may call find_products again for just those items.
5. For each line choose: option 1 = your recommendation, plus up to 2 alternatives ONLY when they differ
   in a way this customer might care about (cheaper, usual product, lower CO2, Finnish, fresh vs frozen).
   Weigh options by the customer's own stated priorities — there is no fixed formula. Prefer products the
   customer usually buys when they fit. Set decision_needed=true only when the right choice genuinely
   depends on the customer's taste or plans. "why" is at most 12 words, concrete (price, usual, CO2...).
6. Call show_cart with the full cart. Then reply briefly (max ~60 words): one sentence on what you
   prepared, then at most 3 short bullets for what needs their attention (a choice to make, a late or
   unavailable item, an assumption that matters). The cart shows all details — do not repeat prices
   of every line. No headings or tables.
7. When the customer asks for a change, call show_cart again with the complete updated cart.

Vocabulary: Valio Aimo calls recurring/standing orders "order templates" — always use that term.
Rules: never invent products, prices or stock — use only tool results. Allergen rules are absolute.
If something cannot arrive in time, say so plainly and offer the closest alternative (other product or
date). Do not narrate your steps before tool calls; the customer sees progress automatically.
Write in the customer's language (English unless they write Finnish)."""

UI_TOOLS = [
    {
        "name": "ask_customer",
        "description": "Ask the customer one short clarifying question with 2-4 tap-able answers. The "
                       "conversation pauses until they answer. Use sparingly (max two per conversation).",
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string"},
                           "options": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4}},
            "required": ["question", "options"],
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
            "required": ["title", "deliver_by", "lines"],
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
    status: str = "idle"  # idle | working | waiting | cart | ordering | ordered | error
    messages: list[dict] = field(default_factory=list)
    cart: dict | None = None
    order: dict | None = None
    question: dict | None = None
    llm: list[dict] = field(default_factory=list)
    pending: dict | None = None  # {"tool_use_id": ..., "other_results": [...]}
    listeners: set = field(default_factory=set)
    task: asyncio.Task | None = None

    def snapshot(self) -> dict:
        return {"id": self.id, "customer_id": self.customer_id, "status": self.status,
                "busy": self.status in ("working", "ordering"), "messages": self.messages,
                "question": self.question, "cart": self.cart, "order": self.order}


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
                  f"cooking — a menu and the number of guests is enough — and I'll prepare the cart. "
                  f"I can also check one of your order templates for the next delivery.", notify=False)
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
                self._msg(s, "error", f"Something went wrong: {type(e).__name__}: {e}", notify=False)
                s.status = "cart" if s.cart else "idle"
            self._notify(s)
        s.task = asyncio.create_task(runner())

    # ------------------------------------------------------------------ customer actions
    def send(self, sid: str, text: str) -> Session:
        s = self.get(sid)
        text = text.strip()
        if not text:
            raise GateError("EMPTY", "Message is empty.")
        self._msg(s, "user", text, notify=False)
        if s.pending:  # answer to ask_customer
            results = s.pending["other_results"] + [{"type": "tool_result", "tool_use_id": s.pending["tool_use_id"],
                                                     "content": f"Customer answered: {text}"}]
            s.pending, s.question = None, None
            s.llm.append({"role": "user", "content": results})
        else:
            prefix = ""
            if s.order and s.order.get("status") in ("CONFIRMED", "PENDING_APPROVAL"):
                prefix = "(The previous cart was already ordered; this is a new request.) "
                s.cart, s.order = None, None
            s.llm.append({"role": "user", "content": prefix + text})
        self._start(s, self._run(s))
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
        s.cart, s.order = None, None
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
            s.cart = self._cart_from(f"{so['name']} — {_day(d.isoformat())}", d, ok, [])
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
        s.llm.append({"role": "user", "content":
                      f"[Order template check by Valio for delivery {d.isoformat()} — '{so['name']}']\n"
                      f"Available:\n{keep}\nProblems:\n{problems}\n\n"
                      f"Find substitutes for the problem items (find_products with replaces=<product_id>, "
                      f"quantity in kg/l when the pack content is known), then show_cart with ALL lines: "
                      f"available lines unchanged as a single option with quantity in 'unit' (packs), and each "
                      f"substitute line with replaces set and up to 3 options, decision_needed=true. Then tell "
                      f"the customer in two sentences what changed."})
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
                   portions: int | None = None) -> dict:
        cart = {"title": title, "deliver_by": deliver_by.isoformat(), "assumptions": assumptions[:4],
                "lines": lines, "portions": portions or None, "reference": "",
                "updated": _now().isoformat(timespec="seconds")}
        self._totals(cart)
        return cart

    @staticmethod
    def _totals(cart: dict) -> None:
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

    # ------------------------------------------------------------------ the agent loop
    async def _run(self, s: Session) -> None:
        b = self.gate.buyer(s.customer_id)
        contact = b["profile"].get("contact") or {}
        today = _now()
        system = SYSTEM.format(today=f"{today:%A %d %B %Y}, {today:%H:%M} ({TIMEZONE})",
                               contact=contact.get("name", "the customer"), role=contact.get("role", "buyer"),
                               customer=b["name"])
        client = anthropic.AsyncAnthropic()
        http = create_mcp_http_client(headers={"Authorization": f"Bearer {load_mandate(s.customer_id, self.gate.state_dir)}"})
        async with http, streamable_http_client(self.gate_url, http_client=http) as (read, write):
            async with ClientSession(read, write) as mcp:
                await mcp.initialize()
                listed = await mcp.list_tools()
                tools = [{"name": t.name, "description": t.description or "",
                          "input_schema": _attr(t, "input_schema", "inputSchema")}
                         for t in listed.tools if t.name in GATE_TOOLS] + UI_TOOLS
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
                    results, ask = [], None
                    for bl in resp.content:
                        if bl.type != "tool_use":
                            continue
                        if bl.name == "ask_customer":
                            ask = bl
                            continue
                        content = await self._tool(s, mcp, bl.name, bl.input)
                        results.append({"type": "tool_result", "tool_use_id": bl.id, "content": content})
                    if ask:
                        if texts:
                            self._msg(s, "assistant", "\n\n".join(texts), notify=False)
                        opts = [str(o) for o in (ask.input.get("options") or [])][:4]
                        s.question = {"text": ask.input.get("question", ""), "options": opts}
                        self._msg(s, "question", s.question["text"], notify=False, options=opts)
                        s.pending = {"tool_use_id": ask.id, "other_results": results}
                        s.status = "waiting"
                        return
                    s.llm.append({"role": "user", "content": results})
                    self._notify(s)
                self._msg(s, "error", "I couldn't finish this request in a reasonable number of steps.",
                          notify=False)
                s.status = "cart" if s.cart else "idle"

    async def _tool(self, s: Session, mcp: ClientSession, name: str, args: dict) -> str:
        if name == "show_cart":
            try:
                d = date.fromisoformat(args["deliver_by"])
            except (KeyError, ValueError):
                return json.dumps({"error": "deliver_by must be YYYY-MM-DD"})
            lines = await asyncio.to_thread(self._price_lines, s.customer_id, args.get("lines") or [], d)
            ref = (s.cart or {}).get("reference", "")
            s.cart = self._cart_from(args.get("title", "Your cart"), d, lines, args.get("assumptions") or [],
                                     portions=args.get("portions"))
            s.cart["reference"] = ref
            self._msg(s, "progress", f"Prepared the cart: {len(lines)} lines, €{s.cart['totals']['total']:,.2f} "
                      f"excl. VAT — prices and stock checked live.", notify=False)
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
                prog["text"] = (f"Searched {sm['catalog_size']:,} products → {sm['matched']:,} matches → "
                                f"{sm['checked_live']} checked for live price & stock → {sm['shortlisted']} "
                                f"candidates for {len(args.get('items') or [])} ingredients")
            except (KeyError, ValueError, TypeError):
                prog["text"] = label
        elif name == "get_customer_context":
            try:
                c = json.loads(text)
                prog["text"] = (f"Read your profile: {len(c['usual_products'])} usual products, "
                                f"{len(c['saved_recipes'])} saved recipes, {len(c['standing_orders'])} order template(s)")
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
