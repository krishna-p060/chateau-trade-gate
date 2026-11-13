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
and that the agent id matches. A mandate from another buyer, a modified mandate, or a mandate for
another agent is refused.

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
| Supplier-warehouse stock (unknown quantity) | APPROVAL | Delivery not guaranteed |
| Estimated delivery date after a passed cut-off | APPROVAL | Not confirmed by Valio |
| Arrives after the requested date | APPROVAL | Buyer must accept the delay |
| Substitute outside stated preferences | APPROVAL | Buyer's choice |
| Price above reference by more than X % | APPROVAL | Price drift |
| Category blocked for this agent | BLOCKED | Scope of the mandate |

Each finding carries a rule id (machine-readable) and a sentence (human-readable). The approver
sees the reasons next to the agent's own rationale.

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
| Mandate issued by script | Mandate editor in the buyer's webshop account |
| Demo console without login | SSO for approvers; approvals also by email / Teams |
| Order stored in the gate | Order handed to Valio's ERP; delivery status back to the agent |
| SQLite state | Postgres; audit log anchored to an external timestamping service |
| Estimated dates after cut-off | Availability API that returns the next feasible date |
| Rule-based substitutes | Recipe-aware substitution and standing-order drift detection |
| Payment out of scope | Agentic payment standards (x402, AP2) for card-less B2B settlement |
