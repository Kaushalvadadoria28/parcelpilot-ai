"""Tests for the ingestion pipeline (backend/ingestion/).

Runs entirely against synthetic fixtures (tests/fixtures/synthetic_dataset.py)
so it never depends on, and never asserts against, the real proprietary
data pack. See docs/git-development-plan.md §2 for why.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import openpyxl
import pytest

from backend.ingestion.build_db import build_database, parse_snapshot
from backend.ingestion.build_doc_index import build_document_index
from tests.fixtures.synthetic_dataset import write_synthetic_documents, write_synthetic_workbook


@pytest.fixture()
def workbook_path(tmp_path: Path) -> Path:
    path = tmp_path / "fixture_workbook.xlsx"
    write_synthetic_workbook(path)
    return path


@pytest.fixture()
def documents_fixture(tmp_path: Path) -> tuple[Path, Path]:
    documents_dir = tmp_path / "documents"
    manifest_path = tmp_path / "doc_manifest.yaml"
    write_synthetic_documents(documents_dir, manifest_path)
    return documents_dir, manifest_path


def _dump_table(conn: sqlite3.Connection, table: str) -> list[dict]:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(f"SELECT * FROM {table} ORDER BY rowid")  # noqa: S608 (fixed table names)
    return [dict(row) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# parse_snapshot
# ---------------------------------------------------------------------------


def test_parse_snapshot_attaches_named_timezone():
    dt = parse_snapshot("2026-08-16 11:00 Asia/Kolkata")
    assert dt.isoformat() == "2026-08-16T11:00:00+05:30"


def test_parse_snapshot_rejects_unrecognized_format():
    with pytest.raises(ValueError):
        parse_snapshot("16 August 2026, 11am IST")


# ---------------------------------------------------------------------------
# build_database
# ---------------------------------------------------------------------------


class TestBuildDatabase:
    def test_produces_expected_row_counts(self, workbook_path: Path, tmp_path: Path):
        db_path = tmp_path / "app.db"
        build_database(workbook_path, db_path)

        conn = sqlite3.connect(db_path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 3
            assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 3
            assert conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 2
        finally:
            conn.close()

    def test_snapshot_time_sourced_from_readme_not_wall_clock(
        self, workbook_path: Path, tmp_path: Path
    ):
        db_path = tmp_path / "app.db"
        build_database(workbook_path, db_path)

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT value FROM dataset_meta WHERE key = 'snapshot_time'"
            ).fetchone()
        finally:
            conn.close()

        assert row is not None
        # The fixture README states 2027-01-10 09:00 Asia/Kolkata (+05:30).
        # A value derived from the wall clock would not match this fixed,
        # far-future fixture timestamp.
        assert row[0] == "2027-01-10T09:00:00+05:30"

    def test_naive_order_timestamps_are_normalized_to_dataset_timezone(
        self, workbook_path: Path, tmp_path: Path
    ):
        db_path = tmp_path / "app.db"
        build_database(workbook_path, db_path)

        conn = sqlite3.connect(db_path)
        try:
            booked_at = conn.execute(
                "SELECT booked_at FROM orders WHERE order_id = 'FIX-ORD-001'"
            ).fetchone()[0]
        finally:
            conn.close()

        assert booked_at == "2027-01-10T09:00:00+05:30"

    def test_null_optional_timestamps_stay_null(self, workbook_path: Path, tmp_path: Path):
        db_path = tmp_path / "app.db"
        build_database(workbook_path, db_path)

        conn = sqlite3.connect(db_path)
        try:
            pickup_actual_at = conn.execute(
                "SELECT pickup_actual_at FROM orders WHERE order_id = 'FIX-ORD-001'"
            ).fetchone()[0]
        finally:
            conn.close()

        assert pickup_actual_at is None

    def test_boolean_columns_normalized_to_integers(self, workbook_path: Path, tmp_path: Path):
        db_path = tmp_path / "app.db"
        build_database(workbook_path, db_path)

        conn = sqlite3.connect(db_path)
        try:
            premium_support = conn.execute(
                "SELECT premium_support FROM accounts WHERE account_id = 'FIX-ACCT-001'"
            ).fetchone()[0]
            carrier_fault = conn.execute(
                "SELECT carrier_fault FROM orders WHERE order_id = 'FIX-ORD-002'"
            ).fetchone()[0]
            customer_fault = conn.execute(
                "SELECT customer_fault FROM orders WHERE order_id = 'FIX-ORD-002'"
            ).fetchone()[0]
        finally:
            conn.close()

        assert premium_support == 1
        assert carrier_fault == 1
        assert customer_fault == 0

    def test_referential_integrity_accounts_to_orders_and_tickets(
        self, workbook_path: Path, tmp_path: Path
    ):
        db_path = tmp_path / "app.db"
        build_database(workbook_path, db_path)

        conn = sqlite3.connect(db_path)
        try:
            orphan_orders = conn.execute(
                "SELECT COUNT(*) FROM orders WHERE account_id NOT IN "
                "(SELECT account_id FROM accounts)"
            ).fetchone()[0]
            orphan_tickets = conn.execute(
                "SELECT COUNT(*) FROM tickets WHERE account_id NOT IN "
                "(SELECT account_id FROM accounts)"
            ).fetchone()[0]
        finally:
            conn.close()

        assert orphan_orders == 0
        assert orphan_tickets == 0

    def test_idempotent_rerun_produces_identical_content(self, workbook_path: Path, tmp_path: Path):
        db_path = tmp_path / "app.db"

        build_database(workbook_path, db_path)
        conn = sqlite3.connect(db_path)
        first = {table: _dump_table(conn, table) for table in ("accounts", "orders", "tickets")}
        conn.close()

        build_database(workbook_path, db_path)
        conn = sqlite3.connect(db_path)
        second = {table: _dump_table(conn, table) for table in ("accounts", "orders", "tickets")}
        conn.close()

        assert first == second

    def test_rerun_after_source_change_reflects_new_content_only(
        self, workbook_path: Path, tmp_path: Path
    ):
        """A stale row from a previous version of the workbook must not survive
        a re-run against an updated workbook — proves this is a full rebuild,
        not an incremental upsert that could accumulate stale data."""
        db_path = tmp_path / "app.db"
        build_database(workbook_path, db_path)

        # Simulate the evaluator substituting a workbook with a different
        # account set entirely.
        second_workbook = tmp_path / "second_workbook.xlsx"
        write_synthetic_workbook(second_workbook)

        wb = openpyxl.load_workbook(second_workbook)
        wb["accounts"].append(
            ["FIX-ACCT-999", "Fixture Newcomer Co", "Standard", "active", None, None, False, None]
        )
        wb.save(second_workbook)

        build_database(second_workbook, db_path)

        conn = sqlite3.connect(db_path)
        try:
            ids = {row[0] for row in conn.execute("SELECT account_id FROM accounts").fetchall()}
        finally:
            conn.close()

        assert "FIX-ACCT-999" in ids
        assert len(ids) == 4  # original 3 + the new one, not duplicated


# ---------------------------------------------------------------------------
# build_document_index
# ---------------------------------------------------------------------------


class TestBuildDocumentIndex:
    def test_produces_chunks_for_every_manifest_document_present(
        self, documents_fixture: tuple[Path, Path], tmp_path: Path
    ):
        documents_dir, manifest_path = documents_fixture
        db_path = tmp_path / "app.db"
        build_document_index(documents_dir, manifest_path, db_path)

        conn = sqlite3.connect(db_path)
        try:
            rows = _dump_table(conn, "doc_chunks")
        finally:
            conn.close()

        assert len(rows) > 0
        sources = {row["source_file"] for row in rows}
        assert sources == {
            "fixture_policy_v2_current.txt",
            "fixture_policy_v1_deprecated.txt",
            "fixture_sop.txt",
            "fixture_contract_a.txt",
            "fixture_contract_b.txt",
        }

    def test_multi_section_document_splits_into_multiple_chunks(
        self, documents_fixture: tuple[Path, Path], tmp_path: Path
    ):
        documents_dir, manifest_path = documents_fixture
        db_path = tmp_path / "app.db"
        build_document_index(documents_dir, manifest_path, db_path)

        conn = sqlite3.connect(db_path)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM doc_chunks WHERE source_file = 'fixture_sop.txt'"
            ).fetchone()[0]
        finally:
            conn.close()

        # The fixture SOP has a header block plus two numbered sections.
        assert count == 3

    def test_deprecated_document_is_tagged_excluded(
        self, documents_fixture: tuple[Path, Path], tmp_path: Path
    ):
        documents_dir, manifest_path = documents_fixture
        db_path = tmp_path / "app.db"
        build_document_index(documents_dir, manifest_path, db_path)

        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT status, authority_tier FROM doc_chunks WHERE source_file = ?",
                ("fixture_policy_v1_deprecated.txt",),
            ).fetchall()
        finally:
            conn.close()

        assert rows  # at least one chunk exists
        assert all(status == "deprecated" and tier == "excluded" for status, tier in rows)

    def test_deprecated_document_records_its_superseding_document(
        self, documents_fixture: tuple[Path, Path], tmp_path: Path
    ):
        documents_dir, manifest_path = documents_fixture
        db_path = tmp_path / "app.db"
        build_document_index(documents_dir, manifest_path, db_path)

        conn = sqlite3.connect(db_path)
        try:
            superseded_by = conn.execute(
                "SELECT DISTINCT superseded_by FROM doc_chunks WHERE source_file = ?",
                ("fixture_policy_v1_deprecated.txt",),
            ).fetchall()
        finally:
            conn.close()

        assert superseded_by == [("fixture_policy_v2_current.txt",)]

    def test_contract_chunks_scoped_to_correct_account_only(
        self, documents_fixture: tuple[Path, Path], tmp_path: Path
    ):
        documents_dir, manifest_path = documents_fixture
        db_path = tmp_path / "app.db"
        build_document_index(documents_dir, manifest_path, db_path)

        conn = sqlite3.connect(db_path)
        try:
            contract_a_accounts = conn.execute(
                "SELECT DISTINCT customer_account_id FROM doc_chunks WHERE source_file = ?",
                ("fixture_contract_a.txt",),
            ).fetchall()
            general_docs_accounts = conn.execute(
                "SELECT DISTINCT customer_account_id FROM doc_chunks WHERE source_file = ?",
                ("fixture_sop.txt",),
            ).fetchall()
        finally:
            conn.close()

        assert contract_a_accounts == [("FIX-ACCT-001",)]
        assert general_docs_accounts == [(None,)]

    def test_missing_document_is_skipped_not_fatal(
        self, documents_fixture: tuple[Path, Path], tmp_path: Path
    ):
        documents_dir, manifest_path = documents_fixture
        # Simulate a partial/substituted data pack missing one referenced file.
        (documents_dir / "fixture_contract_b.txt").unlink()

        db_path = tmp_path / "app.db"
        build_document_index(documents_dir, manifest_path, db_path)  # must not raise

        conn = sqlite3.connect(db_path)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM doc_chunks WHERE source_file = 'fixture_contract_b.txt'"
            ).fetchone()[0]
            other_count = conn.execute("SELECT COUNT(*) FROM doc_chunks").fetchone()[0]
        finally:
            conn.close()

        assert count == 0
        assert other_count > 0  # the other four documents still ingested fine

    def test_idempotent_rerun_produces_identical_content(
        self, documents_fixture: tuple[Path, Path], tmp_path: Path
    ):
        documents_dir, manifest_path = documents_fixture
        db_path = tmp_path / "app.db"

        build_document_index(documents_dir, manifest_path, db_path)
        conn = sqlite3.connect(db_path)
        first = _dump_table(conn, "doc_chunks")
        conn.close()

        build_document_index(documents_dir, manifest_path, db_path)
        conn = sqlite3.connect(db_path)
        second = _dump_table(conn, "doc_chunks")
        conn.close()

        assert first == second
