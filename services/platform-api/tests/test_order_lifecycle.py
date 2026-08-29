import pytest

from app.order_lifecycle import assert_transition


def test_shadow_intent_transition_path_is_explicit() -> None:
    assert_transition("CREATED", "RISK_APPROVED")
    assert_transition("RISK_APPROVED", "WOULD_SUBMIT")


@pytest.mark.parametrize(
    ("current", "requested"),
    [("CREATED", "SUBMITTED"), ("WOULD_SUBMIT", "SUBMITTING"), ("FAILED", "SUBMITTING")],
)
def test_order_lifecycle_rejects_unsafe_skips(current: str, requested: str) -> None:
    with pytest.raises(ValueError, match="INVALID_ORDER_TRANSITION"):
        assert_transition(current, requested)
