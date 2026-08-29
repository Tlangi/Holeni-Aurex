from forexbot.core import Settings
from forexbot.ig_gateway import IGGateway


def make_settings(environment="demo"):
    return Settings(data={"timeframe": "M15", "instruments": {}}, ig_api_key="key",
                    ig_username="user", ig_password="password", ig_account_id="",
                    ig_environment=environment, allow_live=False, unlock_phrase="",
                    gmail_user="", gmail_app_password="", report_recipient="")


def test_demo_gateway_uses_demo_endpoint():
    gateway = IGGateway(make_settings())
    assert gateway.base_url == "https://demo-api.ig.com/gateway/deal"


def test_live_gateway_remains_locked():
    gateway = IGGateway(make_settings("live"))
    try:
        gateway.assert_execution_allowed()
    except PermissionError:
        pass
    else:
        raise AssertionError("live gateway was not blocked")
