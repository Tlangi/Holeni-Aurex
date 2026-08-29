import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import open_database


settings = get_settings()
print({
    "trading_mode": settings.trading_mode,
    "allow_demo": settings.allow_demo_trading,
    "allow_live": settings.allow_live_trading,
    "demo_execution_configured": settings.demo_execution_configured,
})
with open_database(settings) as connection:
    cursor = connection.cursor(as_dict=True)
    checks = {
        "migration": "SELECT COUNT(*) value FROM app.schema_migrations WHERE migration_id='027_model_governance_and_durable_jobs'",
        "lineage_table": "SELECT CASE WHEN OBJECT_ID('app.research_lineages') IS NULL THEN 0 ELSE 1 END value",
        "jobs_table": "SELECT CASE WHEN OBJECT_ID('app.research_jobs') IS NULL THEN 0 ELSE 1 END value",
        "margin_column": "SELECT CASE WHEN COL_LENGTH('app.broker_market_rules','margin_factor_pct') IS NULL THEN 0 ELSE 1 END value",
        "demo_attempts": "SELECT COUNT(*) value FROM app.demo_execution_attempts",
        "governed_validated_models": """SELECT COUNT(*) value FROM app.model_versions mv
            JOIN app.holdout_candidates hc ON hc.holdout_candidate_id=mv.holdout_candidate_id
            WHERE mv.status='VALIDATED' AND hc.status='OWNER_APPROVED'
              AND mv.artifact_sha256=hc.artifact_sha256""",
        "margin_rules_populated": "SELECT COUNT(*) value FROM app.broker_market_rules WHERE margin_factor_pct IS NOT NULL",
    }
    print({name: (cursor.execute(query), cursor.fetchone()["value"])[1] for name, query in checks.items()})
