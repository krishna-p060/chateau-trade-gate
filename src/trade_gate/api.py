"""HTTP surface of the Trade Gate.

  /mcp                         MCP (Streamable HTTP) for agents      — auth: Bearer <mandate vc+jwt>
  /api/v1/...                  REST API for agents (OpenAPI 3.1)     — auth: Bearer <mandate vc+jwt>
  /api/console/...             approver & Valio console (dashboard)  — demo: no auth (SSO in production)
  /.well-known/jwks.json       gate signing keys (verify quotes/orders offline)
  /.well-known/trade-gate.json capability manifest

Run: uv run uvicorn trade_gate.api:app --port 8400
"""
from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from trade_gate.attacks import Attacks
from trade_gate.config import ANTHROPIC_API_KEY, DEMO, ROOT
from trade_gate.demo import DEMO_NOTE, open_gate
from trade_gate.engine.planner import Need
from trade_gate.mcp_server import _order_view, build_mcp
from trade_gate.seed import seed
from trade_gate.service import GateError
from trade_gate.trust.mandate import Mandate
from trade_gate.valio_client import ValioAPIError

gate = open_gate()
seed(gate)
mcp = build_mcp(gate)
mcp_app = mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True)

# live feed for the dashboard: every audit entry is pushed to connected browsers
_subscribers: set[asyncio.Queue] = set()
_loop: asyncio.AbstractEventLoop | None = None


def _broadcast(entry: dict) -> None:
    if _loop is None:
        return
    for q in list(_subscribers):
        _loop.call_soon_threadsafe(q.put_nowait, entry)


gate.audit.listeners.append(_broadcast)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _loop
    _loop = asyncio.get_running_loop()
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Valio Aimo Trade Gate", version="0.1.0", lifespan=lifespan,
              description="Open interface for external purchasing agents: search, plan, signed quotes, "
                          "mandate-checked orders, human approvals and a hash-chained audit trail.")
app.mount("/mcp", mcp_app)


@app.exception_handler(GateError)
async def _gate_error(_req: Request, e: GateError):
    return JSONResponse({"error": e.code, "message": e.message}, status_code=e.status)


@app.exception_handler(ValioAPIError)
@app.exception_handler(httpx.HTTPError)
async def _valio_error(_req: Request, e: Exception):
    return JSONResponse({"error": "VALIO_UNAVAILABLE", "message": "Valio's price and availability service did "
                         f"not answer ({type(e).__name__}); nothing was ordered. Try again in a moment."},
                        status_code=503)


def agent(authorization: str = Header(default="")) -> tuple[Mandate, str]:
    token = authorization.split(" ", 1)[1] if authorization.lower().startswith("bearer ") else None
    return gate.authenticate(token), token


# ------------------------------------------------------------------ discovery
@app.get("/.well-known/jwks.json", tags=["trust"])
def jwks():
    return {"keys": [gate.key.jwk()]}


@app.get("/.well-known/trade-gate.json", tags=["trust"])
def manifest(request: Request):
    return gate.manifest(str(request.base_url).rstrip("/")) | ({"demo": DEMO_NOTE} if DEMO else {})


# ------------------------------------------------------------------ agent REST API
class SearchIn(BaseModel):
    query: str
    diets: list[str] = []
    avoid_allergens: list[str] = []
    require_allergen_data: bool = False
    labels: list[str] = []
    unit: str | None = None
    limit: int = Field(15, le=40)


class OffersIn(BaseModel):
    product_ids: list[str] = Field(..., max_length=40)
    deliver_by: date
    quantity: float | None = None
    unit: str = "unit"


class NeedIn(BaseModel):
    query: str = ""
    quantity: float
    unit: str
    deliver_by: date
    diets: list[str] = []
    avoid_allergens: list[str] = []
    require_allergen_data: bool = False
    preferred_labels: list[str] = []
    product_ids: list[str] = []


class QuoteLine(BaseModel):
    product_id: str
    units: float
    is_substitute: bool = False
    replaces: str | None = None
    outside_preferences: bool = False


class QuoteIn(BaseModel):
    lines: list[QuoteLine]
    deliver_by: date
    note: str = ""


class OrderIn(BaseModel):
    quote_id: str
    rationale: str
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()))


@app.get("/api/v1/mandate", tags=["agent"])
def my_mandate(a=Depends(agent)):
    m, _ = a
    return {"buyer": gate.buyer(m.buyer_id) | {"jwk": None}, "mandate": m.to_credential_subject()}


@app.post("/api/v1/products/search", tags=["agent"])
def search(body: SearchIn, a=Depends(agent)):
    m, _ = a
    return gate.search(m.buyer_id, m.agent_id, query=body.query, diets=body.diets,
                       avoid_allergens=list(dict.fromkeys(body.avoid_allergens + m.dietary.avoid_allergens)),
                       require_allergen_data=body.require_allergen_data, labels=body.labels,
                       content_dim=body.unit, limit=body.limit)


@app.get("/api/v1/products/{pid}", tags=["agent"])
def product(pid: str, a=Depends(agent)):
    return gate.product(pid)


@app.post("/api/v1/offers", tags=["agent"])
def offers(body: OffersIn, a=Depends(agent)):
    m, _ = a
    return gate.offers(m.buyer_id, m.agent_id, body.product_ids, body.deliver_by, body.quantity, body.unit)


@app.post("/api/v1/plans", tags=["agent"])
def make_plan(body: NeedIn, a=Depends(agent)):
    m, _ = a
    need = Need(**body.model_dump())
    need.avoid_allergens = list(dict.fromkeys(need.avoid_allergens + m.dietary.avoid_allergens))
    need.require_allergen_data = need.require_allergen_data or m.dietary.require_allergen_data
    return gate.plan(m.buyer_id, m.agent_id, need)


@app.post("/api/v1/quotes", tags=["agent"])
def quote(body: QuoteIn, a=Depends(agent)):
    m, _ = a
    return gate.create_quote(m.buyer_id, m.agent_id, [ln.model_dump(exclude_none=True) for ln in body.lines],
                             body.deliver_by, body.note)


@app.post("/api/v1/orders", tags=["agent"])
def order(body: OrderIn, a=Depends(agent)):
    m, token = a
    return _order_view(gate.place_order(m.buyer_id, m.agent_id, body.quote_id, token, body.idempotency_key,
                                        body.rationale))


@app.get("/api/v1/orders/{oid}", tags=["agent"])
def get_order(oid: str, a=Depends(agent)):
    m, _ = a
    o = gate.get_order(oid)
    if o["buyer_id"] != m.buyer_id:
        raise GateError("FORBIDDEN", "Not your order.", 403)
    return _order_view(o)


# ------------------------------------------------------------------ console (approver & Valio views)
class DecisionIn(BaseModel):
    approver: str
    approve: bool
    note: str = ""


@app.get("/api/console/buyers", tags=["console"])
def c_buyers():
    return gate.buyers()


@app.get("/api/console/approvals", tags=["console"])
def c_approvals(buyer_id: str | None = None, status: str | None = "PENDING"):
    return gate.approvals(buyer_id, status)


@app.post("/api/console/approvals/{aid}", tags=["console"])
def c_decide(aid: str, body: DecisionIn):
    try:
        return gate.decide(aid, body.approver, body.approve, body.note)
    finally:
        pending = {a["order_id"] for a in gate.approvals(status="PENDING")}
        for sess in shop.sessions.values():
            if sess.order and sess.order.get("status") == "PENDING_APPROVAL" and sess.order["order_id"] not in pending:
                shop.refresh_order(sess)
                if _loop:
                    _loop.call_soon_threadsafe(shop._notify, sess)


@app.get("/api/console/orders", tags=["console"])
def c_orders(buyer_id: str | None = None):
    return gate.orders(buyer_id)


@app.get("/api/console/audit", tags=["console"])
def c_audit(buyer_id: str | None = None, ref: str | None = None, since: int = 0):
    return {"entries": gate.audit.entries(buyer_id, ref, since), "integrity": gate.audit.verify_chain()}


@app.get("/api/console/audit/narrative", tags=["console"])
def c_narrative(buyer_id: str | None = None, ref: str | None = None):
    return {"text": gate.audit.narrative(buyer_id, ref)}


@app.get("/api/console/stream", tags=["console"])
async def c_stream(request: Request):
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.add(q)

    async def gen():
        try:
            yield "retry: 2000\n\n"
            while not await request.is_disconnected():
                try:
                    e = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(e, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            _subscribers.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/console/stats", tags=["console"])
def c_stats() -> dict[str, Any]:
    rows = gate.con.execute("SELECT status, COUNT(*), COALESCE(SUM(total),0) FROM orders GROUP BY status").fetchall()
    return {"orders": {r[0]: {"count": r[1], "total": round(r[2], 2)} for r in rows},
            "valio_api_calls": len(gate.valio.calls), "audit": gate.audit.verify_chain()}


# ------------------------------------------------------------------ demo: run the reference buyer agent
class AgentRunIn(BaseModel):
    buyer_id: str
    request: str
    wait_for_approval_s: float = 600


_runs: dict[str, dict] = {}


@app.get("/api/console/scenarios", tags=["demo"])
def c_scenarios():
    from trade_gate.scenarios import SCENARIOS
    return SCENARIOS


@app.post("/api/console/agent/run", tags=["demo"])
async def c_agent_run(body: AgentRunIn):
    """Start the reference buyer agent in the background; its steps stream on /api/console/stream."""
    from trade_gate.agent.buyer_agent import run_agent
    from trade_gate.config import ANTHROPIC_API_KEY
    from trade_gate.seed import load_mandate

    if not ANTHROPIC_API_KEY:
        raise GateError("NO_LLM_KEY", "Set ANTHROPIC_API_KEY in .env to run the buyer agent.", 503)
    b = gate.buyer(body.buyer_id)
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    _runs[run_id] = {"id": run_id, "buyer_id": b["id"], "request": body.request, "status": "running",
                     "events": []}

    def sink(ev: dict) -> None:
        ev = {"run_id": run_id, "buyer_id": b["id"], **ev}
        _runs[run_id]["events"].append(ev)
        _broadcast(ev)

    async def go():
        try:
            res = await run_agent(body.request, load_mandate(b["id"], gate.state_dir), buyer_name=b["name"], sink=sink,
                                  wait_for_approval_s=body.wait_for_approval_s)
            _runs[run_id].update(status="done", final=res["final"])
        except Exception as e:  # surface failures in the UI instead of dying silently
            sink({"kind": "agent.error", "text": f"{type(e).__name__}: {e}"})
            _runs[run_id]["status"] = "error"

    asyncio.create_task(go())
    return {"run_id": run_id}


@app.get("/api/console/agent/runs/{run_id}", tags=["demo"])
def c_agent_runs(run_id: str):
    if run_id not in _runs:
        raise GateError("UNKNOWN_RUN", "No such run.", 404)
    return _runs[run_id]


# ------------------------------------------------------------------ webshop: Aimo Assistant (customer-facing)
from trade_gate.shop.assistant import Shop  # noqa: E402

shop = Shop(gate)


@app.get("/api/shop/customers", tags=["shop"])
def s_customers(lang: str = "en"):
    out = []
    for b in gate.buyers():
        ctx = gate.customer_context(b["id"])
        m = b.get("mandate") or {}
        out.append({"id": b["id"], "name": b["name"], **ctx["customer"], "priorities": ctx["priorities"],
                    "rules": ctx["rules"], "settings": ctx["settings"],
                    "approval_limit_eur": (m.get("limits") or {}).get("auto_approve_max_order_eur"),
                    "approvers": m.get("approvers", []),
                    "standing_orders": ctx["standing_orders"], "recipes": ctx["saved_recipes"],
                    "usual_products": ctx["usual_products"][:12],
                    "suggestions": (_SUGGESTIONS_FI if lang == "fi" else _SUGGESTIONS).get(b["id"], [])})
    return out


_SUGGESTIONS = {
    "kultakeittio-catering": [
        "Pasta pesto for 40 people on Friday",
        "Pizza margherita for 50 on Saturday",
        "5 kg onions, 2 kg penne and 10 l cooking cream for Tuesday"],
    "hotel-aurora": [
        "Toast Skagen for 150 conference guests on Wednesday",
        "Salmon soup for 80 on Friday"],
    "espoo-childrens-hospital": [
        "Oat porridge for 100 children on Monday",
        "Afternoon snack for 120 children on Monday"],
}


_SUGGESTIONS_FI = {
    "kultakeittio-catering": [
        "Pastaa pestolla 40 hengelle perjantaina",
        "Pizza margheritaa 50 hengelle lauantaina",
        "5 kg sipulia, 2 kg pennepastaa ja 10 l ruokakermaa tiistaiksi"],
    "hotel-aurora": [
        "Toast Skagen 150 konferenssivieraalle keskiviikkona",
        "Lohikeittoa 80 hengelle perjantaina"],
    "espoo-childrens-hospital": [
        "Kaurapuuroa 100 lapselle maanantaina",
        "Välipala 120 lapselle maanantaina"],
}


class SessionIn(BaseModel):
    customer_id: str
    lang: str = "en"


class LangIn(BaseModel):
    lang: str


class MessageIn(BaseModel):
    text: str


class SelectIn(BaseModel):
    line_key: str
    option: int


class LineIn(BaseModel):
    line_key: str


class StandingIn(BaseModel):
    standing_order_id: str


class SettingsIn(BaseModel):
    priorities: list[str] | None = None
    avoid_allergens: list[str] | None = None
    auto_confirm_standing_orders: bool | None = None
    approval_limit_eur: float | None = None


def _need_llm():
    from trade_gate.config import ANTHROPIC_API_KEY
    if not ANTHROPIC_API_KEY:
        raise GateError("NO_LLM_KEY", "Set ANTHROPIC_API_KEY in .env to use the assistant.", 503)


@app.post("/api/shop/sessions", tags=["shop"])
def s_new(body: SessionIn):
    return shop.create(body.customer_id, body.lang).snapshot()


@app.post("/api/shop/sessions/{sid}/lang", tags=["shop"])
async def s_lang(sid: str, body: LangIn):
    return shop.set_lang(sid, body.lang).snapshot()


@app.get("/api/shop/sessions/{sid}", tags=["shop"])
def s_get(sid: str):
    s = shop.get(sid)
    shop.refresh_order(s)
    return s.snapshot()


@app.post("/api/shop/sessions/{sid}/messages", tags=["shop"])
async def s_msg(sid: str, body: MessageIn):
    _need_llm()
    return shop.send(sid, body.text).snapshot()


@app.post("/api/shop/sessions/{sid}/standing-order", tags=["shop"])
async def s_standing(sid: str, body: StandingIn):
    _need_llm()
    return shop.standing_order(sid, body.standing_order_id).snapshot()


@app.post("/api/shop/sessions/{sid}/cart/select", tags=["shop"])
async def s_select(sid: str, body: SelectIn):
    return shop.select(sid, body.line_key, body.option).snapshot()


@app.post("/api/shop/sessions/{sid}/cart/remove", tags=["shop"])
async def s_remove(sid: str, body: LineIn):
    return shop.remove(sid, body.line_key).snapshot()


@app.post("/api/shop/sessions/{sid}/confirm", tags=["shop"])
async def s_confirm(sid: str):
    return (await shop.confirm(sid)).snapshot()


class AnswersIn(BaseModel):
    answers: dict[str, str]


class PlanItemIn(BaseModel):
    key: str | None = None
    name: str
    quantity: float
    unit: str = "kg"
    dish: str | None = None


class PlanIn(BaseModel):
    items: list[PlanItemIn]
    save_recipes: list[str] = []


@app.post("/api/shop/sessions/{sid}/answers", tags=["shop"])
async def s_answers(sid: str, body: AnswersIn):
    _need_llm()
    return shop.answer(sid, body.answers).snapshot()


@app.post("/api/shop/sessions/{sid}/plan/approve", tags=["shop"])
async def s_plan_approve(sid: str, body: PlanIn):
    _need_llm()
    return shop.approve_plan(sid, [i.model_dump() for i in body.items], body.save_recipes).snapshot()


class ReferenceIn(BaseModel):
    reference: str


class TemplateIn(BaseModel):
    name: str = ""


@app.post("/api/shop/sessions/{sid}/cart/reference", tags=["shop"])
async def s_reference(sid: str, body: ReferenceIn):
    return shop.set_reference(sid, body.reference).snapshot()


@app.post("/api/shop/sessions/{sid}/save-template", tags=["shop"])
async def s_save_template(sid: str, body: TemplateIn):
    return shop.save_template(sid, body.name).snapshot()


@app.post("/api/shop/sessions/{sid}/cart/notify", tags=["shop"])
async def s_notify(sid: str, body: LineIn):
    return shop.notify_when_back(sid, body.line_key).snapshot()


@app.get("/api/shop/sessions/{sid}/stream", tags=["shop"])
async def s_stream(sid: str, request: Request):
    s = shop.get(sid)
    q: asyncio.Queue = asyncio.Queue()
    s.listeners.add(q)

    async def gen():
        try:
            yield "retry: 2000\n\n"
            yield f"data: {json.dumps(s.snapshot(), default=str)}\n\n"
            while not await request.is_disconnected():
                try:
                    snap = await asyncio.wait_for(q.get(), timeout=15)
                    while not q.empty():  # only the latest state matters
                        snap = q.get_nowait()
                    yield f"data: {json.dumps(snap, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            s.listeners.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.put("/api/shop/customers/{cid}/settings", tags=["shop"])
def s_settings(cid: str, body: SettingsIn, lang: str = "en"):
    b = gate.buyer(cid)
    who = (b["profile"].get("contact") or {}).get("name", "Customer")
    gate.update_settings(cid, body.model_dump(exclude_none=True), by=who)
    return next(c for c in s_customers(lang) if c["id"] == cid)


@app.get("/api/shop/insights", tags=["valio"])
def s_insights():
    """Valio Aimo's view: orders from the assistant, substitution and preference signals, audit integrity."""
    return gate.insights()


attacks = Attacks(gate.valio, gate.catalog)


class RecipeIn(BaseModel):
    recipe_id: str
    portions: int


@app.post("/api/shop/sessions/{sid}/recipe", tags=["shop"])
def s_recipe(sid: str, body: RecipeIn):
    """Scale a saved recipe and price it as a cart in plain code; needs no model."""
    from trade_gate.shop.recipe_cart import recipe_cart
    return recipe_cart(shop, sid, body.recipe_id, body.portions).snapshot()


@app.get("/api/search-quality", tags=["demo"])
def search_quality():
    """Measured search quality (python -m trade_gate.search_eval): right product first on kitchen requests."""
    import json as _json
    f = ROOT / "docs" / "search-eval.json"
    return _json.loads(f.read_text()) if f.exists() else {}


@app.get("/api/demo/status", tags=["demo"])
def d_status():
    return {"demo": DEMO, "llm": bool(ANTHROPIC_API_KEY), "note": DEMO_NOTE if DEMO else ""}


@app.get("/api/demo/attacks", tags=["demo"])
def d_attacks():
    return attacks.listing()


@app.post("/api/demo/attacks/{attempt_id}", tags=["demo"])
def d_attack(attempt_id: str):
    """Run one attempt to get an order past the gate, on a scratch gate with its own order book."""
    return attacks.run(attempt_id)


# ------------------------------------------------------------------ dashboard (static build, if present)
_WEB = Path(__file__).resolve().parents[2] / "web" / "dist"


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    """Serve the dashboard build (checked per request, so a fresh build needs no restart)."""
    if not _WEB.exists():
        return JSONResponse({"error": "NO_DASHBOARD", "message": "Run `npm run build` in web/."}, status_code=404)
    f = (_WEB / path).resolve()
    if path and f.is_file() and _WEB in f.parents:
        return FileResponse(f)
    return FileResponse(_WEB / "index.html")
