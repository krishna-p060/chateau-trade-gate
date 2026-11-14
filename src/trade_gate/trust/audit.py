"""Append-only, hash-chained audit log.

Each entry stores a plain-language summary (for humans) plus structured data (for machines), and
the SHA-256 of the previous entry. Altering or deleting any past entry breaks every later hash,
so buyer and Valio can both prove the log is intact (verify_chain).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime
from typing import Any

from trade_gate.engine.offers import TZ
from trade_gate.trust.keys import canonical

GENESIS = "0" * 64


class AuditLog:
    def __init__(self, con: sqlite3.Connection, lock: threading.RLock):
        self.con, self.lock = con, lock
        con.execute("""CREATE TABLE IF NOT EXISTS audit (
            seq INTEGER PRIMARY KEY, ts TEXT, buyer_id TEXT, actor TEXT, event TEXT, summary TEXT,
            ref TEXT, data TEXT, prev_hash TEXT, hash TEXT)""")
        con.commit()
        self.listeners: list = []  # callables receiving each new entry (dashboard live feed)

    @staticmethod
    def _hash(entry: dict) -> str:
        body = {k: entry[k] for k in ("seq", "ts", "buyer_id", "actor", "event", "summary", "ref", "data", "prev_hash")}
        return hashlib.sha256(canonical(body).encode()).hexdigest()

    def append(self, *, buyer_id: str | None, actor: str, event: str, summary: str, ref: str | None = None,
               data: Any = None) -> dict:
        with self.lock:
            last = self.con.execute("SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
            seq, prev = (last[0] + 1, last[1]) if last else (1, GENESIS)
            entry = {"seq": seq, "ts": datetime.now(TZ).isoformat(timespec="seconds"), "buyer_id": buyer_id,
                     "actor": actor, "event": event, "summary": summary, "ref": ref,
                     "data": json.loads(canonical(data)) if data is not None else None, "prev_hash": prev}
            entry["hash"] = self._hash(entry)
            self.con.execute("INSERT INTO audit VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (seq, entry["ts"], buyer_id, actor, event, summary, ref,
                              canonical(entry["data"]), prev, entry["hash"]))
            self.con.commit()
        for fn in list(self.listeners):
            try:
                fn(entry)
            except Exception:  # a broken listener must never break the audit trail
                pass
        return entry

    def entries(self, buyer_id: str | None = None, ref: str | None = None, since_seq: int = 0,
                limit: int = 500) -> list[dict]:
        """Matching entries in sequence order; when more than limit match, the newest limit."""
        sql, args = "SELECT * FROM audit WHERE seq > ?", [since_seq]
        if buyer_id:
            sql += " AND buyer_id = ?"
            args.append(buyer_id)
        if ref:
            sql += " AND (ref = ? OR data LIKE ?)"
            args += [ref, f"%{ref}%"]
        rows = self.con.execute(sql + " ORDER BY seq DESC LIMIT ?", (*args, limit)).fetchall()[::-1]
        cols = ["seq", "ts", "buyer_id", "actor", "event", "summary", "ref", "data", "prev_hash", "hash"]
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            d["data"] = json.loads(d["data"]) if d["data"] else None
            out.append(d)
        return out

    def verify_chain(self) -> dict:
        prev, n = GENESIS, 0
        for e in self.entries(limit=10_000_000):
            n += 1
            if e["prev_hash"] != prev or self._hash(e) != e["hash"]:
                return {"valid": False, "broken_at_seq": e["seq"], "checked": n}
            prev = e["hash"]
        return {"valid": True, "checked": n, "head": prev}

    def narrative(self, buyer_id: str | None = None, ref: str | None = None) -> str:
        """Human-readable story of what happened, for buyer or Valio."""
        lines = []
        for e in self.entries(buyer_id=buyer_id, ref=ref):
            lines.append(f"{e['ts'][11:19]}  [{e['actor']}] {e['summary']}")
        return "\n".join(lines)
