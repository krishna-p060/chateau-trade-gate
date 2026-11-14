# Trade Gate — interface & operating model

How an external purchasing agent interacts with Valio Aimo, what it can see and decide, and how
both sides can trust each other without manual checks. Everything here is built on open,
documented standards: **MCP** (Model Context Protocol) and **OpenAPI 3.1** for the interface,
**W3C Verifiable Credentials** (vc+jwt) for authority, **JWS / EdDSA (RFC 8037)** for signed claims,
**JWKS** for key discovery, **GS1** codes for product data.

## 1. Actors

| Actor | Role | Holds |
|---|---|---|
| **Buyer organisation** (hotel, hospital…) | Decides what its agent may do | Its own signing key; issues the mandate |
| **Buyer agent** (any vendor, any model) | Finds, compares, orders on the buyer's behalf | The mandate (bearer credential) |
| **Trade Gate** (Valio side) | Answers queries, quotes, enforces guardrails, records everything | Valio's signing key, the buyer registry |
| **Human approver** (named in the mandate) | Signs off exceptions | Approval console |
| **Customer in the webshop** (chef, kitchen manager) | Describes the need, makes choices, confirms the cart | Webshop login (SSO in production) |
| **Aimo Assistant** (Valio-hosted agent) | Turns menus/events/order templates into carts | The customer's mandate, used through the same MCP tools |

## 2. Flow

```
agent ──get_my_mandate──▶ gate            what am I allowed to do?
agent ──search_products─▶ gate            static catalog only (no rate-limited calls)
agent ──plan_purchase───▶ gate ──▶ Valio price + availability (1 batched call each)
      ◀── good / better / best options + every ruled-out product with its reason
agent ──create_quote────▶ gate ──▶ live re-check ──▶ signed quote (fixed price, valid 2 h)
agent ──place_order─────▶ gate: verify quote signature + mandate signature + guardrails
      ├─ AUTO      → order confirmed, signed confirmation returned
      ├─ APPROVAL  → named human gets reasons + agent rationale → approve / reject
      └─ BLOCKED   → refused with reasons (never overridable, e.g. allergen conflict)
every step ──▶ hash-chained audit log (readable by buyer and Valio)
```

Prices are fixed customer prices: there is no negotiation step. A quote locks them for the
approval window; an expired quote cannot become an order.

## 3. Tools (MCP) / endpoints (REST)

| MCP tool | REST | Purpose |
|---|---|---|
| `get_my_mandate` | `GET /api/v1/mandate` | Limits, allergen rules, approvers — read first |
| `get_customer_context` | — | Segment, stated priorities, rules, usual products, saved recipes, order templates |
| `find_products` | — | Several ingredients at once → deterministic shortlist (≤7 each) with live price, packs, delivery, cut-off, CO₂, usual/substitute flags |
| `search_products` | `POST /api/v1/products/search` | EN/FI full-text search with hard diet/allergen filters |
| `get_product` | `GET /api/v1/products/{id}` | Ingredients, allergens, labels, pack size, substitutes |
| `check_offers` | `POST /api/v1/offers` | Live price + availability for chosen products, in buyer units |
| `plan_purchase` | `POST /api/v1/plans` | Need → ranked options, split orders, rejections with reasons |
| `create_quote` | `POST /api/v1/quotes` | Signed, fixed-price quote for an exact basket |
| `place_order` | `POST /api/v1/orders` | Commit; guardrails decide AUTO / APPROVAL / BLOCKED; idempotent |
| `get_order` | `GET /api/v1/orders/{id}` | Status incl. approval and decision |
| `get_audit_trail` | `GET /api/console/audit/narrative` | Human-readable record of what happened |

Discovery: `/.well-known/trade-gate.json` (capabilities, flow, assumptions) and
`/.well-known/jwks.json` (Valio's public key). Full schema: `/openapi.json`.

## 4. Trust protocol

**Authority (buyer → gate).** The buyer signs a `PurchasingMandate` credential (W3C VC 2.0 data
model, secured as `vc+jwt`, EdDSA) naming the agent and its limits. The agent presents it as a
bearer token. The gate verifies the signature against the buyer's registered key, checks expiry,
and compares the content with the mandate the buyer has on file now. A mandate from another buyer
(`MANDATE_INVALID`), a modified mandate (`MANDATE_INVALID`) and a genuine mandate from before the
buyer changed its rules (`MANDATE_SUPERSEDED`) are refused, and the refusal is logged. The agent id
is read from the mandate itself; binding it to an agent-held key is not built.

**Claims (gate → agent).** Every quote and order confirmation is a JWS signed by Valio's key and
verifiable offline against the JWKS. The quote carries what the agent needs to trust without a
manual check:

| Claim | Meaning |
|---|---|
| `unit_price`, `total_price` | Fixed customer price, valid until `expires_at` |
| `stock_status` | `confirmed` (Valio warehouse quantity) · `untracked` · `unconfirmed` (supplier warehouse; real stock unknown) |
| `earliest_delivery` + `earliest_delivery_confirmed` | Confirmed by Valio, or our estimate after a passed cut-off |
| `content_per_sales_unit` | Verified from Valio's own price-per-litre/kg, not guessed from the name |
| `delivery_reliability` | Share of ordered quantity historically delivered |
| `sustainability_labels`, `co2_kg` | GS1 package labels; product-group CO2 average |

The minimum standard is honesty about uncertainty: anything Valio does not actually know (supplier
stock, estimated dates, missing allergen declarations) is labelled as such, never smoothed over.

## 5. Guardrails model

Evaluated by the gate on every order, independent of what the agent says.

| Rule | Outcome | Why |
|---|---|---|
| Total ≤ autonomous limit | AUTO | Routine purchase |
| Total > autonomous limit | APPROVAL | Spend authority |
| Total > hard maximum | BLOCKED | Never, even with approval |
| Weekly spend would exceed budget | APPROVAL | Budget control |
| Same products ordered in last 24 h push past the autonomous limit | APPROVAL | Stops order splitting |
| Product contains / may contain an allergen the buyer must avoid | BLOCKED | Safety is absolute |
| Product has no allergen declaration (strict buyers) | APPROVAL | Cannot verify safety automatically |
| Stock unknown (`availableAmount ≥ 999999`, typically supplier warehouse) | APPROVAL | Delivery not guaranteed |
| Estimated delivery date after a passed cut-off | APPROVAL | Not confirmed by Valio |
| Arrives after the requested date | APPROVAL | Buyer must accept the delay |
| Substitute outside stated preferences | APPROVAL | Buyer's choice. The agent declares the line a substitute; the webshop assistant always does |
| Unit price more than X % above the last price this buyer paid (or a reference price in its profile) | APPROVAL | Price drift on repeat orders |
| Quantity more than 5× the largest order of that product in the buyer's delivered history, in an order no person has seen | APPROVAL | A slipped digit or a hallucinated quantity; `unusual_quantity_factor` in the mandate, 0 turns it off |
| Category blocked for this agent | BLOCKED | Scope of the mandate (no demo mandate sets one) |

Before any rule runs, the gate refuses a quote line whose quantity is not a positive number, adds up
repeated lines of one product, and at order time reads Valio's availability again past its cache: if
stock or an order-by time no longer holds, the order is refused with `QUOTE_STALE` and what changed.

**Approval.** Only a person named in the buyer's current mandate can decide; any other name is
refused with `APPROVER_NOT_AUTHORISED` and logged. Approval repeats the stock and order-by check and
the price hold: an order that no longer holds is closed (`ORDER_LAPSED`), never confirmed and never
left pending. Names are checked, identities are not: the demo has no login (see §9).

**Settings.** An allergen name the gate cannot map to a GS1 code is not saved (it would show as a rule
and protect nothing; English and Finnish names are known), and the approval limit cannot exceed the
mandate's hard maximum.

Each finding carries a rule id (machine-readable) and a sentence (human-readable). The approver
sees the reasons next to the agent's own rationale.

**Customer-confirmed carts (webshop).** When a person reviews a cart and confirms it, the delivery,
substitution and price warnings they were shown count as accepted (recorded in the decision as
"shown in the cart and accepted by …"). Spend rules, allergen rules and hard limits still apply: a
head chef's cart above €1,500 still goes to the F&B manager; an allergen conflict is still blocked.
Preferences edited in the webshop re-sign the mandate and are logged (`mandate.updated`).

## 5b. The webshop channel: Aimo Assistant

The customer approves at three points; the assistant never skips one:

| Step | Who acts | What happens |
|---|---|---|
| 1. Request | Customer | A dish/menu/event ("pasta pesto for 40 on Friday") or a specific list ("5 kg onions, 2 kg penne") |
| 1b. Questions | Customer taps | Portions, date or diets that are not stated are **asked, never guessed** (up to 3 questions, tap-able answers) |
| 2. Ingredients | **Customer edits and approves** | Broad requests only. The list comes from the customer's **saved recipe** (scaled) or, if none matches, the assistant's **estimate** (labelled as such; can be saved as a recipe). No product search happens before approval; the approved list is authoritative and logged (`plan.approved`, with every change) |
| 3. Products | **Customer chooses and confirms** | One `find_products` call narrows the catalog deterministically; the AI picks priority 1 per line and up to two alternatives using the customer's own priorities; lines that depend on taste are marked "choose one". Guardrail checks (spend limit, allergen rules, delivery) are shown before confirming |
| 4. Order | Gate (+ approver) | Signed quote → `place_order(confirmed_by=…)` → guardrails → signed order, or approval by the named approver |

A specific list skips step 2 (the customer already stated items and quantities). Customer context is
loaded by the application through `get_customer_context`, not recalled by the model.

Signals for Valio: `signal.substitution` (accepted substitute), `signal.preference` (alternative chosen
over the suggestion), `signal.unmet` (need nothing could meet in time), `signal.notify` (back-in-stock
request).

Order templates (Valio's standing orders) are checked for the next delivery day: if everything is
available and the customer allowed it, the order is confirmed automatically; otherwise substitutes are
proposed for the missing items and the customer decides.

## 6. Response logic for exceptions

- **Unit conversion:** litres/kg → sales packs, respecting order multiples (`allowedLotSize`); pack
  content verified from Valio's unit price.
- **Cut-offs:** after `closingTime`, the goods cannot arrive on `availableDate`; the earliest real
  date is estimated from the product's lead time and flagged unconfirmed.
- **Placeholders:** `999999` (supplier warehouse) = unknown stock; `9999999999` = not tracked.
- **Partial availability:** quote refused with the exact stock; planner proposes a split across
  in-stock products.
- **Good / better / best:** cheapest · best value once delivery risk is priced in · highest
  certainty and sustainability. Every ruled-out product is listed with its reason.
- **Substitutes:** Valio's own substitution rules (`substitutions` in the product data) plus
  catalog search under the same diet and allergen constraints; allergen rules are never relaxed.

## 7. Audit trail

Append-only log; each entry has a plain-language summary, structured data, and
`hash = SHA-256(entry + previous hash)`. Changing or deleting any entry breaks every later hash
(`verify_chain`). The same log serves the buyer ("what did my agent do and why?") and Valio ("what
did external agents do in our systems?").

## 7b. Try to break it

`trade_gate/attacks.py` holds ten attempts to get an order past the gate: a forbidden allergen, an
agent approving its own order, a forged mandate, a superseded mandate, a negative line, a split
purchase, ten times the usual quantity, a repeat order after a 20 % price rise, an approval after the
stock is gone, and a rewritten audit entry. Each runs the gate's own code on a scratch gate (same
catalog and Valio client, its own order book) and returns what was sent, the gate's code and reason,
and the audit entries written. `uv run python -m trade_gate.walkthrough` prints them,
`POST /api/demo/attacks/{id}` serves them, the webshop's "Try to break it" tab shows them, and
`tests/test_gate.py` fails if one gets through.

## 8. Assumptions (visible to agents in the manifest)

1. Prices are fixed customer prices; no negotiation.
2. Supplier-warehouse (Terminal) stock is unknown; 999999 is a placeholder.
3. After a passed cut-off, earliest delivery = now + the product's lead time, no Sunday deliveries,
   marked as an estimate.
4. Products without allergen declarations are never treated as allergen-safe.
5. Litres are approximated as kilograms for CO2 estimates.
6. The mock APIs ignore the customer number and requested date; the design does not rely on that.

## 9. Path to production

| Now (hackathon) | Next |
|---|---|
| Buyer keys registered by seed script | Buyer onboarding in the webshop; keys via `did:web` |
| Mandate signed with a demo key on the server | Preferences editor exists; key moves to the customer's browser/passkey so Valio can't forge it |
| Demo console without login | SSO for approvers; approvals also by email / Teams |
| Order stored in the gate | Order handed to Valio's ERP; delivery status back to the agent |
| SQLite state | Postgres; audit log anchored to an external timestamping service |
| Estimated dates after cut-off | Availability API that returns the next feasible date |
| Synthetic purchase history and recipes | Real purchase history and My Aimo recipes / margin calculator |
| Assistant only in the webshop | Same MCP tools exposed to customers' own agents (OAuth consent per mandate) |
| Payment out of scope | Agentic payment standards (x402, AP2) for card-less B2B settlement |
