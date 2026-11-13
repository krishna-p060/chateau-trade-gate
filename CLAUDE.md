# Château Trade Gate — Junction 2026 × Valio Aimo "Trusted Trade Agents"

Context for Claude Code sessions in this folder. The user is the only human on the team; Claude is the rest. Goal: a **winning** submission for Valio Aimo's challenge. Effort is not a constraint; quality is.

## Hard constraints
- **Deadline: Sun 15 Nov 2026 10:00 EET** (final submission, set to FINAL). Peer review Sun 10:30–14:00.
- All code written during the event (started Fri 13 Nov 19:30 EET). Open-source libraries fine. Public repo, MIT.
- Valio data is synthetic and licensed **only for this challenge**. Keep raw data files out of git (`data/` is gitignored); ask Valio mentors before publishing any derived data.
- Secrets in `.env` (gitignored): `VALIO_API_KEY`, LLM API key. Never print or commit them.
- Submission: name ≤30, punchline ≤200, description, 2-minute video (strict), PDF deck, demo + source links.

## The challenge
How can a food-service wholesaler let autonomous purchasing agents find products, compare offers, get the right approval and place an order — without exposing real systems, confidential data or the marketplace roadmap? Prototype the **interface and operating model** for an external purchasing agent, built on **open, verifiable standards**.

**Core (must):** product/price/availability lookup · request price & availability then place order (fixed prices) · permissions & human-approval management.
**Optional:** delivery time & sustainability comparison · substitution/exception handling · traceability/explainability.
**Insights they want:** trust protocol · guardrails model · response logic (partial availability, good-better-best substitution) · audit trail.
**Scenarios:** need→recipe→order · last-minute event · supplier stock-out · proactive selling agent · allergen-safe substitution (school/hospital) · standing-order drift detection.
**Example:** "I need 1,000 litres of lactose-free milk by Monday…"

### Judging
End-to-end demo (request → lookup → order/approval) **30%** · Solving the user need precisely **20%** · Autonomy & controls **20%** · Robustness to exceptions **15%** · Openness & credible path to production **15%**.
Prizes: €4,000 / €2,000 / €1,000.

## Valio mock backend (checked 13 Nov)
- Portal: https://junction26.valioaimo.fi/ (docs at /docs, /redoc, /openapi.json — behind portal login).
- API base `https://junction26.valioaimo.fi/api`, header `X-API-Key`. Endpoints: `GET /ping`, `POST /availability`, `POST /price` (body `{customer, requestedDate, products[1..1000]}`), plus download endpoints. **Undisclosed rate limits; don't price the whole catalog. No order endpoint — ordering/approval is ours to build.**
- Availability: `closingTime` (order cut-off; can already be in the past!), `salesBlock`, `logisticModel` (Stock = real qty; Terminal = supplier warehouse, always 999999 = unknown), `scheduleLines[]` (`availableAmount`, `availableDate` may differ from requested, `salesUnit`; empty = not deliverable).
- Price: `catalogPrice`, `priceWithTax`, `comparisonPrice` + `comparisonUnit` (KG/L), `tax`, `listPrice`, `netPriceFound`, `error`.
- Files: product JSON (17,546 products, ~87 MB; synkkaData with EN/FI names, ingredients, nutrition, `classifications`: allergen CONTAINS/MAY_CONTAIN on ~41%, nonAllergen FREE_FROM, nutritionalClaim e.g. FREE_FROM_LACTOSE/VEGAN, packagingMarkedLabel e.g. EU_ORGANIC_FARMING/SVANEN/MSC; `units[]` with `sizeInBaseUnits`), schema JSON, delivery reliability CSV (4,425 rows, 0–1), carbon footprint CSV (11,033 rows, kg CO2e/kg by product group).

## Our design
Catalog index (SQLite + FTS, EN/FI) → **Trade Gate** core exposed as **MCP server + OpenAPI 3.1 REST** (`search_products`, `get_offers`, `create_quote` with validity, `place_order` idempotent, `get_order`) → **signed quotes** (JWS/Ed25519) and a signed buyer **mandate** credential (spend limits, categories, allergen rules) → **policy engine** (declarative rules → auto / needs_approval / blocked + reasons) → exception logic (unit conversion, cut-off roll-forward, partial-stock split, good-better-best substitutes by €/L, reliability, labels, CO2; missing allergen data = unknown → human) → Claude **buyer agent** using only MCP tools → **dashboard**: live trace, approval card, hash-chained human-readable **audit log**, buyer + Valio views → **scenario suite** with automatic match-precision scoring → docs (spec, assumptions, threat model, roadmap).

## References
- All challenge texts + event rules: `../Junction2026_Software_Challenges.pdf`
- Briefing pack: `~/Downloads/junction-teammate-pack/`
- Sibling project (AfterQuery RL env, separate repo, separate session): `../kitchen-gauntlet/`
