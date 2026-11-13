"""Scenario evaluation: does the agent + gate deliver what the buyer actually asked for?

Runs the reference buyer agent on every scenario against the running gate, then checks the orders
it produced against the scenario's expectations with the catalog as ground truth:
  - diet claims hold for every ordered product        (e.g. lactose-free)
  - forbidden allergens are absent                     (contains or may contain)
  - quantity delivered covers the request              (litres/kg, from Valio-verified pack content)
  - delivery date meets the deadline                   (or the order went to a human)
  - expected guardrail status                          (e.g. over-limit -> PENDING_APPROVAL)

Usage: uv run python -m trade_gate.evaluate [scenario_id ...]   (gate must be running on :8400)
Writes runs/eval-<timestamp>.json and prints a table.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx

from trade_gate.agent.buyer_agent import run_agent
from trade_gate.catalog.codes import expand_allergen, resolve_allergen
from trade_gate.catalog.store import DIET_CLAIMS, Catalog
from trade_gate.config import ROOT
from trade_gate.engine.offers import TZ
from trade_gate.scenarios import SCENARIOS
from trade_gate.seed import load_mandate

CONSOLE = "http://127.0.0.1:8400/api/console"


def _orders_from_events(events: list[dict]) -> list[str]:
    ids = []
    for e in events:
        if e.get("kind") == "agent.tool_result" and e.get("tool") == "place_order" and e.get("ok"):
            try:
                ids.append(json.loads(e["preview"])["order_id"])
            except (json.JSONDecodeError, KeyError):
                pass
    return ids


def check(scenario: dict, orders: list[dict], catalog: Catalog) -> list[tuple[str, bool, str]]:
    exp = scenario.get("expect", {})
    out: list[tuple[str, bool, str]] = []
    if exp.get("no_order"):
        out.append(("no order placed (deadline impossible)", not orders, f"{len(orders)} order(s)"))
        return out
    out.append(("order placed", bool(orders), f"{len(orders)} order(s)"))
    lines = [ln for o in orders for ln in o["quote"]["lines"]]
    if "diet" in exp:
        claim = DIET_CLAIMS[exp["diet"]]
        bad = [ln["name"] for ln in lines if not Catalog._meets_claim(catalog.get(ln["product_id"]), claim)]
        out.append((f"diet {exp['diet']}", not bad and bool(lines), ", ".join(bad) or "all lines comply"))
    if "no_allergens" in exp:
        avoid = set()
        for a in exp["no_allergens"]:
            avoid |= expand_allergen(resolve_allergen(a))
        bad = []
        for ln in lines:
            p = catalog.get(ln["product_id"])
            if (set(p.allergens_contains) | set(p.allergens_may_contain)) & avoid:
                bad.append(ln["name"])
        confirmed_bad = [b for b in bad if any(o["status"] == "CONFIRMED" for o in orders)]
        out.append(("allergen-safe", not confirmed_bad, ", ".join(bad) or "no forbidden allergens"))
    if "quantity_l" in exp:
        got = sum((ln.get("content_per_sales_unit") or 0) * ln["units"] for ln in lines)
        out.append(("quantity covered", got >= exp["quantity_l"] - 1e-6, f"{got:g} L of {exp['quantity_l']} L"))
    if lines:
        late = [ln["name"] for ln in lines if not ln.get("meets_deadline", True)]
        human = any(o["status"] == "PENDING_APPROVAL" for o in orders)
        out.append(("deadline met or escalated", not late or human, ", ".join(late) or "all on time"))
    if "status" in exp:
        sts = [o["status"] for o in orders]
        out.append((f"status {exp['status']}", exp["status"] in sts, ", ".join(sts) or "none"))
    return out


async def evaluate(ids: list[str]) -> dict:
    catalog = Catalog()
    results = []
    async with httpx.AsyncClient(timeout=30) as http:
        for s in SCENARIOS:
            if ids and s["id"] not in ids:
                continue
            events: list[dict] = []
            t0 = datetime.now(TZ)
            res = await run_agent(s["request"], load_mandate(s["buyer_id"]), buyer_name=s["buyer_id"],
                                  sink=events.append)
            secs = (datetime.now(TZ) - t0).total_seconds()
            orders = [(await http.get(f"{CONSOLE}/orders")).json()]
            order_ids = _orders_from_events(events)
            orders = [o for o in orders[0] if o["id"] in order_ids]
            checks = check(s, orders, catalog)
            tools = [e["tool"] for e in events if e.get("kind") == "agent.tool_call"]
            results.append({"scenario": s["id"], "title": s["title"], "seconds": round(secs),
                            "tool_calls": len(tools), "orders": [{"id": o["id"], "status": o["status"],
                                                                  "total": o["total"]} for o in orders],
                            "checks": [{"check": c, "pass": p, "detail": d} for c, p, d in checks],
                            "passed": all(p for _, p, _ in checks), "final": res["final"]})
            mark = "PASS" if results[-1]["passed"] else "FAIL"
            print(f"[{mark}] {s['id']:<22} {secs:5.0f}s  {len(tools):2} tools  "
                  + "; ".join(f"{'✓' if p else '✗'} {c} ({d})" for c, p, d in checks))
    summary = {"run_at": datetime.now(TZ).isoformat(timespec="seconds"),
               "passed": sum(r["passed"] for r in results), "total": len(results), "results": results}
    path = Path(ROOT) / "runs" / f"eval-{datetime.now(TZ):%Y%m%d-%H%M%S}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n{summary['passed']}/{summary['total']} scenarios passed -> {path}")
    return summary


if __name__ == "__main__":
    asyncio.run(evaluate(sys.argv[1:]))
