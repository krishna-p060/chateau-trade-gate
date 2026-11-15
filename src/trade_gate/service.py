"""Trade Gate service: the single core behind the REST API and the MCP server.

Flow: search -> plan (good/better/best) -> create_quote (live re-check, signed, fixed price for a
validity window) -> place_order (quote + buyer mandate verified, guardrails evaluated server-side)
-> AUTO confirm | human approval | block. Everything is written to the hash-chained audit log.
"""
from __future__ import annotations

import json
import math
import secrets
import sqlite3
import threading
from datetime import date, datetime, timedelta

import jwt

from trade_gate.catalog.codes import ALLERGENS, LABELS, allergen_name, resolve_allergen
from trade_gate.catalog.store import Catalog
from trade_gate.config import STATE_DIR
from trade_gate.engine.offers import TZ, _parse_dt, build_offer
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


def _is_approver(person: str, approvers: list[str]) -> bool:
    """True when person is one of the mandate's approvers, given as 'Name (Role)', the full name or the first name."""
    who = person.strip().casefold()
    for a in approvers:
        name = a.split("(")[0].strip().casefold()
        if who and who in (a.strip().casefold(), name, name.split(" ")[0]):
            return True
    return False


def _content(p, o=None) -> tuple[float | None, str | None]:
    """Pack content. Valio's unit price verifies the catalog figure; within 5% keep the round catalog
    number (3 kg, not 2.996 kg), otherwise trust Valio's figure."""
    cat, dim = p.content_per_sales_unit, p.content_dim
    ver = o.content_per_sales_unit if o is not None else None
    if ver and (not cat or abs(ver - cat) / cat > 0.05):
        return round(ver, 2), (o.content_dim or dim)
    return cat, dim


def _pack(p, o=None) -> str:
    content, dim = _content(p, o)
    if content and dim:
        return f"{content:g} {dim}"
    return p.sales_unit.lower()


_STOCK_TEXT = {"confirmed": "in stock", "partial": "partly in stock", "unconfirmed": "orderable, stock not tracked",
               "none": "not available", "unknown": "unknown"}


def _claim(code: str) -> str:
    c = code.upper()
    if c.startswith("FREE_FROM_"):
        return c[10:].lower().replace("_", " ") + "-free"
    return c.lower().replace("_", " ")


def _candidate(p, o, usual: dict | None, valio_sub: bool, deliver_by: date | None = None) -> dict:
    """Compact, decision-ready view of one product for the AI and the cart."""
    content, dim = _content(p, o)
    per = (f"€{o.price_per_content_unit:.2f}/{o.content_dim}" if o.price_per_content_unit and o.content_dim
           else f"€{o.unit_price / content:.2f}/{dim}" if o.unit_price and content and dim else None)
    co2 = o.co2_kg
    if co2 is None and p.co2_kg_per_kg and content and o.units_to_order and dim in ("kg", "l"):
        co2 = round(p.co2_kg_per_kg * content * o.units_to_order, 1)
    planned = (deliver_by.isoformat() if deliver_by and o.meets_deadline else o.earliest_delivery)
    return {
        "product_id": p.id, "name": p.name, "name_fi": p.name_fi or p.name, "brand": p.brand, "pack": _pack(p, o),
        "units": o.units_to_order, "sales_unit": p.sales_unit, "unit_price": o.unit_price,
        "total": o.total_price, "total_with_tax": o.total_price_with_tax,
        "order_by": None if o.cutoff_passed or not _parse_dt(o.closing_time)
                    else _parse_dt(o.closing_time).isoformat(timespec="minutes"), "price_per": per, "delivered_qty": o.delivered_qty,
        "delivery": {"date": planned, "earliest": o.earliest_delivery, "on_time": o.meets_deadline,
                     "confirmed": o.earliest_delivery_confirmed},
        "stock": _STOCK_TEXT.get(o.stock_status, o.stock_status)
                 + (f" ({o.available_amount:g})" if o.stock_status in ("confirmed", "partial") else ""),
        "co2_kg": co2, "labels": [LABELS.get(lb, lb) for lb in p.sustainability_labels],
        "diet": [_claim(c) for c in p.claims][:4], "allergens": [allergen_name(a) for a in p.allergens_contains],
        "may_contain": [allergen_name(a) for a in p.allergens_may_contain],
        "allergen_data": p.has_allergen_data, "country": p.country,
        "usual": bool(usual), "times_bought": usual["times_bought"] if usual else 0,
        "valio_substitute": valio_sub,
        "stock_tracked": o.stock_status in ("confirmed", "partial"),
        "notes": [i.message for i in o.issues
                  if i.severity in ("warning", "blocking") and i.code != "STOCK_UNCONFIRMED"][:3],
        "note_codes": [i.code for i in o.issues
                       if i.severity in ("warning", "blocking") and i.code != "STOCK_UNCONFIRMED"][:3],
    }


class TradeGate:
    def __init__(self, valio, catalog: Catalog | None = None, state_dir=STATE_DIR):
        state_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir = state_dir
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
            CREATE TABLE IF NOT EXISTS purchases (buyer_id TEXT, day TEXT, product_id TEXT, units REAL,
                source TEXT);
            CREATE INDEX IF NOT EXISTS purchases_buyer ON purchases(buyer_id, product_id);
        """)
        cols = {r[1] for r in self.con.execute("PRAGMA table_info(buyers)")}
        if "mandate" not in cols:
            self.con.execute("ALTER TABLE buyers ADD COLUMN mandate TEXT")
            self.con.commit()
        if "unit_price" not in {r[1] for r in self.con.execute("PRAGMA table_info(purchases)")}:
            self.con.execute("ALTER TABLE purchases ADD COLUMN unit_price REAL")
            self.con.commit()
        self.key = KeyPair.load_or_create(state_dir / "gate_ed25519.pem", kid=f"{GATE_ID}-2026-11")
        self.audit = AuditLog(self.con, self.lock)

    # =================================================================== buyers
    def register_buyer(self, buyer_id: str, name: str, jwk: dict, profile: dict | None = None,
                       mandate: dict | None = None) -> None:
        with self.lock:
            self.con.execute("INSERT OR REPLACE INTO buyers (id, name, jwk, profile, mandate) VALUES (?,?,?,?,?)",
                             (buyer_id, name, json.dumps(jwk), json.dumps(profile or {}),
                              json.dumps(mandate) if mandate else None))
            self.con.commit()

    @staticmethod
    def _buyer_row(r) -> dict:
        return {"id": r["id"], "name": r["name"], "jwk": json.loads(r["jwk"]), "profile": json.loads(r["profile"]),
                "mandate": json.loads(r["mandate"]) if r["mandate"] else None}

    def buyer_or_none(self, buyer_id: str) -> dict | None:
        r = self.con.execute("SELECT * FROM buyers WHERE id=?", (buyer_id,)).fetchone()
        return self._buyer_row(r) if r else None

    def buyer(self, buyer_id: str) -> dict:
        b = self.buyer_or_none(buyer_id)
        if not b:
            raise GateError("UNKNOWN_BUYER", f"Buyer {buyer_id} is not registered with the gate.", 404)
        return b

    def buyers(self) -> list[dict]:
        return [{k: v for k, v in self._buyer_row(r).items() if k != "jwk"}
                for r in self.con.execute("SELECT * FROM buyers")]

    def verify_mandate(self, buyer_id: str, mandate_jws: str) -> mandates.Mandate:
        b = self.buyer(buyer_id)
        try:
            m = mandates.verify_mandate(mandate_jws, b["jwk"])
        except (jwt.PyJWTError, ValueError, KeyError) as e:
            raise GateError("MANDATE_INVALID", f"Purchasing mandate failed verification: {e}", 403) from e
        if m.buyer_id != buyer_id:
            raise GateError("MANDATE_MISMATCH", "Mandate was issued for a different buyer.", 403)
        current = b["mandate"]
        if current and m.to_credential_subject() != mandates.Mandate.from_credential_subject(
                current).to_credential_subject():
            raise GateError("MANDATE_SUPERSEDED", f"{b['name']} has changed its purchasing rules since this "
                            "mandate was signed. Fetch the current mandate; the earlier one no longer "
                            "authorises orders.", 403)
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
        try:
            lines = self._merged_lines(lines)
        except GateError as e:
            self.audit.append(buyer_id=buyer_id, actor=GATE_ID, event="quote.refused",
                              summary=f"Refused to quote for {agent_id}: {e.message}",
                              data={"lines": lines, "code": e.code})
            raise
        ids = [ln["product_id"] for ln in lines]
        prods = {p.id: p for p in self.catalog.get_many(ids)}
        missing = [i for i in ids if i not in prods]
        if missing:
            raise GateError("UNKNOWN_PRODUCT", f"Unknown product codes: {', '.join(missing)}", 404)
        prices, avail = self._live(ids, deliver_by)
        now = _now()
        q_lines, problems = [], []
        for ln in lines:
            p = prods[ln["product_id"]]
            units = ln["units"]
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

    @staticmethod
    def _merged_lines(lines: list[dict]) -> list[dict]:
        """One line per product with positive, finite units, so stock and spend are judged on the real total."""
        merged: dict[str, dict] = {}
        for ln in lines:
            try:
                units = float(ln["units"])
            except (KeyError, TypeError, ValueError):
                units = math.nan
            if not math.isfinite(units) or units <= 0:
                raise GateError("BAD_QUANTITY", f"Product {ln.get('product_id')}: units must be a positive "
                                f"number, got {ln.get('units')!r}.")
            if ln["product_id"] in merged:
                merged[ln["product_id"]]["units"] += units
            else:
                merged[ln["product_id"]] = {**ln, "units": units}
        return list(merged.values())

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
    def _live(self, ids: list[str], deliver_by: date, fresh: bool = False) -> tuple[dict, dict]:
        """Valio's prices and availability for ids; fresh=True reads availability past the client's cache."""
        try:
            forget = getattr(self.valio, "forget", None)
            if fresh and forget:
                forget("/availability", ids, deliver_by)
            return self.valio.prices(ids, deliver_by), self.valio.availability(ids, deliver_by)
        except GateError:
            raise
        except Exception as e:
            raise GateError("VALIO_UNAVAILABLE", "Valio's price and availability service did not answer "
                            f"({type(e).__name__}); nothing was ordered. Try again in a moment.", 503) from e

    def _changed_since_quote(self, quote: dict) -> list[str]:
        """What no longer holds for a quote: stock checked afresh and order-by times against the clock."""
        ids = [ln["product_id"] for ln in quote["lines"]]
        deliver_by = date.fromisoformat(quote["deliver_by"])
        prods = {p.id: p for p in self.catalog.get_many(ids)}
        prices, avail = self._live(ids, deliver_by, fresh=True)
        now, changed = _now(), []
        for ln in quote["lines"]:
            p = prods.get(ln["product_id"])
            if not p:
                continue
            o = build_offer(p, prices.get(p.id), avail.get(p.id), need_qty=ln["units"], need_dim="unit",
                            deliver_by=deliver_by, now=now)
            hard = [i for i in o.issues if i.severity == "blocking" and i.code != "LATE"]
            if hard:
                changed += [f"{ln['name']}: {i.message}" for i in hard]
            elif o.stock_status == "partial":
                changed.append(f"{ln['name']}: only {o.available_amount:g} {p.sales_unit} in stock now, "
                               f"{ln['units']:g} quoted.")
            elif ln.get("earliest_delivery") and o.earliest_delivery and o.earliest_delivery > ln["earliest_delivery"]:
                changed.append(f"{ln['name']}: the order-by time has passed since the quote; earliest delivery "
                               f"is now {o.earliest_delivery}, not {ln['earliest_delivery']}.")
        return changed

    def _reference_prices(self, buyer_id: str, profile: dict) -> dict[str, float]:
        """Per product: the reference price in the profile, else the unit price of the buyer's last confirmed order."""
        ref = dict(profile.get("reference_prices") or {})
        for r in self.con.execute("SELECT product_id, unit_price FROM purchases WHERE buyer_id=? AND unit_price "
                                  "IS NOT NULL ORDER BY rowid DESC", (buyer_id,)):
            ref.setdefault(r["product_id"], r["unit_price"])
        return ref

    def _largest_orders(self, buyer_id: str) -> dict[str, float]:
        """Per product delivered on at least four past days: the largest quantity in one order line."""
        return {r[0]: r[1] for r in self.con.execute(
            "SELECT product_id, MAX(units) FROM purchases WHERE buyer_id=? AND day < ? GROUP BY product_id "
            "HAVING COUNT(DISTINCT day) >= 4", (buyer_id, _now().date().isoformat()))}

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
                    idempotency_key: str, rationale: str = "", confirmed_by: str | None = None) -> dict:
        """confirmed_by: the person who reviewed this exact cart (webshop flow). Their confirmation covers
        delivery/substitution warnings they were shown; spend and allergen rules still apply."""
        with self.lock:
            return self._place_order(buyer_id, agent_id, quote_id, mandate_jws, f"{buyer_id}:{idempotency_key}",
                                     rationale, confirmed_by)

    def _place_order(self, buyer_id: str, agent_id: str, quote_id: str, mandate_jws: str, idem_key: str,
                     rationale: str, confirmed_by: str | None) -> dict:
        existing = self.con.execute("SELECT id FROM orders WHERE idem_key=?", (idem_key,)).fetchone()
        if existing:
            return self.get_order(existing["id"])
        stored = self.get_quote(quote_id)
        quote = self.verify_quote(stored["signature"])
        if quote["buyer_id"] != buyer_id:
            raise GateError("QUOTE_MISMATCH", "Quote belongs to another buyer.", 403)
        if self.con.execute("SELECT 1 FROM orders WHERE quote_id=? AND status!='REJECTED'", (quote_id,)).fetchone():
            raise GateError("QUOTE_USED", "This quote already has an order.", 409)
        try:
            m = self.verify_mandate(buyer_id, mandate_jws)
            if m.agent_id != agent_id:
                raise GateError("AGENT_MISMATCH", f"Mandate authorises agent {m.agent_id}, not {agent_id}.", 403)
        except GateError as e:
            self.audit.append(buyer_id=buyer_id, actor=agent_id, event="order.refused", ref=quote_id,
                              summary=f"Refused an order from quote {quote_id} ({e.code}): {e.message}",
                              data={"quote_id": quote_id, "code": e.code})
            raise
        changed = self._changed_since_quote(quote)
        if changed:
            self.audit.append(buyer_id=buyer_id, actor=GATE_ID, event="order.refused", ref=quote_id,
                              summary=f"Refused an order from quote {quote_id}: no longer deliverable as quoted. "
                                      + " ".join(changed), data={"quote_id": quote_id, "changed": changed})
            raise GateError("QUOTE_STALE", "No longer deliverable as quoted: " + " ".join(changed)
                            + " Request a new quote.", 409)
        decision = evaluate(quote, m, self.catalog, week_spend_eur=self._week_spend(buyer_id),
                            confirmed_by=confirmed_by,
                            reference_prices=self._reference_prices(buyer_id, self.buyer(buyer_id)["profile"]),
                            largest_units=self._largest_orders(buyer_id),
                            related_recent_eur=self._related_recent_spend(
                                buyer_id, {ln["product_id"] for ln in quote["lines"]}))
        oid, now = _id("ord"), _now().isoformat(timespec="seconds")
        status = {AUTO: "CONFIRMED", APPROVAL: "PENDING_APPROVAL", BLOCKED: "REJECTED"}[decision.outcome]
        self.con.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (oid, buyer_id, quote_id, status, now, now, quote["total_price"], idem_key,
                          agent_id, rationale, json.dumps(decision.to_dict()), None))
        self.con.commit()
        self.audit.append(buyer_id=buyer_id, actor=agent_id, event="order.requested", ref=oid,
                          summary=(f"{confirmed_by} confirmed the cart in the webshop: order from quote {quote_id} "
                                   f"(€{quote['total_price']:,.2f})." if confirmed_by else
                                   f"Agent requested an order from quote {quote_id} "
                                   f"(€{quote['total_price']:,.2f}). Rationale: {rationale or '—'}"),
                          data={"order_id": oid, "quote_id": quote_id, "rationale": rationale,
                                "confirmed_by": confirmed_by})
        verdict = {AUTO: "within the mandate — confirmed automatically",
                   APPROVAL: "needs human approval", BLOCKED: "blocked"}[decision.outcome]
        self.audit.append(buyer_id=buyer_id, actor=GATE_ID, event="policy.decision", ref=oid,
                          summary=f"Guardrails: order {oid} {verdict}."
                                  + (" " + " ".join(decision.reasons) if decision.reasons else ""),
                          data=decision.to_dict())
        if status == "PENDING_APPROVAL":
            aid = _id("apr")
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
                                        "approved_by": by,
                                        "fulfilment": "Recorded and signed by the gate; not sent to an ERP "
                                                      "(Valio's challenge APIs have no order endpoint)."}},
                              typ="order+jwt")
        with self.lock:
            self.con.execute("UPDATE orders SET status='CONFIRMED', updated=?, confirmation_jws=? WHERE id=?",
                             (now.isoformat(timespec="seconds"), conf, oid))
            self.con.executemany(
                "INSERT INTO purchases (buyer_id, day, product_id, units, source, unit_price) VALUES (?,?,?,?,?,?)",
                [(quote["buyer_id"], quote["deliver_by"], ln["product_id"], ln["units"], oid, ln["unit_price"])
                 for ln in quote["lines"]])
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
        """A person named as approver in the buyer's mandate approves or rejects a held order. Approval
        re-checks stock, order-by times and the price hold; an order that no longer holds is closed."""
        with self.lock:
            a = self.con.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            if not a:
                raise GateError("UNKNOWN_APPROVAL", f"No approval {approval_id}.", 404)
            if a["status"] != "PENDING":
                raise GateError("ALREADY_DECIDED", f"Approval already {a['status'].lower()}.", 409)
            order = self.get_order(a["order_id"])
            b = self.buyer(a["buyer_id"])
            named = (b["mandate"] or {}).get("approvers") or []
            if not _is_approver(approver, named):
                self.audit.append(buyer_id=a["buyer_id"], actor=f"unverified:{approver}", event="approval.refused",
                                  ref=order["id"],
                                  summary=f"Refused a decision on order {order['id']} by “{approver}”: not an "
                                          f"approver in {b['name']}'s mandate ({', '.join(named) or 'none named'}).",
                                  data={"approval_id": approval_id, "attempted_by": approver, "approve": approve})
                raise GateError("APPROVER_NOT_AUTHORISED", f"“{approver}” is not an approver in {b['name']}'s "
                                f"mandate. Named approvers: {', '.join(named) or 'none'}.", 403)
            now = _now().isoformat(timespec="seconds")
            lapsed = self._lapsed(order) if approve else []
            if lapsed:
                why = "No longer deliverable as approved: " + " ".join(lapsed)
                self.con.execute("UPDATE approvals SET status='REJECTED', decided=?, approver=?, note=? WHERE id=?",
                                 (now, "Trade Gate", why, approval_id))
                self.con.execute("UPDATE orders SET status='REJECTED', updated=? WHERE id=?", (now, order["id"]))
                self.con.commit()
                self.audit.append(buyer_id=a["buyer_id"], actor=GATE_ID, event="order.lapsed", ref=order["id"],
                                  summary=f"{approver} approved order {order['id']}, but it was closed unconfirmed. "
                                          f"{why}", data={"approval_id": approval_id, "changed": lapsed})
                raise GateError("ORDER_LAPSED", why + " The order was closed; request a new quote.", 409)
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

    def _lapsed(self, order: dict) -> list[str]:
        try:
            self.verify_quote(self.get_quote(order["quote_id"])["signature"])
        except GateError as e:
            if e.code != "QUOTE_EXPIRED":
                raise
            return [f"the price hold of quote {order['quote_id']} ended at "
                    f"{order['quote']['expires_at'][11:16]}."]
        return self._changed_since_quote(order["quote"])

    # =================================================================== customer data (webshop)
    def ensure_history(self, buyers: list[dict], weeks: int = 8) -> None:
        """Synthetic purchase history: standing orders on their weekdays plus recipe-driven event orders."""
        import random
        days = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3, "Friday": 4, "Saturday": 5}
        today = _now().date()
        for b in buyers:
            if self.con.execute("SELECT 1 FROM purchases WHERE buyer_id=? LIMIT 1", (b["id"],)).fetchone():
                continue
            rnd = random.Random(b["id"])
            rows = []
            for back in range(weeks * 7, 0, -1):
                d = today - timedelta(days=back)
                for so in b["profile"].get("standing_orders", []):
                    if d.weekday() in {days[w] for w in so["weekdays"]}:
                        for ln in so["lines"]:
                            units = max(1, round(ln["units"] * rnd.uniform(0.8, 1.2)))
                            rows.append((b["id"], d.isoformat(), ln["product_id"], units, f"standing:{so['id']}"))
                if d.weekday() == 3 and rnd.random() < 0.6:  # occasional event orders from saved recipes
                    for r in b["profile"].get("recipes", []):
                        for ing in r["ingredients"]:
                            if ing.get("product_id"):
                                rows.append((b["id"], d.isoformat(), ing["product_id"], rnd.randint(2, 8),
                                             f"event:{r['id']}"))
            with self.lock:
                self.con.executemany(
                    "INSERT INTO purchases (buyer_id, day, product_id, units, source) VALUES (?,?,?,?,?)", rows)
                self.con.commit()

    def usual_products(self, buyer_id: str, limit: int = 40) -> list[dict]:
        rows = self.con.execute(
            "SELECT product_id, COUNT(DISTINCT day) AS times, MAX(day) AS last, AVG(units) AS avg_units "
            "FROM purchases WHERE buyer_id=? GROUP BY product_id ORDER BY times DESC LIMIT ?",
            (buyer_id, limit)).fetchall()
        out = []
        for r in rows:
            p = self.catalog.get(r["product_id"])
            if p:
                out.append({"product_id": p.id, "name": p.name, "name_fi": p.name_fi or p.name, "brand": p.brand,
                            "pack": _pack(p),
                            "times_bought": r["times"], "last_bought": r["last"],
                            "typical_units": round(r["avg_units"], 1), "sales_unit": p.sales_unit})
        return out

    def customer_context(self, buyer_id: str) -> dict:
        b = self.buyer(buyer_id)
        prof = b["profile"]
        names = {p.id: p.name for p in self.catalog.get_many(
            [ln["product_id"] for so in prof.get("standing_orders", []) for ln in so["lines"]]
            + [i["product_id"] for r in prof.get("recipes", []) for i in r["ingredients"] if i.get("product_id")])}
        m = b["mandate"] or {}
        return {
            "customer": {"id": b["id"], "name": b["name"], "segment": prof.get("segment"),
                         "contact": prof.get("contact"), "delivery_address": prof.get("delivery_address"),
                         "delivery_days": prof.get("delivery_days", [])},
            "priorities": prof.get("priorities", []),
            "rules": {"avoid_allergens": (m.get("dietary") or {}).get("avoid_allergens", []),
                      "require_allergen_data": (m.get("dietary") or {}).get("require_allergen_data", False),
                      "orders_up_to_eur_confirmed_by_contact": (m.get("limits") or {}).get("auto_approve_max_order_eur"),
                      "above_that_approved_by": m.get("approvers", [])},
            "settings": prof.get("settings", {}),
            "usual_products": self.usual_products(buyer_id, 30),
            "saved_recipes": [{**r, "ingredients": [{**i, **({"product_name": names.get(i["product_id"])}
                                                            if i.get("product_id") else {})}
                                                    for i in r["ingredients"]]}
                              for r in prof.get("recipes", [])],
            "standing_orders": [{**so, "lines": [{**ln, "name": names.get(ln["product_id"])} for ln in so["lines"]]}
                                for so in prof.get("standing_orders", [])],
            "catalog_size": self.catalog_size(),
        }

    def catalog_size(self) -> int:
        if not hasattr(self, "_catalog_size"):
            self._catalog_size = self.catalog.con.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        return self._catalog_size

    def shortlist(self, buyer_id: str, agent_id: str, items: list[dict], deliver_by: date,
                  per_item: int = 7) -> dict:
        """Narrow 17k products to a short, priced, deliverable list per ingredient (deterministic), so the
        AI only chooses among plausible products. One batched price + one availability call for all items."""
        b = self.buyer(buyer_id)
        dietary = (b["mandate"] or {}).get("dietary") or {}
        usual = {u["product_id"]: u for u in self.usual_products(buyer_id, 200)}
        plans = []
        for it in items:
            q = (it.get("query") or it.get("name") or "").strip()
            unit = (it.get("unit") or "unit").lower()
            dim = unit if unit in ("l", "kg") else None
            avoid = list(dict.fromkeys((it.get("avoid_allergens") or []) + dietary.get("avoid_allergens", [])))
            kw = dict(diets=it.get("diets") or [], avoid_allergens=avoid,
                      require_allergen_data=bool(it.get("require_allergen_data") or dietary.get("require_allergen_data")),
                      content_dim=dim)
            found = self.catalog.search(q, limit=80, **kw)
            words = q.split()
            while len(found) < 4 and len(words) > 1:  # relax: drop the least important (last) word
                words = words[:-1]
                found = self.catalog.search(" ".join(words), limit=80, **kw)
            ids = [p.id for p in found]
            replaced = it.get("replaces")
            extra: list[str] = []
            if replaced:
                rp = self.catalog.get(replaced)
                extra = [s for s in (rp.substitutes if rp else []) if s != replaced]
            if it.get("product_ids"):
                extra = list(it["product_ids"]) + extra
            usual_hits = [i for i in ids if i in usual]
            pool = list(dict.fromkeys(extra + usual_hits + ids[:16]))
            pool = [i for i in pool if i != replaced]
            plans.append({"item": it, "query": q, "unit": unit, "matched": len(found), "pool": pool,
                          "valio_subs": set(extra)})
        all_ids = list(dict.fromkeys(i for pl in plans for i in pl["pool"]))
        prods = {p.id: p for p in self.catalog.get_many(all_ids)}
        prices = self.valio.prices(all_ids, deliver_by) if all_ids else {}
        avail = self.valio.availability(all_ids, deliver_by) if all_ids else {}
        out_items = []
        for pl in plans:
            it, cands, excluded = pl["item"], [], {}
            qty = float(it.get("quantity") or 1)
            for pid in pl["pool"]:
                p = prods.get(pid)
                if not p:
                    continue
                o = build_offer(p, prices.get(pid), avail.get(pid), need_qty=qty, need_dim=pl["unit"],
                                deliver_by=deliver_by)
                hard = [i for i in o.issues if i.severity == "blocking" and i.code != "LATE"]
                if hard or not o.feasible and o.unit_price is None:
                    excluded[hard[0].code if hard else "NO_PRICE"] = excluded.get(hard[0].code if hard else "NO_PRICE", 0) + 1
                    continue
                cands.append(_candidate(p, o, usual.get(pid), pid in pl["valio_subs"], deliver_by))
            cands.sort(key=lambda c: (not c["delivery"]["on_time"], not c["usual"] and not c["valio_substitute"]))
            if not any(c["delivery"]["on_time"] for c in cands):
                self.signal(buyer_id, "unmet",
                            f"{b['name']} needed “{pl['query']}” ({qty:g} {pl['unit']}) by {deliver_by:%a %d %b}: "
                            + ("nothing deliverable in time." if cands else "no matching product available."),
                            {"need": pl["query"], "quantity": qty, "unit": pl["unit"],
                             "deliver_by": deliver_by.isoformat(), "excluded": excluded,
                             "late_alternatives": [c["product_id"] for c in cands[:3]]})
            out_items.append({"key": it.get("key") or pl["query"], "need": pl["query"], "quantity": qty,
                              "unit": pl["unit"], "matched_in_catalog": pl["matched"],
                              "checked_live": len(pl["pool"]), "excluded": excluded,
                              "candidates": cands[:per_item]})
        summary = {"catalog_size": self.catalog_size(), "matched": sum(p["matched"] for p in plans),
                   "checked_live": len(all_ids), "shortlisted": sum(len(i["candidates"]) for i in out_items)}
        self.audit.append(buyer_id=buyer_id, actor=agent_id, event="catalog.shortlist",
                          summary=f"Shortlisted products for {len(items)} ingredient(s): searched "
                                  f"{summary['catalog_size']:,} products → {summary['matched']} matches → "
                                  f"{summary['checked_live']} checked for live price and stock → "
                                  f"{summary['shortlisted']} candidates.",
                          data={"items": [i.get("query") or i.get("name") for i in items], **summary})
        return {"deliver_by": deliver_by.isoformat(), "summary": summary, "items": out_items}

    def update_settings(self, buyer_id: str, changes: dict, by: str) -> dict:
        """The customer edits preferences and rules; the mandate is re-signed and the change is logged."""
        from trade_gate.seed import sign_mandate

        b = self.buyer(buyer_id)
        prof, m = b["profile"], mandates.Mandate.from_credential_subject(b["mandate"])
        self._check_settings(changes, m)
        what = []
        if "priorities" in changes and [p for p in changes["priorities"] if p.strip()] != prof.get("priorities"):
            prof["priorities"] = [p for p in changes["priorities"] if p.strip()]
            what.append("priorities")
        if changes.get("auto_confirm_standing_orders") == (prof.get("settings") or {}).get("auto_confirm_standing_orders"):
            changes = {k: v for k, v in changes.items() if k != "auto_confirm_standing_orders"}
        if changes.get("avoid_allergens") == m.dietary.avoid_allergens:
            changes = {k: v for k, v in changes.items() if k != "avoid_allergens"}
        if changes.get("approval_limit_eur") == m.limits.auto_approve_max_order_eur:
            changes = {k: v for k, v in changes.items() if k != "approval_limit_eur"}
        if "auto_confirm_standing_orders" in changes:
            prof.setdefault("settings", {})["auto_confirm_standing_orders"] = bool(changes["auto_confirm_standing_orders"])
            what.append("standing-order autonomy " + ("on" if changes["auto_confirm_standing_orders"] else "off"))
        if "avoid_allergens" in changes:
            m.dietary.avoid_allergens = list(changes["avoid_allergens"])
            what.append("allergens to avoid: " + (", ".join(m.dietary.avoid_allergens) or "none"))
        if "approval_limit_eur" in changes:
            m.limits.auto_approve_max_order_eur = float(changes["approval_limit_eur"])
            what.append(f"approval limit €{m.limits.auto_approve_max_order_eur:,.0f}")
        if not what:
            return b
        self.register_buyer(buyer_id, b["name"], b["jwk"], prof, m.to_credential_subject())
        sign_mandate(m, self.state_dir)
        self.audit.append(buyer_id=buyer_id, actor=f"human:{by}", event="mandate.updated",
                          summary=f"{by} updated settings ({'; '.join(what) or 'no change'}); the purchasing "
                                  f"mandate was re-signed by the customer.",
                          data={"changes": changes})
        return self.buyer(buyer_id)

    @staticmethod
    def _check_settings(changes: dict, m: mandates.Mandate) -> None:
        unknown = [a for a in changes.get("avoid_allergens") or [] if not resolve_allergen(a)]
        if unknown:
            raise GateError("UNKNOWN_ALLERGEN", f"Not saved: “{', '.join(unknown)}” is not an allergen the gate "
                            "can check products against, so it would protect nothing. Known names: "
                            + ", ".join(sorted(set(ALLERGENS.values()) - {"no declarable allergens"})) + ".")
        limit = changes.get("approval_limit_eur")
        if limit is not None and not 0 <= float(limit) <= m.limits.hard_max_order_eur:
            raise GateError("LIMIT_OUT_OF_RANGE", f"Not saved: the approval limit must be between €0 and the "
                            f"hard limit of €{m.limits.hard_max_order_eur:,.0f} per order.")

    def add_order_template(self, buyer_id: str, name: str, lines: list[dict], weekdays: list[str], by: str) -> dict:
        """Save a cart as an order template (Valio's term for a reusable / standing order)."""
        b = self.buyer(buyer_id)
        prof = b["profile"]
        tpl = {"id": _id("tpl"), "name": name.strip() or "My order template", "weekdays": weekdays,
               "lines": [{"product_id": ln["product_id"], "units": ln["units"]} for ln in lines]}
        prof.setdefault("standing_orders", []).append(tpl)
        self.register_buyer(buyer_id, b["name"], b["jwk"], prof, b["mandate"])
        self.audit.append(buyer_id=buyer_id, actor=f"human:{by}", event="template.created", ref=tpl["id"],
                          summary=f"{by} saved order template “{tpl['name']}” ({len(lines)} products"
                                  + (f", {'/'.join(w[:3] for w in weekdays)}" if weekdays else "") + ").",
                          data=tpl)
        return tpl

    def add_recipe(self, buyer_id: str, name: str, portions: int, ingredients: list[dict], by: str) -> dict:
        """Save an approved ingredient list as the customer's recipe (used for scaling next time)."""
        b = self.buyer(buyer_id)
        prof = b["profile"]
        r = {"id": _id("r"), "name": name, "portions": portions, "ingredients": ingredients}
        prof["recipes"] = [x for x in prof.get("recipes", []) if x["name"].lower() != name.lower()] + [r]
        self.register_buyer(buyer_id, b["name"], b["jwk"], prof, b["mandate"])
        self.audit.append(buyer_id=buyer_id, actor=f"human:{by}", event="recipe.saved", ref=r["id"],
                          summary=f"{by} saved the recipe “{name}” ({portions} portions, "
                                  f"{len(ingredients)} ingredients).", data=r)
        return r

    def signal(self, buyer_id: str, kind: str, summary: str, data: dict) -> None:
        """Signals for Valio Aimo: substitutions accepted, alternatives preferred, demand we could not meet."""
        self.audit.append(buyer_id=buyer_id, actor=f"customer:{buyer_id}", event=f"signal.{kind}",
                          summary=summary, data=data)

    def insights(self) -> dict:
        sig = [e for e in self.audit.entries(None, None, 0) if e["event"].startswith("signal.")]
        return {"signals": sig[::-1][:100], "orders": self.orders(limit=50),
                "integrity": self.audit.verify_chain()}

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
            "flow": ["get_my_mandate / get_customer_context", "find_products (shortlist) / search_products",
                     "plan_purchase / check_offers", "create_quote", "place_order",
                     "(human approval if required)", "get_order"],
            "channels": {"webshop_assistant": "Aimo Assistant in Valio Aimo's webshop uses these same MCP tools",
                         "customer_agents": "A customer's own agent connects to /mcp with its signed mandate"},
            "guardrail_outcomes": [AUTO, APPROVAL, BLOCKED],
            "assumptions": [
                "Prices are fixed customer prices; no negotiation.",
                "availableAmount >= 999999 means stock unknown (Valio, 14 Nov): orderable, delivery not guaranteed.",
                "Empty availability means not available. allowedLotSize 0.01 is treated as 1.",
                "A 429 from Valio blocks the key for 30 s; the gate waits 31 s before retrying.",
                "No order API exists: confirmed orders are signed by the gate and recorded, not sent to an ERP.",
                "After a passed cut-off, earliest delivery is estimated from the product's lead time "
                "and marked unconfirmed.",
                "No deliveries on Sundays.",
                "Products without allergen declarations are never treated as allergen-safe.",
            ],
        }
