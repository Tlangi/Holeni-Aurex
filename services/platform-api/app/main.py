from contextlib import asynccontextmanager
import logging
from threading import Lock
from typing import AsyncIterator

from fastapi import BackgroundTasks, Depends, FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import (
    DatabaseUnavailable,
    check_database,
    operational_schema_ready,
    tenant_has_trading_account,
)
from app.dashboard import dashboard_unavailable_payload, read_dashboard
from app.forward_evidence import read_forward_evidence
from app.forward_promotion import read_forward_shadow_promotions
from app.demo_execution import (
    OneOffDemoExecutionRequest, execute_one_off_demo, read_demo_execution_attempts,
)
from app.ig_execution import IGExecutionBlocked, IGExecutionRejected, IGSubmissionUnknown
from app.ig_demo import IGDemoClient, IGDemoUnavailable
from app.ig_sync import SyncAlreadyRunning, sync_ig_demo
from app.holdout_service import (
    ApproveHoldoutRequest,
    EvaluateHoldoutRequest,
    FreezeCandidateRequest,
    ReserveResearchLineageRequest,
    approve_holdout_candidate,
    evaluate_holdout,
    freeze_candidate,
    read_holdout_status,
    reserve_research_lineage,
)
from app.auth import (
    AuthenticatedUser,
    LoginRequest,
    login_owner,
    logout_owner,
    require_user,
)
from app.observability import CorrelationLoggingMiddleware, configure_logging
from app.operations_status import read_operational_assurance
from app.scheduler import AccountSyncScheduler
from app.trading_status import read_trading_status
from app.markets import read_candles, read_market_inventory
from app.market_data_operations import read_market_data_operations
from app.market_intelligence import model_readiness
from app.model_monitoring import read_model_monitoring
from app.macro_intelligence import generate_market_decisions, read_macro_status, sync_official_macro_sources
from app.trades import read_trade_history
from app.readiness import read_trading_readiness
from app.replay_engine import ReplayRequest, read_replay_runs, run_replay
from app.research_evidence import sync_cost_models, sync_quality_evidence
from app.research_jobs import (
    enqueue_evidence_refresh,
    enqueue_protocol_audit,
    enqueue_selective_tournament,
    read_research_jobs,
)
from app.research_service import ResearchReplayRequest, read_research_status, run_research_replay
from app.model_tournament import ModelTournamentRequest, run_and_record_tournament
from app.trading_operations import (read_model_validation, read_order_intents, read_reconciliation_status,
                                    read_risk_status, read_shadow_trades)
from app.trading_controls import (
    EngineControlRequest, StrategyStatusRequest, change_engine_control,
    change_strategy_status, read_strategies,
)

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("aurex.research")
_research_evidence_refresh_lock = Lock()


def _refresh_research_evidence() -> None:
    try:
        sync_quality_evidence(settings)
        sync_cost_models(settings)
    except Exception:
        logger.exception("Research evidence refresh failed")
    finally:
        _research_evidence_refresh_lock.release()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    scheduler = AccountSyncScheduler(settings)
    if operational_schema_ready(settings):
        scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
)
app.add_middleware(CorrelationLoggingMiddleware)


@app.post("/api/v1/auth/login", tags=["authentication"])
def auth_login(credentials: LoginRequest, request: Request, response: Response) -> dict[str, object]:
    user = login_owner(credentials, request, response, settings)
    return {
        "user": {
            "id": user.user_id,
            "tenant_id": user.tenant_id,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role,
        }
    }


@app.post("/api/v1/auth/logout", tags=["authentication"])
def auth_logout(
    request: Request,
    response: Response,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, str]:
    logout_owner(request, response, user, settings)
    return {"status": "logged_out"}


@app.get("/api/v1/auth/me", tags=["authentication"])
def auth_me(user: AuthenticatedUser = Depends(require_user)) -> dict[str, object]:
    return {
        "user": {
            "id": user.user_id,
            "tenant_id": user.tenant_id,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role,
        }
    }


@app.get("/health/live", tags=["health"])
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def health_ready() -> JSONResponse:
    database_ready, database_status = check_database(settings)
    payload = {
        "status": "ready" if database_ready else "not_ready",
        "checks": {
            "database": database_status,
            "smtp": "configured" if settings.smtp_configured else "not_configured",
            "ig_demo": "configured" if settings.ig_configured else "not_configured",
        },
        "safety": {
            "trading_mode": settings.trading_mode,
            "broker_environment": settings.broker_environment,
        },
    }
    return JSONResponse(
        content=payload,
        status_code=status.HTTP_200_OK if database_ready else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@app.get("/api/v1/dashboard", tags=["dashboard"])
def dashboard(user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    try:
        return JSONResponse(content=read_dashboard(settings, user.tenant_id))
    except DatabaseUnavailable:
        return JSONResponse(
            content=dashboard_unavailable_payload(settings),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@app.get("/api/v1/trading/status", tags=["trading"])
def trading_status(user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    """Read trading readiness and safety gates; this endpoint cannot submit orders."""
    try:
        return JSONResponse(content=read_trading_status(settings, user.tenant_id))
    except DatabaseUnavailable:
        return JSONResponse(
            content={"status": "unavailable", "message": "Database is unavailable"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@app.get("/api/v1/trading/readiness", tags=["trading"])
def trading_readiness(user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    """Evaluate every known demo-auto gate. This route cannot enable or submit orders."""
    payload = read_trading_readiness(settings, user.tenant_id)
    return JSONResponse(content=payload)


@app.get("/api/v1/models/readiness", tags=["models"])
def models_readiness(user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    """Return data and validation evidence separately for every enabled market."""
    try:
        return JSONResponse(content=jsonable_encoder(model_readiness(settings, user.tenant_id)))
    except DatabaseUnavailable:
        return JSONResponse(content={"status": "unavailable", "markets": []}, status_code=503)


@app.get("/api/v1/models/validation", tags=["models"])
def models_validation(user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    return JSONResponse(content=read_model_validation(settings, user.tenant_id))


@app.get("/api/v1/models/monitoring", tags=["models"])
def models_monitoring(user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    """Read feature, calibration and cost drift evidence; never change model status."""
    return JSONResponse(content=jsonable_encoder(read_model_monitoring(settings, user.tenant_id)))


@app.post("/api/v1/replay/runs", tags=["replay"])
def create_replay(
    body: ReplayRequest, user: AuthenticatedUser = Depends(require_user),
) -> JSONResponse:
    """Run an offline, persisted replay. This route has no broker capability."""
    try:
        return JSONResponse(content=run_replay(settings, user.tenant_id, body))
    except ValueError as exc:
        return JSONResponse(content={"status": "blocked", "message": str(exc)}, status_code=409)


@app.get("/api/v1/replay/runs", tags=["replay"])
def replay_runs(limit: int = 20, user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    return JSONResponse(content=read_replay_runs(settings, user.tenant_id, limit=limit))


@app.get("/api/v1/research/status", tags=["research"])
def research_status(limit: int = 20, user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    """Read strategy evidence. This route has no execution capability."""
    return JSONResponse(content=jsonable_encoder(read_research_status(settings, user.tenant_id, limit=limit)))


@app.post("/api/v1/research/evidence/sync", tags=["research"])
def research_evidence_sync(
    background_tasks: BackgroundTasks, user: AuthenticatedUser = Depends(require_user),
) -> JSONResponse:
    """Queue a durable evidence refresh without training or execution."""
    if user.role.lower() not in {"owner", "administrator", "admin"}:
        return JSONResponse(content={"status": "forbidden", "message": "Owner role is required",
                                     "execution_enabled": False}, status_code=403)
    return JSONResponse(content=enqueue_evidence_refresh(
        settings, user.tenant_id, user.user_id,
    ), status_code=202)


@app.get("/api/v1/research/jobs", tags=["research"])
def research_job_status(limit: int = 20, user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    return JSONResponse(content=read_research_jobs(settings, user.tenant_id, limit))


@app.post("/api/v1/research/protocol/audit", tags=["research"])
def research_protocol_audit(user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    """Queue development-only leakage and provider-boundary audits."""
    if user.role.lower() not in {"owner", "administrator", "admin"}:
        return JSONResponse(content={"status": "forbidden", "message": "Owner role is required",
                                     "execution_enabled": False}, status_code=403)
    return JSONResponse(content=enqueue_protocol_audit(
        settings, user.tenant_id, user.user_id,
    ), status_code=202)


@app.post("/api/v1/research/replay", tags=["research"])
def research_replay(
    body: ResearchReplayRequest, user: AuthenticatedUser = Depends(require_user),
) -> JSONResponse:
    """Run a non-promotable replay of the latest model and persist diagnostics."""
    try:
        return JSONResponse(content=run_research_replay(settings, user.tenant_id, body))
    except ValueError as exc:
        return JSONResponse(content={"status": "blocked", "message": str(exc),
                                     "execution_enabled": False}, status_code=409)


@app.post("/api/v1/research/model-tournament", tags=["research"])
def research_model_tournament(
    body: ModelTournamentRequest, user: AuthenticatedUser = Depends(require_user),
) -> JSONResponse:
    """Compare local challengers on development data; never promote or execute."""
    try:
        return JSONResponse(content=jsonable_encoder(
            run_and_record_tournament(settings, user.tenant_id, body.market, notes=body.notes),
        ))
    except ValueError as exc:
        return JSONResponse(content={"status": "blocked", "message": str(exc),
                                     "execution_enabled": False}, status_code=409)


@app.post("/api/v1/research/selective-tournament", tags=["research"])
def research_selective_tournament(
    body: ModelTournamentRequest, user: AuthenticatedUser = Depends(require_user),
) -> JSONResponse:
    """Queue a target-bound development-only tournament; never inspect holdout or execute."""
    try:
        return JSONResponse(content=jsonable_encoder(enqueue_selective_tournament(
            settings, user.tenant_id, user.user_id, body.market, body.notes,
        )), status_code=202)
    except ValueError as exc:
        return JSONResponse(content={"status": "blocked", "message": str(exc),
                                     "execution_enabled": False}, status_code=409)


@app.get("/api/v1/research/holdout", tags=["research"])
def research_holdout_status(user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    """Read immutable candidate and single-use holdout evidence."""
    return JSONResponse(content=jsonable_encoder(read_holdout_status(settings, user.tenant_id)))


@app.post("/api/v1/research/lineage/reserve", tags=["research"])
def research_lineage_reserve(
    body: ReserveResearchLineageRequest, user: AuthenticatedUser = Depends(require_user),
) -> JSONResponse:
    """Pre-register research choices and reserve the untouched final holdout."""
    try:
        return JSONResponse(content=jsonable_encoder(reserve_research_lineage(
            settings, user.tenant_id, user.user_id, user.role, body,
        )))
    except PermissionError as exc:
        return JSONResponse(content={"status": "forbidden", "message": str(exc),
                                     "execution_enabled": False}, status_code=403)
    except ValueError as exc:
        return JSONResponse(content={"status": "blocked", "message": str(exc),
                                     "execution_enabled": False}, status_code=409)


@app.post("/api/v1/research/holdout/freeze", tags=["research"])
def research_holdout_freeze(
    body: FreezeCandidateRequest, user: AuthenticatedUser = Depends(require_user),
) -> JSONResponse:
    """Freeze development evidence without reading or enabling the final holdout."""
    try:
        return JSONResponse(content=jsonable_encoder(freeze_candidate(settings, user.tenant_id, body)))
    except ValueError as exc:
        return JSONResponse(content={"status": "blocked", "message": str(exc),
                                     "execution_enabled": False}, status_code=409)


@app.post("/api/v1/research/holdout/evaluate", tags=["research"])
def research_holdout_evaluate(
    body: EvaluateHoldoutRequest, user: AuthenticatedUser = Depends(require_user),
) -> JSONResponse:
    """Consume one frozen holdout exactly once; never promote or submit an order."""
    try:
        return JSONResponse(content=jsonable_encoder(evaluate_holdout(settings, user.tenant_id, body)))
    except ValueError as exc:
        return JSONResponse(content={"status": "blocked", "message": str(exc),
                                     "execution_enabled": False}, status_code=409)


@app.post("/api/v1/research/holdout/approve", tags=["research"])
def research_holdout_approve(
    body: ApproveHoldoutRequest, user: AuthenticatedUser = Depends(require_user),
) -> JSONResponse:
    """Owner approval binds one passed artifact; it enables forward shadow only."""
    try:
        return JSONResponse(content=jsonable_encoder(approve_holdout_candidate(
            settings, user.tenant_id, user.user_id, user.role, body,
        )))
    except PermissionError as exc:
        return JSONResponse(content={"status": "forbidden", "message": str(exc),
                                     "execution_enabled": False}, status_code=403)
    except ValueError as exc:
        return JSONResponse(content={"status": "blocked", "message": str(exc),
                                     "execution_enabled": False}, status_code=409)


@app.get("/api/v1/macro/status", tags=["macro-intelligence"])
def macro_status(user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    """Read official-source evidence, currency scores and the latest audited decisions."""
    try:
        return JSONResponse(content=read_macro_status(settings, user.tenant_id))
    except DatabaseUnavailable:
        return JSONResponse(content={"status": "unavailable", "sources": [], "currencies": [], "decisions": []}, status_code=503)


@app.post("/api/v1/macro/sync", tags=["macro-intelligence"])
def macro_sync(user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    """Refresh allow-listed official sources and decisions; this route cannot submit an order."""
    result = sync_official_macro_sources(settings)
    result["decisions"] = generate_market_decisions(settings, user.tenant_id)
    result["execution_enabled"] = False
    return JSONResponse(content=result)


@app.get("/api/v1/shadow/trades", tags=["trading"])
def shadow_trades(limit: int = 50, user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    return JSONResponse(content=read_shadow_trades(settings, user.tenant_id, limit=limit))


@app.get("/api/v1/forward-shadow/promotion", tags=["trading"])
def forward_shadow_promotion(user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    return JSONResponse(content=read_forward_shadow_promotions(settings, user.tenant_id))


@app.get("/api/v1/demo-execution/attempts", tags=["trading"])
def demo_execution_attempts(
    limit: int = 20, user: AuthenticatedUser = Depends(require_user),
) -> JSONResponse:
    return JSONResponse(content=read_demo_execution_attempts(settings, user.tenant_id, limit))


@app.post("/api/v1/demo-execution/one-off", tags=["trading"])
def one_off_demo_execution(
    payload: OneOffDemoExecutionRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> JSONResponse:
    if user.role != "owner":
        return JSONResponse(content={"status": "forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
    try:
        result = execute_one_off_demo(
            settings, user.tenant_id, user.user_id, payload,
            correlation_id=getattr(request.state, "correlation_id", None),
        )
        return JSONResponse(content=result)
    except IGExecutionBlocked as exc:
        return JSONResponse(content={"status": "blocked", "message": str(exc)}, status_code=status.HTTP_409_CONFLICT)
    except IGExecutionRejected as exc:
        return JSONResponse(content={"status": "rejected", "reason": exc.reason}, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    except IGSubmissionUnknown:
        return JSONResponse(
            content={"status": "submission_unknown", "message": "Reconciliation is required; the order will not be retried"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@app.get("/api/v1/forward-evidence", tags=["trading"])
def forward_evidence(limit: int = 200, user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    """Read immutable forward observations. This route cannot enable or submit orders."""
    return JSONResponse(content=read_forward_evidence(settings, user.tenant_id, limit=limit))


@app.post("/api/v1/trading/control", tags=["trading"])
def trading_control(
    body: EngineControlRequest, request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> JSONResponse:
    try:
        return JSONResponse(content=change_engine_control(
            settings, user, body, correlation_id=getattr(request.state, "correlation_id", None)
        ))
    except PermissionError as exc:
        return JSONResponse(content={"status": "forbidden", "message": str(exc)}, status_code=403)
    except ValueError as exc:
        return JSONResponse(content={"status": "blocked", "message": str(exc)}, status_code=409)


@app.get("/api/v1/strategies", tags=["trading"])
def strategies(user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    return JSONResponse(content=read_strategies(settings, user.tenant_id))


@app.patch("/api/v1/strategies/{strategy_id}", tags=["trading"])
def strategy_status(
    strategy_id: str, body: StrategyStatusRequest, request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> JSONResponse:
    try:
        return JSONResponse(content=change_strategy_status(
            settings, user, strategy_id, body,
            correlation_id=getattr(request.state, "correlation_id", None),
        ))
    except PermissionError as exc:
        return JSONResponse(content={"status": "forbidden", "message": str(exc)}, status_code=403)
    except LookupError as exc:
        return JSONResponse(content={"status": "not_found", "message": str(exc)}, status_code=404)


@app.get("/api/v1/markets", tags=["markets"])
def market_inventory(user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    try:
        return JSONResponse(content=read_market_inventory(settings, user.tenant_id))
    except PermissionError as exc:
        return JSONResponse(content={"status": "forbidden", "message": str(exc)}, status_code=403)
    except DatabaseUnavailable:
        return JSONResponse(content={"status": "unavailable"}, status_code=503)


@app.get("/api/v1/market-data/operations", tags=["markets"])
def market_data_operations(user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    """Read quarantined provider rows and bounded recovery jobs."""
    return JSONResponse(content=jsonable_encoder(read_market_data_operations(settings)))


@app.get("/api/v1/markets/candles", tags=["markets"])
def market_candles(
    symbol: str = "EURUSD",
    timeframe: str = "M5",
    limit: int = 100,
    period: str = "7D",
    user: AuthenticatedUser = Depends(require_user),
) -> JSONResponse:
    try:
        return JSONResponse(
            content=read_candles(
                settings, user.tenant_id, symbol=symbol, timeframe=timeframe, limit=limit,
                period=period,
            )
        )
    except ValueError as exc:
        return JSONResponse(
            content={"status": "invalid_request", "message": str(exc)},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except PermissionError as exc:
        return JSONResponse(
            content={"status": "forbidden", "message": str(exc)},
            status_code=status.HTTP_403_FORBIDDEN,
        )
    except DatabaseUnavailable:
        return JSONResponse(
            content={"status": "unavailable", "message": "Database is unavailable"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@app.get("/api/v1/trades/history", tags=["trading"])
def trade_history(
    limit: int = 50,
    user: AuthenticatedUser = Depends(require_user),
) -> JSONResponse:
    try:
        return JSONResponse(content=read_trade_history(settings, user.tenant_id, limit=limit))
    except DatabaseUnavailable:
        return JSONResponse(
            content={"status": "unavailable", "message": "Database is unavailable"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@app.get("/api/v1/orders", tags=["trading"])
def orders(limit: int = 50, user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    try:
        return JSONResponse(content=read_order_intents(settings, user.tenant_id, limit=limit))
    except DatabaseUnavailable:
        return JSONResponse(content={"status": "unavailable"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


@app.get("/api/v1/markets", tags=["markets"])
def market_inventory(user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    try:
        return JSONResponse(content=read_market_inventory(settings, user.tenant_id))
    except PermissionError as exc:
        return JSONResponse(content={"status": "forbidden", "message": str(exc)}, status_code=403)
    except DatabaseUnavailable:
        return JSONResponse(content={"status": "unavailable"}, status_code=503)


@app.get("/api/v1/risk/status", tags=["trading"])
def risk_status(user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    try:
        return JSONResponse(content=read_risk_status(settings, user.tenant_id))
    except DatabaseUnavailable:
        return JSONResponse(content={"status": "unavailable"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


@app.get("/api/v1/reconciliation", tags=["trading"])
def reconciliation(limit: int = 50, user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    try:
        return JSONResponse(content=read_reconciliation_status(settings, user.tenant_id, limit=limit))
    except DatabaseUnavailable:
        return JSONResponse(content={"status": "unavailable"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


@app.get("/api/v1/operations/status", tags=["operations"])
def operations_status(
    limit: int = 10, user: AuthenticatedUser = Depends(require_user),
) -> JSONResponse:
    try:
        return JSONResponse(
            content=jsonable_encoder(read_operational_assurance(settings, user.tenant_id, limit=limit))
        )
    except DatabaseUnavailable:
        return JSONResponse(content={"status": "unavailable"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


@app.get("/api/v1/integrations/ig/status", tags=["integrations"])
def ig_demo_status(user: AuthenticatedUser = Depends(require_user)) -> JSONResponse:
    """Authenticate and read account metadata; never places or changes an order."""
    try:
        if not tenant_has_trading_account(settings, user.tenant_id):
            return JSONResponse(
                content={"status": "unavailable", "message": "No tenant trading account"},
                status_code=status.HTTP_404_NOT_FOUND,
            )
        with IGDemoClient(settings) as client:
            account = client.account()
            positions = client.positions()
            conversion = client.zar_rate(account.currency)
        return JSONResponse(
            content={
                "status": "connected",
                "message": "IG demo connection is current",
                "environment": "demo",
                "account": {
                    "id": account.masked_account_id,
                    "name": account.account_name,
                    "currency": account.currency,
                    "open_positions": len(positions),
                    "reporting_currency": "ZAR",
                    "conversion_source": conversion.source,
                    "conversion_observed_at_utc": conversion.observed_at_utc.isoformat(),
                },
                "execution_enabled": False,
            }
        )
    except (IGDemoUnavailable, ValueError) as exc:
        return JSONResponse(
            content={"status": "unavailable", "message": str(exc), "execution_enabled": False},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@app.post("/api/v1/integrations/ig/sync", tags=["integrations"])
def synchronise_ig_demo(
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> JSONResponse:
    """Read IG demo data and persist it. This endpoint cannot place orders."""
    try:
        if not tenant_has_trading_account(settings, user.tenant_id):
            return JSONResponse(
                content={"status": "unavailable", "message": "No tenant trading account"},
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return JSONResponse(
            content=sync_ig_demo(
                settings, correlation_id=getattr(request.state, "correlation_id", None)
            )
        )
    except IGDemoUnavailable as exc:
        return JSONResponse(
            content={"status": "unavailable", "message": str(exc), "execution_enabled": False},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except SyncAlreadyRunning as exc:
        return JSONResponse(
            content={"status": "busy", "message": str(exc), "execution_enabled": False},
            status_code=status.HTTP_409_CONFLICT,
        )
    except DatabaseUnavailable:
        return JSONResponse(
            content={"status": "unavailable", "message": "Database is unavailable"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    approve_holdout_candidate,
