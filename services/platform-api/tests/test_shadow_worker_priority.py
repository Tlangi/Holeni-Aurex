from unittest.mock import Mock, patch

from app.config import Settings
from app.shadow_worker import ShadowTradingWorker


def test_operational_path_runs_before_research_maintenance() -> None:
    worker = ShadowTradingWorker(Settings(automatic_model_training_enabled=False))
    worker._synchronize_rules = Mock()
    worker._synchronize_macro = Mock()
    worker._all_tenant_ids = Mock(return_value=[])
    worker._tenant_ids = Mock(return_value=[])
    worker._component = Mock()
    worker._audit_market_quality = Mock()
    worker._train_models = Mock()

    events: list[str] = []
    worker._synchronize_rules.side_effect = lambda: events.append("rules")
    worker._synchronize_macro.side_effect = lambda: events.append("macro")
    worker._component.side_effect = lambda *args: events.append("trading")
    worker._audit_market_quality.side_effect = lambda: events.append("quality")

    with patch("app.shadow_worker.process_one_research_job", return_value=None):
        worker._run_locked_cycle()

    assert events == ["rules", "macro", "trading", "quality"]
    worker._train_models.assert_not_called()


def test_legacy_training_requires_explicit_opt_in() -> None:
    worker = ShadowTradingWorker(Settings(automatic_model_training_enabled=True))
    worker._synchronize_rules = Mock()
    worker._synchronize_macro = Mock()
    worker._all_tenant_ids = Mock(return_value=[])
    worker._tenant_ids = Mock(return_value=[])
    worker._component = Mock()
    worker._audit_market_quality = Mock()
    worker._train_models = Mock()

    with patch("app.shadow_worker.process_one_research_job", return_value=None):
        worker._run_locked_cycle()

    worker._train_models.assert_called_once_with()
