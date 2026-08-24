"""Typed domain models for the structured ParcelPilot data.

These mirror the SQLite schema produced by `backend/ingestion/build_db.py`
exactly (see that module for the authoritative column list). They are
immutable (`frozen=True`) because they represent an already-fetched
snapshot of a database row — nothing downstream should be able to mutate
one and have the change silently not persist anywhere.

Status fields (`Order.status`, `Ticket.status`, `Account.plan`) are kept as
plain `str` here rather than a strict enum, so that a substituted data pack
using a value this repository hasn't seen yet still loads instead of
failing at the data layer. Enum-like matching against the known values
belongs in the rule engine (Milestone 1, commit 2), which is the layer
that actually needs to reason about "is this a status my rules know how to
handle" and must surface an unknown status as uncertainty rather than a
crash.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Account(_Frozen):
    account_id: str
    account_name: str
    plan: str
    status: str
    csm: str | None = None
    contract_file: str | None = None
    premium_support: bool
    notes: str | None = None


class Order(_Frozen):
    order_id: str
    account_id: str
    carrier: str | None = None
    status: str
    booked_at: datetime
    pickup_window_start: datetime | None = None
    pickup_window_end: datetime | None = None
    pickup_actual_at: datetime | None = None
    shipment_fee_inr: float | None = None
    carrier_fault: bool
    customer_fault: bool
    cancellation_requested_at: datetime | None = None
    notes: str | None = None


class Ticket(_Frozen):
    ticket_id: str
    account_id: str
    created_at: datetime
    status: str
    subject: str | None = None
    description: str | None = None
    channel: str | None = None
    assigned_to: str | None = None
    last_customer_message_at: datetime | None = None
    historical_resolution: str | None = None


class DatasetMeta(_Frozen):
    """Mirrors the `dataset_meta` key/value table — the dataset's own
    declared reference time and related metadata, never the wall clock.
    """

    snapshot_time: datetime
    currency: str
    notes: str
    important: str
    source_workbook: str
