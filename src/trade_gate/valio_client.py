"""Client for Valio Aimo's mock pricing & availability APIs.

Respects the API's guidance: query only narrowed-down products, batch up to 1,000 codes,
cache briefly, back off on rate limits. Every live call is recorded so the audit trail can
show exactly which Valio responses a decision was based on.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

from trade_gate.config import VALIO_API_BASE, VALIO_API_KEY, VALIO_CUSTOMER

MAX_BATCH = 1000
CACHE_TTL_S = 120


class ValioAPIError(RuntimeError):
    pass


@dataclass
class _Cache:
    ttl: float = CACHE_TTL_S
    store: dict[tuple, tuple[float, Any]] = field(default_factory=dict)

    def get(self, key: tuple) -> Any | None:
        hit = self.store.get(key)
        if hit and time.monotonic() - hit[0] < self.ttl:
            return hit[1]
        return None

    def put(self, key: tuple, value: Any) -> None:
        self.store[key] = (time.monotonic(), value)


RATE_LIMIT_BLOCK_S = 31  # Valio: 429 => blocked for 30 s


class ValioClient:
    def __init__(self, api_key: str = VALIO_API_KEY, base: str = VALIO_API_BASE,
                 customer: str = VALIO_CUSTOMER, timeout: float = 20.0):
        if not api_key:
            raise ValioAPIError("VALIO_API_KEY missing: add it to .env")
        self.customer = customer
        self._http = httpx.Client(base_url=base, timeout=timeout,
                                  headers={"X-API-Key": api_key, "Content-Type": "application/json"})
        self._cache = _Cache()
        self.calls: list[dict] = []  # lightweight log of live calls (endpoint, n products, ms, status)

    # ------------------------------------------------------------------ low level
    def _post(self, path: str, products: list[str], requested: date) -> dict:
        body = {"customer": self.customer, "requestedDate": requested.isoformat(), "products": products}
        delay = 1.0
        for attempt in range(5):
            t0 = time.monotonic()
            r = self._http.post(path, json=body)
            self.calls.append({"endpoint": path, "products": len(products), "requestedDate": body["requestedDate"],
                               "status": r.status_code, "ms": round((time.monotonic() - t0) * 1000)})
            if r.status_code == 429:
                # Valio: a 429 blocks the key for 30 seconds; retrying earlier only extends the block.
                time.sleep(max(float(r.headers.get("Retry-After", 0) or 0), RATE_LIMIT_BLOCK_S))
                continue
            if r.status_code >= 500:
                time.sleep(min(delay, 10))
                delay *= 2
                continue
            if r.status_code != 200:
                raise ValioAPIError(f"{path} -> HTTP {r.status_code}: {r.text[:300]}")
            return r.json()
        raise ValioAPIError(f"{path} kept failing (rate limited or server error)")

    def _batched(self, path: str, products: list[str], requested: date, key: str) -> dict[str, dict]:
        out: dict[str, dict] = {}
        todo = []
        for pid in dict.fromkeys(products):  # de-duplicate, keep order
            hit = self._cache.get((path, pid, requested))
            if hit is not None:
                out[pid] = hit
            else:
                todo.append(pid)
        for i in range(0, len(todo), MAX_BATCH):
            chunk = todo[i:i + MAX_BATCH]
            data = self._post(path, chunk, requested)
            for item in data.get(key, []):
                pid = item.get("productId")
                item["_meta"] = {k: v for k, v in data.items() if k != key}
                self._cache.put((path, pid, requested), item)
                out[pid] = item
        return out

    # ------------------------------------------------------------------ public
    def ping(self) -> bool:
        return self._http.get("/ping").status_code == 200

    def availability(self, products: list[str], requested: date) -> dict[str, dict]:
        return self._batched("/availability", products, requested, "products")

    def prices(self, products: list[str], requested: date) -> dict[str, dict]:
        return self._batched("/price", products, requested, "products")
