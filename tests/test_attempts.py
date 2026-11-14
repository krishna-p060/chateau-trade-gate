"""What an agent, an approver or a stale quote cannot get past the gate. Offline, on the fixtures of test_gate."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from test_gate import B, BA, H, HA, MON, NOW, FrozenClock, frozen_clock, gate, order
from trade_gate.service import GateError


def test_approver_must_be_named_in_the_mandate(gate):
    o = order(gate, B, BA, [{"product_id": "464306", "units": 2000}])
    for name in (BA, "Jari Nieminen", ""):
        with pytest.raises(GateError) as e:
            gate.decide(o["approval"]["id"], name, True)
        assert e.value.code == "APPROVER_NOT_AUTHORISED"
    assert gate.get_order(o["id"])["status"] == "PENDING_APPROVAL"
    assert [x["event"] for x in gate.audit.entries(B, o["id"])].count("approval.refused") == 3
    assert gate.decide(o["approval"]["id"], "Laura Mäkinen", True)["status"] == "CONFIRMED"


def test_mandate_from_before_a_rule_change_is_refused(gate):
    old = gate.tokens[B]
    gate.update_settings(B, {"approval_limit_eur": 500}, by="Jari")
    q = gate.create_quote(B, BA, [{"product_id": "464306", "units": 1000}], MON)
    with pytest.raises(GateError) as e:
        gate.place_order(B, BA, q["quote"]["quote_id"], old, str(uuid.uuid4()))
    assert e.value.code == "MANDATE_SUPERSEDED" and gate.orders(B) == []
    from trade_gate.seed import load_mandate
    o = gate.place_order(B, BA, q["quote"]["quote_id"], load_mandate(B, gate.state_dir), str(uuid.uuid4()))
    assert o["status"] == "PENDING_APPROVAL"


def test_stock_gone_after_the_quote_stops_the_order(gate):
    q = gate.create_quote(B, BA, [{"product_id": "464306", "units": 100}], MON)
    gate.valio.stock["464306"] = ("Stock", 40)
    with pytest.raises(GateError) as e:
        gate.place_order(B, BA, q["quote"]["quote_id"], gate.tokens[B], str(uuid.uuid4()))
    assert e.value.code == "QUOTE_STALE" and "only 40 ST in stock now, 100 quoted" in e.value.message
    assert gate.orders(B) == []


def test_stock_gone_before_approval_closes_the_order(gate):
    o = order(gate, B, BA, [{"product_id": "464306", "units": 2000}])
    gate.valio.stock["464306"] = ("Stock", 0)
    with pytest.raises(GateError) as e:
        gate.decide(o["approval"]["id"], "Laura Mäkinen (F&B Manager)", True)
    assert e.value.code == "ORDER_LAPSED"
    closed = gate.get_order(o["id"])
    assert closed["status"] == "REJECTED" and not closed["confirmation_jws"] and gate.approvals(B) == []


def test_expired_price_hold_closes_the_order_at_approval(gate, monkeypatch):
    from trade_gate import service
    o = order(gate, B, BA, [{"product_id": "464306", "units": 2000}])
    monkeypatch.setattr(service, "verify", lambda *a, **k: (_ for _ in ()).throw(service.jwt.ExpiredSignatureError()))
    with pytest.raises(GateError) as e:
        gate.decide(o["approval"]["id"], "Laura", True)
    assert e.value.code == "ORDER_LAPSED" and "price hold" in e.value.message
    assert gate.get_order(o["id"])["status"] == "REJECTED"


def test_negative_units_and_repeated_lines_cannot_dodge_limits(gate):
    for units in (-500, 0, float("nan"), float("inf")):
        with pytest.raises(GateError) as e:
            gate.create_quote(B, BA, [{"product_id": "464306", "units": 2000},
                                      {"product_id": "464306", "units": units}], MON)
        assert e.value.code == "BAD_QUANTITY"
    with pytest.raises(GateError) as e:
        gate.create_quote(B, BA, [{"product_id": "462775", "units": 40}, {"product_id": "462775", "units": 40}], MON)
    assert e.value.code == "QUOTE_REFUSED" and "only 51 ST in stock, 80 requested" in e.value.message


def test_price_rise_since_the_last_order_needs_approval(gate):
    from trade_gate.attacks import Shifted
    gate.valio = Shifted(gate.valio)
    assert order(gate, B, BA, [{"product_id": "463335", "units": 100}])["status"] == "CONFIRMED"
    gate.valio.price_factor["463335"] = 1.2
    o = order(gate, B, BA, [{"product_id": "463335", "units": 100}])
    assert o["status"] == "PENDING_APPROVAL"
    assert [f["rule"] for f in o["decision"]["findings"] if f["outcome"] == "APPROVAL"] == ["price.increase"]


def test_order_far_above_purchase_history_needs_approval(gate):
    top = gate._largest_orders(B)["463982"]
    assert order(gate, B, BA, [{"product_id": "463982", "units": top * 5}])["status"] == "CONFIRMED"
    o = order(gate, B, BA, [{"product_id": "463982", "units": top * 10}])
    assert o["status"] == "PENDING_APPROVAL"
    assert [f["rule"] for f in o["decision"]["findings"] if f["outcome"] == "APPROVAL"] == ["quantity.unusual"]


def test_settings_that_would_protect_nothing_or_exceed_the_hard_limit_are_not_saved(gate, catalog):
    with pytest.raises(GateError) as e:
        gate.update_settings(H, {"avoid_allergens": ["peanuts", "nutz"]}, by="Sanna")
    assert e.value.code == "UNKNOWN_ALLERGEN"
    with pytest.raises(GateError) as e:
        gate.update_settings(B, {"approval_limit_eur": 50_000}, by="Jari")
    assert e.value.code == "LIMIT_OUT_OF_RANGE"
    assert gate.buyer(H)["mandate"]["dietary"]["avoid_allergens"] == ["peanuts", "tree nuts", "sesame"]
    gate.update_settings(H, {"avoid_allergens": ["maapähkinät", "pähkinät", "seesami", "kala"]}, by="Sanna")
    assert gate.buyer(H)["mandate"]["dietary"]["avoid_allergens"] == ["maapähkinät", "pähkinät", "seesami", "kala"]
    from trade_gate.seed import load_mandate
    gate.tokens[H] = load_mandate(H, gate.state_dir)
    fish = next((p for p in catalog.search("salmon", limit=40) if "AF" in p.allergens_contains), None)
    assert fish is None or order(gate, H, HA, [{"product_id": fish.id, "units": 1}])["status"] == "REJECTED"
    assert gate.buyer(B)["mandate"]["limits"]["auto_approve_max_order_eur"] == 1500


def test_same_idempotency_key_from_two_buyers_gives_two_orders(gate):
    key = str(uuid.uuid4())
    a = gate.place_order(B, BA, gate.create_quote(B, BA, [{"product_id": "463335", "units": 1}], MON)["quote"]["quote_id"],
                         gate.tokens[B], key)
    h = gate.place_order(H, HA, gate.create_quote(H, HA, [{"product_id": "463335", "units": 1}], MON)["quote"]["quote_id"],
                         gate.tokens[H], key)
    assert a["id"] != h["id"] and h["buyer_id"] == H


def test_audit_view_keeps_the_newest_entries(gate):
    for i in range(30):
        gate.signal(B, "test", f"signal {i}", {})
    newest = gate.audit.entries(limit=5)
    assert [e["summary"] for e in newest] == [f"signal {i}" for i in range(25, 30)]


def test_confirming_the_same_cart_twice_gives_one_order(gate):
    from trade_gate.shop.assistant import Shop

    shop = Shop(gate)
    s = shop.create(B)
    s.cart = shop._cart_from("Milk", MON, shop._price_lines(
        B, [{"key": "m", "need": "milk", "quantity": 10, "unit": "unit",
             "options": [{"product_id": "463335", "why": "x"}]}], MON), [])
    first = shop._place(s)
    assert first["order_id"] == shop._place(s)["order_id"] and len(gate.orders(B)) == 1
    s.order = {**first, "status": "REJECTED"}
    assert shop._place(s)["order_id"] != first["order_id"]


def test_valio_outage_at_confirm_leaves_the_cart_usable(gate):
    import asyncio

    from trade_gate.shop.assistant import Shop

    shop = Shop(gate)
    s = shop.create(B)
    s.cart = shop._cart_from("Milk", MON, shop._price_lines(
        B, [{"key": "m", "need": "milk", "quantity": 10, "unit": "unit",
             "options": [{"product_id": "463335", "why": "x"}]}], MON), [])
    working = gate.valio.availability
    gate.valio.availability = lambda ids, d: (_ for _ in ()).throw(TimeoutError("read timed out"))
    asyncio.run(shop.confirm(s.id))
    assert s.status == "cart" and s.order is None and s.messages[-1]["role"] == "error"
    gate.valio.availability = working
    asyncio.run(shop.confirm(s.id))
    assert s.status == "ordered" and s.order["status"] == "CONFIRMED"


def test_failed_run_leaves_no_unanswered_tool_call(gate):
    from trade_gate.shop.assistant import Shop

    s = Shop(gate).create(B)
    s.llm = [{"role": "user", "content": "soup for 20"},
             {"role": "assistant", "content": [SimpleNamespace(type="text"), SimpleNamespace(type="tool_use")]}]
    Shop._drop_unanswered_tool_call(s)
    assert [m["role"] for m in s.llm] == ["user"]


def test_every_attempt_to_get_past_the_gate_is_stopped(tmp_path, monkeypatch):
    from trade_gate import attacks
    from trade_gate.demo import SimulatedValio, sample_catalog

    monkeypatch.setattr(attacks, "datetime", FrozenClock)
    runner = attacks.Attacks(SimulatedValio(now=lambda: NOW), sample_catalog(tmp_path / "catalog.sqlite"))
    results = [runner.run(a["id"]) for a in runner.listing()]
    assert [r["id"] for r in results if not r["stopped"]] == ["typed-name"]
    assert [r["id"] for r in results if r["known_gap"]] == ["typed-name"]
    assert {r["verdict"] for r in results} == {"REFUSED", "BLOCKED", "HELD", "DETECTED", "NOT_STOPPED"}
    assert all(r["audit"] for r in results)


def test_saved_recipe_becomes_a_cart_with_cost_per_portion_without_a_model(tmp_path, monkeypatch):
    from trade_gate.demo import SimulatedValio, sample_catalog
    from trade_gate.seed import seed
    from trade_gate.service import TradeGate
    from trade_gate.shop import recipe_cart as rc
    from trade_gate.shop.assistant import Shop

    monkeypatch.setattr(rc, "datetime", FrozenClock)
    g = TradeGate(SimulatedValio(now=lambda: NOW), sample_catalog(tmp_path / "catalog.sqlite"), state_dir=tmp_path / "s")
    seed(g)
    shop = Shop(g)
    s = shop.create("kultakeittio-catering")
    rc.recipe_cart(shop, s.id, "r-salmon-pasta", 80)
    by_need = {ln["need"]: ln for ln in s.cart["lines"]}
    assert by_need["spaghetti"]["options"][0]["units"] == 8 and not by_need["spaghetti"]["decision_needed"]
    assert by_need["salmon fillet"]["decision_needed"] and len(by_need["salmon fillet"]["options"]) >= 2
    assert all(o["delivery"]["on_time"] for ln in s.cart["lines"] for o in ln["options"])
    totals = s.cart["totals"]
    assert totals["per_portion"] == round(totals["total"] / 80, 2) == 3.23
    assert s.cart["deliver_by"] == "2026-11-17" and s.status == "cart"
    assert shop._place(s)["status"] == "CONFIRMED"
    with pytest.raises(GateError) as e:
        rc.recipe_cart(shop, s.id, "no-such-recipe", 80)
    assert e.value.code == "UNKNOWN_RECIPE"
