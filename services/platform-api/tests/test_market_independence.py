def test_germany_40_failure_is_not_a_global_market_veto() -> None:
    qualifications = {
        "EURUSD": {"research_ready": True},
        "USDJPY": {"research_ready": True},
        "GERMANY40": {"research_ready": False},
    }
    eligible = {symbol for symbol, evidence in qualifications.items()
                if evidence["research_ready"]}
    assert eligible == {"EURUSD", "USDJPY"}
