"""Pure development-only comparison of frozen executable opportunity outcomes."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
import math

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def selected_model_factory(name: str):
    if name == "LOGISTIC_REGRESSION":
        return make_pipeline(StandardScaler(),
            LogisticRegression(max_iter=1000, random_state=17))
    if name == "RANDOM_FOREST":
        return RandomForestClassifier(
            n_estimators=200, min_samples_leaf=5, random_state=17, n_jobs=1)
    if name == "HGB":
        return HistGradientBoostingClassifier(
            max_iter=100, learning_rate=0.05, max_leaf_nodes=15, random_state=17)
    raise ValueError(f"Unregistered prospective model: {name}")


def chronological_development_split(members: list[dict], *, purge_minutes: int = 120):
    ordered = sorted(members, key=lambda row: (row["decision_at_utc"], row["opportunity_id"]))
    cut = math.floor(len(ordered) * 0.7)
    assessment = ordered[cut:]
    if not assessment:
        return [], []
    first = datetime.fromisoformat(assessment[0]["decision_at_utc"].replace("Z", "+00:00"))
    training = [row for row in ordered[:cut]
                if datetime.fromisoformat(row["decision_at_utc"].replace("Z", "+00:00"))
                + timedelta(minutes=purge_minutes) < first]
    return training, assessment


def complete_comparison_members(members: list[dict], outcomes: list[dict],
                                families: list[str]) -> list[dict]:
    required = {(family, sensitivity, direction)
                for family in families for sensitivity in ("NORMAL_P75", "STRESSED_P95")
                for direction in ("LONG", "SHORT")}
    by_id = {}
    for row in outcomes:
        if row["status"] == "EVALUATED":
            by_id.setdefault(row["opportunity_id"], set()).add((
                row["execution_policy_version"], row["cost_sensitivity"], row["direction"]))
    return [member for member in members if by_id.get(member["opportunity_id"]) == required]


def action_target(long_return: float, short_return: float) -> int:
    # np.argmax's first maximum makes NO_TRADE the conservative tie winner.
    return int(np.argmax([0.0, long_return, short_return]))


def trade_metrics(returns: list[float], no_trade_count: int) -> dict:
    gains = sum(value for value in returns if value > 0)
    losses = -sum(value for value in returns if value < 0)
    equity = peak = 1.0
    max_drawdown = 0.0
    for value in returns:
        equity *= 1 + value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return {"trade_count": len(returns), "no_trade_count": no_trade_count,
            "profit_factor": gains / losses if losses > 0 else None,
            "trade_expectancy": sum(returns) / len(returns) if returns else None,
            "max_compounded_drawdown": max_drawdown,
            "cumulative_compounded_return": equity - 1}


def run_development_comparison(frozen: dict, prereg: dict, economic: dict) -> dict:
    family_ids = [family["id"] for family in economic["policy_families"]]
    feature_names = sorted(frozen["members"][0]["features"])
    results = []
    all_outcomes = frozen["outcomes"]
    for market in frozen["markets"]:
        symbol = market["market"]
        members = [row for row in frozen["members"] if row["market"] == symbol]
        outcomes = [row for row in all_outcomes if row["market"] == symbol]
        common = complete_comparison_members(members, outcomes, family_ids)
        summary = {"market": symbol, "joined": len(members),
                   "common_evaluable": len(common), "excluded_from_comparison": len(members) - len(common),
                   "candidates": [], "selected_development_candidate": None}
        if len(members) < prereg["minimum_joined_per_market"]:
            summary["status"] = "BELOW_JOINED_MINIMUM"
            results.append(summary)
            continue
        training, assessment = chronological_development_split(common)
        summary.update({"training_count": len(training), "assessment_count": len(assessment),
            "first_assessment_decision_utc": assessment[0]["decision_at_utc"] if assessment else None})
        if len(training) < 30 or len(assessment) < 15:
            summary["status"] = "INSUFFICIENT_CHRONOLOGICAL_SPLIT"
            results.append(summary)
            continue
        keyed = {(row["opportunity_id"], row["execution_policy_version"],
                  row["cost_sensitivity"], row["direction"]): float(row["net_return"])
                 for row in outcomes if row["status"] == "EVALUATED"}
        x_train = np.asarray([[float(row["features"][name]) for name in feature_names]
                              for row in training], dtype=float)
        x_test = np.asarray([[float(row["features"][name]) for name in feature_names]
                             for row in assessment], dtype=float)
        if not np.isfinite(x_train).all() or not np.isfinite(x_test).all():
            raise ValueError(f"Invalid frozen point-in-time feature: {symbol}")
        for family in family_ids:
            y_train = np.asarray([action_target(
                keyed[(row["opportunity_id"], family, "NORMAL_P75", "LONG")],
                keyed[(row["opportunity_id"], family, "NORMAL_P75", "SHORT")])
                for row in training])
            if len(set(y_train)) < 2:
                for model_name in ("LOGISTIC_REGRESSION", "RANDOM_FOREST", "HGB"):
                    summary["candidates"].append({"family": family, "model": model_name,
                        "status": "SINGLE_CLASS_TRAINING", "development_selectable": False})
                continue
            models = {name: selected_model_factory(name) for name in
                      ("LOGISTIC_REGRESSION", "RANDOM_FOREST", "HGB")}
            for model_name, model in models.items():
                model.fit(x_train, y_train)
                predictions = model.predict(x_test)
                metrics = {}
                for sensitivity in ("NORMAL_P75", "STRESSED_P95"):
                    returns = [keyed[(row["opportunity_id"], family, sensitivity,
                                      "LONG" if int(action) == 1 else "SHORT")]
                               for row, action in zip(assessment, predictions) if int(action) != 0]
                    metrics[sensitivity] = trade_metrics(returns,
                        sum(int(action) == 0 for action in predictions))
                normal, stressed = metrics["NORMAL_P75"], metrics["STRESSED_P95"]
                selectable = (normal["trade_count"] >= 10
                    and all(item["profit_factor"] is not None and item["profit_factor"] > 1
                            and item["trade_expectancy"] is not None and item["trade_expectancy"] > 0
                            for item in (normal, stressed)))
                summary["candidates"].append({"family": family, "model": model_name,
                    "status": "ASSESSED_DEVELOPMENT_ONLY", "training_class_counts":
                    dict(sorted(Counter(int(value) for value in y_train).items())),
                    "assessment_action_counts": dict(sorted(Counter(int(value) for value in predictions).items())),
                    "metrics": metrics, "development_selectable": selectable})
        eligible = [item for item in summary["candidates"] if item["development_selectable"]]
        if eligible:
            winner = sorted(eligible, key=lambda item: (
                -item["metrics"]["STRESSED_P95"]["trade_expectancy"],
                -item["metrics"]["STRESSED_P95"]["profit_factor"],
                item["model"], item["family"]))[0]
            summary["selected_development_candidate"] = {
                "family": winner["family"], "model": winner["model"]}
        summary["status"] = "DEVELOPMENT_ONLY_COMPLETE"
        results.append(summary)
    return {"feature_names": feature_names, "markets": results,
            "validation_accessed": False, "holdout_accessed": False,
            "model_promotion": "NONE", "broker_submission_authority": False}
