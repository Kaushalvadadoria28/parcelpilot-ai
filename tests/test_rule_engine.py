"""Tests for the deterministic rule engine (backend/rules/{cancellation,
service_credit,sla}.py).

Every test here calls the pure rule functions directly — no LLM, no agent,
no database required for the vast majority of cases. All fixture values
are fictitious (see tests/fixtures/policy_fixtures.py) and never coincide
with the real assessment pack's numbers; boundary tests compute their
boundaries symbolically from the fixture's own configured thresholds
(`fixture_policy_defaults.cancellation_free_window_minutes`, etc.) rather
than hardcoding any literal that could be mistaken for a real one.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from backend.db import queries
from backend.models import (
    CancellationDecision,
    CancellationOverride,
    CreditEligibility,
    ServiceCreditOverride,
    SeverityConfidence,
    SlaBreachStatus,
    SlaTarget,
)
from backend.rules import cancellation as cancellation_module
from backend.rules import service_credit as service_credit_module
from backend.rules import sla as sla_module
from backend.rules.cancellation import check_cancellation_eligibility
from backend.rules.service_credit import check_service_credit_eligibility
from backend.rules.sla import check_sla_status

REFERENCE_TIME = datetime(2027, 1, 10, 9, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


class TestCancellationEligibility:
    def test_draft_is_always_free_regardless_of_timestamps(self, fixture_policy_defaults):
        result = check_cancellation_eligibility(
            order_status="DRAFT",
            booked_at=REFERENCE_TIME - timedelta(days=100),
            cancellation_requested_at=None,
            pickup_actual_at=None,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.decision == CancellationDecision.ALLOWED_NO_FEE
        assert result.fee_inr == 0.0

    def test_delivered_cannot_be_cancelled(self, fixture_policy_defaults):
        result = check_cancellation_eligibility(
            order_status="DELIVERED",
            booked_at=REFERENCE_TIME - timedelta(days=1),
            cancellation_requested_at=None,
            pickup_actual_at=REFERENCE_TIME - timedelta(hours=1),
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.decision == CancellationDecision.NOT_ALLOWED

    def test_picked_up_cannot_be_cancelled_through_this_rule(self, fixture_policy_defaults):
        result = check_cancellation_eligibility(
            order_status="PICKED_UP",
            booked_at=REFERENCE_TIME - timedelta(hours=2),
            cancellation_requested_at=None,
            pickup_actual_at=REFERENCE_TIME - timedelta(hours=1),
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.decision == CancellationDecision.NOT_ALLOWED

    def test_unknown_status_needs_verification_not_an_invented_decision(
        self, fixture_policy_defaults
    ):
        result = check_cancellation_eligibility(
            order_status="SOME_FUTURE_STATUS",
            booked_at=REFERENCE_TIME - timedelta(hours=1),
            cancellation_requested_at=None,
            pickup_actual_at=None,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.decision == CancellationDecision.NEEDS_VERIFICATION
        assert "order_status" in result.missing_fields

    def test_booked_with_pickup_actual_at_is_inconsistent(self, fixture_policy_defaults):
        result = check_cancellation_eligibility(
            order_status="BOOKED",
            booked_at=REFERENCE_TIME - timedelta(hours=2),
            cancellation_requested_at=None,
            pickup_actual_at=REFERENCE_TIME - timedelta(minutes=10),
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.decision == CancellationDecision.NEEDS_VERIFICATION

    def test_request_before_booking_is_inconsistent(self, fixture_policy_defaults):
        booked_at = REFERENCE_TIME
        result = check_cancellation_eligibility(
            order_status="BOOKED",
            booked_at=booked_at,
            cancellation_requested_at=booked_at - timedelta(minutes=5),
            pickup_actual_at=None,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.decision == CancellationDecision.NEEDS_VERIFICATION
        assert "cancellation_requested_at" in result.missing_fields

    def test_booked_within_free_window_is_free(self, fixture_policy_defaults):
        booked_at = REFERENCE_TIME
        window = timedelta(minutes=fixture_policy_defaults.cancellation_free_window_minutes)
        result = check_cancellation_eligibility(
            order_status="BOOKED",
            booked_at=booked_at,
            cancellation_requested_at=booked_at + window / 2,
            pickup_actual_at=None,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.decision == CancellationDecision.ALLOWED_NO_FEE
        assert result.fee_inr == 0.0

    def test_booked_exactly_at_free_window_boundary_is_still_free(self, fixture_policy_defaults):
        booked_at = REFERENCE_TIME
        window = timedelta(minutes=fixture_policy_defaults.cancellation_free_window_minutes)
        result = check_cancellation_eligibility(
            order_status="BOOKED",
            booked_at=booked_at,
            cancellation_requested_at=booked_at + window,
            pickup_actual_at=None,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.decision == CancellationDecision.ALLOWED_NO_FEE

    def test_booked_just_past_free_window_incurs_fee(self, fixture_policy_defaults):
        booked_at = REFERENCE_TIME
        window = timedelta(minutes=fixture_policy_defaults.cancellation_free_window_minutes)
        result = check_cancellation_eligibility(
            order_status="BOOKED",
            booked_at=booked_at,
            cancellation_requested_at=booked_at + window + timedelta(minutes=1),
            pickup_actual_at=None,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.decision == CancellationDecision.ALLOWED_WITH_FEE
        assert result.fee_inr == fixture_policy_defaults.cancellation_fee_after_window_inr

    def test_contract_waiver_overrides_fee_even_long_after_window(self, fixture_policy_defaults):
        booked_at = REFERENCE_TIME
        result = check_cancellation_eligibility(
            order_status="BOOKED",
            booked_at=booked_at,
            cancellation_requested_at=booked_at + timedelta(days=3),
            pickup_actual_at=None,
            reference_time=REFERENCE_TIME,
            override=CancellationOverride(fee_waived=True),
            policy=fixture_policy_defaults,
        )
        assert result.decision == CancellationDecision.ALLOWED_NO_FEE
        assert result.fee_inr == 0.0

    def test_explicit_non_waiving_override_still_applies_default_fee_logic(
        self, fixture_policy_defaults
    ):
        booked_at = REFERENCE_TIME
        window = timedelta(minutes=fixture_policy_defaults.cancellation_free_window_minutes)
        result = check_cancellation_eligibility(
            order_status="BOOKED",
            booked_at=booked_at,
            cancellation_requested_at=booked_at + window + timedelta(minutes=1),
            pickup_actual_at=None,
            reference_time=REFERENCE_TIME,
            override=CancellationOverride(fee_waived=False),
            policy=fixture_policy_defaults,
        )
        assert result.decision == CancellationDecision.ALLOWED_WITH_FEE

    def test_no_cancellation_requested_at_uses_reference_time(self, fixture_policy_defaults):
        window = timedelta(minutes=fixture_policy_defaults.cancellation_free_window_minutes)
        booked_at = REFERENCE_TIME - (window + timedelta(minutes=5))
        result = check_cancellation_eligibility(
            order_status="BOOKED",
            booked_at=booked_at,
            cancellation_requested_at=None,
            pickup_actual_at=None,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        # reference_time is 5 minutes past the free window measured from booked_at.
        assert result.decision == CancellationDecision.ALLOWED_WITH_FEE

    @pytest.mark.parametrize("configured_window_minutes", [5, 999])
    def test_changing_policy_config_changes_the_result_without_changing_code(
        self, configured_window_minutes, fixture_policy_defaults
    ):
        policy = fixture_policy_defaults.model_copy(
            update={"cancellation_free_window_minutes": configured_window_minutes}
        )
        booked_at = REFERENCE_TIME
        arbitrary_elapsed = timedelta(minutes=37)
        result = check_cancellation_eligibility(
            order_status="BOOKED",
            booked_at=booked_at,
            cancellation_requested_at=booked_at + arbitrary_elapsed,
            pickup_actual_at=None,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=policy,
        )
        if arbitrary_elapsed <= timedelta(minutes=configured_window_minutes):
            assert result.decision == CancellationDecision.ALLOWED_NO_FEE
        else:
            assert result.decision == CancellationDecision.ALLOWED_WITH_FEE


# ---------------------------------------------------------------------------
# Service credit
# ---------------------------------------------------------------------------


class TestServiceCreditEligibility:
    def test_missing_pickup_window_end_needs_verification(self, fixture_policy_defaults):
        result = check_service_credit_eligibility(
            pickup_window_end=None,
            pickup_actual_at=None,
            carrier_fault=True,
            customer_fault=False,
            shipment_fee_inr=1000.0,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.eligibility == CreditEligibility.NEEDS_VERIFICATION
        assert "pickup_window_end" in result.missing_fields

    def test_missing_carrier_fault_needs_verification(self, fixture_policy_defaults):
        result = check_service_credit_eligibility(
            pickup_window_end=REFERENCE_TIME - timedelta(hours=5),
            pickup_actual_at=None,
            carrier_fault=None,
            customer_fault=False,
            shipment_fee_inr=1000.0,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.eligibility == CreditEligibility.NEEDS_VERIFICATION
        assert "carrier_fault" in result.missing_fields

    def test_missing_customer_fault_needs_verification(self, fixture_policy_defaults):
        result = check_service_credit_eligibility(
            pickup_window_end=REFERENCE_TIME - timedelta(hours=5),
            pickup_actual_at=None,
            carrier_fault=True,
            customer_fault=None,
            shipment_fee_inr=1000.0,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.eligibility == CreditEligibility.NEEDS_VERIFICATION
        assert "customer_fault" in result.missing_fields

    def test_all_unknown_fields_are_all_reported_together(self, fixture_policy_defaults):
        result = check_service_credit_eligibility(
            pickup_window_end=None,
            pickup_actual_at=None,
            carrier_fault=None,
            customer_fault=None,
            shipment_fee_inr=None,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert set(result.missing_fields) == {
            "pickup_window_end",
            "carrier_fault",
            "customer_fault",
        }

    def test_customer_fault_disqualifies_regardless_of_carrier_fault(self, fixture_policy_defaults):
        result = check_service_credit_eligibility(
            pickup_window_end=REFERENCE_TIME - timedelta(hours=10),
            pickup_actual_at=REFERENCE_TIME,
            carrier_fault=True,
            customer_fault=True,
            shipment_fee_inr=1000.0,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.eligibility == CreditEligibility.NOT_ELIGIBLE

    def test_no_carrier_fault_is_not_eligible(self, fixture_policy_defaults):
        result = check_service_credit_eligibility(
            pickup_window_end=REFERENCE_TIME - timedelta(hours=10),
            pickup_actual_at=REFERENCE_TIME,
            carrier_fault=False,
            customer_fault=False,
            shipment_fee_inr=1000.0,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.eligibility == CreditEligibility.NOT_ELIGIBLE

    def test_pickup_window_not_yet_ended_is_not_eligible(self, fixture_policy_defaults):
        result = check_service_credit_eligibility(
            pickup_window_end=REFERENCE_TIME + timedelta(hours=1),
            pickup_actual_at=None,
            carrier_fault=True,
            customer_fault=False,
            shipment_fee_inr=1000.0,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.eligibility == CreditEligibility.NOT_ELIGIBLE

    def test_delay_exactly_at_threshold_boundary_is_not_yet_eligible(self, fixture_policy_defaults):
        threshold = timedelta(hours=fixture_policy_defaults.credit_default_delay_threshold_hours)
        result = check_service_credit_eligibility(
            pickup_window_end=REFERENCE_TIME - threshold,
            pickup_actual_at=REFERENCE_TIME,
            carrier_fault=True,
            customer_fault=False,
            shipment_fee_inr=1000.0,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.eligibility == CreditEligibility.NOT_ELIGIBLE

    def test_delay_just_past_threshold_is_eligible_with_default_amount(
        self, fixture_policy_defaults
    ):
        threshold = timedelta(hours=fixture_policy_defaults.credit_default_delay_threshold_hours)
        fee = 1000.0
        result = check_service_credit_eligibility(
            pickup_window_end=REFERENCE_TIME - threshold - timedelta(minutes=1),
            pickup_actual_at=REFERENCE_TIME,
            carrier_fault=True,
            customer_fault=False,
            shipment_fee_inr=fee,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.eligibility == CreditEligibility.ELIGIBLE
        expected = min(
            fixture_policy_defaults.credit_default_cap_inr,
            fee * fixture_policy_defaults.credit_default_percent / 100,
        )
        assert result.amount_inr == pytest.approx(expected)

    def test_eligible_but_missing_shipment_fee_needs_verification(self, fixture_policy_defaults):
        threshold = timedelta(hours=fixture_policy_defaults.credit_default_delay_threshold_hours)
        result = check_service_credit_eligibility(
            pickup_window_end=REFERENCE_TIME - threshold - timedelta(minutes=1),
            pickup_actual_at=REFERENCE_TIME,
            carrier_fault=True,
            customer_fault=False,
            shipment_fee_inr=None,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.eligibility == CreditEligibility.NEEDS_VERIFICATION
        assert "shipment_fee_inr" in result.missing_fields

    def test_contract_threshold_override_changes_eligibility(
        self, fixture_policy_defaults, fixture_contract_overrides
    ):
        override = fixture_contract_overrides["FIX-ACCT-002"].service_credit
        assert override is not None and override.delay_threshold_hours is not None
        default_threshold = timedelta(
            hours=fixture_policy_defaults.credit_default_delay_threshold_hours
        )
        override_threshold = timedelta(hours=override.delay_threshold_hours)
        assert (
            override_threshold > default_threshold
        )  # sanity: override is genuinely tighter/looser

        window_end = REFERENCE_TIME - default_threshold - timedelta(minutes=1)
        common_kwargs = dict(
            pickup_window_end=window_end,
            pickup_actual_at=REFERENCE_TIME,
            carrier_fault=True,
            customer_fault=False,
            shipment_fee_inr=1000.0,
            reference_time=REFERENCE_TIME,
            policy=fixture_policy_defaults,
        )
        without_override = check_service_credit_eligibility(override=None, **common_kwargs)
        with_override = check_service_credit_eligibility(override=override, **common_kwargs)

        assert without_override.eligibility == CreditEligibility.ELIGIBLE
        assert with_override.eligibility == CreditEligibility.NOT_ELIGIBLE

    def test_contract_fixed_amount_override_ignores_shipment_fee(
        self, fixture_policy_defaults, fixture_contract_overrides
    ):
        override = fixture_contract_overrides["FIX-ACCT-002"].service_credit
        assert override is not None and override.delay_threshold_hours is not None
        window_end = (
            REFERENCE_TIME - timedelta(hours=override.delay_threshold_hours) - timedelta(minutes=1)
        )
        result = check_service_credit_eligibility(
            pickup_window_end=window_end,
            pickup_actual_at=REFERENCE_TIME,
            carrier_fault=True,
            customer_fault=False,
            shipment_fee_inr=None,  # deliberately unknown — must not matter in fixed mode
            reference_time=REFERENCE_TIME,
            override=override,
            policy=fixture_policy_defaults,
        )
        assert result.eligibility == CreditEligibility.ELIGIBLE
        assert result.amount_inr == override.credit_amount_inr

    def test_fixed_mode_without_amount_configured_is_a_config_error(self, fixture_policy_defaults):
        bad_override = ServiceCreditOverride(credit_amount_mode="fixed", credit_amount_inr=None)
        threshold = timedelta(hours=fixture_policy_defaults.credit_default_delay_threshold_hours)
        with pytest.raises(ValueError):
            check_service_credit_eligibility(
                pickup_window_end=REFERENCE_TIME - threshold - timedelta(minutes=1),
                pickup_actual_at=REFERENCE_TIME,
                carrier_fault=True,
                customer_fault=False,
                shipment_fee_inr=1000.0,
                reference_time=REFERENCE_TIME,
                override=bad_override,
                policy=fixture_policy_defaults,
            )

    def test_amount_at_manager_approval_threshold_does_not_require_approval(
        self, fixture_policy_defaults
    ):
        threshold_inr = fixture_policy_defaults.credit_manager_approval_threshold_inr
        override = ServiceCreditOverride(
            credit_amount_mode="fixed", credit_amount_inr=threshold_inr
        )
        threshold_hours = timedelta(
            hours=fixture_policy_defaults.credit_default_delay_threshold_hours
        )
        result = check_service_credit_eligibility(
            pickup_window_end=REFERENCE_TIME - threshold_hours - timedelta(minutes=1),
            pickup_actual_at=REFERENCE_TIME,
            carrier_fault=True,
            customer_fault=False,
            shipment_fee_inr=None,
            reference_time=REFERENCE_TIME,
            override=override,
            policy=fixture_policy_defaults,
        )
        assert result.amount_inr == threshold_inr
        assert result.requires_manager_approval is False

    def test_amount_just_above_manager_approval_threshold_requires_approval(
        self, fixture_policy_defaults
    ):
        threshold_inr = fixture_policy_defaults.credit_manager_approval_threshold_inr
        override = ServiceCreditOverride(
            credit_amount_mode="fixed", credit_amount_inr=threshold_inr + 1
        )
        threshold_hours = timedelta(
            hours=fixture_policy_defaults.credit_default_delay_threshold_hours
        )
        result = check_service_credit_eligibility(
            pickup_window_end=REFERENCE_TIME - threshold_hours - timedelta(minutes=1),
            pickup_actual_at=REFERENCE_TIME,
            carrier_fault=True,
            customer_fault=False,
            shipment_fee_inr=None,
            reference_time=REFERENCE_TIME,
            override=override,
            policy=fixture_policy_defaults,
        )
        assert result.requires_manager_approval is True

    def test_monthly_aggregate_cap_is_surfaced_but_not_enforced(self, fixture_policy_defaults):
        override = ServiceCreditOverride(monthly_aggregate_cap_inr=12345.0)
        threshold_hours = timedelta(
            hours=fixture_policy_defaults.credit_default_delay_threshold_hours
        )
        result = check_service_credit_eligibility(
            pickup_window_end=REFERENCE_TIME - threshold_hours - timedelta(minutes=1),
            pickup_actual_at=REFERENCE_TIME,
            carrier_fault=True,
            customer_fault=False,
            shipment_fee_inr=1000.0,
            reference_time=REFERENCE_TIME,
            override=override,
            policy=fixture_policy_defaults,
        )
        assert result.monthly_aggregate_cap_inr == 12345.0
        assert any("12345" in evidence_line for evidence_line in result.evidence)

    def test_no_pickup_actual_at_uses_reference_time_as_comparison_point(
        self, fixture_policy_defaults
    ):
        threshold = timedelta(hours=fixture_policy_defaults.credit_default_delay_threshold_hours)
        result = check_service_credit_eligibility(
            pickup_window_end=REFERENCE_TIME - threshold - timedelta(minutes=1),
            pickup_actual_at=None,
            carrier_fault=True,
            customer_fault=False,
            shipment_fee_inr=1000.0,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.eligibility == CreditEligibility.ELIGIBLE


# ---------------------------------------------------------------------------
# SLA
# ---------------------------------------------------------------------------


class TestSlaStatus:
    def test_unresolved_severity_is_unknown_not_guessed(self, fixture_policy_defaults):
        result = check_sla_status(
            plan="Enterprise",
            severity=None,
            severity_confidence=SeverityConfidence.UNRESOLVED,
            created_at=REFERENCE_TIME - timedelta(hours=1),
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.breach_status == SlaBreachStatus.UNKNOWN
        assert result.severity_confidence == SeverityConfidence.UNRESOLVED
        assert "severity" in result.missing_fields

    def test_none_severity_with_explicit_confidence_still_returns_unknown_not_a_crash(
        self, fixture_policy_defaults
    ):
        result = check_sla_status(
            plan="Enterprise",
            severity=None,
            severity_confidence=SeverityConfidence.EXPLICIT,
            created_at=REFERENCE_TIME - timedelta(hours=1),
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.breach_status == SlaBreachStatus.UNKNOWN

    def test_explicit_severity_within_target(self, fixture_policy_defaults):
        target = fixture_policy_defaults.sla_targets["Enterprise"]["P1"]
        created_at = REFERENCE_TIME - (target.to_timedelta() / 2)
        result = check_sla_status(
            plan="Enterprise",
            severity="P1",
            severity_confidence=SeverityConfidence.EXPLICIT,
            created_at=created_at,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.breach_status == SlaBreachStatus.WITHIN_TARGET
        assert result.target == target

    def test_exactly_at_target_boundary(self, fixture_policy_defaults):
        target = fixture_policy_defaults.sla_targets["Enterprise"]["P1"]
        created_at = REFERENCE_TIME - target.to_timedelta()
        result = check_sla_status(
            plan="Enterprise",
            severity="P1",
            severity_confidence=SeverityConfidence.EXPLICIT,
            created_at=created_at,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.breach_status == SlaBreachStatus.AT_TARGET

    def test_past_target_is_breached(self, fixture_policy_defaults):
        target = fixture_policy_defaults.sla_targets["Enterprise"]["P1"]
        created_at = REFERENCE_TIME - target.to_timedelta() - timedelta(minutes=1)
        result = check_sla_status(
            plan="Enterprise",
            severity="P1",
            severity_confidence=SeverityConfidence.EXPLICIT,
            created_at=created_at,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.breach_status == SlaBreachStatus.BREACHED

    def test_inferred_severity_is_labeled_not_silently_authoritative(self, fixture_policy_defaults):
        target = fixture_policy_defaults.sla_targets["Enterprise"]["P1"]
        created_at = REFERENCE_TIME - (target.to_timedelta() / 2)
        result = check_sla_status(
            plan="Enterprise",
            severity="P1",
            severity_confidence=SeverityConfidence.INFERRED,
            created_at=created_at,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.severity_confidence == SeverityConfidence.INFERRED
        assert any("inferred" in line.lower() for line in result.evidence)

    def test_contract_override_target_takes_precedence_over_plan_default(
        self, fixture_policy_defaults, fixture_contract_overrides
    ):
        override = fixture_contract_overrides["FIX-ACCT-001"].sla
        assert override is not None
        override_target = override.targets["P1"]
        plan_target = fixture_policy_defaults.sla_targets["Enterprise"]["P1"]
        assert override_target != plan_target  # sanity: the override actually differs

        created_at = REFERENCE_TIME - override_target.to_timedelta() - timedelta(minutes=1)
        result = check_sla_status(
            plan="Enterprise",
            severity="P1",
            severity_confidence=SeverityConfidence.EXPLICIT,
            created_at=created_at,
            reference_time=REFERENCE_TIME,
            override=override,
            policy=fixture_policy_defaults,
        )
        assert result.target == override_target
        assert result.breach_status == SlaBreachStatus.BREACHED

    def test_partial_override_falls_back_to_plan_default_for_missing_severity(
        self, fixture_policy_defaults, fixture_contract_overrides
    ):
        override = fixture_contract_overrides["FIX-ACCT-001"].sla
        assert override is not None
        assert "P3" not in override.targets  # confirms this override is genuinely partial
        plan_target = fixture_policy_defaults.sla_targets["Enterprise"]["P3"]

        created_at = REFERENCE_TIME - (plan_target.to_timedelta() / 2)
        result = check_sla_status(
            plan="Enterprise",
            severity="P3",
            severity_confidence=SeverityConfidence.EXPLICIT,
            created_at=created_at,
            reference_time=REFERENCE_TIME,
            override=override,
            policy=fixture_policy_defaults,
        )
        assert result.target == plan_target

    def test_unknown_plan_has_no_configured_target(self, fixture_policy_defaults):
        result = check_sla_status(
            plan="SomeNewPlanTier",
            severity="P1",
            severity_confidence=SeverityConfidence.EXPLICIT,
            created_at=REFERENCE_TIME - timedelta(hours=1),
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.breach_status == SlaBreachStatus.UNKNOWN
        assert "sla_target" in result.missing_fields

    def test_unknown_severity_value_has_no_configured_target(self, fixture_policy_defaults):
        result = check_sla_status(
            plan="Enterprise",
            severity="P4",
            severity_confidence=SeverityConfidence.EXPLICIT,
            created_at=REFERENCE_TIME - timedelta(hours=1),
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.breach_status == SlaBreachStatus.UNKNOWN

    def test_created_at_after_reference_time_is_inconsistent(self, fixture_policy_defaults):
        result = check_sla_status(
            plan="Enterprise",
            severity="P1",
            severity_confidence=SeverityConfidence.EXPLICIT,
            created_at=REFERENCE_TIME + timedelta(hours=1),
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.breach_status == SlaBreachStatus.UNKNOWN
        assert "created_at" in result.missing_fields

    def test_business_time_target_surfaces_an_assumption(self, fixture_policy_defaults):
        target = fixture_policy_defaults.sla_targets["Enterprise"]["P3"]
        assert target.is_business_time is True
        created_at = REFERENCE_TIME - (target.to_timedelta() / 2)
        result = check_sla_status(
            plan="Enterprise",
            severity="P3",
            severity_confidence=SeverityConfidence.EXPLICIT,
            created_at=created_at,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.assumptions != []

    def test_calendar_time_target_has_no_business_time_assumption(self, fixture_policy_defaults):
        target = fixture_policy_defaults.sla_targets["Enterprise"]["P1"]
        assert target.is_business_time is False
        created_at = REFERENCE_TIME - (target.to_timedelta() / 2)
        result = check_sla_status(
            plan="Enterprise",
            severity="P1",
            severity_confidence=SeverityConfidence.EXPLICIT,
            created_at=created_at,
            reference_time=REFERENCE_TIME,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert result.assumptions == []

    def test_snapshot_time_drives_the_result_not_the_wall_clock(self, fixture_policy_defaults):
        target = fixture_policy_defaults.sla_targets["Enterprise"]["P1"]
        created_at = REFERENCE_TIME
        earlier_reference = created_at + (target.to_timedelta() / 2)
        later_reference = created_at + target.to_timedelta() + timedelta(minutes=1)

        earlier_result = check_sla_status(
            plan="Enterprise",
            severity="P1",
            severity_confidence=SeverityConfidence.EXPLICIT,
            created_at=created_at,
            reference_time=earlier_reference,
            override=None,
            policy=fixture_policy_defaults,
        )
        later_result = check_sla_status(
            plan="Enterprise",
            severity="P1",
            severity_confidence=SeverityConfidence.EXPLICIT,
            created_at=created_at,
            reference_time=later_reference,
            override=None,
            policy=fixture_policy_defaults,
        )
        assert earlier_result.breach_status == SlaBreachStatus.WITHIN_TARGET
        assert later_result.breach_status == SlaBreachStatus.BREACHED


# ---------------------------------------------------------------------------
# Configuration injection: same code, different config, different result
# ---------------------------------------------------------------------------


class TestConfigurationInjectionChangesResultsWithoutCodeChanges:
    def test_service_credit_cap_change_changes_the_amount(self, fixture_policy_defaults):
        threshold = timedelta(hours=fixture_policy_defaults.credit_default_delay_threshold_hours)
        window_end = REFERENCE_TIME - threshold - timedelta(minutes=1)
        fee = 10_000.0

        low_cap_policy = fixture_policy_defaults.model_copy(update={"credit_default_cap_inr": 50})
        high_cap_policy = fixture_policy_defaults.model_copy(
            update={"credit_default_cap_inr": 5000}
        )

        common_kwargs = dict(
            pickup_window_end=window_end,
            pickup_actual_at=REFERENCE_TIME,
            carrier_fault=True,
            customer_fault=False,
            shipment_fee_inr=fee,
            reference_time=REFERENCE_TIME,
            override=None,
        )
        low = check_service_credit_eligibility(policy=low_cap_policy, **common_kwargs)
        high = check_service_credit_eligibility(policy=high_cap_policy, **common_kwargs)

        percent_amount = fee * fixture_policy_defaults.credit_default_percent / 100
        assert low.amount_inr == 50  # the low cap binds
        assert high.amount_inr == pytest.approx(
            percent_amount
        )  # the percent-of-fee amount binds instead
        assert low.amount_inr != high.amount_inr

    def test_sla_target_change_changes_breach_status(self, fixture_policy_defaults):
        created_at = REFERENCE_TIME - timedelta(hours=5)

        def with_p1_target(target: SlaTarget):
            return fixture_policy_defaults.model_copy(
                update={
                    "sla_targets": {
                        **fixture_policy_defaults.sla_targets,
                        "Enterprise": {
                            **fixture_policy_defaults.sla_targets["Enterprise"],
                            "P1": target,
                        },
                    }
                }
            )

        tight_policy = with_p1_target(SlaTarget(amount=1, unit="hours", is_business_time=False))
        loose_policy = with_p1_target(SlaTarget(amount=100, unit="hours", is_business_time=False))

        common_kwargs = dict(
            plan="Enterprise",
            severity="P1",
            severity_confidence=SeverityConfidence.EXPLICIT,
            created_at=created_at,
            reference_time=REFERENCE_TIME,
            override=None,
        )
        tight_result = check_sla_status(policy=tight_policy, **common_kwargs)
        loose_result = check_sla_status(policy=loose_policy, **common_kwargs)

        assert tight_result.breach_status == SlaBreachStatus.BREACHED
        assert loose_result.breach_status == SlaBreachStatus.WITHIN_TARGET


# ---------------------------------------------------------------------------
# The rule engine must never read the wall clock
# ---------------------------------------------------------------------------


class TestRuleEngineNeverUsesTheWallClock:
    @pytest.mark.parametrize("module", [cancellation_module, service_credit_module, sla_module])
    def test_module_source_never_references_the_system_clock(self, module):
        source = inspect.getsource(module)
        forbidden_tokens = ["datetime.now(", "date.today(", "utcnow(", "time.time("]
        offenders = [token for token in forbidden_tokens if token in source]
        assert offenders == [], f"{module.__name__} references the wall clock: {offenders}"


# ---------------------------------------------------------------------------
# Composition with the structured data access layer (Milestone 1, commit 1)
# ---------------------------------------------------------------------------


class TestComposesWithTheDataAccessLayer:
    def test_cancellation_rule_consumes_real_query_layer_objects(
        self, synthetic_db_connection, fixture_policy_defaults
    ):
        order = queries.get_order("FIX-ORD-001", conn=synthetic_db_connection)
        assert order is not None

        result = check_cancellation_eligibility(
            order_status=order.status,
            booked_at=order.booked_at,
            cancellation_requested_at=order.cancellation_requested_at,
            pickup_actual_at=order.pickup_actual_at,
            reference_time=order.booked_at + timedelta(days=1),
            override=None,
            policy=fixture_policy_defaults,
        )
        assert isinstance(result.decision, CancellationDecision)

    def test_service_credit_rule_consumes_real_query_layer_objects(
        self, synthetic_db_connection, fixture_policy_defaults
    ):
        order = queries.get_order("FIX-ORD-002", conn=synthetic_db_connection)
        assert order is not None

        result = check_service_credit_eligibility(
            pickup_window_end=order.pickup_window_end,
            pickup_actual_at=order.pickup_actual_at,
            carrier_fault=order.carrier_fault,
            customer_fault=order.customer_fault,
            shipment_fee_inr=order.shipment_fee_inr,
            reference_time=order.booked_at + timedelta(hours=10),
            override=None,
            policy=fixture_policy_defaults,
        )
        assert isinstance(result.eligibility, CreditEligibility)
