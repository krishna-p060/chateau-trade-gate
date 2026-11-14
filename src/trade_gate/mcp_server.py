"""MCP interface of the Trade Gate (Model Context Protocol, Streamable HTTP).

External purchasing agents connect to /mcp and authenticate with their buyer-signed purchasing
mandate as `Authorization: Bearer <vc+jwt>`. Every tool runs against the same TradeGate core as
the REST API; guardrails are enforced by the gate, not by the agent.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from mcp.server.mcpserver import Context, MCPServer

from trade_gate.engine.planner import Need
from trade_gate.service import GateError, TradeGate

INSTRUCTIONS = """You are connected to Valio Aimo's Trade Gate, the official interface for external
purchasing agents. Typical flow: get_my_mandate -> search_products -> plan_purchase (or check_offers)
-> create_quote -> place_order -> get_order. Prices are fixed (no negotiation). Quantities in quotes
and orders are in SALES UNITS (packs), not litres/kg: use plan_purchase or check_offers to convert.
Orders outside your mandate are not refused silently: they go to a named human approver or are
blocked with reasons. Always pass your reasoning in place_order(rationale=...): it is shown to the
human approver and stored in the audit trail."""


def build_mcp(gate: TradeGate) -> MCPServer:
    mcp = MCPServer(name="valio-aimo-trade-gate", title="Valio Aimo Trade Gate", instructions=INSTRUCTIONS,
                    version="0.1.0")

    def who(ctx: Context):
        auth = (ctx.headers or {}).get("authorization", "")
        token = auth.split(" ", 1)[1] if auth.lower().startswith("bearer ") else None
        m = gate.authenticate(token)
        return m, token

    def guard(fn):
        try:
            return fn()
        except GateError as e:
            return {"error": e.code, "message": e.message}

    @mcp.tool()
    def get_my_mandate(ctx: Context) -> dict[str, Any]:
        """Return what your buyer authorises you to do: spend limits, allergen rules, substitution and
        delivery rules, and who approves exceptions. Call this first."""
        def run():
            m, _ = who(ctx)
            b = gate.buyer(m.buyer_id)
            return {"buyer": {"id": b["id"], "name": b["name"], **b["profile"]}, "agent_id": m.agent_id,
                    "limits": m.limits.__dict__, "dietary": m.dietary.__dict__,
                    "substitution": m.substitution.__dict__, "delivery": m.delivery.__dict__,
                    "approvers": m.approvers}
        return guard(run)

    @mcp.tool()
    def search_products(ctx: Context, query: str, diets: list[str] | None = None,
                        avoid_allergens: list[str] | None = None, require_allergen_data: bool = False,
                        labels: list[str] | None = None, unit: str | None = None, limit: int = 25) -> dict[str, Any]:
        """Search Valio Aimo's catalog (English or Finnish words). Static data only, no prices.
        diets: lactose_free | gluten_free | vegan | vegetarian. avoid_allergens: names like 'milk',
        'peanuts', 'tree nuts', 'gluten', 'sesame'. unit: 'l' or 'kg' to keep only products measured so.
        Products with no allergen declaration are marked allergen_status='unknown', never 'safe'."""
        def run():
            m, _ = who(ctx)
            res = gate.search(m.buyer_id, m.agent_id, query=query, diets=diets or [],
                              avoid_allergens=list(dict.fromkeys((avoid_allergens or []) + m.dietary.avoid_allergens)),
                              require_allergen_data=require_allergen_data, labels=labels or [],
                              content_dim=unit, limit=min(limit, 60))
            keep = ("id", "name", "brand", "sales_unit", "content_per_sales_unit", "content_dim", "claims",
                    "sustainability_labels", "allergens_contains", "allergens_may_contain", "allergen_status",
                    "delivery_reliability", "allowed_lot_size", "substitutes")
            return {"count": len(res), "products": [{k: p[k] for k in keep} for p in res]}
        return guard(run)

    @mcp.tool()
    def get_customer_context(ctx: Context) -> dict[str, Any]:
        """What Valio Aimo knows about this customer: segment, contact person, stated priorities, rules
        (allergens, approval limit and approver), usual products from purchase history, saved recipes and
        standing orders. Call once at the start; use it instead of asking the customer."""
        def run():
            m, _ = who(ctx)
            return gate.customer_context(m.buyer_id)
        return guard(run)

    @mcp.tool()
    def find_products(ctx: Context, items: list[dict[str, Any]], deliver_by: str) -> dict[str, Any]:
        """Shortlist products for several ingredients at once, with live price and availability.
        items: [{key, query (2-3 English words, e.g. 'cooking cream', 'salmon fillet'), quantity, unit
        ('kg' | 'l' | 'unit'), optional diets ['lactose_free'|'gluten_free'|'vegan'|'vegetarian'],
        avoid_allergens, replaces (product_id being substituted), product_ids (must-include)}].
        Valio narrows the 17k catalog deterministically (search, diet and allergen filters, customer's usual
        products, Valio's official substitutes), prices the packs for the quantity and checks delivery by
        deliver_by (YYYY-MM-DD). Returns up to 7 candidates per item with pack count, total, €/kg or €/l,
        delivery date, stock, CO2, allergens and whether the customer usually buys it."""
        def run():
            m, _ = who(ctx)
            return gate.shortlist(m.buyer_id, m.agent_id, items[:25], date.fromisoformat(deliver_by))
        return guard(run)

    @mcp.tool()
    def get_product(ctx: Context, product_id: str) -> dict[str, Any]:
        """Full static details of one product: ingredients, allergens, labels, pack size, substitutes."""
        def run():
            who(ctx)
            return gate.product(product_id)
        return guard(run)

    @mcp.tool()
    def check_offers(ctx: Context, product_ids: list[str], deliver_by: str, quantity: float | None = None,
                     unit: str = "unit") -> dict[str, Any]:
        """Live price + availability for specific products (max 40), translated into your need.
        deliver_by: YYYY-MM-DD. quantity+unit ('l', 'kg' or 'unit' = sales packs) computes packs to
        order, total price, stock certainty, cut-off status and earliest delivery, with issues explained."""
        def run():
            m, _ = who(ctx)
            offers = gate.offers(m.buyer_id, m.agent_id, product_ids[:40], date.fromisoformat(deliver_by),
                                 quantity, unit)
            return {"offers": offers}
        return guard(run)

    @mcp.tool()
    def plan_purchase(ctx: Context, query: str, quantity: float, unit: str, deliver_by: str,
                      diets: list[str] | None = None, avoid_allergens: list[str] | None = None,
                      preferred_labels: list[str] | None = None, product_ids: list[str] | None = None,
                      require_allergen_data: bool = False) -> dict[str, Any]:
        """Turn a need ('1000 l lactose-free milk by 2026-11-16') into ranked options: good (cheapest),
        better (best value after delivery risk), best (most certain / sustainable), plus split orders when
        stock is partial, and every ruled-out product with its reason. unit: 'l' | 'kg' | 'unit'.
        Pass product_ids to restrict planning to products you already judged relevant."""
        def run():
            m, _ = who(ctx)
            need = Need(query=query, quantity=quantity, unit=unit, deliver_by=date.fromisoformat(deliver_by),
                        diets=diets or [], avoid_allergens=list(dict.fromkeys((avoid_allergens or []) + m.dietary.avoid_allergens)),
                        require_allergen_data=require_allergen_data or m.dietary.require_allergen_data,
                        preferred_labels=preferred_labels or [], product_ids=product_ids or [])
            if product_ids:
                need.query = ""
            p = gate.plan(m.buyer_id, m.agent_id, need)
            p["rejected"] = p["rejected"][:12]
            return p
        return guard(run)

    @mcp.tool()
    def create_quote(ctx: Context, lines: list[dict[str, Any]], deliver_by: str, note: str = "") -> dict[str, Any]:
        """Lock fixed prices for an exact basket. lines: [{product_id, units (sales packs), optional
        is_substitute, replaces, outside_preferences}]. Valio re-checks live price/stock and returns a
        quote signed by Valio (EdDSA), valid for 2 hours. Refuses with reasons if stock or lot size fails."""
        def run():
            m, _ = who(ctx)
            q = gate.create_quote(m.buyer_id, m.agent_id, lines, date.fromisoformat(deliver_by), note)
            return {"quote": q["quote"], "signature": q["signature"]}
        return guard(run)

    @mcp.tool()
    def place_order(ctx: Context, quote_id: str, rationale: str, idempotency_key: str | None = None) -> dict[str, Any]:
        """Commit a quote. The gate verifies your mandate and applies the buyer's guardrails:
        CONFIRMED (within your authority), PENDING_APPROVAL (a named human must sign off; reasons
        returned) or REJECTED (never allowed, e.g. allergen conflict). Safe to retry with the same
        idempotency_key. rationale: why this is the right purchase, in one or two sentences."""
        def run():
            m, token = who(ctx)
            o = gate.place_order(m.buyer_id, m.agent_id, quote_id, token, idempotency_key or str(uuid.uuid4()),
                                 rationale)
            return _order_view(o)
        return guard(run)

    @mcp.tool()
    def get_order(ctx: Context, order_id: str) -> dict[str, Any]:
        """Current status of an order, including approval status and the guardrail decision."""
        def run():
            m, _ = who(ctx)
            o = gate.get_order(order_id)
            if o["buyer_id"] != m.buyer_id:
                raise GateError("FORBIDDEN", "Not your order.", 403)
            return _order_view(o)
        return guard(run)

    @mcp.tool()
    def get_audit_trail(ctx: Context, order_id: str | None = None) -> dict[str, Any]:
        """Human-readable log of what you and the gate did (optionally for one order), plus chain integrity."""
        def run():
            m, _ = who(ctx)
            return {"narrative": gate.audit.narrative(buyer_id=m.buyer_id, ref=order_id),
                    "integrity": gate.audit.verify_chain()}
        return guard(run)

    return mcp


def _order_view(o: dict) -> dict:
    return {"order_id": o["id"], "status": o["status"], "total_price": o["total"],
            "decision": o["decision"]["outcome"] if o.get("decision") else None,
            "reasons": [f["message"] for f in (o.get("decision") or {}).get("findings", []) if f["outcome"] != "AUTO"],
            "approval": ({"id": o["approval"]["id"], "status": o["approval"]["status"],
                          "approver": o["approval"]["approver"], "note": o["approval"]["note"]}
                         if o.get("approval") else None),
            "lines": [{k: ln[k] for k in ("product_id", "name", "units", "sales_unit", "unit_price", "line_total",
                                          "earliest_delivery")} for ln in o["quote"]["lines"]],
            "confirmation_signature": o.get("confirmation_jws")}
