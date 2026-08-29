from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import yaml
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    data: dict
    ig_api_key: str
    ig_username: str
    ig_password: str
    ig_account_id: str
    ig_environment: str
    allow_live: bool
    unlock_phrase: str
    gmail_user: str
    gmail_app_password: str
    report_recipient: str


def load_settings(path: str = "config.yaml") -> Settings:
    load_dotenv()
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    settings = Settings(
        data=data,
        ig_api_key=os.environ.get("IG_API_KEY", ""),
        ig_username=os.environ.get("IG_USERNAME", ""),
        ig_password=os.environ.get("IG_PASSWORD", ""),
        ig_account_id=os.environ.get("IG_ACCOUNT_ID", ""),
        ig_environment=os.environ.get("IG_ENVIRONMENT", "demo").lower(),
        allow_live=os.environ.get("ALLOW_LIVE_TRADING", "false").lower() == "true",
        unlock_phrase=os.environ.get("LIVE_UNLOCK_PHRASE", ""),
        gmail_user=os.environ.get("GMAIL_SMTP_USER", ""),
        gmail_app_password=os.environ.get("GMAIL_SMTP_APP_PASSWORD", ""),
        report_recipient=os.environ.get("TRADE_REPORT_RECIPIENT", "larrymaswanganye@gmail.com"),
    )
    _validate(settings)
    return settings


def _validate(settings: Settings) -> None:
    data = settings.data
    required = {"symbols", "timeframe", "history_bars", "model", "risk", "reporting"}
    missing = required - set(data or {})
    if missing:
        raise ValueError(f"Missing configuration sections: {sorted(missing)}")
    if not data["symbols"] or len(set(data["symbols"])) != len(data["symbols"]):
        raise ValueError("Symbols must be a non-empty unique list")
    if data["timeframe"] not in TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe: {data['timeframe']}")
    if settings.ig_environment not in {"demo", "live"}:
        raise ValueError("IG_ENVIRONMENT must be demo or live")
    if settings.ig_environment == "live" and not (settings.allow_live and settings.unlock_phrase == "I_ACCEPT_LIVE_TRADING_RISK"):
        raise PermissionError("IG live configuration blocked by the double safety lock")
    if set(data["symbols"]) != set(data["instruments"]):
        raise ValueError("Each symbol must have exactly one IG instrument mapping")
    model, risk = data["model"], data["risk"]
    if not 0 < model["sell_probability"] < model["buy_probability"] < 1:
        raise ValueError("Signal probabilities must satisfy 0 < sell < buy < 1")
    if not 0 < risk["risk_per_trade_pct"] <= 1:
        raise ValueError("risk_per_trade_pct must be greater than 0 and no more than 1")
    if not 0 < risk["max_daily_loss_pct"] <= 10:
        raise ValueError("max_daily_loss_pct must be greater than 0 and no more than 10")
    hour = data["reporting"]["daily_email_hour_local"]
    if not isinstance(hour, int) or not 0 <= hour <= 23:
        raise ValueError("daily_email_hour_local must be an integer from 0 to 23")


TIMEFRAMES = {
    "M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4",
}
