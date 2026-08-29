from forexbot.errors import HistoricalQuotaExceeded, IGAPIError
from forexbot.ig_gateway import IGGateway


class Response:
    ok = False
    status_code = 403
    text = ""

    @staticmethod
    def json():
        return {"errorCode": "error.public-api.exceeded-account-historical-data-allowance"}


def test_historical_quota_response_has_specific_error():
    try:
        IGGateway._raise(Response(), "history")
    except HistoricalQuotaExceeded as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("quota response was not classified")


def test_generic_api_error_remains_typed():
    response = Response()
    response.json = lambda: {"errorCode": "error.security.api-key-invalid"}
    try:
        IGGateway._raise(response, "login")
    except IGAPIError as exc:
        assert exc.error_code == "error.security.api-key-invalid"
    else:
        raise AssertionError("API error was not classified")
