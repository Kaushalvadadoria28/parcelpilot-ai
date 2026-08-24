"""Deterministic failed-pickup service-credit rule.

Implements the eligibility and amount math from the assessment's
Cancellation & Service Credit SOP: a customer is eligible for a credit when
the pickup ran later than a configured delay threshold past the end of its
scheduled window, the carrier was at fault, and the customer was not.
Eligible credits are the lower of a configured cap or a percentage of the
shipment fee, unless a contract override replaces the threshold and/or
amount. Amounts above a configured threshold require manager approval.

This function is pure and never guesses: if the delay, carrier-fault, or
customer-fault facts are unknown (`None`), it returns
`CreditEligibility.NEEDS_VERIFICATION` with the specific missing fields
rather than assuming an answer either way. `reference_time` must be
supplied by the caller (the dataset's snapshot time in production, never
the wall clock) and is only used when the order hasn't been picked up yet.
"""

from __future__ import annotations

from datetime import datetime

from backend.models import CreditEligibility, CreditResult, PolicyDefaults, ServiceCreditOverride


def check_service_credit_eligibility(
    *,
    pickup_window_end: datetime | None,
    pickup_actual_at: datetime | None,
    carrier_fault: bool | None,
    customer_fault: bool | None,
    shipment_fee_inr: float | None,
    reference_time: datetime,
    override: ServiceCreditOverride | None,
    policy: PolicyDefaults,
) -> CreditResult:
    missing_fields: list[str] = []
    if pickup_window_end is None:
        missing_fields.append("pickup_window_end")
    if carrier_fault is None:
        missing_fields.append("carrier_fault")
    if customer_fault is None:
        missing_fields.append("customer_fault")

    if missing_fields:
        return CreditResult(
            eligibility=CreditEligibility.NEEDS_VERIFICATION,
            missing_fields=missing_fields,
            evidence=[
                "Carrier fault, pickup timing, and customer fault must all be known "
                "before a credit can be promised; do not guess when any of them is "
                "unknown."
            ],
        )

    # mypy/type-narrowing note: missing_fields is empty, so all three are non-None below.
    assert pickup_window_end is not None
    assert carrier_fault is not None
    assert customer_fault is not None

    if customer_fault:
        return CreditResult(
            eligibility=CreditEligibility.NOT_ELIGIBLE,
            evidence=["The customer was at fault (in whole or in part); no credit applies."],
        )

    if not carrier_fault:
        return CreditResult(
            eligibility=CreditEligibility.NOT_ELIGIBLE,
            evidence=["The carrier was not at fault; no credit applies."],
        )

    comparison_point = pickup_actual_at if pickup_actual_at is not None else reference_time
    delay = comparison_point - pickup_window_end
    delay_hours = delay.total_seconds() / 3600

    if delay_hours <= 0:
        return CreditResult(
            eligibility=CreditEligibility.NOT_ELIGIBLE,
            evidence=["The pickup window has not yet ended; there is no delay to credit."],
        )

    threshold_hours = (
        override.delay_threshold_hours
        if override is not None and override.delay_threshold_hours is not None
        else policy.credit_default_delay_threshold_hours
    )

    if delay_hours <= threshold_hours:
        return CreditResult(
            eligibility=CreditEligibility.NOT_ELIGIBLE,
            evidence=[
                f"Pickup was {delay_hours:.2f} hour(s) late, at or under the "
                f"{threshold_hours:.2f}-hour eligibility threshold."
            ],
        )

    mode = (
        override.credit_amount_mode
        if override is not None and override.credit_amount_mode is not None
        else "lower_of_cap_or_percent"
    )

    evidence = [
        f"Pickup was {delay_hours:.2f} hour(s) late due to carrier fault, past the "
        f"{threshold_hours:.2f}-hour eligibility threshold — eligible for a credit."
    ]

    if mode == "fixed":
        if override is None or override.credit_amount_inr is None:
            raise ValueError(
                "Contract override specifies credit_amount_mode='fixed' but no "
                "credit_amount_inr was configured — this is a configuration error, "
                "not a runtime data gap."
            )
        amount = override.credit_amount_inr
        evidence.append(f"Credit amount is a fixed INR {amount:.2f} per this account's contract.")
    else:
        if shipment_fee_inr is None:
            return CreditResult(
                eligibility=CreditEligibility.NEEDS_VERIFICATION,
                missing_fields=["shipment_fee_inr"],
                evidence=[
                    *evidence,
                    "Credit amount is the lower of a cap or a percentage of the "
                    "shipment fee, but the shipment fee is unknown.",
                ],
            )
        cap = (
            override.credit_cap_inr
            if override is not None and override.credit_cap_inr is not None
            else policy.credit_default_cap_inr
        )
        percent = (
            override.credit_percent
            if override is not None and override.credit_percent is not None
            else policy.credit_default_percent
        )
        percent_amount = shipment_fee_inr * percent / 100
        amount = min(cap, percent_amount)
        evidence.append(
            f"Credit amount is the lower of INR {cap:.2f} or {percent:g}% of the "
            f"INR {shipment_fee_inr:.2f} shipment fee (INR {percent_amount:.2f}) = "
            f"INR {amount:.2f}."
        )

    requires_manager_approval = amount > policy.credit_manager_approval_threshold_inr
    if requires_manager_approval:
        evidence.append(
            f"INR {amount:.2f} exceeds the INR "
            f"{policy.credit_manager_approval_threshold_inr:.2f} manager-approval "
            "threshold; manager approval is required before issuing this credit."
        )

    monthly_aggregate_cap_inr = override.monthly_aggregate_cap_inr if override is not None else None
    if monthly_aggregate_cap_inr is not None:
        evidence.append(
            f"This account's contract also caps monthly aggregate credits at INR "
            f"{monthly_aggregate_cap_inr:.2f}; this system does not track a running "
            "monthly total, so verify against credits already issued this month "
            "before approving."
        )

    return CreditResult(
        eligibility=CreditEligibility.ELIGIBLE,
        amount_inr=amount,
        requires_manager_approval=requires_manager_approval,
        monthly_aggregate_cap_inr=monthly_aggregate_cap_inr,
        evidence=evidence,
    )
