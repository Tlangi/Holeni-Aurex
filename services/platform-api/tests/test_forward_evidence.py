from app.forward_evidence import evidence_state
from app.config import Settings
from app.health_monitor import _web_health_url


def test_forward_evidence_accumulates_below_evidence_floor() -> None:
    assert evidence_state({"demo_auto_ready": False, "checks": {"sufficient_data": False}}) == "ACCUMULATING"


def test_validated_market_enters_forward_shadow_before_demo_readiness() -> None:
    assert evidence_state({
        "demo_auto_ready": False,
        "checks": {"sufficient_data": True, "validated_model": True},
    }) == "FORWARD_SHADOW"


def test_demo_ready_is_never_inferred_from_data_count_alone() -> None:
    assert evidence_state({
        "demo_auto_ready": False,
        "checks": {"sufficient_data": True, "validated_model": False},
    }) == "BLOCKED"
    assert evidence_state({"demo_auto_ready": True, "checks": {}}) == "DEMO_TEST_READY"


def test_production_health_monitor_checks_the_deployed_https_site() -> None:
    settings = Settings(
        _env_file=None, app_env="production", web_origins="https://holeniaurex.co.za",
        auth_hash_pepper="x" * 32, session_cookie_secure=True,
    )
    assert _web_health_url(settings) == "https://holeniaurex.co.za/_health"
