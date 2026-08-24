"""Shared pytest fixtures for tests that need a populated database.

Builds a real SQLite database via the actual Milestone 0 ingestion
pipeline, from the synthetic fixture workbook — never the proprietary
data pack — so every test that uses these fixtures is exercising the same
code path production ingestion uses, just against fictional data.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from backend.ingestion.build_db import build_database
from backend.models import AccountContractOverrides, PolicyDefaults
from tests.fixtures.policy_fixtures import (
    build_fixture_contract_overrides,
    build_fixture_policy_defaults,
)
from tests.fixtures.synthetic_dataset import write_synthetic_workbook


@pytest.fixture()
def synthetic_db_path(tmp_path: Path) -> Path:
    workbook_path = tmp_path / "fixture_workbook.xlsx"
    write_synthetic_workbook(workbook_path)
    db_path = tmp_path / "app.db"
    build_database(workbook_path, db_path)
    return db_path


@pytest.fixture()
def synthetic_db_connection(synthetic_db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(synthetic_db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture()
def fixture_policy_defaults() -> PolicyDefaults:
    """A fictitious PolicyDefaults profile, never matching the real
    assessment pack's numbers — see tests/fixtures/policy_fixtures.py."""
    return build_fixture_policy_defaults()


@pytest.fixture()
def fixture_contract_overrides() -> dict[str, AccountContractOverrides]:
    """Fictitious per-account contract overrides mirroring the real pack's
    *patterns* (fee waiver + tighter SLA; credit threshold/amount
    override) with entirely different numbers and account IDs."""
    return build_fixture_contract_overrides()
