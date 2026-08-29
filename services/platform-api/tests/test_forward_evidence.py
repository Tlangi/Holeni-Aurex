from app.forward_evidence import evidence_state


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
