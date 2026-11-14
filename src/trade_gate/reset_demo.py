"""Start the demo from a clean state: fresh synthetic purchase history, no orders, empty audit log.

Non-destructive: the current database is moved aside to data/state/gate.sqlite.bak-<timestamp>.
Keys and mandates are kept (mandates are re-signed from the seed on the next server start).
Stop the server first, then: uv run python -m trade_gate.reset_demo
"""
from datetime import datetime

from trade_gate.config import STATE_DIR

if __name__ == "__main__":
    db = STATE_DIR / "gate.sqlite"
    if db.exists():
        bak = db.with_name(f"gate.sqlite.bak-{datetime.now():%Y%m%d-%H%M%S}")
        db.rename(bak)
        print(f"Moved {db.name} -> {bak.name}. Start the server to regenerate the demo state.")
    else:
        print("No database yet; nothing to reset.")
