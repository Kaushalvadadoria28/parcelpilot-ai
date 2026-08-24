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

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


# ---------------------------------------------------------------------------
# Resolved policy configuration (Milestone 1, commit 2)
#
# These types are the *output* of the configuration loaders in
# backend/rules/policy_defaults.py and backend/rules/contract_overrides.py.
# The pure rule functions in backend/rules/{cancellation,service_credit,sla}.py
# take already-resolved instances of these as explicit parameters — they
# never read a YAML file themselves. See docs/git-development-plan.md §2 for
# why the real numbers live in a gitignored config file rather than here.
# ---------------------------------------------------------------------------


class SlaTarget(_Frozen):
    """A single first-response target, e.g. "30 minutes" or "1 business day".

    `is_business_time` records whether the source policy phrased this as a
    business-hours/business-day target. None of the supplied policy
    documents define what a "business hour" actually spans (which hours,
    which days, which holidays), so this rule engine treats the *magnitude*
    as continuous calendar time for elapsed-time arithmetic and instead
    surfaces the flag as an explicit assumption in `SlaResult.assumptions`
    — it does not silently pretend the calculation is exact.
    """

    amount: float
    unit: Literal["minutes", "hours", "days"]
    is_business_time: bool

    def to_timedelta(self) -> timedelta:
        if self.unit == "minutes":
            return timedelta(minutes=self.amount)
        if self.unit == "hours":
            return timedelta(hours=self.amount)
        return timedelta(days=self.amount)

    def describe(self) -> str:
        unit_label = self.unit if self.amount != 1 else self.unit[:-1]
        qualifier = "business " if self.is_business_time else ""
        return f"{self.amount:g} {qualifier}{unit_label}"


class PolicyDefaults(_Frozen):
    """Resolved, non-contract-specific policy thresholds.

    Loaded from `config/policy_defaults.yaml` (real, gitignored) or
    `config/policy_defaults.example.yaml` (fictitious, public) by
    `backend/rules/policy_defaults.py`.
    """

    sla_targets: dict[str, dict[str, SlaTarget]]  # plan -> severity -> target
    cancellation_free_window_minutes: float
    cancellation_fee_after_window_inr: float
    credit_default_delay_threshold_hours: float
    credit_default_cap_inr: float
    credit_default_percent: float
    credit_manager_approval_threshold_inr: float


class CancellationOverride(_Frozen):
    fee_waived: bool


class ServiceCreditOverride(_Frozen):
    delay_threshold_hours: float | None = None
    credit_amount_mode: Literal["fixed", "lower_of_cap_or_percent"] | None = None
    credit_amount_inr: float | None = None
    credit_cap_inr: float | None = None
    credit_percent: float | None = None
    # Informational only — this rule engine has no credit-issuance ledger to
    # enforce a running monthly total against (see docs/system-design.md's
    # risk register). Surfaced in CreditResult so a caller can flag it for
    # manual verification rather than pretending it's been checked.
    monthly_aggregate_cap_inr: float | None = None


class SlaOverride(_Frozen):
    """A contract's SLA targets. May be partial — a severity missing from
    `targets` falls back to the plan default for that severity."""

    targets: dict[str, SlaTarget]  # severity -> target


class AccountContractOverrides(_Frozen):
    account_id: str
    cancellation: CancellationOverride | None = None
    service_credit: ServiceCreditOverride | None = None
    sla: SlaOverride | None = None


# ---------------------------------------------------------------------------
# Rule-engine results
# ---------------------------------------------------------------------------


class CancellationDecision(StrEnum):
    ALLOWED_NO_FEE = "allowed_no_fee"
    ALLOWED_WITH_FEE = "allowed_with_fee"
    NOT_ALLOWED = "not_allowed"
    NEEDS_VERIFICATION = "needs_verification"


class CancellationResult(_Frozen):
    decision: CancellationDecision
    fee_inr: float | None = None
    missing_fields: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class CreditEligibility(StrEnum):
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    NEEDS_VERIFICATION = "needs_verification"


class CreditResult(_Frozen):
    eligibility: CreditEligibility
    amount_inr: float | None = None
    requires_manager_approval: bool = False
    monthly_aggregate_cap_inr: float | None = None
    missing_fields: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class SeverityConfidence(StrEnum):
    """How the ticket severity fed into `check_sla_status` was determined.

    Severity is not a stored field anywhere in the dataset — it must always
    be inferred (today, by a human or, from Milestone 5 onward, an LLM
    reading the ticket description against the policy's P1/P2/P3
    definitions). This enum exists so that inferred severity is never
    silently treated as equivalent to an explicitly stated fact.
    """

    EXPLICIT = "explicit"
    INFERRED = "inferred"
    UNRESOLVED = "unresolved"


class SlaBreachStatus(StrEnum):
    WITHIN_TARGET = "within_target"
    AT_TARGET = "at_target"
    BREACHED = "breached"
    UNKNOWN = "unknown"


class SlaResult(_Frozen):
    severity: str | None = None
    severity_confidence: SeverityConfidence
    target: SlaTarget | None = None
    elapsed: timedelta | None = None
    breach_status: SlaBreachStatus
    assumptions: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
