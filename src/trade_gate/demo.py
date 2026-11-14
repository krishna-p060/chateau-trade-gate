"""Keyless demo mode: the bundled sample catalog and a simulated Valio price/availability client.

Active with TRADE_GATE_DEMO=1, or when VALIO_API_KEY is empty and data/catalog.sqlite does not exist.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path

from trade_gate.catalog.build_index import build
from trade_gate.catalog.store import Catalog
from trade_gate.config import DEMO, DEMO_DIR, SAMPLE_DIR
from trade_gate.engine.offers import TZ, UNKNOWN_STOCK_THRESHOLD
from trade_gate.service import TradeGate

log = logging.getLogger("trade_gate.demo")
DEMO_NOTE = ("Demo mode: bundled synthetic sample catalog and simulated Valio prices and availability; "
             "no Valio data or API key in use.")


class SimulatedValio:
    """Same interface as ValioClient, answering from sample/simulated_valio.json instead of Valio's mock API.

    Reproduces what the mock showed: Stock products report real amounts (one is short, one is at 0, one
    carries the 999999 placeholder); Terminal products always report 999999 and close several days before
    delivery, so near dates arrive with a closingTime already in the past; a product that cannot be
    delivered has empty scheduleLines. Dates follow the requested date and today's clock; stock never
    changes, because Valio has no order API.
    """

    def __init__(self, path: Path = SAMPLE_DIR / "simulated_valio.json", now=None):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.vat_rate: float = data["vat_rate"]
        self.products: dict[str, dict] = data["products"]
        self._now = now or (lambda: datetime.now(TZ))
        self.calls: list[dict] = []

    def _known(self, endpoint: str, products: list[str], requested: date) -> list[tuple[str, dict]]:
        self.calls.append({"endpoint": endpoint, "products": len(products),
                           "requestedDate": requested.isoformat(), "status": 200, "ms": 0, "simulated": True})
        return [(pid, self.products[pid]) for pid in dict.fromkeys(products) if pid in self.products]

    def ping(self) -> bool:
        return True

    def prices(self, products: list[str], requested: date) -> dict[str, dict]:
        valid_from = self._now().date().replace(day=1).isoformat()
        out = {}
        for pid, p in self._known("/price", products, requested):
            comp = p["comparison_price"]
            out[pid] = {
                "productId": pid, "quantity": 1.0, "error": False, "netPriceFound": False,
                "catalogPrice": {"value": p["price"], "valueWithTax": round(p["price"] * (1 + self.vat_rate / 100), 2),
                                 "currency": "EUR", "validFrom": valid_from, "validTo": "9999-12-31"},
                "comparisonPrice": {"value": comp, "valueWithTax": round(comp * (1 + self.vat_rate / 100), 2)}
                                   if comp else None,
                "comparisonUnit": p["comparison_unit"], "tax": {"taxRate": self.vat_rate, "taxValue": 0}}
        return out

    def availability(self, products: list[str], requested: date) -> dict[str, dict]:
        day = max(requested, self._now().date() + timedelta(days=1))
        if day.weekday() == 6:
            day += timedelta(days=1)
        out = {}
        for pid, p in self._known("/availability", products, requested):
            terminal = p["logistic_model"] == "Terminal"
            closing = datetime.combine(day - timedelta(days=p["lead_days"]), time(15 if terminal else 17), TZ)
            deliverable = p["deliverable"]
            out[pid] = {
                "productId": pid, "logisticModel": p["logistic_model"], "salesBlock": False,
                "closingTime": closing.strftime("%Y-%m-%dT%H:%M:%S%z") if deliverable else None,
                "scheduleLines": [{"salesBlock": False,
                                   "availableAmount": UNKNOWN_STOCK_THRESHOLD if terminal else p["stock"],
                                   "availableDate": day.isoformat(), "salesUnit": p["sales_unit"]}]
                                 if deliverable else []}
        return out


def sample_catalog(db_path: Path) -> Catalog:
    """Build the bundled sample catalog into db_path and open it."""
    build(db_path, SAMPLE_DIR)
    return Catalog(db_path)


def demo_gate(root: Path = DEMO_DIR) -> TradeGate:
    """A gate on the sample catalog and the simulated client; catalog and state live under root."""
    return TradeGate(SimulatedValio(), sample_catalog(root / "catalog.sqlite"), state_dir=root / "state")


def open_catalog() -> Catalog:
    return sample_catalog(DEMO_DIR / "catalog.sqlite") if DEMO else Catalog()


def open_gate() -> TradeGate:
    """The gate for this process: live Valio client and data/catalog.sqlite, or the keyless demo."""
    if not DEMO:
        from trade_gate.valio_client import ValioClient
        return TradeGate(ValioClient())
    gate = demo_gate()
    log.warning("%s Catalog: %d products. State: %s", DEMO_NOTE, gate.catalog_size(), gate.state_dir)
    return gate
