"""Shared fixtures: the catalog every test reads (bundled sample; TRADE_GATE_TEST_REAL_CATALOG=1 uses data/catalog.sqlite)."""
from __future__ import annotations

import os

import pytest

from trade_gate.catalog.store import Catalog
from trade_gate.config import DB_PATH
from trade_gate.demo import sample_catalog


@pytest.fixture(scope="session")
def catalog(tmp_path_factory):
    if os.getenv("TRADE_GATE_TEST_REAL_CATALOG", "") == "1":
        if not DB_PATH.exists():
            pytest.fail(f"TRADE_GATE_TEST_REAL_CATALOG=1 but {DB_PATH} does not exist; build it with "
                        "`uv run python -m trade_gate.catalog.build_index`.")
        return Catalog()
    return sample_catalog(tmp_path_factory.mktemp("catalog") / "catalog.sqlite")
