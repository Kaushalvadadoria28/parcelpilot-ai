"""Deterministic cancellation-eligibility rule.

Implements the order-status state machine and free-cancellation-window
math described in `docs/system-design.md` (Part F/H) and the assessment's
Cancellation & Service Credit SOP: DRAFT is always free; a BOOKED order is
free within a configured window of its booking time and incurs a fee after
that unless the account's contract waives it entirely; PICKED_UP and
DELIVERED orders cannot be cancelled through this rule at all.

This function is pure: every fact it needs is an explicit parameter, it
never queries a database, reads a config file, or calls the wall clock.
`reference_time` must be supplied by the caller — in production that will
be the dataset's own snapshot time (`backend.db.queries.get_dataset_meta`),
never the machine's running clock.
"""

from __future__ import annotations

from datetime import datetime

from backend.models import (
    CancellationDecision,
    CancellationOverride,
    CancellationResult,
    PolicyDefaults,
)


def check_cancellation_eligibility(
    *,
    order_status: str,
    booked_at: datetime,
    cancellation_requested_at: datetime | None,
    pickup_actual_at: datetime | None,
    reference_time: datetime,
    override: CancellationOverride | None,
    policy: PolicyDefaults,
) -> CancellationResult:
    if order_status == "DRAFT":
        return CancellationResult(
            decision=CancellationDecision.ALLOWED_NO_FEE,
            fee_inr=0.0,
            evidence=["Order status is DRAFT: cancellable at no charge under any circumstance."],
        )

    if order_status == "DELIVERED":
        return CancellationResult(
            decision=CancellationDecision.NOT_ALLOWED,
            evidence=["Order status is DELIVERED: cannot be cancelled."],
        )

    if order_status == "PICKED_UP":
        return CancellationResult(
            decision=CancellationDecision.NOT_ALLOWED,
            evidence=[
                "Order status is PICKED_UP: cannot be cancelled through this rule; "
                "a return-to-origin request is the applicable workflow instead."
            ],
        )

    if order_status != "BOOKED":
        return CancellationResult(
            decision=CancellationDecision.NEEDS_VERIFICATION,
            missing_fields=["order_status"],
            evidence=[
                f"Order status {order_status!r} is not one this rule engine recognizes "
                "(expected DRAFT, BOOKED, PICKED_UP, or DELIVERED)."
            ],
        )

    # order_status == "BOOKED" from here on.
    if pickup_actual_at is not None:
        return CancellationResult(
            decision=CancellationDecision.NEEDS_VERIFICATION,
            missing_fields=["order_status vs pickup_actual_at consistency"],
            evidence=[
                "Order status is BOOKED but a pickup_actual_at timestamp is already "
                "present — status and pickup records are inconsistent (this matches "
                "the shape of a delayed pickup-confirmation issue). Verify the actual "
                "carrier pickup status before deciding whether PICKED_UP or BOOKED "
                "rules apply."
            ],
        )

    request_time = (
        cancellation_requested_at if cancellation_requested_at is not None else reference_time
    )
    if request_time < booked_at:
        return CancellationResult(
            decision=CancellationDecision.NEEDS_VERIFICATION,
            missing_fields=["cancellation_requested_at"],
            evidence=[
                "The cancellation request (or reference) time is earlier than "
                "booked_at — these timestamps are inconsistent."
            ],
        )

    elapsed_minutes = (request_time - booked_at).total_seconds() / 60

    if override is not None and override.fee_waived:
        return CancellationResult(
            decision=CancellationDecision.ALLOWED_NO_FEE,
            fee_inr=0.0,
            evidence=[
                "This account's contract waives the cancellation fee for BOOKED "
                "shipments regardless of how long ago the shipment was booked."
            ],
        )

    if elapsed_minutes <= policy.cancellation_free_window_minutes:
        return CancellationResult(
            decision=CancellationDecision.ALLOWED_NO_FEE,
            fee_inr=0.0,
            evidence=[
                f"{elapsed_minutes:.0f} minute(s) elapsed since booking, within the "
                f"{policy.cancellation_free_window_minutes:.0f}-minute free-cancellation "
                "window."
            ],
        )

    return CancellationResult(
        decision=CancellationDecision.ALLOWED_WITH_FEE,
        fee_inr=policy.cancellation_fee_after_window_inr,
        evidence=[
            f"{elapsed_minutes:.0f} minute(s) elapsed since booking, past the "
            f"{policy.cancellation_free_window_minutes:.0f}-minute free-cancellation "
            f"window; a fee of INR {policy.cancellation_fee_after_window_inr:.2f} applies."
        ],
    )
