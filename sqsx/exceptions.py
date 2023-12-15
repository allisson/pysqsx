class Retry(Exception):
    """
    This exception must be used when we need a custom backoff config
    """

    def __init__(self, min_backoff_seconds: int, max_backoff_seconds: int):
        self.min_backoff_seconds = min_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds


class NoRetry(Exception):
    """
    This exception must be used when we need that the message will be removed from the queue
    """

    pass
