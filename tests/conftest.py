"""Shared fixtures: tests read data/catalog.sqlite when it exists (built from Valio's files), else the bundled sample catalog."""
from __future__ import annotations

import pytest

from trade_gate.catalog.store import Catalog
from trade_gate.config import DB_PATH
from trade_gate.demo import sample_catalog


@pytest.fixture(scope="session")
def catalog(tmp_path_factory):
    if DB_PATH.exists():
        return Catalog()
    return sample_catalog(tmp_path_factory.mktemp("catalog") / "catalog.sqlite")
