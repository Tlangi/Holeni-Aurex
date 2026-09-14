"""Isolated read-only owner summary API; never starts trading schedulers."""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.auth import AuthenticatedUser, authenticate_session_token
from app.config import Settings, get_settings
from app.database import DatabaseUnavailable
from app.owner_overview import read_market_summary, read_owner_readiness


app = FastAPI(title="Aurex owner summaries", docs_url=None, redoc_url=None, openapi_url=None)


def owner_session(request: Request, settings: Settings = Depends(get_settings)) -> AuthenticatedUser:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        user = authenticate_session_token(token, settings)
    except DatabaseUnavailable:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Platform data unavailable") from None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    return user


def _response(payload: dict[str, object], status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=payload, status_code=status_code, headers={"Cache-Control": "no-store"})


@app.get("/api/v1/owner/readiness")
def readiness(user: AuthenticatedUser = Depends(owner_session),
              settings: Settings = Depends(get_settings)) -> JSONResponse:
    try:
        return _response(read_owner_readiness(settings, user.tenant_id))
    except DatabaseUnavailable:
        return _response({"overall_health": "OFFLINE", "blocking_reasons": [
            {"code": "DATABASE_UNAVAILABLE", "message": "Platform data is unavailable.", "action": "View System"},
        ]}, 503)


@app.get("/api/v1/owner/markets")
def markets(user: AuthenticatedUser = Depends(owner_session),
            settings: Settings = Depends(get_settings)) -> JSONResponse:
    try:
        return _response(read_market_summary(settings, user.tenant_id))
    except PermissionError:
        return _response({"status": "forbidden", "markets": []}, 403)
    except DatabaseUnavailable:
        return _response({"status": "unavailable", "markets": []}, 503)
