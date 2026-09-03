from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.config import Settings
from app.experimental_demo import (
    ExperimentalGateInput,
    _artifact_evidence,
    evaluate_experimental_gate,
    experimental_attempt_key,
    minimum_size_risk_zar,
    startup_recover_experimental_demo,
)
from app.model_pipeline import FEATURES
from sklearn.dummy import DummyClassifier
import hashlib
import joblib
import numpy as np
import pandas as pd
from app.ig_execution import (
    ExperimentalCloseGate, ExperimentalExecutionGate, IGExecutionBlocked,
    assert_experimental_close_gate, assert_experimental_execution_gate,
)


def eligible_gate() -> ExperimentalGateInput:
    return ExperimentalGateInput(
        feature_enabled=True, owner_armed=True, within_window=True,
        demo_environment_locked=True, market_tier=1, owner_active=True,
        risk_profile_active=True, daily_ledger_current=True,
        experimental_ledger_current=True, market_data_fresh=True,
        market_open=True, broker_healthy=True, broker_rules_current=True,
        reconciliation_clear=True, stop_present=True, target_present=True,
        holding_period_present=True, risk_cap_zar=Decimal("100"),
        minimum_size_risk_zar=Decimal("10"),
    )


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("feature_enabled", False, "EXPERIMENTAL_DEMO_FEATURE_DISABLED"),
    ("owner_armed", False, "EXPERIMENT_NOT_ARMED"),
    ("within_window", False, "EXPERIMENT_EXPIRED"),
    ("demo_environment_locked", False, "EXPERIMENTAL_DEMO_ENVIRONMENT_LOCK_FAILED"),
    ("owner_active", False, "OWNER_READINESS_FAILED"),
    ("risk_profile_active", False, "RISK_PROFILE_INACTIVE"),
    ("daily_ledger_current", False, "DAILY_LEDGER_UNAVAILABLE"),
    ("experimental_ledger_current", False, "EXPERIMENT_LEDGER_UNAVAILABLE"),
    ("market_data_fresh", False, "DATA_STALE"),
    ("market_open", False, "MARKET_CLOSED"),
    ("broker_healthy", False, "BROKER_ACCOUNT_UNHEALTHY"),
    ("broker_rules_current", False, "BROKER_RULE_VALIDATION_FAILED"),
    ("reconciliation_clear", False, "RECONCILIATION_MISMATCH"),
    ("stop_present", False, "INVALID_STOP"),
    ("target_present", False, "MISSING_TARGET"),
    ("holding_period_present", False, "MAX_HOLDING_PERIOD_REQUIRED"),
    ("daily_loss_limit_reached", True, "EXPERIMENT_DAILY_LOSS_LIMIT"),
    ("programme_drawdown_limit_reached", True, "EXPERIMENT_PROGRAMME_DRAWDOWN_LIMIT"),
    ("daily_losing_trade_limit_reached", True, "EXPERIMENT_DAILY_LOSING_TRADE_LIMIT"),
    ("duplicate_attempt", True, "DUPLICATE_EXPERIMENTAL_ATTEMPT"),
])
def test_rejection_chain(field: str, value: object, reason: str) -> None:
    assert evaluate_experimental_gate(replace(eligible_gate(), **{field: value})) == reason


def test_tier_three_is_always_research_only() -> None:
    assert evaluate_experimental_gate(replace(eligible_gate(), market_tier=3)) == "TIER_RESEARCH_ONLY"


def test_unknown_submission_is_global_circuit_breaker() -> None:
    assert evaluate_experimental_gate(
        replace(eligible_gate(), unknown_submission_count=1)
    ) == "UNKNOWN_SUBMISSION_BLOCK"


def test_one_open_position_is_global_limit() -> None:
    assert evaluate_experimental_gate(
        replace(eligible_gate(), open_position_count=1)
    ) == "OPEN_POSITION_LIMIT"


def test_minimum_size_never_overrides_risk_cap() -> None:
    gate = replace(eligible_gate(), minimum_size_risk_zar=Decimal("100.01"),
                   risk_cap_zar=Decimal("100"))
    assert evaluate_experimental_gate(gate) == "SKIP_MINIMUM_SIZE_EXCEEDS_EXPERIMENT_RISK_CAP"


def test_minimum_size_risk_is_deterministic() -> None:
    assert minimum_size_risk_zar(
        entry=Decimal("100"), stop=Decimal("98"), minimum_size=Decimal("0.5"),
        value_per_price_point_zar=Decimal("20"),
    ) == Decimal("20.000000")


def test_attempt_key_is_stable_and_side_specific() -> None:
    timestamp = datetime(2026, 9, 1, 8, 30, tzinfo=timezone.utc)
    first = experimental_attempt_key("p", "m", "eurusd", timestamp, "BUY")
    second = experimental_attempt_key("p", "m", "EURUSD", timestamp, "BUY")
    sell = experimental_attempt_key("p", "m", "EURUSD", timestamp, "SELL")
    assert first == second
    assert first != sell
    assert len(first) == 64


def test_feature_flag_defaults_false_and_requires_all_demo_locks() -> None:
    settings = Settings(_env_file=None, sql_password="x", ig_api_key="k", ig_username="u",
                        ig_password="p", ig_account_id="a", trading_mode="demo",
                        allow_demo_trading=True)
    assert settings.experimental_demo_enabled is False
    assert settings.experimental_demo_configured is False


def test_eligible_gate_passes_without_model_or_forward_promotion_fields() -> None:
    assert evaluate_experimental_gate(eligible_gate()) == "ELIGIBLE"
    assert not hasattr(eligible_gate(), "validated_model")
    assert not hasattr(eligible_gate(), "forward_shadow_promoted")


def test_transport_gate_rejects_disabled_feature_before_network() -> None:
    settings = Settings(_env_file=None, sql_password="x", ig_api_key="k", ig_username="u",
                        ig_password="p", ig_account_id="DEMO-1", trading_mode="demo",
                        allow_demo_trading=True)
    gate = ExperimentalExecutionGate(True, "ELIGIBLE", "DEMO-1", "demo", False)
    with pytest.raises(IGExecutionBlocked, match="FEATURE_DISABLED"):
        assert_experimental_execution_gate(settings, gate)


def test_transport_gate_requires_exact_demo_account() -> None:
    settings = Settings(_env_file=None, sql_password="x", ig_api_key="k", ig_username="u",
                        ig_password="p", ig_account_id="DEMO-1", trading_mode="demo",
                        allow_demo_trading=True, experimental_demo_enabled=True)
    gate = ExperimentalExecutionGate(True, "ELIGIBLE", "DEMO-2", "demo", False)
    with pytest.raises(IGExecutionBlocked, match="ENVIRONMENT_LOCK_FAILED"):
        assert_experimental_execution_gate(settings, gate)


def test_startup_recovery_does_not_touch_broker_when_feature_disabled() -> None:
    settings = Settings(_env_file=None)
    assert startup_recover_experimental_demo(settings) == {
        "status": "FEATURE_DISABLED", "checked": 0,
    }


def test_safe_close_remains_available_after_entry_flag_is_disabled() -> None:
    settings = Settings(_env_file=None, ig_api_key="k", ig_username="u", ig_password="p",
                        ig_account_id="DEMO-1")
    assert_experimental_close_gate(
        settings, ExperimentalCloseGate("DEMO-1", "demo", False),
    )


def test_safe_close_never_accepts_live_environment() -> None:
    settings = Settings(_env_file=None, ig_api_key="k", ig_username="u", ig_password="p",
                        ig_account_id="DEMO-1")
    with pytest.raises(IGExecutionBlocked, match="ENVIRONMENT_LOCK_FAILED"):
        assert_experimental_close_gate(
            settings, ExperimentalCloseGate("DEMO-1", "live", False),
        )


def test_artifact_evidence_requires_checksum(tmp_path) -> None:
    path = tmp_path / "candidate.joblib"
    joblib.dump({"model": object(), "features": FEATURES}, path)
    evidence = _artifact_evidence({"artifact_path": str(path), "artifact_sha256": "0" * 64})
    assert evidence["exists"] is True
    assert evidence["checksum_valid"] is False
    assert evidence["loadable"] is False


def test_artifact_evidence_accepts_audited_legacy_metadata(tmp_path) -> None:
    model = DummyClassifier(strategy="prior").fit(
        pd.DataFrame([[0.0] * len(FEATURES), [1.0] * len(FEATURES)], columns=FEATURES),
        np.array([0, 1]),
    )
    path = tmp_path / "legacy.joblib"
    joblib.dump({"model": model, "features": FEATURES}, path)
    evidence = _artifact_evidence({
        "artifact_path": str(path), "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "feature_version": "legacy-v1", "label_version": "AUDITED_LABEL_V1",
    })
    assert evidence["loadable"] is True
    assert evidence["deterministic_inference"] is True
    assert evidence["metadata_source"] == "AUDITED_EXPERIMENT"
