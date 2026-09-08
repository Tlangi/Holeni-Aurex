from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    """Configuration loaded from the local, untracked .env file."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Aurex Platform API"
    app_env: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8010
    web_host: str = "127.0.0.1"
    web_port: int = 4210
    web_origins: str = "http://127.0.0.1:4210,http://localhost:4210"

    sql_server: str = "localhost\\SQLEXPRESS"
    sql_host: str = "127.0.0.1"
    sql_port: int = 1433
    sql_database: str = "ForexSaas"
    sql_username: str = "ForexSaasApp"
    sql_password: str = Field(default="", repr=False)
    sql_driver: str = "ODBC Driver 18 for SQL Server"
    sql_encrypt: bool = True
    sql_trust_server_certificate: bool = True
    trusted_hosts: str = "127.0.0.1,localhost"

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = Field(
        default="", validation_alias=AliasChoices("SMTP_USERNAME", "GMAIL_SMTP_USER")
    )
    smtp_password: str = Field(
        default="",
        repr=False,
        validation_alias=AliasChoices("SMTP_PASSWORD", "GMAIL_SMTP_APP_PASSWORD"),
    )
    smtp_from_email: str = Field(
        default="", validation_alias=AliasChoices("SMTP_FROM_EMAIL", "SMTP_FROM")
    )
    smtp_from_name: str = "Aurex"
    smtp_use_tls: bool = True
    trade_report_recipient: str = ""

    ig_api_key: str = Field(default="", repr=False)
    ig_username: str = Field(default="", repr=False)
    ig_password: str = Field(default="", repr=False)
    ig_account_id: str = ""
    ig_environment: str = "demo"
    allow_demo_trading: bool = False
    allow_live_trading: bool = False
    experimental_demo_enabled: bool = False

    reporting_currency: str = "ZAR"
    app_timezone: str = "Africa/Johannesburg"
    app_locale: str = "en-ZA"
    owner_display_name: str = "Demo owner"
    owner_email: str = ""
    session_cookie_name: str = "aurex_session"
    csrf_cookie_name: str = "aurex_csrf"
    csrf_header_name: str = "x-aurex-csrf"
    session_hours: int = 12
    session_cookie_secure: bool = False
    auth_hash_pepper: str = Field(default="", repr=False)
    auth_failure_window_minutes: int = Field(default=15, ge=5, le=60)
    auth_max_email_failures: int = Field(default=5, ge=3, le=20)
    auth_max_address_failures: int = Field(default=20, ge=5, le=100)
    auth_lockout_minutes: int = Field(default=30, ge=5, le=1440)
    background_sync_enabled: bool = True
    account_sync_seconds: int = 60
    stale_after_seconds: int = 180
    shadow_cycle_seconds: int = 30
    broker_rule_sync_seconds: int = 900
    model_training_check_seconds: int = 21600
    model_minimum_rows: int = 2000
    model_minimum_new_rows: int = 96
    model_acceptance_auc: float = 0.52
    model_walk_forward_windows: int = 3
    model_minimum_trades: int = 20
    model_round_trip_cost_bps: float = 1.0
    model_max_drawdown_pct: float = 10.0
    macro_intelligence_enabled: bool = True
    macro_sync_seconds: int = 900
    macro_source_timeout_seconds: int = 15
    macro_evidence_max_age_hours: int = 168
    macro_event_blackout_minutes: int = 60
    macro_decision_threshold: float = 0.35
    intelligence_enabled: bool = False
    llm_provider: str = "disabled"
    llm_model_fast: str = ""
    llm_model_deep: str = ""
    llm_base_url: str = ""
    llm_api_key: str = Field(default="", repr=False)
    llm_timeout_seconds: int = Field(default=30, ge=5, le=180)
    llm_max_retries: int = Field(default=1, ge=0, le=3)
    llm_circuit_failure_threshold: int = Field(default=3, ge=1, le=20)
    historical_backfill_enabled: bool = False
    historical_backfill_poll_seconds: int = Field(default=60, ge=15, le=3600)
    historical_backfill_min_free_gb: int = Field(default=20, ge=5, le=1000)
    historical_backfill_max_attempts: int = Field(default=3, ge=1, le=10)
    historical_minimum_coverage: float = Field(default=0.985, ge=0.95, le=1.0)
    historical_maximum_largest_gap_minutes: int = Field(default=15, ge=1, le=240)
    historical_maximum_unexpected_gaps: int = Field(default=250, ge=0, le=5000)
    historical_maximum_rejected_tick_ratio: float = Field(default=0.001, ge=0.0, le=0.01)
    historical_minimum_cross_source_candles: int = Field(default=100, ge=20, le=10000)
    historical_minimum_cross_source_match: float = Field(default=0.99, ge=0.90, le=1.0)
    historical_cross_source_tolerance_ratio: float = Field(default=0.0005, ge=0.00001, le=0.01)
    log_level: str = "INFO"
    health_monitor_seconds: int = 60
    operational_alert_cooldown_minutes: int = 60
    daily_progress_report_enabled: bool = True
    daily_progress_report_hour_sast: int = Field(default=18, ge=0, le=23)
    backup_directory: str = "C:\\Projects\\Forex\\operations\\backups"
    replay_slippage_bps: float = 0.5
    replay_funding_bps_per_day: float = 0.25
    forward_evidence_seconds: int = 900
    market_quality_check_seconds: int = 3600
    execution_m5_fresh_seconds: int = 900
    execution_m15_fresh_seconds: int = 1800
    execution_quote_fresh_seconds: int = 900
    broker_rule_fresh_seconds: int = 86400
    execution_gap_lookback_hours: int = 24
    research_segment_minimum_completeness: float = 0.985
    cost_model_minimum_observations: int = 50
    cost_model_optimistic_percentile: float = 50.0
    cost_model_normal_percentile: float = 75.0
    cost_model_stressed_percentile: float = 95.0
    research_confidence_buckets: str = "0.50,0.55,0.60,0.65,0.70,1.00"
    max_research_cpu_threads: int = Field(default=2, ge=1, le=8)
    holdout_fraction: float = 0.20
    holdout_minimum_rows: int = 500
    holdout_minimum_trades: int = 30
    holdout_minimum_profit_factor: float = 1.10
    holdout_maximum_drawdown_pct: float = 3.0
    holdout_maximum_calibration_error: float = 0.20
    holdout_maximum_feature_drift: float = 1.0
    holdout_minimum_regime_coverage: float = 0.50

    trading_mode: str = "disabled"
    broker_environment: str = "demo"

    @model_validator(mode="after")
    def enforce_external_security(self) -> "Settings":
        if self.app_env.lower() in {"production", "staging"}:
            missing = []
            if len(self.auth_hash_pepper) < 32: missing.append("AUTH_HASH_PEPPER")
            if not self.session_cookie_secure: missing.append("SESSION_COOKIE_SECURE")
            sql_is_loopback = self.sql_host.lower() in {"127.0.0.1", "localhost", "::1"} or \
                self.sql_server.lower().split("\\", 1)[0] in {".", "(local)", "localhost", "127.0.0.1"}
            if self.sql_trust_server_certificate and not sql_is_loopback:
                missing.append("SQL_TRUST_SERVER_CERTIFICATE")
            if any(origin.startswith("http://") for origin in self.allowed_origins):
                missing.append("HTTPS_WEB_ORIGINS")
            if missing:
                raise ValueError("External deployment security requirements missing: " + ",".join(missing))
        return self

    @field_validator("trading_mode")
    @classmethod
    def enforce_safe_trading_mode(cls, value: str) -> str:
        if value.lower() not in {"disabled", "demo"}:
            raise ValueError("Only 'disabled' and 'demo' trading modes are allowed")
        return value.lower()

    @field_validator("sql_server")
    @classmethod
    def normalize_named_instance(cls, value: str) -> str:
        # Dotenv values are literal; users often copy a language-escaped `\\`.
        while "\\\\" in value:
            value = value.replace("\\\\", "\\")
        return value

    @field_validator("broker_environment")
    @classmethod
    def enforce_demo_broker(cls, value: str) -> str:
        if value.lower() != "demo":
            raise ValueError("The platform currently supports the demo broker environment only")
        return "demo"

    @field_validator("ig_environment")
    @classmethod
    def enforce_demo_ig(cls, value: str) -> str:
        if value.lower() != "demo":
            raise ValueError("IG_ENVIRONMENT must remain 'demo' during this phase")
        return "demo"

    @field_validator("allow_live_trading")
    @classmethod
    def prohibit_live_trading(cls, value: bool) -> bool:
        if value:
            raise ValueError("ALLOW_LIVE_TRADING must remain false during this phase")
        return False

    @field_validator("model_minimum_rows")
    @classmethod
    def enforce_model_evidence_floor(cls, value: int) -> int:
        if value < 2000:
            raise ValueError("MODEL_MINIMUM_ROWS cannot be below the 2,000-row evidence floor")
        return value

    @field_validator("model_minimum_new_rows")
    @classmethod
    def enforce_model_retraining_increment(cls, value: int) -> int:
        if value < 24:
            raise ValueError("MODEL_MINIMUM_NEW_ROWS cannot be below 24 completed M15 candles")
        return value

    @field_validator("model_acceptance_auc")
    @classmethod
    def enforce_model_acceptance_range(cls, value: float) -> float:
        if not 0.5 <= value <= 0.9:
            raise ValueError("MODEL_ACCEPTANCE_AUC must be between 0.5 and 0.9")
        return value

    @field_validator("macro_sync_seconds")
    @classmethod
    def enforce_macro_sync_interval(cls, value: int) -> int:
        if value < 300:
            raise ValueError("MACRO_SYNC_SECONDS cannot be below 300")
        return value

    @field_validator("health_monitor_seconds")
    @classmethod
    def enforce_health_interval(cls, value: int) -> int:
        if value < 30:
            raise ValueError("HEALTH_MONITOR_SECONDS cannot be below 30")
        return value

    @field_validator("forward_evidence_seconds")
    @classmethod
    def enforce_forward_evidence_interval(cls, value: int) -> int:
        if value < 60:
            raise ValueError("FORWARD_EVIDENCE_SECONDS cannot be below 60")
        return value

    @field_validator("market_quality_check_seconds")
    @classmethod
    def enforce_quality_check_interval(cls, value: int) -> int:
        if value < 900:
            raise ValueError("MARKET_QUALITY_CHECK_SECONDS cannot be below 900")
        return value

    @field_validator("macro_decision_threshold")
    @classmethod
    def enforce_macro_decision_threshold(cls, value: float) -> float:
        if not 0.1 <= value <= 0.9:
            raise ValueError("MACRO_DECISION_THRESHOLD must be between 0.1 and 0.9")
        return value

    @field_validator("reporting_currency")
    @classmethod
    def enforce_zar_reporting(cls, value: str) -> str:
        if value.upper() != "ZAR":
            raise ValueError("REPORTING_CURRENCY must be ZAR for the South African launch")
        return "ZAR"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.web_origins.split(",") if origin.strip()]

    @property
    def allowed_hosts(self) -> list[str]:
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]

    @property
    def database_configured(self) -> bool:
        return bool(self.sql_server and self.sql_database and self.sql_username and self.sql_password)

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_username and self.smtp_password and self.smtp_from_email)

    @property
    def ig_configured(self) -> bool:
        return bool(self.ig_api_key and self.ig_username and self.ig_password and self.ig_account_id)

    @property
    def intelligence_provider_configured(self) -> bool:
        provider = self.llm_provider.strip().lower()
        if not self.intelligence_enabled or provider in {"", "disabled"}:
            return False
        if provider == "ollama":
            return bool(self.llm_base_url and (self.llm_model_fast or self.llm_model_deep))
        return bool(self.llm_api_key and (self.llm_model_fast or self.llm_model_deep))

    @property
    def demo_execution_configured(self) -> bool:
        """The immutable, fail-closed configuration gate for broker execution."""
        return (
            self.trading_mode == "demo"
            and self.ig_environment == "demo"
            and self.broker_environment == "demo"
            and self.allow_demo_trading
            and not self.allow_live_trading
            and self.ig_configured
        )

    @property
    def experimental_demo_configured(self) -> bool:
        """Independent fail-closed opt-in for the broker-evidence programme."""
        return (
            self.experimental_demo_enabled
            and self.trading_mode == "demo"
            and self.ig_environment == "demo"
            and self.broker_environment == "demo"
            and self.allow_demo_trading
            and not self.allow_live_trading
            and self.ig_configured
        )

    @property
    def odbc_connection_string(self) -> str:
        parts = [
            f"DRIVER={{{self.sql_driver}}}",
            f"SERVER={self.sql_server}",
            f"DATABASE={self.sql_database}",
            f"UID={self.sql_username}",
            f"PWD={self.sql_password}",
            f"Encrypt={'yes' if self.sql_encrypt else 'no'}",
            f"TrustServerCertificate={'yes' if self.sql_trust_server_certificate else 'no'}",
        ]
        return ";".join(parts)

    @property
    def sqlalchemy_database_url(self) -> str:
        return f"mssql+pyodbc:///?odbc_connect={quote_plus(self.odbc_connection_string)}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
