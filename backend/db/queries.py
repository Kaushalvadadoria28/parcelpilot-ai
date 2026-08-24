"""Read-only query functions over the ingested SQLite database.

This is a trusted/internal layer for Milestone 1: every function here
returns whatever rows match its arguments, with no account- or role-based
scoping. Milestone 2 wraps these functions in a Principal-scoped layer
rather than modifying them in place, so authorization is added, not
retrofitted, on top of a data layer that is already correct.

Every function accepts an optional `conn`. When omitted, a fresh read-only
connection is opened and closed around the call (see
`backend/db/connection.py`); tests and callers that want to reuse one
connection across several calls pass their own.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from backend.db.connection import connect
from backend.models import Account, DatasetMeta, DocChunk, Order, Ticket


@contextmanager
def _connection_or(
    conn: sqlite3.Connection | None, db_path: Path | None = None
) -> Iterator[sqlite3.Connection]:
    if conn is not None:
        yield conn
    else:
        with connect(db_path) as owned:
            yield owned


def _row_to_account(row: sqlite3.Row) -> Account:
    return Account(
        account_id=row["account_id"],
        account_name=row["account_name"],
        plan=row["plan"],
        status=row["status"],
        csm=row["csm"],
        contract_file=row["contract_file"],
        premium_support=bool(row["premium_support"]),
        notes=row["notes"],
    )


def _row_to_order(row: sqlite3.Row) -> Order:
    return Order(
        order_id=row["order_id"],
        account_id=row["account_id"],
        carrier=row["carrier"],
        status=row["status"],
        booked_at=row["booked_at"],
        pickup_window_start=row["pickup_window_start"],
        pickup_window_end=row["pickup_window_end"],
        pickup_actual_at=row["pickup_actual_at"],
        shipment_fee_inr=row["shipment_fee_inr"],
        carrier_fault=bool(row["carrier_fault"]),
        customer_fault=bool(row["customer_fault"]),
        cancellation_requested_at=row["cancellation_requested_at"],
        notes=row["notes"],
    )


def _row_to_ticket(row: sqlite3.Row) -> Ticket:
    return Ticket(
        ticket_id=row["ticket_id"],
        account_id=row["account_id"],
        created_at=row["created_at"],
        status=row["status"],
        subject=row["subject"],
        description=row["description"],
        channel=row["channel"],
        assigned_to=row["assigned_to"],
        last_customer_message_at=row["last_customer_message_at"],
        historical_resolution=row["historical_resolution"],
    )


def _row_to_doc_chunk(row: sqlite3.Row) -> DocChunk:
    return DocChunk(
        chunk_id=row["chunk_id"],
        source_file=row["source_file"],
        document_type=row["document_type"],
        version=row["version"],
        status=row["status"],
        effective_date=row["effective_date"],
        customer_account_id=row["customer_account_id"],
        authority_tier=row["authority_tier"],
        superseded_by=row["superseded_by"],
        section=row["section"],
        page=row["page"],
        content=row["content"],
    )


# ---------------------------------------------------------------------------
# dataset_meta
# ---------------------------------------------------------------------------


def get_dataset_meta(*, conn: sqlite3.Connection | None = None) -> DatasetMeta:
    """Return the dataset's own declared metadata, including its reference
    "now" (`snapshot_time`). Callers needing "the current time" for a
    calculation should get it from here, never from the system clock.
    """
    with _connection_or(conn) as c:
        rows = c.execute("SELECT key, value FROM dataset_meta").fetchall()
    values = {row["key"]: row["value"] for row in rows}
    return DatasetMeta(
        snapshot_time=values["snapshot_time"],
        currency=values["currency"],
        notes=values["notes"],
        important=values["important"],
        source_workbook=values["source_workbook"],
    )


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------


def get_account(account_id: str, *, conn: sqlite3.Connection | None = None) -> Account | None:
    with _connection_or(conn) as c:
        row = c.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
    return _row_to_account(row) if row is not None else None


def list_accounts(*, conn: sqlite3.Connection | None = None) -> list[Account]:
    with _connection_or(conn) as c:
        rows = c.execute("SELECT * FROM accounts ORDER BY account_id").fetchall()
    return [_row_to_account(row) for row in rows]


# ---------------------------------------------------------------------------
# orders
# ---------------------------------------------------------------------------


def get_order(order_id: str, *, conn: sqlite3.Connection | None = None) -> Order | None:
    with _connection_or(conn) as c:
        row = c.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    return _row_to_order(row) if row is not None else None


def list_orders(
    *,
    account_id: str | None = None,
    status: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[Order]:
    query = "SELECT * FROM orders WHERE 1=1"
    params: list[str] = []
    if account_id is not None:
        query += " AND account_id = ?"
        params.append(account_id)
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY order_id"

    with _connection_or(conn) as c:
        rows = c.execute(query, params).fetchall()
    return [_row_to_order(row) for row in rows]


# ---------------------------------------------------------------------------
# tickets
# ---------------------------------------------------------------------------


def get_ticket(ticket_id: str, *, conn: sqlite3.Connection | None = None) -> Ticket | None:
    with _connection_or(conn) as c:
        row = c.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
    return _row_to_ticket(row) if row is not None else None


def list_tickets(
    *,
    account_id: str | None = None,
    status: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[Ticket]:
    query = "SELECT * FROM tickets WHERE 1=1"
    params: list[str] = []
    if account_id is not None:
        query += " AND account_id = ?"
        params.append(account_id)
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY ticket_id"

    with _connection_or(conn) as c:
        rows = c.execute(query, params).fetchall()
    return [_row_to_ticket(row) for row in rows]


# ---------------------------------------------------------------------------
# doc_chunks
# ---------------------------------------------------------------------------


def get_doc_chunk(chunk_id: int, *, conn: sqlite3.Connection | None = None) -> DocChunk | None:
    with _connection_or(conn) as c:
        row = c.execute("SELECT * FROM doc_chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
    return _row_to_doc_chunk(row) if row is not None else None


def list_doc_chunks(
    *,
    customer_account_id: str | None = None,
    status: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[DocChunk]:
    """List document chunks, optionally filtered by an exact
    `customer_account_id` match. This is a plain filter, not an
    authorization decision: it does not know that `None` should also mean
    "visible to everyone" — that unioning of general-plus-one-account
    visibility is Milestone 2's job (backend/auth/authorize.py), not this
    trusted/unscoped layer's.
    """
    query = "SELECT * FROM doc_chunks WHERE 1=1"
    params: list[str] = []
    if customer_account_id is not None:
        query += " AND customer_account_id = ?"
        params.append(customer_account_id)
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY chunk_id"

    with _connection_or(conn) as c:
        rows = c.execute(query, params).fetchall()
    return [_row_to_doc_chunk(row) for row in rows]
