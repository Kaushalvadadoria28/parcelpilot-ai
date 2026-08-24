"""Fictitious policy-defaults and contract-override fixtures for rule-engine
tests.

Mirrors the numbers in config/policy_defaults.example.yaml exactly, so the
same fictitious policy profile is used whether a test constructs a
PolicyDefaults object directly in Python or loads it from the example YAML
file (see tests/test_policy_config.py for the latter). These values are
never derived from, and never coincide with, the real assessment pack's
numbers — see docs/git-development-plan.md §2.
"""

from __future__ import annotations

from backend.models import (
    AccountContractOverrides,
    CancellationOverride,
    PolicyDefaults,
    ServiceCreditOverride,
    SlaOverride,
    SlaTarget,
)


def build_fixture_policy_defaults() -> PolicyDefaults:
    return PolicyDefaults(
        sla_targets={
            "Enterprise": {
                "P1": SlaTarget(amount=45, unit="minutes", is_business_time=False),
                "P2": SlaTarget(amount=3, unit="hours", is_business_time=False),
                "P3": SlaTarget(amount=2, unit="days", is_business_time=True),
            },
            "Growth": {
                "P1": SlaTarget(amount=3, unit="hours", is_business_time=True),
                "P2": SlaTarget(amount=6, unit="hours", is_business_time=True),
                "P3": SlaTarget(amount=3, unit="days", is_business_time=True),
            },
            "Standard": {
                "P1": SlaTarget(amount=6, unit="hours", is_business_time=True),
                "P2": SlaTarget(amount=2, unit="days", is_business_time=True),
                "P3": SlaTarget(amount=3, unit="days", is_business_time=True),
            },
        },
        cancellation_free_window_minutes=20,
        cancellation_fee_after_window_inr=199,
        credit_default_delay_threshold_hours=3,
        credit_default_cap_inr=400,
        credit_default_percent=8,
        credit_manager_approval_threshold_inr=900,
    )


def build_fixture_contract_overrides() -> dict[str, AccountContractOverrides]:
    """Two fictitious accounts exercising the same *patterns* as the real
    pack's two contracts — a full cancellation-fee waiver plus a tighter
    SLA, and a service-credit threshold/amount override — with entirely
    different, made-up numbers and account IDs."""
    fee_waiver_account = AccountContractOverrides(
        account_id="FIX-ACCT-001",
        cancellation=CancellationOverride(fee_waived=True),
        sla=SlaOverride(
            targets={
                "P1": SlaTarget(amount=10, unit="minutes", is_business_time=False),
                "P2": SlaTarget(amount=30, unit="minutes", is_business_time=False),
                # P3 intentionally omitted, to exercise partial-override
                # fallback to the plan default.
            }
        ),
    )
    credit_override_account = AccountContractOverrides(
        account_id="FIX-ACCT-002",
        service_credit=ServiceCreditOverride(
            delay_threshold_hours=5,
            credit_amount_mode="fixed",
            credit_amount_inr=350,
        ),
    )
    return {
        fee_waiver_account.account_id: fee_waiver_account,
        credit_override_account.account_id: credit_override_account,
    }
