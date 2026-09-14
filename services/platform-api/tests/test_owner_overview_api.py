from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

from app.auth import AuthenticatedUser
from app.owner_overview_api import app, markets, owner_session, readiness


def test_owner_summary_routes_live_only_in_read_only_service():
    from app.main import app as trading_api

    summary_paths = {"/api/v1/owner/readiness", "/api/v1/owner/markets"}
    assert summary_paths <= set(app.openapi()["paths"])
    assert summary_paths.isdisjoint(trading_api.openapi()["paths"])


def _request(cookie: str = "") -> Request:
    headers = [(b"cookie", f"aurex_session={cookie}".encode())] if cookie else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def test_owner_summary_routes_require_a_session_and_expose_no_write_method():
    settings = SimpleNamespace(session_cookie_name="aurex_session")
    with pytest.raises(HTTPException) as exc:
        owner_session(_request(), settings)
    assert exc.value.status_code == 401
    paths = {route.path: route.methods for route in app.routes}
    for path in ("/api/v1/owner/readiness", "/api/v1/owner/markets"):
        assert "GET" in paths[path]
        assert "POST" not in paths[path]


def test_owner_summary_routes_are_tenant_scoped_and_no_store(monkeypatch):
    user = AuthenticatedUser("user-1", "tenant-1", "owner@example.com", "Owner", "owner")
    settings = SimpleNamespace(session_cookie_name="aurex_session")
    monkeypatch.setattr("app.owner_overview_api.authenticate_session_token", lambda _token, _settings: user)
    assert owner_session(_request("test-token"), settings) == user
    observed = []
    monkeypatch.setattr("app.owner_overview_api.read_owner_readiness",
                        lambda _settings, tenant: observed.append(("readiness", tenant)) or {"overall_health": "HEALTHY"})
    monkeypatch.setattr("app.owner_overview_api.read_market_summary",
                        lambda _settings, tenant: observed.append(("markets", tenant)) or {"markets": []})
    first = readiness(user, settings)
    second = markets(user, settings)
    assert first.status_code == second.status_code == 200
    assert first.headers["cache-control"] == second.headers["cache-control"] == "no-store"
    assert observed == [("readiness", "tenant-1"), ("markets", "tenant-1")]
