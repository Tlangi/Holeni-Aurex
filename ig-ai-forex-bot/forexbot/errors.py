class BotError(Exception):
    """Expected operational failure that should be shown without a traceback."""


class IGAPIError(BotError):
    def __init__(self, operation: str, status_code: int, error_code: str):
        self.operation = operation
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(f"{operation} failed (HTTP {status_code}, {error_code})")


class HistoricalQuotaExceeded(IGAPIError):
    pass


class MarketDataUnavailable(BotError):
    pass


class CycleFailed(BotError):
    pass


class IGConnectionError(BotError):
    pass
