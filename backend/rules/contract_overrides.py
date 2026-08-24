"""Loader for per-account contract overrides.

Mirrors `backend/rules/policy_defaults.py`'s separation of concerns: this
module is the *only* place that reads `config/contract_overrides.yaml`
(real, gitignored) or `config/contract_overrides.example.yaml` (fictitious,
public). The pure rule functions never read this file — a caller resolves
an account's override (or `None`, if the account has no contract on a given
topic) via `get_override()` and passes it in explicitly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from backend.models import (
    AccountContractOverrides,
    CancellationOverride,
    ServiceCreditOverride,
    SlaOverride,
    SlaTarget,
)

_REAL_PATH = Path("config/contract_overrides.yaml")
_EXAMPLE_PATH = Path("config/contract_overrides.example.yaml")

_SEVERITIES = ("P1", "P2", "P3")

ContractOverrideRegistry = dict[str, AccountContractOverrides]


def default_config_path() -> Path:
    return _REAL_PATH if _REAL_PATH.exists() else _EXAMPLE_PATH


def _parse_cancellation(rule: dict[str, Any]) -> CancellationOverride:
    return CancellationOverride(fee_waived=bool(rule["fee_waived"]))


def _parse_service_credit(rule: dict[str, Any]) -> ServiceCreditOverride:
    return ServiceCreditOverride(
        delay_threshold_hours=rule.get("delay_threshold_hours"),
        credit_amount_mode=rule.get("credit_amount_mode"),
        credit_amount_inr=rule.get("credit_amount_inr"),
        credit_cap_inr=rule.get("credit_cap_inr"),
        credit_percent=rule.get("credit_percent"),
        monthly_aggregate_cap_inr=rule.get("monthly_aggregate_cap_inr"),
    )


def _parse_sla(rule: dict[str, Any]) -> SlaOverride:
    targets = {
        severity: SlaTarget(
            amount=target["amount"],
            unit=target["unit"],
            is_business_time=target["is_business_time"],
        )
        for severity, target in rule.items()
        if severity in _SEVERITIES
    }
    return SlaOverride(targets=targets)


_TOPIC_PARSERS = {
    "cancellation": ("cancellation", _parse_cancellation),
    "service_credit": ("service_credit", _parse_service_credit),
    "sla": ("sla", _parse_sla),
}


def load_contract_overrides(path: Path | None = None) -> ContractOverrideRegistry:
    """Load and validate every account's contract overrides from `path` (or
    the default resolution in `default_config_path()`)."""
    resolved_path = path if path is not None else default_config_path()
    raw = yaml.safe_load(resolved_path.read_text(encoding="utf-8")) or {}

    registry: ContractOverrideRegistry = {}
    for entry in raw.get("overrides", []):
        account_id = entry["account_id"]
        topic = entry["topic"]
        rule = entry["rule"]

        if topic not in _TOPIC_PARSERS:
            raise ValueError(
                f"Unknown contract override topic {topic!r} for account {account_id!r}"
            )
        field_name, parse = _TOPIC_PARSERS[topic]

        existing = registry.get(account_id, AccountContractOverrides(account_id=account_id))
        registry[account_id] = existing.model_copy(update={field_name: parse(rule)})

    return registry


def get_override(
    registry: ContractOverrideRegistry, account_id: str
) -> AccountContractOverrides | None:
    return registry.get(account_id)
