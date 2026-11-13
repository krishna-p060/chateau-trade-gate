"""Reference external purchasing agent (the buyer's side).

It knows nothing about Valio's internals: it connects to the Trade Gate over MCP (Streamable HTTP),
authenticates with the buyer-signed mandate, and uses only the gate's published tools. The gate,
not this agent, enforces the guardrails.

Run one request from the CLI:
  uv run python -m trade_gate.agent.buyer_agent hotel-aurora "I need 1,000 litres of lactose-free milk by Monday"
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import anthropic
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from trade_gate.config import AGENT_MODEL, TIMEZONE
from trade_gate.engine.offers import TZ

GATE_MCP_URL = "http://127.0.0.1:8400/mcp/"
MAX_TURNS = 30

SYSTEM = """You are the purchasing agent of a professional kitchen. You buy from Valio Aimo, a Finnish
food-service wholesaler, only through Valio's Trade Gate tools.

How to work:
1. Call get_my_mandate first so you know your spending authority, allergen rules and approvers.
2. Work out exactly what the buyer needs: product type, quantity and unit, delivery date, dietary and
   allergen constraints. Resolve relative dates ("Monday", "tomorrow") from today's date given below.
3. search_products, then judge relevance yourself: "milk" means plain drinking milk, not coffee milk,
   sour milk, ice cream or milk powder. Prefer pack sizes that suit the quantity.
4. plan_purchase with the product_ids you judged relevant. Compare the good / better / best options
   and read why products were ruled out (cut-offs, partial stock, unknown supplier stock).
5. Pick the option that best matches what the buyer asked for. If nothing meets the request, choose
   the closest safe alternative and say plainly what differs (later date, different pack, substitute).
6. create_quote for that exact basket (quantities in sales units), then place_order with a one or two
   sentence rationale a human approver can read.
7. If the order is PENDING_APPROVAL, do not try to get around it (no splitting into smaller orders,
   no swapping products to dodge a rule). Tell the buyer what the approver must decide and why.

Never invent product data, prices or stock: use only what the tools return. Allergen safety is
absolute: never order a product that contains or may contain an allergen the buyer must avoid, and
treat products without allergen declarations as unverified.

Finish with a short report for the buyer: what you ordered (or proposed), total price excl. VAT,
delivery date, order status, and any trade-offs or risks they should know about."""


EventSink = Callable[[dict], Awaitable[None] | None]


async def _emit(sink: EventSink | None, kind: str, **data: Any) -> None:
    if sink is None:
        return
    r = sink({"kind": kind, "ts": datetime.now(TZ).isoformat(timespec="seconds"), **data})
    if asyncio.iscoroutine(r):
        await r


def _attr(obj, *names, default=None):
    """MCP SDK 2.x uses snake_case attributes; 1.x used camelCase. Accept either."""
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return default


def _tool_result_text(result) -> str:
    structured = _attr(result, "structured_content", "structuredContent")
    if structured:
        return json.dumps(structured, ensure_ascii=False, default=str)
    parts = [getattr(c, "text", "") for c in (result.content or [])]
    return "\n".join(p for p in parts if p) or "{}"


async def run_agent(request: str, mandate_jwt: str, *, buyer_name: str = "", sink: EventSink | None = None,
                    model: str = AGENT_MODEL, gate_url: str = GATE_MCP_URL,
                    wait_for_approval_s: float = 0) -> dict:
    """Run the buyer agent on one natural-language request. Returns transcript summary."""
    client = anthropic.AsyncAnthropic()
    http = create_mcp_http_client(headers={"Authorization": f"Bearer {mandate_jwt}"})
    today = datetime.now(TZ)
    user_msg = (f"Today is {today:%A %d %B %Y}, {today:%H:%M} ({TIMEZONE}).\n"
                f"Request from {buyer_name or 'the kitchen'}: {request}")
    messages: list[dict] = [{"role": "user", "content": user_msg}]
    await _emit(sink, "agent.start", request=request, model=model)

    async with http, streamable_http_client(gate_url, http_client=http) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            tools = [{"name": t.name, "description": t.description or "",
                      "input_schema": _attr(t, "input_schema", "inputSchema")} for t in listed.tools]
            pending_orders: set[str] = set()
            final_text = ""

            for _turn in range(MAX_TURNS):
                resp = await client.beta.messages.create(
                    model=model,
                    max_tokens=16000,
                    system=SYSTEM,
                    tools=tools,
                    messages=messages,
                    thinking={"type": "adaptive", "display": "summarized"},
                    output_config={"effort": "high"},
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
                messages.append({"role": "assistant", "content": resp.content})
                for block in resp.content:
                    if block.type == "thinking" and block.thinking:
                        await _emit(sink, "agent.thinking", text=block.thinking)
                    elif block.type == "text" and block.text.strip():
                        await _emit(sink, "agent.say", text=block.text)
                        final_text = block.text
                if resp.stop_reason == "refusal":
                    await _emit(sink, "agent.error", text="The model declined this request.")
                    break
                if resp.stop_reason != "tool_use":
                    break

                results = []
                for block in resp.content:
                    if block.type != "tool_use":
                        continue
                    await _emit(sink, "agent.tool_call", tool=block.name, input=block.input)
                    try:
                        out = await session.call_tool(block.name, block.input)
                        text = _tool_result_text(out)
                        is_err = bool(_attr(out, "is_error", "isError", default=False)) or '"error"' in text[:40]
                    except Exception as e:  # transport problems are reported to the model, not fatal
                        text, is_err = json.dumps({"error": "TOOL_FAILED", "message": str(e)}), True
                    limit = 12000 if block.name in ("plan_purchase", "create_quote", "place_order", "check_offers") else 1500
                    await _emit(sink, "agent.tool_result", tool=block.name, ok=not is_err, preview=text[:limit])
                    if block.name == "place_order" and not is_err:
                        o = json.loads(text)
                        if o.get("status") == "PENDING_APPROVAL":
                            pending_orders.add(o["order_id"])
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": text,
                                    **({"is_error": True} if is_err else {})})
                messages.append({"role": "user", "content": results})

            # Optionally wait for the human decision, then let the agent report the outcome.
            if pending_orders and wait_for_approval_s > 0:
                await _emit(sink, "agent.waiting", orders=sorted(pending_orders))
                decided = await _wait_for_decisions(session, pending_orders, wait_for_approval_s)
                if decided:
                    messages.append({"role": "user", "content": "Update from the gate: " + json.dumps(decided)
                                     + ". Give the buyer a one-paragraph final status."})
                    resp = await client.beta.messages.create(
                        model=model, max_tokens=4000, system=SYSTEM, tools=tools, messages=messages,
                        thinking={"type": "adaptive"}, output_config={"effort": "medium"},
                        betas=["server-side-fallback-2026-07-01"], fallbacks="default")
                    for block in resp.content:
                        if block.type == "text" and block.text.strip():
                            final_text = block.text
                            await _emit(sink, "agent.say", text=block.text)

    await _emit(sink, "agent.done", text=final_text)
    return {"final": final_text, "turns": len(messages)}


async def _wait_for_decisions(session: ClientSession, order_ids: set[str], timeout_s: float) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_s
    decided: dict[str, str] = {}
    while order_ids - decided.keys() and asyncio.get_running_loop().time() < deadline:
        for oid in order_ids - decided.keys():
            o = json.loads(_tool_result_text(await session.call_tool("get_order", {"order_id": oid})))
            if o.get("status") in ("CONFIRMED", "REJECTED"):
                decided[oid] = o["status"] + (f" (approver note: {o['approval']['note']})"
                                              if o.get("approval") and o["approval"].get("note") else "")
        await asyncio.sleep(2)
    return decided


def _print_event(e: dict) -> None:
    k = e["kind"]
    if k == "agent.tool_call":
        print(f"  → {e['tool']}({json.dumps(e['input'], ensure_ascii=False)[:160]})")
    elif k == "agent.tool_result":
        print(f"    {'✓' if e['ok'] else '✗'} {e['preview'][:200]}")
    elif k in ("agent.say", "agent.done"):
        print(f"\n{e.get('text', '')}\n")
    elif k == "agent.thinking":
        print(f"  (thinking) {e['text'][:200]}")


if __name__ == "__main__":
    from trade_gate.seed import load_mandate

    buyer, req = sys.argv[1], " ".join(sys.argv[2:])
    asyncio.run(run_agent(req, load_mandate(buyer), buyer_name=buyer, sink=_print_event))
