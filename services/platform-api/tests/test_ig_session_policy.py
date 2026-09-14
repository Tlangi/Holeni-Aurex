from types import SimpleNamespace

import pytest

from app.ig_demo import IGDemoClient, IGDemoUnavailable, ig_error_category


@pytest.mark.parametrize("code,expected", [
    ("error.public-api.exceeded-account-historical-data-allowance", "HISTORICAL_QUOTA"),
    ("error.security.account-disabled", "AUTHENTICATION"),
    ("error.security.invalid-details", "AUTHENTICATION"),
    ("error.security.client-token-invalid", "SESSION"),
    ("error.public-api.exceeded-api-key-allowance", "SESSION"),
    ("error.public-api.exceeded-data-allowance", "RATE_QUOTA"),
])
def test_ig_error_categories_are_operationally_distinct(code: str, expected: str) -> None:
    assert ig_error_category(code) == expected


def test_historical_prices_fail_closed_when_policy_is_disabled() -> None:
    client = object.__new__(IGDemoClient)
    client.settings = SimpleNamespace(ig_historical_data_enabled=False)
    with pytest.raises(IGDemoUnavailable) as caught:
        client.historical_prices("CS.D.USDJPY.CFD.IP")
    assert caught.value.error_code == "IG_HISTORICAL_DISABLED_BY_POLICY"
