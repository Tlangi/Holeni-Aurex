from contextlib import contextmanager

import pytest
from pydantic import ValidationError

from app.auth import AuthenticatedUser
from app.proposal_approval_reservations import (
    ACKNOWLEDGEMENT, ApprovalReservationRequest, _token_digest,
    reserve_owner_approval,
)


OWNER = AuthenticatedUser("owner-id", "tenant-id", "owner@example.test", "Owner", "owner")
CHALLENGE_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class FakeCursor:
    def __init__(self, *, proposal_exists=True, token_consumed=True):
        self.proposal_exists = proposal_exists
        self.token_consumed = token_consumed
        self.rowcount = 0
        self.sql = []

    def execute(self, query, params):
        self.sql.append((query, params))
        self.rowcount = (1 if self.token_consumed else 0) if "UPDATE app.proposal_approval_challenges" in query else 1

    def fetchone(self):
        return {"trade_proposal_id": "proposal-id"} if self.proposal_exists else None


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, as_dict=False):
        return self.fake_cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def fake_database(connection):
    @contextmanager
    def opening(_settings):
        yield connection
    return opening


def test_reservation_token_requires_exact_acknowledgement():
    with pytest.raises(ValidationError):
        ApprovalReservationRequest(challenge_id=CHALLENGE_ID, token="b" * 43,
                                   acknowledgement="execute trade")


def test_reservation_consumes_token_and_commits_without_broker_call(monkeypatch):
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    monkeypatch.setattr("app.proposal_approval_reservations.open_database", fake_database(connection))
    body = ApprovalReservationRequest(challenge_id=CHALLENGE_ID, token="b" * 43,
                                      acknowledgement=ACKNOWLEDGEMENT)
    result = reserve_owner_approval(object(), OWNER, "proposal-id", body)
    assert result["broker_order_submitted"] is False
    assert result["submission_status"] == "PRE_SUBMISSION_BLOCKED"
    assert connection.commits == 1
    assert "UPDLOCK,HOLDLOCK" in cursor.sql[0][0]
    assert _token_digest(body.token) in cursor.sql[1][1]
    assert not any("IGDemo" in query or "submit" in query.lower() for query, _ in cursor.sql)


def test_used_or_invalid_token_rolls_back_without_reservation(monkeypatch):
    cursor = FakeCursor(token_consumed=False)
    connection = FakeConnection(cursor)
    monkeypatch.setattr("app.proposal_approval_reservations.open_database", fake_database(connection))
    body = ApprovalReservationRequest(challenge_id=CHALLENGE_ID, token="b" * 43,
                                      acknowledgement=ACKNOWLEDGEMENT)
    with pytest.raises(ValueError, match="APPROVAL_TOKEN_INVALID_EXPIRED_OR_USED"):
        reserve_owner_approval(object(), OWNER, "proposal-id", body)
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert len(cursor.sql) == 2
