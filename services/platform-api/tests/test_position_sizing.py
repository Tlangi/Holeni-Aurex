from decimal import Decimal

from app.position_sizing import PositionSizingInput, calculate_position_size


def case(**overrides: str) -> PositionSizingInput:
    values = dict(account_equity="20000", risk_percentage="0.25", entry_price="1.1000",
                  stop_price="1.0980", broker_minimum_size="0.01",
                  broker_size_increment="0.01", value_per_point_account_currency="100000",
                  margin_factor_pct="3.33", available_margin="20000")
    values.update(overrides)
    return PositionSizingInput(**{key: Decimal(value) for key, value in values.items()})


def test_eurusd_independent_twenty_pip_example() -> None:
    # USD 50 risk / (0.0020 * USD 100,000 per 1.0 price move) = 0.25 lots.
    result = calculate_position_size(case())
    assert result.approved
    assert result.maximum_loss_amount == Decimal("50")
    assert result.broker_rounded_size == Decimal("0.25")
    assert result.estimated_stop_loss == Decimal("50.000000")


def test_jpy_conversion_and_floor_rounding() -> None:
    # USD value of one JPY price point is supplied after authoritative conversion.
    result = calculate_position_size(case(entry_price="159.50", stop_price="159.20",
        value_per_point_account_currency="628.9308176", broker_size_increment="0.01"))
    expected_raw = Decimal("50") / (Decimal("0.30") * Decimal("628.9308176"))
    assert result.raw_size == expected_raw
    assert result.broker_rounded_size == Decimal("0.26")
    assert result.estimated_stop_loss <= Decimal("50")


def test_index_and_gold_decimal_examples() -> None:
    dax = calculate_position_size(case(entry_price="25800", stop_price="25600",
        value_per_point_account_currency="1.17", broker_minimum_size="0.5",
        broker_size_increment="0.1", margin_factor_pct="5"))
    assert not dax.approved and dax.rejection_reason == "BROKER_MINIMUM_EXCEEDS_RISK"
    gold = calculate_position_size(case(entry_price="4320", stop_price="4310",
        value_per_point_account_currency="1", broker_minimum_size="0.1",
        broker_size_increment="0.1", margin_factor_pct="5"))
    assert gold.approved and gold.broker_rounded_size == Decimal("5.0")


def test_minimum_size_never_rounds_risk_up() -> None:
    result = calculate_position_size(case(account_equity="100", risk_percentage="0.25",
        broker_minimum_size="1", broker_size_increment="1"))
    assert not result.approved
    assert result.rejection_reason == "BROKER_MINIMUM_EXCEEDS_RISK"
    assert result.broker_rounded_size == 0
