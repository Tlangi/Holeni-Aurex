from __future__ import annotations

import math


def clamp_volume(raw: float, minimum: float, maximum: float, step: float) -> float:
    if step <= 0:
        raise ValueError("Volume step must be positive")
    if minimum <= 0 or maximum < minimum:
        raise ValueError("Invalid volume limits")
    units = math.floor(raw / step + 1e-9)
    volume = min(maximum, units * step)
    if volume < minimum:
        raise ValueError("Calculated volume is below the broker minimum; trade blocked")
    return round(volume, 8)


def position_size(equity: float, risk_pct: float, stop_distance: float,
                  tick_size: float, tick_value: float, volume_min: float,
                  volume_max: float, volume_step: float, configured_max: float) -> float:
    if min(equity, stop_distance, tick_size, tick_value) <= 0:
        raise ValueError("Invalid sizing input")
    cash_risk = equity * risk_pct / 100
    cash_loss_per_lot = (stop_distance / tick_size) * tick_value
    raw = cash_risk / cash_loss_per_lot
    return clamp_volume(raw, volume_min, min(volume_max, configured_max), volume_step)


def daily_loss_blocked(equity: float, start_equity: float, max_loss_pct: float) -> bool:
    return start_equity > 0 and ((start_equity-equity) / start_equity * 100) >= max_loss_pct
