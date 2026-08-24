"""Tests for the configuration loaders (backend/rules/policy_defaults.py,
backend/rules/contract_overrides.py).

These loaders are the *only* code allowed to read the YAML config files —
the pure rule functions never do (see backend/rules/{cancellation,
service_credit,sla}.py). Tests here exercise the public example files
(fictitious values) plus the real-vs-example default-resolution logic in
an isolated temp directory, so they pass identically whether or not the
real, locally-supplied config happens to exist on the machine running them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.rules import contract_overrides, policy_defaults

_EXAMPLE_POLICY_PATH = Path("config/policy_defaults.example.yaml")
_EXAMPLE_OVERRIDES_PATH = Path("config/contract_overrides.example.yaml")


class TestLoadPolicyDefaults:
    def test_loads_the_public_example_file(self):
        defaults = policy_defaults.load_policy_defaults(_EXAMPLE_POLICY_PATH)

        assert defaults.cancellation_free_window_minutes == 20
        assert defaults.cancellation_fee_after_window_inr == 199
        assert defaults.credit_default_delay_threshold_hours == 3
        assert defaults.credit_default_cap_inr == 400
        assert defaults.credit_default_percent == 8
        assert defaults.credit_manager_approval_threshold_inr == 900

        enterprise_p1 = defaults.sla_targets["Enterprise"]["P1"]
        assert enterprise_p1.amount == 45
        assert enterprise_p1.unit == "minutes"
        assert enterprise_p1.is_business_time is False

        growth_p3 = defaults.sla_targets["Growth"]["P3"]
        assert growth_p3.is_business_time is True

    def test_default_resolution_prefers_real_file_when_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Isolated in a temp directory so this doesn't depend on whether a
        real config/policy_defaults.yaml happens to exist on this machine."""
        # Resolve and read the example file's absolute path *before*
        # changing directories, or this would try to read it relative to
        # tmp_path instead of the real repo.
        example_content = _EXAMPLE_POLICY_PATH.resolve().read_text(encoding="utf-8")

        monkeypatch.chdir(tmp_path)
        (tmp_path / "config").mkdir()

        example = tmp_path / "config" / "policy_defaults.example.yaml"
        example.write_text(example_content, encoding="utf-8")

        assert policy_defaults.default_config_path() == Path("config/policy_defaults.example.yaml")

        real = tmp_path / "config" / "policy_defaults.yaml"
        real.write_text(example_content, encoding="utf-8")

        assert policy_defaults.default_config_path() == Path("config/policy_defaults.yaml")


class TestLoadContractOverrides:
    def test_loads_the_public_example_file(self):
        registry = contract_overrides.load_contract_overrides(_EXAMPLE_OVERRIDES_PATH)

        fee_waiver_account = registry["DEMO-ACCT-001"]
        assert fee_waiver_account.cancellation is not None
        assert fee_waiver_account.cancellation.fee_waived is True
        assert fee_waiver_account.sla is not None
        assert set(fee_waiver_account.sla.targets) == {"P1", "P2", "P3"}

        credit_override_account = registry["DEMO-ACCT-002"]
        assert credit_override_account.service_credit is not None
        assert credit_override_account.service_credit.credit_amount_mode == "fixed"
        assert credit_override_account.service_credit.credit_amount_inr == 275
        assert credit_override_account.service_credit.delay_threshold_hours == 6

    def test_get_override_returns_none_for_unknown_account(self):
        registry = contract_overrides.load_contract_overrides(_EXAMPLE_OVERRIDES_PATH)
        assert contract_overrides.get_override(registry, "NOT-A-REAL-ACCOUNT") is None

    def test_get_override_returns_the_account_when_present(self):
        registry = contract_overrides.load_contract_overrides(_EXAMPLE_OVERRIDES_PATH)
        override = contract_overrides.get_override(registry, "DEMO-ACCT-001")
        assert override is not None
        assert override.account_id == "DEMO-ACCT-001"

    def test_unknown_topic_raises_a_clear_error(self, tmp_path: Path):
        bad_manifest = tmp_path / "bad.yaml"
        bad_manifest.write_text(
            "overrides:\n  - account_id: X\n    topic: not_a_real_topic\n    rule: {}\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="not_a_real_topic"):
            contract_overrides.load_contract_overrides(bad_manifest)

    def test_empty_overrides_file_produces_empty_registry(self, tmp_path: Path):
        empty_manifest = tmp_path / "empty.yaml"
        empty_manifest.write_text("overrides: []\n", encoding="utf-8")
        assert contract_overrides.load_contract_overrides(empty_manifest) == {}
