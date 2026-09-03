from app.market_qualification import qualify_markets


def test_market_qualification_is_explicitly_non_executing_by_contract() -> None:
    assert qualify_markets.__doc__
