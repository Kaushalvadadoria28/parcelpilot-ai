"""Loader for the default (non-contract-specific) policy thresholds.

This module is the *only* place in the rule engine that reads
`config/policy_defaults.yaml` (real, gitignored — see
docs/git-development-plan.md §2) or `config/policy_defaults.example.yaml`
(fictitious, public). It loads and validates the file into a `PolicyDefaults`
object; the pure rule functions in `backend/rules/{cancellation,
service_credit,sla}.py` take that already-resolved object as an explicit
parameter and never touch YAML themselves:

    policy_defaults.yaml -> load_policy_defaults() -> PolicyDefaults
                                                            |
                                                            v
                                              pure rule function -> typed result

This keeps the rule functions testable with plain fixture values, with no
dependency on this loader or on the real assessment pack.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from backend.models import PolicyDefaults, SlaTarget

_REAL_PATH = Path("config/policy_defaults.yaml")
_EXAMPLE_PATH = Path("config/policy_defaults.example.yaml")

_SEVERITIES = ("P1", "P2", "P3")


def _parse_sla_target(raw: dict[str, Any]) -> SlaTarget:
    return SlaTarget(
        amount=raw["amount"],
        unit=raw["unit"],
        is_business_time=raw["is_business_time"],
    )


def default_config_path() -> Path:
    """The real file if a caller has supplied one locally, else the public
    fictitious example. Preferring the real file when present is what lets
    manual verification against the real pack "just work" without any code
    change — the example is not a safe stand-in for real answers, it exists
    so the loader (and everything built on it) has something to run against
    in this public repository.
    """
    return _REAL_PATH if _REAL_PATH.exists() else _EXAMPLE_PATH


def load_policy_defaults(path: Path | None = None) -> PolicyDefaults:
    """Load and validate policy defaults from `path` (or the default
    resolution in `default_config_path()`)."""
    resolved_path = path if path is not None else default_config_path()
    raw = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))

    sla_targets: dict[str, dict[str, SlaTarget]] = {}
    for plan, severities in raw["sla_targets"].items():
        sla_targets[plan] = {
            severity: _parse_sla_target(target)
            for severity, target in severities.items()
            if severity in _SEVERITIES
        }

    cancellation = raw["cancellation"]
    credit = raw["service_credit"]

    return PolicyDefaults(
        sla_targets=sla_targets,
        cancellation_free_window_minutes=cancellation["free_window_minutes"],
        cancellation_fee_after_window_inr=cancellation["fee_after_window_inr"],
        credit_default_delay_threshold_hours=credit["default_delay_threshold_hours"],
        credit_default_cap_inr=credit["default_credit_cap_inr"],
        credit_default_percent=credit["default_credit_percent"],
        credit_manager_approval_threshold_inr=credit["manager_approval_threshold_inr"],
    )
