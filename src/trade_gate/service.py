"""Trade Gate service: the single core behind the REST API and the MCP server.

Flow: search -> plan (good/better/best) -> create_quote (live re-check, signed, fixed price for a
validity window) -> place_order (quote + buyer mandate verified, guardrails evaluated server-side)
-> AUTO confirm | human approval | block. Everything is written to the hash-chained audit log.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from datetime import date, datetime, timedelta

import jwt

from trade_gate.catalog.store import Catalog
from trade_gate.config import STATE_DIR
from trade_gate.engine.offers import TZ, build_offer
from trade_gate.engine.planner import Need, plan
from trade_gate.trust import mandate as mandates
from trade_gate.trust.audit import AuditLog
from trade_gate.trust.keys import KeyPair, canonical, verify
from trade_gate.trust.policy import APPROVAL, AUTO, BLOCKED, evaluate

QUOTE_VALIDITY = timedelta(hours=2)  # prices held while a human approves
GATE_ID = "valio-aimo-trade-gate"


class GateError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _now() -> datetime:
    return datetime.now(TZ)


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(5)}"


class TradeGate:
    def __init__(self, valio, catalog: Catalog | None = None, state_dir=STATE_DIR):
        state_dir.mkdir(parents=True, exist_ok=True)
        self.valio = valio
        self.catalog = catalog or Catalog()
        self.lock = threading.RLock()
        self.con = sqlite3.connect(state_dir / "gate.sqlite", check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.executescript("""
            CREATE TABLE IF NOT EXISTS buyers (id TEXT PRIMARY KEY, name TEXT, jwk TEXT, profile TEXT);
            CREATE TABLE IF NOT EXISTS quotes (id TEXT PRIMARY KEY, buyer_id TEXT, created TEXT, expires TEXT,
                body TEXT, jws TEXT);
            CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, buyer_id TEXT, quote_id TEXT, status TEXT,
                created TEXT, updated TEXT, total REAL, idem_key TEXT UNIQUE, agent_id TEXT, rationale TEXT,
                decision TEXT, confirmation_jws TEXT);
            CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, order_id TEXT, buyer_id TEXT, status TEXT,
                created TEXT, decided TEXT, approver TEXT, note TEXT, reasons TEXT);
        """)
        self.key = KeyPair.load_or_create(state_dir / "gate_ed25519.pem", kid=f"{GATE_ID}-2026-11")
        self.audit = AuditLog(self.con, self.lock)

    # =================================================================== buyers
    def register_buyer(self, buyer_id: str, name: str, jwk: dict, profile: dict | None = None) -> None:
        with self.lock:
            self.con.execute("INSERT OR REPLACE INTO buyers VALUES (?,?,?,?)",
                             (buyer_id, name, json.dumps(jwk), json.dumps(profile or {})))
            self.con.commit()

    def buyer(self, buyer_id: str) -> dict:
        r = self.con.execute("SELECT * FROM buyers WHERE id=?", (buyer_id,)).fetchone()
        if not r:
            raise GateError("UNKNOWN_BUYER", f"Buyer {buyer_id} is not registered with the gate.", 404)
        return {"id": r["id"], "name": r["name"], "jwk": json.loads(r["jwk"]), "profile": json.loads(r["profile"])}

    def buyers(self) -> list[dict]:
        return [{"id": r["id"], "name": r["name"], "profile": json.loads(r["profile"])}
                for r in self.con.execute("SELECT * FROM buyers")]

    def verify_mandate(self, buyer_id: str, mandate_jws: str) -> mandates.Mandate:
        b = self.buyer(buyer_id)
        try:
            m = mandates.verify_mandate(mandate_jws, b["jwk"])
        except (jwt.PyJWTError, ValueError, KeyError) as e:
            raise GateError("MANDATE_INVALID", f"Purchasing mandate failed verification: {e}", 403) from e
        if m.buyer_id != buyer_id:
            raise GateError("MANDATE_MISMATCH", "Mandate was issued for a different buyer.", 403)
        return m

    def authenticate(self, mandate_jws: str | None) -> mandates.Mandate:
        """Identify the calling agent from its buyer-signed mandate (bearer token)."""
        if not mandate_jws:
            raise GateError("NO_MANDATE", "Present your buyer-signed purchasing mandate as a Bearer token.", 401)
        try:
            unverified = jwt.decode(mandate_jws, options={"verify_signature": False})
            buyer_id = unverified["vc"]["credentialSubject"]["buyer_id"]
        except (jwt.PyJWTError, KeyError, TypeError) as e:
            raise GateError("MANDATE_INVALID", "Bearer token is not a purchasing mandate.", 401) from e
        return self.verify_mandate(buyer_id, mandate_jws)

    # =================================================================== discovery
    def search(self, buyer_id: str | None, agent_id: str, **kw) -> list[dict]:
        res = self.catalog.search(**kw)
        self.audit.append(buyer_id=buyer_id, actor=agent_id, event="catalog.search",
                          summary=f"Searched the catalog for “{kw.get('query', '')}”"
                                  + (f" (diets: {', '.join(kw['diets'])})" if kw.get("diets") else "")
                                  + (f" (avoid: {', '.join(kw['avoid_allergens'])})" if kw.get("avoid_allergens") else "")
                                  + f": {len(res)} products.",
                          data={"filters": kw, "results": [p.id for p in res]})
        return [p.public() for p in res]

    def product(self, pid: str) -> dict:
        p = self.catalog.get(pid)
        if not p:
            raise GateError("UNKNOWN_PRODUCT", f"No product {pid}.", 404)
        return p.public()

    def offers(self, buyer_id: str | None, agent_id: str, product_ids: list[str], deliver_by: date,
               quantity: float | None = None, unit: str = "unit") -> list[dict]:
        prods = self.catalog.get_many(product_ids)
        prices = self.valio.prices([p.id for p in prods], deliver_by)
        avail = self.valio.availability([p.id for p in prods], deliver_by)
        out = [build_offer(p, prices.get(p.id), avail.get(p.id), need_qty=quantity, need_dim=unit,
                           deliver_by=deliver_by).to_dict() for p in prods]
        self.audit.append(buyer_id=buyer_id, actor=agent_id, event="offers.check",
                          summary=f"Checked live price and availability for {len(prods)} products "
                                  f"for delivery by {deliver_by}.",
                          data={"products": product_ids, "deliver_by": deliver_by.isoformat()})
        return out

    def plan(self, buyer_id: str | None, agent_id: str, need: Need) -> dict:
        p = plan(need, self.catalog, self.valio)
        top = p.options[0] if p.options else None
        summary = (f"Planned “{need.query}” — {need.quantity:g} {need.unit} by {need.deliver_by}: "
                   f"{len(p.options)} options, {len(p.rejected)} products ruled out.")
        if top:
            summary += f" Cheapest: {top.title} at €{min(o.total_price for o in p.options):,.2f}."
        if p.exception:
            summary += f" Exception: {p.exception.split(':')[0]}."
        self.audit.append(buyer_id=buyer_id, actor=agent_id, event="plan.created", summary=summary,
                          data={"need": need.to_dict(), "options": [
                              {"tier": o.tier, "title": o.title, "total": o.total_price,
                               "confidence": o.confidence, "meets_deadline": o.meets_deadline,
                               "earliest_delivery": o.earliest_delivery, "delivered_qty": o.delivered_qty,
                               "reasons": o.reasons, "warnings": o.warnings,
                               "lines": [{"product_id": ln.product_id, "name": ln.name, "units": ln.units,
                                          "sales_unit": ln.sales_unit, "unit_price": ln.unit_price,
                                          "line_total": ln.total_price, "stock_status": ln.stock_status,
                                          "earliest_delivery": ln.earliest_delivery} for ln in o.lines]}
                              for o in p.options],
                              "rejected": p.rejected[:20], "exception": p.exception})
        return p.to_dict()

    # =================================================================== quotes
    def create_quote(self, buyer_id: str, agent_id: str, lines: list[dict], deliver_by: date,
                     note: str = "") -> dict:
        self.buyer(buyer_id)
        if not lines:
            raise GateError("EMPTY_QUOTE", "A quote needs at least one line.")
        ids = [ln["product_id"] for ln in lines]
        prods = {p.id: p for p in self.catalog.get_many(ids)}
        missing = [i for i in ids if i not in prods]
        if missing:
            raise GateError("UNKNOWN_PRODUCT", f"Unknown product codes: {', '.join(missing)}", 404)
        prices = self.valio.prices(ids, deliver_by)
        avail = self.valio.availability(ids, deliver_by)
        now = _now()
        q_lines, problems = [], []
        for ln in lines:
            p = prods[ln["product_id"]]
            units = float(ln["units"])
            o = build_offer(p, prices.get(p.id), avail.get(p.id), need_qty=units, need_dim="unit",
                            deliver_by=deliver_by, now=now)
            if o.units_to_order != units:
                problems.append(f"{p.name}: must be ordered in multiples of {p.allowed_lot_size:g} "
                                f"{p.sales_unit} (e.g. {o.units_to_order:g}).")
            hard = [i for i in o.issues if i.severity == "blocking" and i.code != "LATE"]
            if hard:
                problems += [f"{p.name}: {i.message}" for i in hard]
            if o.stock_status == "partial":
                problems.append(f"{p.name}: only {o.available_amount:g} {p.sales_unit} in stock, {units:g} requested.")
            q_lines.append({
                "product_id": p.id, "name": p.name, "units": units, "sales_unit": p.sales_unit,
                "unit_price": o.unit_price, "unit_price_with_tax": o.unit_price_with_tax,
                "line_total": round(units * (o.unit_price or 0), 2),
                "line_total_with_tax": round(units * (o.unit_price_with_tax or 0), 2),
                "content_per_sales_unit": o.content_per_sales_unit, "content_dim": o.content_dim,
                "stock_status": o.stock_status, "logistic_model": o.logistic_model,
                "closing_time": o.closing_time, "earliest_delivery": o.earliest_delivery,
                "earliest_delivery_confirmed": o.earliest_delivery_confirmed, "meets_deadline": o.meets_deadline,
                "delivery_reliability": o.delivery_reliability, "reliability_known": o.reliability_known,
                "sustainability_labels": o.sustainability_labels, "co2_kg": o.co2_kg,
                "issues": [i.__dict__ for i in o.issues],
                **{k: ln[k] for k in ("is_substitute", "replaces", "outside_preferences") if k in ln},
            })
        if problems:
            self.audit.append(buyer_id=buyer_id, actor=GATE_ID, event="quote.refused",
                              summary="Refused to quote: " + " ".join(problems),
                              data={"lines": lines, "problems": problems})
            raise GateError("QUOTE_REFUSED", " ".join(problems), 409)

        qid = _id("q")
        expires = now + QUOTE_VALIDITY
        body = {
            "quote_id": qid, "gate": GATE_ID, "buyer_id": buyer_id, "agent_id": agent_id,
            "issued_at": now.isoformat(timespec="seconds"), "expires_at": expires.isoformat(timespec="seconds"),
            "deliver_by": deliver_by.isoformat(), "currency": "EUR", "lines": q_lines,
            "total_price": round(sum(ln["line_total"] for ln in q_lines), 2),
            "total_price_with_tax": round(sum(ln["line_total_with_tax"] for ln in q_lines), 2),
            "price_basis": "Fixed Valio price for this customer; not negotiable; held until expires_at.",
            "note": note,
        }
        jws = self.key.sign({"iss": GATE_ID, "sub": buyer_id, "jti": qid, "iat": int(now.timestamp()),
                             "exp": int(expires.timestamp()), "quote": body}, typ="quote+jwt")
        with self.lock:
            self.con.execute("INSERT INTO quotes VALUES (?,?,?,?,?,?)",
                             (qid, buyer_id, body["issued_at"], body["expires_at"], canonical(body), jws))
            self.con.commit()
        lines_txt = "; ".join(f"{ln['units']:g} × {ln['name']} @ €{ln['unit_price']:.2f}" for ln in q_lines)
        self.audit.append(buyer_id=buyer_id, actor=GATE_ID, event="quote.issued", ref=qid,
                          summary=f"Issued signed quote {qid}: {lines_txt}. Total €{body['total_price']:,.2f} "
                                  f"excl. VAT, valid until {expires:%H:%M}.",
                          data={"quote_id": qid, "total": body["total_price"], "lines": [
                              {k: ln[k] for k in ("product_id", "units", "unit_price", "stock_status",
                                                  "earliest_delivery")} for ln in q_lines]})
        return {"quote": body, "signature": jws}

    def get_quote(self, quote_id: str) -> dict:
        r = self.con.execute("SELECT body, jws FROM quotes WHERE id=?", (quote_id,)).fetchone()
        if not r:
            raise GateError("UNKNOWN_QUOTE", f"No quote {quote_id}.", 404)
        return {"quote": json.loads(r["body"]), "signature": r["jws"]}

    def verify_quote(self, jws: str) -> dict:
        try:
            claims = verify(jws, self.key.jwk())
        except jwt.ExpiredSignatureError as e:
            raise GateError("QUOTE_EXPIRED", "The quote has expired; request a new one.", 409) from e
        except jwt.PyJWTError as e:
            raise GateError("QUOTE_INVALID", f"Quote signature invalid: {e}", 400) from e
        return claims["quote"]

    # =================================================================== orders
    def _week_spend(self, buyer_id: str) -> float:
        start = (_now() - timedelta(days=_now().weekday())).date().isoformat()
        r = self.con.execute("SELECT COALESCE(SUM(total),0) FROM orders WHERE buyer_id=? AND status IN "
                             "('CONFIRMED','PENDING_APPROVAL') AND created >= ?", (buyer_id, start)).fetchone()
        return float(r[0])

    def _related_recent_spend(self, buyer_id: str, product_ids: set[str]) -> float:
        since = (_now() - timedelta(hours=24)).isoformat(timespec="seconds")
        total = 0.0
        for r in self.con.execute("SELECT o.total, q.body FROM orders o JOIN quotes q ON q.id = o.quote_id "
                                  "WHERE o.buyer_id=? AND o.status IN ('CONFIRMED','PENDING_APPROVAL') "
                                  "AND o.created >= ?", (buyer_id, since)):
            if {ln["product_id"] for ln in json.loads(r["body"])["lines"]} & product_ids:
                total += float(r["total"])
        return total

    def place_order(self, buyer_id: str, agent_id: str, quote_id: str, mandate_jws: str,
                    idempotency_key: str, rationale: str = "") -> dict:
        existing = self.con.execute("SELECT id FROM orders WHERE idem_key=?", (idempotency_key,)).fetchone()
        if existing:
            return self.get_order(existing["id"])
        stored = self.get_quote(quote_id)
        quote = self.verify_quote(stored["signature"])
        if quote["buyer_id"] != buyer_id:
            raise GateError("QUOTE_MISMATCH", "Quote belongs to another buyer.", 403)
        if self.con.execute("SELECT 1 FROM orders WHERE quote_id=? AND status!='REJECTED'", (quote_id,)).fetchone():
            raise GateError("QUOTE_USED", "This quote already has an order.", 409)
        m = self.verify_mandate(buyer_id, mandate_jws)
        if m.agent_id != agent_id:
            raise GateError("AGENT_MISMATCH", f"Mandate authorises agent {m.agent_id}, not {agent_id}.", 403)
        decision = evaluate(quote, m, self.catalog, week_spend_eur=self._week_spend(buyer_id),
                            reference_prices=self.buyer(buyer_id)["profile"].get("reference_prices"),
                            related_recent_eur=self._related_recent_spend(
                                buyer_id, {ln["product_id"] for ln in quote["lines"]}))
        oid, now = _id("ord"), _now().isoformat(timespec="seconds")
        status = {AUTO: "CONFIRMED", APPROVAL: "PENDING_APPROVAL", BLOCKED: "REJECTED"}[decision.outcome]
        with self.lock:
            self.con.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                             (oid, buyer_id, quote_id, status, now, now, quote["total_price"], idempotency_key,
                              agent_id, rationale, json.dumps(decision.to_dict()), None))
            self.con.commit()
        self.audit.append(buyer_id=buyer_id, actor=agent_id, event="order.requested", ref=oid,
                          summary=f"Agent requested an order from quote {quote_id} "
                                  f"(€{quote['total_price']:,.2f}). Rationale: {rationale or '—'}",
                          data={"order_id": oid, "quote_id": quote_id, "rationale": rationale})
        verdict = {AUTO: "within the mandate — confirmed automatically",
                   APPROVAL: "needs human approval", BLOCKED: "blocked"}[decision.outcome]
        self.audit.append(buyer_id=buyer_id, actor=GATE_ID, event="policy.decision", ref=oid,
                          summary=f"Guardrails: order {oid} {verdict}."
                                  + (" " + " ".join(decision.reasons) if decision.reasons else ""),
                          data=decision.to_dict())
        if status == "PENDING_APPROVAL":
            aid = _id("apr")
            with self.lock:
                self.con.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?,?)",
                                 (aid, oid, buyer_id, "PENDING", now, None, None, None,
                                  json.dumps(decision.reasons)))
                self.con.commit()
            self.audit.append(buyer_id=buyer_id, actor=GATE_ID, event="approval.requested", ref=oid,
                              summary=f"Approval {aid} sent to {', '.join(m.approvers) or 'buyer approver'}.",
                              data={"approval_id": aid, "order_id": oid, "reasons": decision.reasons})
        elif status == "CONFIRMED":
            self._confirm(oid, quote, by="policy:auto")
        return self.get_order(oid)

    def _confirm(self, oid: str, quote: dict, by: str) -> None:
        now = _now()
        conf = self.key.sign({"iss": GATE_ID, "sub": quote["buyer_id"], "jti": oid, "iat": int(now.timestamp()),
                              "order": {"order_id": oid, "quote_id": quote["quote_id"], "status": "CONFIRMED",
                                        "total_price": quote["total_price"], "deliver_by": quote["deliver_by"],
                                        "lines": [{k: ln[k] for k in ("product_id", "units", "unit_price",
                                                                      "earliest_delivery")} for ln in quote["lines"]],
                                        "approved_by": by}}, typ="order+jwt")
        with self.lock:
            self.con.execute("UPDATE orders SET status='CONFIRMED', updated=?, confirmation_jws=? WHERE id=?",
                             (now.isoformat(timespec="seconds"), conf, oid))
            self.con.commit()
        self.audit.append(buyer_id=quote["buyer_id"], actor=GATE_ID, event="order.confirmed", ref=oid,
                          summary=f"Order {oid} confirmed ({by}). €{quote['total_price']:,.2f} excl. VAT, "
                                  f"delivery {max(ln['earliest_delivery'] or '' for ln in quote['lines'])}.",
                          data={"order_id": oid, "approved_by": by})

    def get_order(self, oid: str) -> dict:
        r = self.con.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not r:
            raise GateError("UNKNOWN_ORDER", f"No order {oid}.", 404)
        d = dict(r)
        d["decision"] = json.loads(d["decision"]) if d["decision"] else None
        d["quote"] = self.get_quote(d["quote_id"])["quote"]
        a = self.con.execute("SELECT * FROM approvals WHERE order_id=? ORDER BY created DESC", (oid,)).fetchone()
        d["approval"] = dict(a) | {"reasons": json.loads(a["reasons"])} if a else None
        return d

    def orders(self, buyer_id: str | None = None, limit: int = 50) -> list[dict]:
        sql, args = "SELECT id FROM orders", []
        if buyer_id:
            sql, args = sql + " WHERE buyer_id=?", [buyer_id]
        return [self.get_order(r["id"]) for r in self.con.execute(sql + " ORDER BY created DESC LIMIT ?",
                                                                    (*args, limit))]

    # =================================================================== approvals
    def approvals(self, buyer_id: str | None = None, status: str | None = "PENDING") -> list[dict]:
        sql, args = "SELECT * FROM approvals WHERE 1=1", []
        if buyer_id:
            sql, args = sql + " AND buyer_id=?", args + [buyer_id]
        if status:
            sql, args = sql + " AND status=?", args + [status]
        out = []
        for a in self.con.execute(sql + " ORDER BY created DESC", args):
            d = dict(a) | {"reasons": json.loads(a["reasons"])}
            d["order"] = self.get_order(a["order_id"])
            out.append(d)
        return out

    def decide(self, approval_id: str, approver: str, approve: bool, note: str = "") -> dict:
        a = self.con.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
        if not a:
            raise GateError("UNKNOWN_APPROVAL", f"No approval {approval_id}.", 404)
        if a["status"] != "PENDING":
            raise GateError("ALREADY_DECIDED", f"Approval already {a['status'].lower()}.", 409)
        order = self.get_order(a["order_id"])
        now = _now().isoformat(timespec="seconds")
        if approve:
            self.verify_quote(self.get_quote(order["quote_id"])["signature"])  # price still held?
        with self.lock:
            self.con.execute("UPDATE approvals SET status=?, decided=?, approver=?, note=? WHERE id=?",
                             ("APPROVED" if approve else "REJECTED", now, approver, note, approval_id))
            if not approve:
                self.con.execute("UPDATE orders SET status='REJECTED', updated=? WHERE id=?", (now, order["id"]))
            self.con.commit()
        self.audit.append(buyer_id=a["buyer_id"], actor=f"human:{approver}",
                          event="approval.approved" if approve else "approval.rejected", ref=order["id"],
                          summary=f"{approver} {'approved' if approve else 'rejected'} order {order['id']}"
                                  + (f": “{note}”" if note else "."),
                          data={"approval_id": approval_id, "note": note})
        if approve:
            self._confirm(order["id"], order["quote"], by=f"human:{approver}")
        return self.get_order(order["id"])

    # =================================================================== discovery doc
    def manifest(self, base_url: str = "") -> dict:
        return {
            "name": "Valio Aimo Trade Gate",
            "description": "Open interface for external purchasing agents to search, quote and order from "
                           "Valio Aimo, with buyer-signed mandates, gate-enforced guardrails, signed quotes "
                           "and a verifiable audit trail.",
            "version": "0.1.0",
            "protocols": {"mcp": f"{base_url}/mcp", "openapi": f"{base_url}/openapi.json"},
            "signing": {"alg": "EdDSA", "jwks_uri": f"{base_url}/.well-known/jwks.json"},
            "mandate_format": "W3C Verifiable Credential (vc+jwt), type PurchasingMandate",
            "flow": ["get_my_mandate", "search_products", "plan_purchase / check_offers", "create_quote", "place_order",
                     "(human approval if required)", "get_order"],
            "guardrail_outcomes": [AUTO, APPROVAL, BLOCKED],
            "assumptions": [
                "Prices are fixed customer prices; no negotiation.",
                "Supplier-warehouse (Terminal) stock is unknown; 999999 is treated as unconfirmed.",
                "After a passed cut-off, earliest delivery is estimated from the product's lead time "
                "and marked unconfirmed.",
                "No deliveries on Sundays.",
                "Products without allergen declarations are never treated as allergen-safe.",
            ],
        }
