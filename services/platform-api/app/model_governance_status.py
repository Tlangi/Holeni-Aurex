from __future__ import annotations


def model_governance_blocker(row: dict[str, object]) -> str | None:
    """Return the next honest governance gate for one market.

    Owner approval is deliberately last: it must never disguise a failed
    development or holdout evaluation.
    """
    if bool(row.get("governed_model")):
        return None
    if bool(row.get("owner_review_required")):
        return "OWNER_MODEL_APPROVAL_REQUIRED"
    if bool(row.get("development_passed")):
        return "NO_HOLDOUT_PASSED_MODEL"
    return "NO_DEVELOPMENT_PASSED_MODEL"


MODEL_GOVERNANCE_STAGE_SQL = """
CASE WHEN EXISTS(
  SELECT 1 FROM app.model_versions mv
  JOIN app.holdout_candidates hc ON hc.holdout_candidate_id=mv.holdout_candidate_id
  WHERE mv.market_id=m.market_id AND mv.status='VALIDATED'
    AND hc.status='OWNER_APPROVED' AND mv.artifact_sha256=hc.artifact_sha256
) THEN 1 ELSE 0 END governed_model,
CASE WHEN EXISTS(
  SELECT 1 FROM app.holdout_candidates hc
  WHERE hc.market_id=m.market_id AND hc.status='OWNER_REVIEW_REQUIRED'
) THEN 1 ELSE 0 END owner_review_required,
CASE WHEN EXISTS(
  SELECT 1 FROM app.model_versions mv
  WHERE mv.market_id=m.market_id
    AND mv.status IN ('DEVELOPMENT_PASSED','HOLDOUT_PASSED')
) OR EXISTS(
  SELECT 1 FROM app.holdout_candidates hc
  WHERE hc.market_id=m.market_id
    AND hc.status IN ('FROZEN','EVALUATING','HOLDOUT_PASSED','OWNER_REVIEW_REQUIRED','OWNER_APPROVED')
) THEN 1 ELSE 0 END development_passed
"""
