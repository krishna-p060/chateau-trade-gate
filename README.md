# Château Trade Gate — Aimo Assistant

**An AI ordering assistant for Valio Aimo's webshop, built on an open, guardrailed interface for
purchasing agents. The chef decides what to serve; the assistant does the busy work; the customer
confirms; Valio's gate enforces the rules and signs every order.**

Built at Junction 2026 for Valio Aimo's challenge *Trusted Trade Agents*.

> *Wednesday, a caterer gets a call:* "Company party for 80 on Saturday: creamy salmon pasta, green
> salad and a dessert. 6 guests are gluten-free."
>
> Aimo Assistant reads the customer's saved recipes and 8 weeks of purchase history, scales the recipes
> to 74 + 6 gluten-free portions, and narrows Valio's **17,546 products → 661 matches → 205 checked live
> → 88 candidates** with plain code before the AI chooses. It notices the customer's usual Barilla
> spaghetti cannot be delivered, offers fresh vs frozen salmon as the customer's choice, and builds a
> cart: priority 1 per line with alternatives when they matter (cheaper, usual, lower CO₂, Finnish),
> each with a one-line *why*, live price, stock, delivery and cut-off. The chef confirms; the gate
> checks the customer's signed mandate (spend limit, allergens), and Valio signs the order.

## What Valio Aimo told us, and what we built

| Mentors / Valio said | Built |
|---|---|
| "Assume the agent is surfaced in our own webshop… with an MCP decoupling layer" | **Aimo Assistant** in a webshop UI, talking to Valio only through the Trade Gate's **MCP tools** — the same interface a customer's own agent can use later |
| "The trickiest bit is finding the correct products… something deterministic needs to happen first" | `find_products`: search, diet/allergen filters, usual products and Valio's substitutes narrow 17.5k → a priced shortlist; the AI only chooses among plausible products |
| "Don't hard-code how customers value price, CO₂, quality" | Customers write their **priorities** in plain words (editable); the AI weighs options by them |
| "Not assuming things on behalf of the customer… ask for help builds trust" | Unknowns are **asked with tap-able answers**; broad requests stop at an **editable ingredient list** (from the saved recipe, or a labelled estimate) that the customer approves before any product is picked; ranked **priority 1/2/3** options; "choose one" lines |
| "Customers have standard orders… if we lack a product, suggest a substitute; we get a signal" | **Order template check**: unavailable items → substitutes → customer confirms → **substitution signals** for Valio |
| "Human approval would be required… maybe dropped later if reliability is good enough" (Discord) | Customer confirms every cart; spend above the limit goes to a named approver; optional **auto-confirm when nothing changed** |
| Recipes & margins in My Aimo; carbon footprint reports | Saved recipes drive quantities; **cost per portion**; CO₂ per line and per cart |
| Webshop: order templates, user reference, availability notifications, cut-off times | Save cart as **order template**, **your reference**, **notify me when back**, **order-by** cut-off per line |

### The usual order in one tap

Most days a kitchen orders what it ordered last week. The start screen leads with it:

- **Your next usual order**: the order template for the next delivery day, checked live (products,
  total, cut-off). If everything is available: **Order as usual**, then 5 seconds to undo. If
  something is missing, only that is shown, with a substitute ready (Valio's substitute list, the
  customer's history, kitchen-size packs first); everything else stays as usual.
- **Order again**: any recent order (template, event, or one built with the assistant), re-checked live.
- **Quantity buttons**: −20% / usual / +20% / +50% / ×2 for the whole order, − / + one pack per line.
- **Weekly reminder** (preview of the SMS or email): before the cut-off the chef gets *"Your Friday
  order is ready: 8 products, about €228. One thing to check: …"* with **Confirm** / **Review**.

No AI is needed for this path (plain code, about a second); the assistant can still change the cart
afterwards, and the gate checks the signed mandate on every order.

Optional asks: delivery & sustainability comparison (reliability, stock certainty, CO₂, labels),
substitution & exceptions (cut-offs, unknown stock, lot sizes, pack maths, late items), traceability
(hash-chained plain-language audit log, signed quotes and confirmations).

## Architecture

```
 Webshop: Aimo Assistant (Valio-hosted)  ─┐
 Customer's own agent (any vendor/model) ─┴─ MCP / REST + Bearer <buyer-signed mandate> ─▶ Trade Gate
      get_customer_context · find_products · check_offers · create_quote · place_order …     ├─ catalog index (SQLite FTS, EN/FI)
                                                                                              ├─ offers & shortlist (unit maths, cut-offs, risk)
                                                                                              ├─ Valio price & availability APIs (batched, cached, 429-aware)
                                                                                              ├─ trust: mandate (W3C VC) · signed quotes/orders · JWKS
                                                                                              ├─ guardrails: AUTO / APPROVAL / BLOCKED with reasons
                                                                                              └─ hash-chained audit log · signals for Valio
```

The AI proposes; the gate decides. Spend limits, allergen rules and signatures are enforced by plain
code on Valio's side, so a wrong or manipulated model can't exceed what the customer signed.

## Run it

```bash
cp .env.example .env              # VALIO_API_KEY and ANTHROPIC_API_KEY
uv sync
uv run python -m trade_gate.catalog.build_index   # needs Valio's files in data/raw/ (resource portal)
uv run uvicorn trade_gate.api:app --port 8400     # gate + MCP + webshop (seeds demo customers on start)
(cd web && npm install && npm run build)          # webshop at http://localhost:8400, console at /console
```

- Webshop: `http://localhost:8400/` (Assistant · Approvals · Valio view · Preferences)
- MCP: `http://localhost:8400/mcp` (Streamable HTTP, `Authorization: Bearer <mandate>`)
- REST docs `/docs` · manifest `/.well-known/trade-gate.json` · keys `/.well-known/jwks.json`
- External-agent demo: `uv run python -m trade_gate.agent.buyer_agent hotel-aurora "1,000 L lactose-free milk by Monday"`
- Reset demo state (moves the DB aside): stop the server, `uv run python -m trade_gate.reset_demo`
- Tests (offline, deterministic): `uv run pytest`

## Demo customers

| Customer | Who confirms | Rules in the signed mandate |
|---|---|---|
| Kultakeittiö Catering (events 20–400 guests) | Mikko, chef-owner | Confirms up to €3,000; order template auto-confirms when nothing changed |
| Hotel Aurora Group (4 hotels) | Jari, head chef | Above €1,500 → Laura Mäkinen, F&B manager; reports CO₂ |
| Espoo Children's Hospital Kitchen | Sanna, kitchen manager | Peanuts, tree nuts, sesame blocked; products without allergen data → dietitian |

## Data

Valio Aimo's synthetic challenge data and mock APIs. Data files are not in this repository (licensed
for the challenge only); download them from the resource portal into `data/raw/`. Purchase history,
recipes and order templates of the demo customers are synthetic.

Answers from Valio we rely on (Discord, 14 Nov): `availableAmount ≥ 999999` = stock unknown but
orderable; empty availability = not available; `allowedLotSize 0.01` = 1; a 429 blocks for 30 s; no
order API — orders are produced for human approval and signed by the gate.

## Team

Built during Junction 2026 (13–15 Nov, Espoo). MIT licence.
