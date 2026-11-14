"""Guardrail and trust tests. Offline: a fake Valio client mirrors the mock API's real behaviour
(Stock vs Terminal, 999999 placeholders, cut-offs, partial stock) so results are reproducible."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from trade_gate.engine.offers import TZ, build_offer
from trade_gate.engine.planner import Need, plan
from trade_gate.service import GateError, TradeGate
from trade_gate.seed import seed

MON = date(2026, 11, 16)
NOW = datetime(2026, 11, 14, 10, 0, tzinfo=TZ)


class FakeValio:
    """Deterministic stand-in for Valio's /price and /availability."""

    def __init__(self):
        self.calls = []
        self.stock = {"462775": ("Stock", 51), "464306": ("Stock", 5000), "463335": ("Stock", 5000),
                      "463038": ("Terminal", 999_999)}

    def prices(self, ids, d):
        self.calls.append(("price", len(ids)))
        out = {}
        for pid in ids:
            base = {"464306": 1.01, "463335": 1.40, "462775": 1.20, "463038": 31.31}.get(pid, 4.0)
            comp = {"463038": 1.57}.get(pid, base)
            out[pid] = {"productId": pid, "quantity": 1.0, "error": False, "netPriceFound": False,
                        "catalogPrice": {"value": base, "valueWithTax": round(base * 1.135, 2), "currency": "EUR",
                                         "validFrom": "2026-09-01", "validTo": "9999-12-31"},
                        "comparisonPrice": {"value": comp, "valueWithTax": comp}, "comparisonUnit": "L",
                        "tax": {"taxRate": 13.5, "taxValue": 0}}
        return out

    def availability(self, ids, d):
        self.calls.append(("availability", len(ids)))
        out = {}
        for pid in ids:
            model, amount = self.stock.get(pid, ("Stock", 500))
            cut = "2026-11-12T15:00:00+0200" if model == "Terminal" else "2026-11-15T17:00:00+0200"
            out[pid] = {"productId": pid, "logisticModel": model, "salesBlock": False, "closingTime": cut,
                        "scheduleLines": [{"salesBlock": False, "availableAmount": amount,
                                           "availableDate": "2026-11-16", "salesUnit": "ST"}]}
        return out


class FrozenClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    """The gate, the planner and signature checks all read NOW, so FakeValio's fixed cut-offs hold on any day."""
    import jwt.api_jwt

    from trade_gate import service
    from trade_gate.engine import offers, planner
    from trade_gate.shop import assistant
    from trade_gate.trust import audit, mandate

    for module in (service, offers, planner, assistant, audit, jwt.api_jwt):
        monkeypatch.setattr(module, "datetime", FrozenClock)
    monkeypatch.setattr(mandate, "time", SimpleNamespace(time=NOW.timestamp))


@pytest.fixture()
def gate(tmp_path, catalog):
    g = TradeGate(FakeValio(), catalog, state_dir=tmp_path)
    tokens = seed(g)
    g.tokens = tokens
    return g


def order(g, buyer, agent, lines, rationale="test"):
    q = g.create_quote(buyer, agent, lines, MON)
    return g.place_order(buyer, agent, q["quote"]["quote_id"], g.tokens[buyer], str(uuid.uuid4()), rationale)


H, HA = "espoo-childrens-hospital", "hospital-kitchen-agent"
B, BA = "hotel-aurora", "aurora-procure-bot"


# ------------------------------------------------------------------ offers / planner
def test_terminal_cutoff_passed_is_flagged_and_late(catalog):
    p = catalog.get("463038")
    fv = FakeValio()
    o = build_offer(p, fv.prices(["463038"], MON)["463038"], fv.availability(["463038"], MON)["463038"],
                    need_qty=1000, need_dim="l", deliver_by=MON, now=NOW)
    codes = {i.code for i in o.issues}
    assert {"STOCK_UNCONFIRMED", "CUTOFF_PASSED", "LATE"} <= codes
    assert o.content_per_sales_unit == 20 and o.content_source == "catalog_verified"
    assert o.units_to_order == 50 and not o.meets_deadline


def test_plan_uses_two_batched_calls_and_explains_rejections(catalog):
    fv = FakeValio()
    res = plan(Need(query="lactose-free milk", quantity=1000, unit="l", deliver_by=MON, diets=["lactose_free"]),
               catalog, fv, now=NOW)
    assert fv.calls == [("price", fv.calls[0][1]), ("availability", fv.calls[1][1])]
    assert res.options and res.options[0].tier == "good"
    assert all(o.meets_deadline for o in res.options)
    rejected = {r["product_id"]: r["reasons"] for r in res.rejected}
    assert any("51" in " ".join(r) for r in rejected.values())  # partial stock explained


def test_any_amount_from_999999_up_means_unknown_stock(catalog):
    """Valio (Discord, 14 Nov): availableAmount >= 999999 = stock unknown, even on Stock products."""
    p = catalog.get("464306")
    for amount in (999_999, 666_666_666, 9_999_999_999):
        avail = {"logisticModel": "Stock", "salesBlock": False, "closingTime": "2026-11-15T17:00:00+0200",
                 "scheduleLines": [{"availableAmount": amount, "availableDate": "2026-11-16"}]}
        o = build_offer(p, FakeValio().prices([p.id], MON)[p.id], avail, need_qty=10, need_dim="unit",
                        deliver_by=MON, now=NOW)
        assert o.stock_status == "unconfirmed" and any(i.code == "STOCK_UNCONFIRMED" for i in o.issues)


# ------------------------------------------------------------------ guardrails
def test_small_order_is_autonomous(gate):
    assert order(gate, B, BA, [{"product_id": "463335", "units": 100}])["status"] == "CONFIRMED"


def test_over_limit_needs_approval_then_human_confirms(gate):
    o = order(gate, B, BA, [{"product_id": "464306", "units": 2000}])
    assert o["status"] == "PENDING_APPROVAL"
    o = gate.decide(o["approval"]["id"], "Laura", True, "ok")
    assert o["status"] == "CONFIRMED" and o["confirmation_jws"]


def test_split_order_is_detected(gate):
    assert order(gate, B, BA, [{"product_id": "464306", "units": 1000}])["status"] == "CONFIRMED"
    o = order(gate, B, BA, [{"product_id": "464306", "units": 1000}])
    assert o["status"] == "PENDING_APPROVAL"
    assert any(f["rule"] == "spend.split_order" for f in o["decision"]["findings"])


def test_unconfirmed_supplier_stock_needs_approval(gate):
    o = order(gate, B, BA, [{"product_id": "463038", "units": 10}])
    rules = {f["rule"] for f in o["decision"]["findings"] if f["outcome"] == "APPROVAL"}
    assert {"delivery.unconfirmed_stock", "delivery.estimated_date", "delivery.late"} <= rules


def test_allergen_conflict_is_blocked_even_with_approval(gate, catalog):
    pid = catalog.search("Kinder Bueno", limit=1)[0].id
    o = order(gate, H, HA, [{"product_id": pid, "units": 1}])
    assert o["status"] == "REJECTED" and o["decision"]["outcome"] == "BLOCKED"
    assert gate.approvals(H) == []


def test_missing_allergen_data_goes_to_human(gate, catalog):
    p = next(x for x in catalog.search("cracker", limit=200) if not x.has_allergen_data)
    o = order(gate, H, HA, [{"product_id": p.id, "units": 1}])
    assert o["status"] == "PENDING_APPROVAL"
    assert any(f["rule"] == "allergen.unverified" for f in o["decision"]["findings"])


def test_partial_stock_quote_is_refused(gate):
    with pytest.raises(GateError) as e:
        gate.create_quote(B, BA, [{"product_id": "462775", "units": 200}], MON)
    assert e.value.code == "QUOTE_REFUSED"


# ------------------------------------------------------------------ trust
def test_forged_or_foreign_mandate_rejected(gate):
    q = gate.create_quote(H, HA, [{"product_id": "463335", "units": 1}], MON)
    with pytest.raises(GateError) as e:
        gate.place_order(H, HA, q["quote"]["quote_id"], gate.tokens[B], str(uuid.uuid4()))
    assert e.value.code == "MANDATE_INVALID"


def test_tampered_quote_signature_rejected(gate):
    q = gate.create_quote(B, BA, [{"product_id": "463335", "units": 1}], MON)
    head, body, sig = q["signature"].split(".")
    with pytest.raises(GateError) as e:
        gate.verify_quote(f"{head}.{body}.{sig[:-4]}AAAA")
    assert e.value.code == "QUOTE_INVALID"


def test_idempotent_retry(gate):
    q = gate.create_quote(B, BA, [{"product_id": "463335", "units": 1}], MON)
    key = str(uuid.uuid4())
    a = gate.place_order(B, BA, q["quote"]["quote_id"], gate.tokens[B], key)
    b = gate.place_order(B, BA, q["quote"]["quote_id"], gate.tokens[B], key)
    assert a["id"] == b["id"]


def test_audit_chain_detects_tampering(gate):
    order(gate, B, BA, [{"product_id": "463335", "units": 1}])
    assert gate.audit.verify_chain()["valid"]
    gate.con.execute("UPDATE audit SET summary='edited' WHERE seq=1")
    assert not gate.audit.verify_chain()["valid"]


# ------------------------------------------------------------------ webshop assistant (no LLM)
def test_webshop_cart_over_limit_goes_to_approver_and_session_updates(gate):
    from trade_gate.shop.assistant import Shop

    shop = Shop(gate)
    s = shop.create(B)
    lines = shop._price_lines(B, [{"key": "milk", "need": "Lactose-free milk", "quantity": 2000, "unit": "l",
                                   "options": [{"product_id": "464306", "why": "cheapest"}]}], MON)
    s.cart = shop._cart_from("Conference", MON, lines, [])
    o = shop._place(s)
    assert o["status"] == "PENDING_APPROVAL" and o["approver"].startswith("Laura")
    s.order = o
    gate.decide(gate.get_order(o["order_id"])["approval"]["id"], "Laura Mäkinen (F&B Manager)", True, "ok")
    shop.refresh_order(s)
    assert s.order["status"] == "CONFIRMED" and s.order["signed"]
    assert "approved" in s.messages[-1]["text"]


def test_customer_confirmation_covers_shown_warnings_but_not_allergens(gate):
    from trade_gate.shop.assistant import Shop

    shop = Shop(gate)
    s = shop.create(B)
    # Terminal product: unknown stock + passed cut-off -> would need approval for an autonomous agent
    s.cart = shop._cart_from("Cream", MON, shop._price_lines(
        B, [{"key": "c", "need": "cream", "quantity": 2, "unit": "unit",
             "options": [{"product_id": "463038", "why": "x"}]}], MON), [])
    o = shop._place(s)
    assert o["status"] == "CONFIRMED" and o["accepted"]


def test_settings_change_resigns_mandate_and_no_change_does_not(gate):
    before = len(gate.audit.entries(B, None, 0))
    gate.update_settings(B, {"approval_limit_eur": 1500}, by="Jari")  # unchanged
    assert len(gate.audit.entries(B, None, 0)) == before
    gate.update_settings(B, {"approval_limit_eur": 500}, by="Jari")
    from trade_gate.seed import load_mandate
    m = gate.verify_mandate(B, load_mandate(B, gate.state_dir))
    assert m.limits.auto_approve_max_order_eur == 500


def test_ingredient_list_must_be_approved_and_edits_are_recorded(gate, monkeypatch):
    """Broad requests pause on an editable ingredient list; the customer's edits are authoritative and logged."""
    from trade_gate.shop.assistant import Shop

    shop = Shop(gate)
    s = shop.create(B)
    shop._propose(s, {"title": "Soup for 20", "deliver_by": MON.isoformat(),
                      "dishes": [{"name": "Soup", "portions": 20, "source": "estimate"}],
                      "items": [{"key": "a", "name": "cream", "quantity": 2, "unit": "l", "dish": "Soup"},
                                {"key": "b", "name": "dill", "quantity": 0.1, "unit": "kg", "dish": "Soup"}]})
    s.pending = {"kind": "plan", "tool_use_id": "t1", "other_results": []}
    assert s.plan["status"] == "proposed" and s.plan["dishes"][0]["source"] == "estimate" and s.cart is None
    monkeypatch.setattr(shop, "_start", lambda sess, coro: coro.close())  # no LLM in tests
    shop.approve_plan(s.id, [{"key": "a", "name": "cream", "quantity": 3, "unit": "l"},
                             {"key": None, "name": "salmon", "quantity": 2.5, "unit": "kg"}], save_recipes=["Soup"])
    assert s.plan["status"] == "approved"
    assert s.plan["changes"] == ["cream: 2 l → 3 l", "added salmon 2.5 kg", "removed dill"]
    sent = json.loads(s.llm[-1]["content"][-1]["content"])
    assert [i["quantity"] for i in sent["items"]] == [3, 2.5]
    events = [e["event"] for e in gate.audit.entries(B, None, 0)]
    assert "plan.approved" in events and "recipe.saved" in events
    assert any(r["name"] == "Soup" for r in gate.buyer(B)["profile"]["recipes"])
