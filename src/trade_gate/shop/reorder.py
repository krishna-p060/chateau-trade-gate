"""Quick re-ordering for busy kitchens: the usual order in one tap, any past order again, quantity
buttons, and the weekly reminder.

Plain code, no AI: prices and stock come live from Valio, substitutes for missing items come from
Valio's own substitute list and the customer's purchase history (the same deterministic shortlist the
assistant uses). The customer still confirms, and the gate checks the signed mandate on every order.
"""
from __future__ import annotations

import asyncio
import math
import re
from datetime import date, datetime, timedelta

from trade_gate.engine.offers import TZ
from trade_gate.service import GateError
from trade_gate.shop.i18n import day, eur, t

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SCALES = (0.5, 0.8, 1.0, 1.2, 1.5, 2.0)


def _today() -> date:
    return datetime.now(TZ).date()


def next_delivery(weekdays: list[str], today: date | None = None) -> date:
    """First delivery day after today on one of the given weekdays (any weekday if none)."""
    wd = {WEEKDAYS.index(w) for w in weekdays if w in WEEKDAYS} or {0, 1, 2, 3, 4}
    d = (today or _today()) + timedelta(days=1)
    while d.weekday() not in wd:
        d += timedelta(days=1)
    return d


def _packs(q: float) -> int:
    return max(1, math.ceil(q - 1e-6))


_MULTI = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|g|l|ml)\s*x\s*(\d+)", re.I)


def _pack_content(gate, p, d: date) -> tuple[float | None, str | None]:
    """Content of one sales unit in kg/l: catalog, else Valio's unit price, else '1kgx15' in the name."""
    if p.content_per_sales_unit and p.content_dim in ("kg", "l"):
        return p.content_per_sales_unit, p.content_dim
    pr = gate.valio.prices([p.id], d).get(p.id) or {}
    cp, comp = (pr.get("catalogPrice") or {}).get("value"), (pr.get("comparisonPrice") or {}).get("value")
    if cp and comp and pr.get("comparisonUnit") in ("KG", "L"):
        return round(cp / comp, 3), pr["comparisonUnit"].lower()
    m = _MULTI.search(p.name or "")
    if m:
        n, u, k = float(m.group(1).replace(",", ".")), m.group(2).lower(), int(m.group(3))
        return (n * k / 1000 if u in ("g", "ml") else n * k), ("kg" if u in ("kg", "g") else "l")
    return None, None


def _short(name: str, words: int = 3) -> str:
    """'Barilla Spaghetti n.5 durum wheat pasta 1kgx15' -> 'Barilla Spaghetti n.5'."""
    return " ".join([w for w in name.split() if not any(c.isdigit() for c in w) or "." in w][:words]) or name


def _query(name: str, brand: str | None) -> str:
    """Catalog search words for a product's substitute: drop the brand and pack sizes."""
    skip = {w.lower() for w in (brand or "").split()}
    words = [w for w in name.replace(",", " ").split()
             if w.lower() not in skip and not any(c.isdigit() for c in w) and len(w) > 1]
    return " ".join(words[:3]) or name


class ReorderMixin:
    """Mixed into Shop (needs self.gate, self.get, self._msg, self._notify, self._price_lines, self._cart_from,
    self._totals, self._user_turn)."""

    # ------------------------------------------------------------------ sources: templates and past orders
    def _templates(self, cid: str) -> list[dict]:
        b = self.gate.buyer(cid)
        return [{"source": f"tpl:{so['id']}", "kind": "template", "name": so["name"], "weekdays": so["weekdays"],
                 "lines": [{"product_id": ln["product_id"], "units": ln["units"]} for ln in so["lines"]],
                 "deliver_by": next_delivery(so["weekdays"])}
                for so in b["profile"].get("standing_orders", [])]

    def _past_orders(self, cid: str, limit: int = 5) -> list[dict]:
        """Recent deliveries from the purchase history, one entry per order (event orders of a day together)."""
        b = self.gate.buyer(cid)
        prof = b["profile"]
        tpl_names = {so["id"]: so["name"] for so in prof.get("standing_orders", [])}
        recipe_names = {r["id"]: r["name"] for r in prof.get("recipes", [])}
        since = (_today() - timedelta(days=45)).isoformat()
        rows = self.gate.con.execute(
            "SELECT day, source, product_id, SUM(units) AS units FROM purchases WHERE buyer_id=? AND day>=? "
            "GROUP BY day, source, product_id ORDER BY day DESC, source", (cid, since)).fetchall()
        groups: dict[tuple, dict] = {}
        latest_of: dict[str, str] = {}  # an order template appears once, at its latest delivery
        for r in rows:
            src = r["source"] or ""
            key = (r["day"], "event" if src.startswith("event:") else src)
            if src.startswith("standing:") and latest_of.setdefault(src, r["day"]) != r["day"]:
                continue
            g = groups.get(key)
            if g is None:
                if len(groups) >= limit:
                    continue
                g = groups[key] = {"source": f"past|{r['day']}|{key[1]}", "day": r["day"], "lines": {},
                                   "recipes": [], "raw": src}
            if src.startswith("event:") and recipe_names.get(src[6:]) and recipe_names[src[6:]] not in g["recipes"]:
                g["recipes"].append(recipe_names[src[6:]])
            g["lines"][r["product_id"]] = g["lines"].get(r["product_id"], 0) + r["units"]
        delivery_days = prof.get("delivery_days") or []
        out = []
        for (d, k), g in groups.items():
            if k.startswith("standing:"):
                kind, name = "template", tpl_names.get(k[9:], "")
            elif k == "event":
                kind, name = "event", ", ".join(g["recipes"])
            else:
                kind, name = "order", ""
                try:
                    q = self.gate.get_order(k)["quote"]
                    name = re.split(r" [–—] ", (q.get("note") or "").split(" · ")[-1])[0]
                except GateError:
                    pass
            out.append({"source": g["source"], "kind": kind, "name": name, "day": d,
                        "lines": [{"product_id": p, "units": float(u)} for p, u in g["lines"].items()],
                        "deliver_by": next_delivery(delivery_days)})
        return out

    def _source(self, cid: str, source: str) -> dict:
        if source.startswith("tpl:"):
            found = next((x for x in self._templates(cid) if x["source"] == source), None)
        else:
            found = next((x for x in self._past_orders(cid, 12) if x["source"] == source), None)
        if not found:
            raise GateError("UNKNOWN_SOURCE", f"No order or template {source}.", 404)
        return found

    # ------------------------------------------------------------------ live check of a source
    def _check(self, cid: str, src: dict, scale: float = 1.0) -> tuple[list[dict], list[tuple]]:
        """Price every line live; split into (ok lines, problems) — the same rule as the template check."""
        d = src["deliver_by"]
        lines = self._price_lines(cid, [
            {"key": f"r{i}", "need": "", "quantity": _packs(ln["units"] * scale), "unit": "unit",
             "base_quantity": ln["units"],
             "options": [{"product_id": ln["product_id"], "why": ""}]}
            for i, ln in enumerate(src["lines"])], d)
        ok, bad = [], []
        for ln, s in zip(lines, src["lines"]):
            ln["base_quantity"], ln["base_unit"] = float(s["units"]), "unit"
            opt = ln["options"][0] if ln["options"] else None
            p = self.gate.catalog.get(s["product_id"])
            ln["need"] = (opt or {}).get("name") or (p.name if p else s["product_id"])
            ln["need_fi"] = (opt or {}).get("name_fi") or (p.name_fi if p and p.name_fi else ln["need"])
            if opt and opt["delivery"]["on_time"] and "not available" not in opt["stock"]:
                ok.append(ln)
            else:
                why = ln.get("problem") or ((opt or {}).get("notes") or ["not available"])[0]
                bad.append((ln, s, p, why))
        return ok, bad

    def _summary(self, cid: str, src: dict, lang: str) -> dict:
        ok, bad = self._check(cid, src)
        sel = [ln["options"][0] for ln in ok]
        order_bys = [o["order_by"] for o in sel if o.get("order_by")]
        names = [(ln["need_fi"] if lang == "fi" else ln["need"]) for ln in ok + [b[0] for b in bad]]
        cart = self._cart_from("", src["deliver_by"], ok, [], customer_id=cid, lang=lang)
        flags = [{"level": c["level"], "label": c["label"]} for c in cart["checks"]
                 if c["level"] != "ok" and c["id"] != "delivery"]  # e.g. "goes to the dietitian"
        return {k: v for k, v in src.items() if k not in ("lines", "deliver_by")} | {
            "deliver_by": src["deliver_by"].isoformat(), "lines_n": len(src["lines"]),
            "total": round(sum(o["total"] or 0 for o in sel), 2), "order_by": min(order_bys) if order_bys else None,
            "ok_n": len(ok), "names": names[:6], "flags": flags,
            "problems": [{"name": (ln["need_fi"] if lang == "fi" else ln["need"]), "why": why}
                         for ln, _s, _p, why in bad]}

    def reorder_overview(self, cid: str, lang: str = "en") -> dict:
        """Start screen: the next usual order (live), other templates, recent orders, the reminder preview."""
        b = self.gate.buyer(cid)
        sources = self._templates(cid) + self._past_orders(cid)
        by_day: dict[date, list[str]] = {}
        for x in sources:  # one batched price + availability call per delivery day; the rest hits the cache
            by_day.setdefault(x["deliver_by"], []).extend(ln["product_id"] for ln in x["lines"])
        for d, ids in by_day.items():
            ids = list(dict.fromkeys(ids))
            self.gate.valio.prices(ids, d)
            self.gate.valio.availability(ids, d)
        tpls = [self._summary(cid, x, lang) for x in sources if x["kind"] == "template" and x["source"].startswith("tpl:")]
        tpls.sort(key=lambda x: x["deliver_by"])
        past = [self._summary(cid, x, lang) for x in sources if x["source"].startswith("past|")]
        nxt = tpls[0] if tpls else None
        settings = b["profile"].get("settings") or {}
        channel = settings.get("reminder", "sms")
        contact = b["profile"].get("contact") or {}
        reminder = None
        if nxt:
            send = date.fromisoformat((nxt["order_by"] or nxt["deliver_by"])[:10])
            if not nxt["order_by"]:
                send -= timedelta(days=1)
            changes = len(nxt["problems"])
            reminder = {
                "channel": channel, "send_at": f"{send.isoformat()}T08:00:00+02:00",
                "to": contact.get("name", ""), "source": nxt["source"],
                "subject": t(lang, "rem_subject", name=nxt["name"], day=day(nxt["deliver_by"], lang)),
                "text": t(lang, "rem_text", first=contact.get("name", "").split(" ")[0], name=nxt["name"],
                          day=day(nxt["deliver_by"], lang), n=nxt["lines_n"], total=eur(nxt["total"], lang, 0))
                        + " " + (t(lang, "rem_all_ok") if not changes else t(
                            lang, "rem_changes_one" if changes == 1 else "rem_changes_other", n=changes,
                            items=", ".join(_short(p["name"]) for p in nxt["problems"][:2]))),
                "ready": not changes,
            }
        return {"next": nxt, "templates": tpls, "recent": past, "reminder": reminder,
                "reminder_channel": channel}

    # ------------------------------------------------------------------ build the cart
    def _substitutes(self, cid: str, bad: list[tuple], d: date, scale: float,
                     lang: str = "en") -> tuple[list[dict], list[dict]]:
        """For each problem line: up to 3 deliverable substitutes (Valio's list and the customer's usual first)."""
        if not bad:
            return [], []
        items = []
        for ln, s, p, _why in bad:
            units = s["units"] * scale
            content, dim = _pack_content(self.gate, p, d) if p else (None, None)
            if content and dim:
                qty, unit = round(units * content, 3), dim
            else:
                qty, unit = _packs(units), "unit"
            items.append({"key": ln["key"], "query": _query(p.name if p else ln["need"], p.brand if p else None),
                          "quantity": qty, "unit": unit, "replaces": s["product_id"]})
        res = self.gate.shortlist(cid, "aimo-assistant", items, d, per_item=6)
        subs, dropped = [], []
        for (ln, s, p, why), it, found in zip(bad, items, res["items"]):
            cands = sorted((c for c in found["candidates"] if c["delivery"]["on_time"]),
                           key=lambda c: (not c["valio_substitute"], not c["usual"], c["units"] > 20,
                                          c["total"] or 0))[:3]  # kitchen-size packs, then price
            name = p.name if p else ln["need"]
            name_fi = (p.name_fi if p and p.name_fi else name)
            if not cands:
                dropped.append({"product_id": s["product_id"], "name": name, "name_fi": name_fi, "why": why})
                continue
            for c in cands:
                c["why"] = t(lang, "why_valio_sub" if c["valio_substitute"] else "why_usual" if c["usual"]
                             else "why_similar")
            subs.append({"key": ln["key"], "need": name, "need_fi": name_fi, "dish": None,
                         "quantity": it["quantity"], "unit": it["unit"],
                         "base_quantity": float(it["quantity"]) / scale if scale else float(it["quantity"]),
                         "base_unit": it["unit"], "decision_needed": len(cands) > 1,
                         "replaces": {"product_id": s["product_id"], "name": name, "name_fi": name_fi},
                         "selected": 0, "options": cands, "problem": None, "problem_why": why})
        return subs, dropped

    def _repeat_cart(self, cid: str, source: str, scale: float, lang: str) -> dict:
        src = self._source(cid, source)
        ok, bad = self._check(cid, src, scale)
        subs, dropped = self._substitutes(cid, bad, src["deliver_by"], scale, lang)
        order = {ln["key"]: i for i, ln in enumerate(ok + [b[0] for b in bad])}
        lines = sorted(subs, key=lambda x: order[x["key"]]) + ok  # changes first, then the usual
        for ln in ok:
            ln["options"][0]["why"] = ""
        name = src["name"] or (t(lang, "past_order_of", day=day(src.get("day"), lang)))
        cart = self._cart_from(f"{name} — {day(src['deliver_by'].isoformat(), lang)}", src["deliver_by"], lines, [],
                               customer_id=cid, lang=lang)
        cart["repeat"] = {"source": source, "kind": src["kind"], "name": name, "scale": scale,
                          "changes": len(subs), "dropped": dropped, "usual_n": len(ok),
                          "day": src.get("day")}
        self._totals(cart)
        return cart

    async def repeat(self, sid: str, source: str, scale: float = 1.0):
        s = self.get(sid)
        if s.status in ("working", "ordering"):
            raise GateError("BUSY", t(s.lang, "busy"), 409)
        if scale not in SCALES:
            raise GateError("BAD_SCALE", f"Scale must be one of {SCALES}.")
        prev = s.status
        s.status = "working"
        self._notify(s)
        try:
            cart = await asyncio.to_thread(self._repeat_cart, s.customer_id, source, scale, s.lang)
        except Exception:
            s.status = prev
            self._notify(s)
            raise
        self._drop_pending(s)
        s.cart, s.order, s.plan = cart, None, None
        rp = cart["repeat"]
        self._msg(s, "user", t(s.lang, "repeat_msg", name=rp["name"]), notify=False)
        self._msg(s, "progress", t(s.lang, "template_checked", n=rp["usual_n"] + rp["changes"] + len(rp["dropped"]),
                                    day=day(cart["deliver_by"], s.lang), ok=rp["usual_n"],
                                    bad=rp["changes"] + len(rp["dropped"])), notify=False)
        self._llm_note(s, cart)
        s.status = "cart"
        self._notify(s)
        return s

    def _drop_pending(self, s) -> None:
        """A question or list the assistant was waiting on is no longer relevant: close it in the history."""
        if s.pending:
            s.llm.append({"role": "user", "content": s.pending["other_results"] + [{
                "type": "tool_result", "tool_use_id": s.pending["tool_use_id"],
                "content": "The customer left this and loaded a previous order into the cart instead."}]})
            s.pending, s.question = None, None

    def _llm_note(self, s, cart: dict) -> None:
        """Tell the assistant what is in the cart, so a follow-up request in the chat starts from it."""
        lines = "\n".join(
            f"- key {ln['key']}: {ln['options'][ln['selected']]['name']} (product "
            f"{ln['options'][ln['selected']]['product_id']}), {ln['quantity']:g} {ln['unit']}"
            + (f", replaces {ln['replaces']['name']}" if ln.get("replaces") else "")
            for ln in cart["lines"] if ln["options"])
        self._user_turn(s, f"[The customer loaded “{cart['repeat']['name']}” into the cart without the assistant "
                           f"(delivery {cart['deliver_by']}). Current cart:\n{lines}\nIf they ask for a change, "
                           f"call show_cart with the full updated cart.]")

    # ------------------------------------------------------------------ quantity buttons
    def _reprice(self, s, targets: dict[str, float]) -> None:
        """Re-price the given lines at new quantities (same products, same choice)."""
        cart = s.cart
        todo = [ln for ln in cart["lines"] if ln["key"] in targets and ln["options"]]
        if not todo:
            return
        d = date.fromisoformat(cart["deliver_by"])
        fresh = self._price_lines(s.customer_id, [
            {"key": ln["key"], "need": ln["need"], "dish": ln.get("dish"), "quantity": targets[ln["key"]],
             "unit": ln["unit"], "decision_needed": ln.get("decision_needed"),
             "replaces": (ln.get("replaces") or {}).get("product_id"),
             "options": [{"product_id": o["product_id"], "why": o.get("why", "")} for o in ln["options"]]}
            for ln in todo], d)
        for ln, f in zip(todo, fresh):
            if not f["options"]:
                continue
            chosen = ln["options"][ln["selected"]]["product_id"]
            ln["options"] = f["options"]
            ln["selected"] = next((i for i, o in enumerate(f["options"]) if o["product_id"] == chosen), 0)
            ln["quantity"] = targets[ln["key"]]
        cart["updated"] = datetime.now(TZ).isoformat(timespec="seconds")
        self._totals(cart)

    def _editable(self, sid: str):
        s = self.get(sid)
        if not s.cart or not s.cart["lines"]:
            raise GateError("NO_CART", t(s.lang, "no_cart"), 409)
        if s.status in ("working", "ordering") or s.order:
            raise GateError("BUSY", t(s.lang, "wait"), 409)
        return s

    async def scale_cart(self, sid: str, scale: float):
        """−20 % / usual / +20 % / ×2 for the whole cart, from the usual quantities."""
        s = self._editable(sid)
        if scale not in SCALES:
            raise GateError("BAD_SCALE", f"Scale must be one of {SCALES}.")
        targets = {}
        for ln in s.cart["lines"]:
            base = ln.get("base_quantity") or ln["quantity"] / (s.cart.get("repeat") or {}).get("scale", 1.0)
            ln["base_quantity"] = base
            targets[ln["key"]] = _packs(base * scale) if ln["unit"] == "unit" else round(base * scale, 3)
        await asyncio.to_thread(self._reprice, s, targets)
        s.cart.setdefault("repeat", {})["scale"] = scale
        self._notify(s)
        return s

    async def step_line(self, sid: str, key: str, delta: int):
        """One pack more or less on a line."""
        s = self._editable(sid)
        ln = self._line(s, key)
        if not ln["options"] or delta not in (-1, 1):
            raise GateError("BAD_STEP", "Step by one pack.")
        units = ln["options"][ln["selected"]]["units"] or 1
        new_units = units + delta
        if new_units < 1:
            raise GateError("MIN_ONE", t(s.lang, "min_one"), 409)
        if ln["unit"] == "unit":
            q = float(new_units)
        else:  # keep the line's own unit (kg/l): scale the need so the chosen pack count moves by one
            q = round(ln["quantity"] * new_units / units * (1 - 1e-6), 4)
        await asyncio.to_thread(self._reprice, s, {key: q})
        ln["edited"] = True
        self._notify(s)
        return s
