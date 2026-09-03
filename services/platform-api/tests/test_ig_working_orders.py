from app.ig_demo import IGDemoClient


def test_working_orders_uses_read_only_get(monkeypatch) -> None:
    client = object.__new__(IGDemoClient)
    monkeypatch.setattr(client, "_get", lambda path, version: {"workingOrders": [{"dealId": "x"}]})
    assert client.working_orders() == [{"dealId": "x"}]
