"""Pure locked-model validation calculations."""
from __future__ import annotations

from collections import Counter

from app.prospective_development_tournament import trade_metrics


def replay_metrics(
    members: list[dict], outcomes: list[dict], predictions: list[int],
    *, family: str, minimum_trades: int,
) -> dict[str, object]:
    if len(members) != len(predictions):
        raise ValueError("Validation prediction count differs from frozen membership")
    keyed = {
        (row["opportunity_id"], row["cost_sensitivity"], row["direction"]): row
        for row in outcomes if row["execution_policy_version"] == family
    }
    metrics: dict[str, dict[str, object]] = {}
    incomplete: dict[str, int] = {}
    for sensitivity in ("NORMAL_P75", "STRESSED_P95"):
        returns: list[float] = []
        missing = 0
        no_trade = 0
        for member, prediction in zip(members, predictions):
            action = int(prediction)
            if action == 0:
                no_trade += 1
                continue
            direction = "LONG" if action == 1 else "SHORT"
            outcome = keyed.get((member["opportunity_id"], sensitivity, direction))
            if not outcome or outcome.get("status") != "EVALUATED":
                missing += 1
                continue
            returns.append(float(outcome["net_return"]))
        metrics[sensitivity] = trade_metrics(returns, no_trade)
        incomplete[sensitivity] = missing
    normal = metrics["NORMAL_P75"]
    stressed = metrics["STRESSED_P95"]
    passed = (
        int(normal["trade_count"]) >= minimum_trades
        and incomplete["NORMAL_P75"] == 0
        and incomplete["STRESSED_P95"] == 0
        and all(
            item["profit_factor"] is not None and float(item["profit_factor"]) > 1
            and item["trade_expectancy"] is not None and float(item["trade_expectancy"]) > 0
            for item in (normal, stressed)
        )
    )
    return {
        "prediction_action_counts": {
            str(key): value for key, value in sorted(Counter(int(v) for v in predictions).items())
        },
        "metrics": metrics,
        "non_evaluable_predicted_trades": incomplete,
        "validation_passed": passed,
    }
