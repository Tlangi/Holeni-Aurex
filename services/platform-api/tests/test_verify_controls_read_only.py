from scripts import verify_controls


class FakeCursor:
    def __init__(self):
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))
        assert query.lstrip().upper().startswith("SELECT")

    def fetchall(self):
        if len(self.queries) == 1:
            return [("tenant-1", "SHADOW", 0)]
        return [("ACTIVE", 2), ("PAUSED", 1)]


class FakeConnection:
    def __init__(self):
        self.fake_cursor = FakeCursor()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.fake_cursor


def test_control_snapshot_only_reads(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr(verify_controls, "open_database", lambda _settings: connection)
    result = verify_controls.read_control_snapshot(object())
    assert result == {
        "status": "observed", "verification": "READ_ONLY", "controls": [{
            "tenant_id": "tenant-1", "engine_mode": "SHADOW",
            "new_orders_enabled": False,
            "strategy_status_counts": {"ACTIVE": 2, "PAUSED": 1},
        }],
    }
    assert len(connection.fake_cursor.queries) == 2
