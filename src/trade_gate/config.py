"""Central configuration. Secrets come from .env (never committed)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "catalog.sqlite"
STATE_DIR = DATA_DIR / "state"  # orders, quotes, approvals, audit log, keys

VALIO_API_BASE = os.getenv("VALIO_API_BASE", "https://junction26.valioaimo.fi/api")
VALIO_API_KEY = os.getenv("VALIO_API_KEY", "")
VALIO_CUSTOMER = os.getenv("VALIO_CUSTOMER", "123")  # customer id does not affect mock responses

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AGENT_MODEL = os.getenv("AGENT_MODEL", "claude-opus-5-5")

TIMEZONE = "Europe/Helsinki"
