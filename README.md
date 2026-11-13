# Château Trade Gate

**An open, guardrailed interface that lets AI purchasing agents find, price and order from Valio Aimo,
with human approval where it matters and a tamper-evident audit trail.**

Built at Junction 2026 for Valio Aimo's challenge *Trusted Trade Agents*.

> "I need 1,000 litres of lactose-free milk by Monday."
>
> The agent finds 40 candidates in the catalog, checks live price and availability in **two batched
> calls**, and sees what a naive integration would miss: the cheapest 10 L packs ship from a supplier
> warehouse whose **Monday cut-off already passed**, and two cheaper 1 L options only have 51 and 384
> packs in stock. It proposes 1,000 × Valio Eila 1 L at €1,010 for confirmed Monday delivery, gets a
> **signed quote**, and orders. The gate checks the buyer's **signed mandate**: €1,010 is under the
> €1,500 autonomous limit, so the order is confirmed. Every step is in the audit log.

## What it does

| Valio's core asks | How |
|---|---|
| Product, price & availability lookup | MCP tools + REST: EN/FI catalog search with hard diet/allergen filters; live price & availability translated into the buyer's units |
| Request → order at fixed prices | Signed quotes (EdDSA JWS) lock the price for the approval window; idempotent orders |
| Permissions & human approval | Buyer-signed mandate (W3C Verifiable Credential); gate-enforced guardrails: **AUTO / APPROVAL / BLOCKED** with reasons |
| *Delivery & sustainability comparison* | Delivery reliability, stock certainty, GS1 sustainability labels, CO2 estimate in every offer |
| *Substitution & exceptions* | Unit conversion, cut-offs, placeholders, partial stock, split orders, good/better/best, Valio's own substitution rules |
| *Traceability* | Hash-chained audit log in plain language for buyer and Valio; chain verification |

Details: [docs/INTERFACE.md](docs/INTERFACE.md) — flow, tools, trust protocol, guardrails, assumptions,
path to production.

## Architecture

```
 Buyer's agent (any vendor/model) ──MCP / REST + Bearer mandate──▶ Trade Gate (Valio side)
                                                                    ├─ catalog index (SQLite FTS, 17.5k products)
                                                                    ├─ planner & offers (unit math, cut-offs, risk)
                                                                    ├─ Valio mock APIs (price, availability) ◀─ batched, cached
                                                                    ├─ trust: mandate verify · signed quotes · JWKS
                                                                    ├─ guardrails engine (AUTO / APPROVAL / BLOCKED)
                                                                    └─ hash-chained audit log ──▶ dashboard (approver + Valio views)
```

## Run it

```bash
cp .env.example .env              # add VALIO_API_KEY (+ ANTHROPIC_API_KEY for the demo agent)
uv sync
uv run python -m trade_gate.catalog.build_index   # needs Valio's files in data/raw/ (from the resource portal)
uv run python -m trade_gate.seed                  # demo buyers, keys and signed mandates
uv run uvicorn trade_gate.api:app --port 8400     # gate + MCP + dashboard
(cd web && npm install && npm run build)          # dashboard at http://localhost:8400
```

- MCP endpoint: `http://localhost:8400/mcp` (Streamable HTTP, `Authorization: Bearer <mandate>`)
- REST docs: `http://localhost:8400/docs` · manifest: `/.well-known/trade-gate.json` · keys: `/.well-known/jwks.json`
- Demo agent from the CLI:
  `uv run python -m trade_gate.agent.buyer_agent hotel-aurora "I need 1,000 litres of lactose-free milk by Monday"`
- Tests (offline, deterministic): `uv run pytest`

## Demo buyers

| Buyer | Mandate |
|---|---|
| Hotel Aurora Group | Autonomous up to €1,500 per order, €12,000/week; supplier-warehouse stock and estimated dates need approval; approver: F&B manager |
| Espoo Children's Hospital Kitchen | Autonomous up to €800; must avoid peanuts, tree nuts, sesame (blocked); missing allergen data needs approval; approver: clinical dietitian |

## Data

Valio Aimo's synthetic challenge data (product file, delivery reliability, carbon footprint) and mock
APIs. The data files are not included in this repository (licensed for the challenge only); download
them from the challenge resource portal into `data/raw/`.

## Team

Built during Junction 2026 (13–15 Nov, Espoo). MIT licence.
