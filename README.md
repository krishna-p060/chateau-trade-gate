# Château Trade Gate — Aimo Assistant

An AI ordering assistant for Valio Aimo's webshop (food wholesale for professional kitchens), built for
the Junction 2026 challenge *Trusted Trade Agents*. The AI builds the cart. It cannot place it: every
order passes a gate on Valio's side that checks, in plain code, the mandate the customer signed, the
customer's own eight weeks of purchases and Valio's live stock, then signs the order or refuses it.

**Try to break it. No keys, no Valio data, two seconds:**

```bash
uv sync && uv run python -m trade_gate.walkthrough
```

| An agent tries to | The gate answers |
|---|---|
| order a hazelnut bar for the children's hospital | `BLOCKED` `allergen.conflict`. Nothing goes to approval: no human can override it |
| approve its own €2,980 order | `REFUSED` `APPROVER_NOT_AUTHORISED`. Still waiting for Laura Mäkinen, F&B manager |
| raise its own limit to €1,000,000 and sign with its own key | `REFUSED` `MANDATE_INVALID` |
| keep the genuine mandate from before the customer lowered the limit | `REFUSED` `MANDATE_SUPERSEDED` |
| add a negative line so an over-limit basket totals less | `REFUSED` `BAD_QUANTITY` |
| split one purchase into two halves under the limit | second half `HELD` `spend.split_order` |
| order 20 packs of butter where eight weeks of history never show more than 2 | `HELD` `quantity.unusual` |
| repeat last week's order after the price rose 20% | `HELD` `price.increase` (€1.01 → €1.21) |
| get an approval after the stock is gone | `REFUSED` `ORDER_LAPSED`. Closed, never confirmed, never left pending |
| rewrite the audit entry of a blocked order to "confirmed" | `DETECTED` at that entry: the hash chain breaks there |

Ten of ten stopped, each in under half a second, each with the audit entries the gate wrote. The same ten are buttons
in the webshop's **Try to break it** tab and a test that fails if one gets through. They run on the
bundled 51-product sample catalog and a simulated Valio; with Valio's key they run against Valio's
17,546 products and live price and availability APIs.

## The assistant, on Valio's data

> *Wednesday, a caterer gets a call:* "Company party for 80 on Saturday: creamy salmon pasta, green
> salad and a dessert. 6 guests are gluten-free."

Aimo Assistant reads the customer's saved recipes and 8 weeks of purchase history, scales the recipes
to 74 + 6 gluten-free portions, and narrows Valio's **17,546 products → 661 matches → 205 checked live
→ 88 candidates** with plain code before the AI chooses. It notices the customer's usual Barilla
spaghetti cannot be delivered, offers fresh vs frozen salmon as the customer's choice, and builds a
cart: priority 1 per line with alternatives when they matter (cheaper, usual, lower CO₂, Finnish), each
with a one-line *why*, live price, stock, delivery, order-by time and cost per portion. The chef
confirms; the gate checks the mandate and signs.

What is not there: Valio's mock has no order API, so a confirmed order is signed and recorded by the
gate and goes no further. The webshop has no login: the gate checks that an approver is named in the
mandate, not that the person typing is that approver. The proactive selling agent from the brief is not
built; Valio's side gets signals instead (substitutes accepted, alternatives preferred, demand nothing
could meet). Order-template drift is two checks, price against the last price paid and quantity against
history. The keyless mode shows the gate, not the assistant, which needs an Anthropic key.

## Run it

Without keys (sample catalog, simulated Valio; the server says so at start and in its manifest):

```bash
uv sync
uv run python -m trade_gate.walkthrough          # the challenge's 1,000 L example, 6 exceptions, 7 attempts: 31 checks
uv run pytest                                    # 33 tests, offline, fixed clock
(cd web && npm install && npm run build)
uv run uvicorn trade_gate.api:app --port 8400    # http://localhost:8400 opens on "Try to break it"
```

With Valio's data and the assistant:

```bash
cp .env.example .env                             # VALIO_API_KEY and ANTHROPIC_API_KEY
# put product_data.json, delivery_reliability.csv and carbon_footprint.csv from the resource portal in data/raw/
uv run python -m trade_gate.catalog.build_index
(cd web && npm install && npm run build)
uv run uvicorn trade_gate.api:app --port 8400    # gate + MCP + webshop; seeds the demo customers
```

- Webshop: `http://localhost:8400/` (Assistant · Approvals · Valio view · Preferences · Try to break it)
- MCP: `http://localhost:8400/mcp` (Streamable HTTP, `Authorization: Bearer <mandate>`)
- REST docs `/docs` · manifest `/.well-known/trade-gate.json` · keys `/.well-known/jwks.json`
- External-agent demo: `uv run python -m trade_gate.agent.buyer_agent hotel-aurora "1,000 L lactose-free milk by Monday"`
- Reset demo state (moves the DB aside): stop the server, `uv run python -m trade_gate.reset_demo`
- `TRADE_GATE_DEMO=1` forces the keyless mode; `TRADE_GATE_TEST_REAL_CATALOG=1 uv run pytest` runs the tests on the real catalog

## What Valio Aimo told us, and what we built

| Mentors / Valio said | Built |
|---|---|
| "Assume the agent is surfaced in our own webshop… with an MCP decoupling layer" | **Aimo Assistant** in a webshop UI, talking to Valio only through the Trade Gate's **MCP tools**, the same interface a customer's own agent can use later |
| "The trickiest bit is finding the correct products… something deterministic needs to happen first" | `find_products`: search, diet/allergen filters, usual products and Valio's substitutes narrow 17.5k → a priced shortlist; the AI only chooses among plausible products |
| "Don't hard-code how customers value price, CO₂, quality" | Customers write their **priorities** in plain words (editable); the AI weighs options by them |
| "Not assuming things on behalf of the customer… ask for help builds trust" | Unknowns are **asked with tap-able answers**; broad requests stop at an **editable ingredient list** (from the saved recipe, or a labelled estimate) that the customer approves before any product is picked; ranked **priority 1/2/3** options; "choose one" lines |
| "Customers have standard orders… if we lack a product, suggest a substitute; we get a signal" | **Order template check**: unavailable items → substitutes → customer confirms → **substitution signals** for Valio |
| "Human approval would be required… maybe dropped later if reliability is good enough" (Discord) | Customer confirms every cart; spend above the limit goes to a named approver; optional **auto-confirm when nothing changed**, which a price rise or an unusual quantity sends back to a person |
| Recipes & margins in My Aimo; carbon footprint reports | Saved recipes drive quantities; **cost per portion**; CO₂ per line and per cart |
| Webshop: order templates, user reference, availability notifications, cut-off times | Save cart as **order template**, **your reference**, **notify me when back**, **order-by** cut-off per line |

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

Interface, trust protocol, guardrail rules, exception logic and the path to production: [docs/INTERFACE.md](docs/INTERFACE.md).

## Demo customers

| Customer | Who confirms | Rules in the signed mandate |
|---|---|---|
| Kultakeittiö Catering (events 20–400 guests) | Mikko, chef-owner | Confirms up to €3,000; order template auto-confirms when nothing changed |
| Hotel Aurora Group (4 hotels) | Jari, head chef | Above €1,500 → Laura Mäkinen, F&B manager; reports CO₂ |
| Espoo Children's Hospital Kitchen | Sanna, kitchen manager | Peanuts, tree nuts, sesame blocked; products without allergen data → dietitian |

## Data

Valio Aimo's synthetic challenge data and mock APIs. Valio's files are not in this repository (licensed
for the challenge only). The bundled sample in `src/trade_gate/sample/` is 51 products written for this
repository in the same format. Purchase history, recipes and order templates of the demo customers are
synthetic.

Answers from Valio we rely on (Discord, 14 Nov): `availableAmount ≥ 999999` = stock unknown but
orderable; empty availability = not available; `allowedLotSize 0.01` = 1; a 429 blocks for 30 s; no
order API.

Built during Junction 2026 (13–15 Nov, Espoo). MIT licence.
