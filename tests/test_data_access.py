"""Tests for the structured data access layer (backend/db/, backend/models.py).

Runs entirely against a database built from the synthetic fixture workbook
(tests/fixtures/synthetic_dataset.py via the tests/conftest.py fixtures),
never the real proprietary pack. This layer is intentionally trusted/
unscoped for this milestone — account- and role-based access control is
added on top of it in Milestone 2, not tested here.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest
from pydantic import ValidationError

from backend.db import queries
from backend.db.connection import connect
from backend.models import Account, DatasetMeta, Order, Ticket

# ---------------------------------------------------------------------------
# dataset_meta
# ---------------------------------------------------------------------------


def test_get_dataset_meta_returns_typed_snapshot(synthetic_db_connection: sqlite3.Connection):
    meta = queries.get_dataset_meta(conn=synthetic_db_connection)

    assert isinstance(meta, DatasetMeta)
    assert isinstance(meta.snapshot_time, datetime)
    assert meta.snapshot_time.tzinfo is not None
    # Matches the fixed value written by tests/fixtures/synthetic_dataset.py —
    # proves this came from the fixture README, not the wall clock.
    assert meta.snapshot_time.isoformat() == "2027-01-10T09:00:00+05:30"
    assert meta.currency == "INR"


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------


def test_get_account_returns_typed_model(synthetic_db_connection: sqlite3.Connection):
    account = queries.get_account("FIX-ACCT-001", conn=synthetic_db_connection)

    assert isinstance(account, Account)
    assert account.account_id == "FIX-ACCT-001"
    assert account.plan == "Enterprise"
    assert account.premium_support is True
    assert isinstance(account.premium_support, bool)


def test_get_account_returns_none_for_unknown_id(synthetic_db_connection: sqlite3.Connection):
    assert queries.get_account("NOT-A-REAL-ACCOUNT", conn=synthetic_db_connection) is None


def test_list_accounts_returns_all_rows_as_typed_models(
    synthetic_db_connection: sqlite3.Connection,
):
    accounts = queries.list_accounts(conn=synthetic_db_connection)

    assert len(accounts) == 3
    assert all(isinstance(a, Account) for a in accounts)
    assert {a.account_id for a in accounts} == {
        "FIX-ACCT-001",
        "FIX-ACCT-002",
        "FIX-ACCT-003",
    }


def test_account_model_is_immutable(synthetic_db_connection: sqlite3.Connection):
    account = queries.get_account("FIX-ACCT-001", conn=synthetic_db_connection)
    assert account is not None
    with pytest.raises(ValidationError):
        account.account_name = "Changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# orders
# ---------------------------------------------------------------------------


def test_get_order_returns_typed_model_with_parsed_timestamps(
    synthetic_db_connection: sqlite3.Connection,
):
    order = queries.get_order("FIX-ORD-001", conn=synthetic_db_connection)

    assert isinstance(order, Order)
    assert order.account_id == "FIX-ACCT-001"
    assert order.status == "BOOKED"
    assert isinstance(order.booked_at, datetime)
    assert order.booked_at.tzinfo is not None
    assert order.booked_at.isoformat() == "2027-01-10T09:00:00+05:30"
    # Not yet picked up in the fixture — must stay None, not a sentinel string.
    assert order.pickup_actual_at is None


def test_get_order_returns_none_for_unknown_id(synthetic_db_connection: sqlite3.Connection):
    assert queries.get_order("NOT-A-REAL-ORDER", conn=synthetic_db_connection) is None


def test_order_boolean_fields_are_real_booleans(synthetic_db_connection: sqlite3.Connection):
    order = queries.get_order("FIX-ORD-002", conn=synthetic_db_connection)
    assert order is not None
    assert order.carrier_fault is True
    assert order.customer_fault is False
    assert isinstance(order.carrier_fault, bool)
    assert isinstance(order.customer_fault, bool)


def test_list_orders_with_no_filter_returns_every_order(
    synthetic_db_connection: sqlite3.Connection,
):
    orders = queries.list_orders(conn=synthetic_db_connection)
    assert len(orders) == 3
    assert all(isinstance(o, Order) for o in orders)


def test_list_orders_filtered_by_account_has_no_cross_account_leakage(
    synthetic_db_connection: sqlite3.Connection,
):
    orders = queries.list_orders(account_id="FIX-ACCT-001", conn=synthetic_db_connection)

    assert len(orders) == 1
    assert orders[0].order_id == "FIX-ORD-001"
    assert all(o.account_id == "FIX-ACCT-001" for o in orders)


def test_list_orders_filtered_by_status(synthetic_db_connection: sqlite3.Connection):
    delivered = queries.list_orders(status="DELIVERED", conn=synthetic_db_connection)
    booked = queries.list_orders(status="BOOKED", conn=synthetic_db_connection)

    assert [o.order_id for o in delivered] == ["FIX-ORD-003"]
    assert {o.order_id for o in booked} == {"FIX-ORD-001", "FIX-ORD-002"}


def test_list_orders_filtered_by_account_and_status_combined(
    synthetic_db_connection: sqlite3.Connection,
):
    orders = queries.list_orders(
        account_id="FIX-ACCT-002", status="BOOKED", conn=synthetic_db_connection
    )
    assert [o.order_id for o in orders] == ["FIX-ORD-002"]


def test_list_orders_filter_matching_nothing_returns_empty_list(
    synthetic_db_connection: sqlite3.Connection,
):
    orders = queries.list_orders(
        account_id="FIX-ACCT-003", status="BOOKED", conn=synthetic_db_connection
    )
    assert orders == []


# ---------------------------------------------------------------------------
# tickets
# ---------------------------------------------------------------------------


def test_get_ticket_returns_typed_model(synthetic_db_connection: sqlite3.Connection):
    ticket = queries.get_ticket("FIX-TKT-002", conn=synthetic_db_connection)

    assert isinstance(ticket, Ticket)
    assert ticket.account_id == "FIX-ACCT-002"
    assert ticket.status == "closed"
    # This is the fixture's historical-resolution trap: present, but must
    # never be treated as authoritative by any code that consumes it later.
    assert ticket.historical_resolution is not None


def test_get_ticket_returns_none_for_unknown_id(synthetic_db_connection: sqlite3.Connection):
    assert queries.get_ticket("NOT-A-REAL-TICKET", conn=synthetic_db_connection) is None


def test_list_tickets_filtered_by_account_has_no_cross_account_leakage(
    synthetic_db_connection: sqlite3.Connection,
):
    tickets = queries.list_tickets(account_id="FIX-ACCT-001", conn=synthetic_db_connection)

    assert len(tickets) == 1
    assert tickets[0].ticket_id == "FIX-TKT-001"


def test_list_tickets_filtered_by_status(synthetic_db_connection: sqlite3.Connection):
    open_tickets = queries.list_tickets(status="open", conn=synthetic_db_connection)
    closed_tickets = queries.list_tickets(status="closed", conn=synthetic_db_connection)

    assert [t.ticket_id for t in open_tickets] == ["FIX-TKT-001"]
    assert [t.ticket_id for t in closed_tickets] == ["FIX-TKT-002"]


def test_list_tickets_with_no_rows_for_account_returns_empty_list(
    synthetic_db_connection: sqlite3.Connection,
):
    # FIX-ACCT-003 has orders but no tickets in the fixture.
    assert queries.list_tickets(account_id="FIX-ACCT-003", conn=synthetic_db_connection) == []


# ---------------------------------------------------------------------------
# connection-layer behavior
# ---------------------------------------------------------------------------


def test_default_connection_path_is_read_only(synthetic_db_path):
    """The query layer's own connections must be structurally incapable of
    writing, independent of any application-level convention — a bug in a
    future query function that attempted a write must fail loudly here."""
    with connect(synthetic_db_path) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO accounts (account_id, account_name, plan, status, premium_support) "
                "VALUES ('X', 'X', 'X', 'X', 0)"
            )


def test_queries_accept_an_externally_supplied_connection(synthetic_db_path):
    """Functions must work against a connection the caller opened and owns,
    not only the module's own default-path connection — needed by every
    later layer (rule engine, agent tools) that manages connection
    lifecycle itself."""
    conn = sqlite3.connect(synthetic_db_path)
    conn.row_factory = sqlite3.Row
    try:
        account = queries.get_account("FIX-ACCT-002", conn=conn)
    finally:
        conn.close()

    assert account is not None
    assert account.account_id == "FIX-ACCT-002"
