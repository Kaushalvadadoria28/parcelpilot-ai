"""Deterministic SLA target/breach calculation.

Compares elapsed time since a ticket was created against its applicable
first-response target (plan default, or a contract override when one
exists for the relevant severity) as of an explicitly supplied reference
time — never the wall clock.

Severity is not a stored field anywhere in the dataset (see
`docs/git-development-plan.md` and `backend/models.py::SeverityConfidence`):
it must be supplied by the caller along with a `severity_confidence` that
says whether it was explicitly stated, textually inferred, or could not be
resolved at all. This function never invents a severity and never treats
an inferred one as equivalent to an explicit fact — an unresolved severity
always produces `SlaBreachStatus.UNKNOWN`, not a guessed default.
"""

from __future__ import annotations

from datetime import datetime

from backend.models import (
    PolicyDefaults,
    SeverityConfidence,
    SlaBreachStatus,
    SlaOverride,
    SlaResult,
    SlaTarget,
)


def _resolve_target(
    *, plan: str, severity: str, override: SlaOverride | None, policy: PolicyDefaults
) -> SlaTarget | None:
    if override is not None and severity in override.targets:
        return override.targets[severity]
    return policy.sla_targets.get(plan, {}).get(severity)


def check_sla_status(
    *,
    plan: str,
    severity: str | None,
    severity_confidence: SeverityConfidence,
    created_at: datetime,
    reference_time: datetime,
    override: SlaOverride | None,
    policy: PolicyDefaults,
) -> SlaResult:
    evidence: list[str] = []

    elapsed = reference_time - created_at
    if elapsed.total_seconds() < 0:
        return SlaResult(
            severity=severity,
            severity_confidence=severity_confidence,
            breach_status=SlaBreachStatus.UNKNOWN,
            missing_fields=["created_at"],
            evidence=[
                "created_at is after the reference time — these timestamps are "
                "inconsistent; elapsed time cannot be computed."
            ],
        )

    evidence.append(f"{elapsed} elapsed since the ticket was created.")

    # Checked unconditionally (not just for the UNRESOLVED case) so that an
    # inconsistent input — INFERRED/EXPLICIT confidence paired with no
    # actual severity value — is still treated as unresolved rather than
    # passing `None` on to the target lookup below.
    if severity is None or severity_confidence is SeverityConfidence.UNRESOLVED:
        return SlaResult(
            severity=None,
            severity_confidence=SeverityConfidence.UNRESOLVED,
            elapsed=elapsed,
            breach_status=SlaBreachStatus.UNKNOWN,
            missing_fields=["severity"],
            evidence=[
                *evidence,
                "Severity could not be resolved, so no SLA target applies and breach "
                "status cannot be determined.",
            ],
        )

    if severity_confidence is SeverityConfidence.INFERRED:
        evidence.append(f"Severity {severity!r} was textually inferred, not explicitly stated.")

    target = _resolve_target(plan=plan, severity=severity, override=override, policy=policy)
    if target is None:
        return SlaResult(
            severity=severity,
            severity_confidence=severity_confidence,
            elapsed=elapsed,
            breach_status=SlaBreachStatus.UNKNOWN,
            missing_fields=["sla_target"],
            evidence=[
                *evidence,
                f"No SLA target is configured for plan {plan!r} / severity {severity!r}.",
            ],
        )

    evidence.append(f"Applicable target is {target.describe()}.")

    assumptions: list[str] = []
    if target.is_business_time:
        assumptions.append(
            "This target is expressed in business hours/days; elapsed time was "
            "computed as continuous calendar time because no business-hour "
            "calendar is defined in the source policy documents. The actual "
            "business-time-elapsed could be less, which could change a result "
            "near the boundary."
        )

    target_duration = target.to_timedelta()
    if elapsed < target_duration:
        breach_status = SlaBreachStatus.WITHIN_TARGET
        evidence.append("Elapsed time is within the target.")
    elif elapsed == target_duration:
        breach_status = SlaBreachStatus.AT_TARGET
        evidence.append("Elapsed time has just reached the target, but not yet exceeded it.")
    else:
        breach_status = SlaBreachStatus.BREACHED
        evidence.append("Elapsed time has exceeded the target: this ticket is in breach.")

    return SlaResult(
        severity=severity,
        severity_confidence=severity_confidence,
        target=target,
        elapsed=elapsed,
        breach_status=breach_status,
        assumptions=assumptions,
        evidence=evidence,
    )
