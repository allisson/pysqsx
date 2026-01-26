"""
Custom exceptions for controlling message retry behavior in sqsx.

These exceptions allow task handlers to override the default retry behavior:
- Retry: Retry the message with custom backoff parameters
- NoRetry: Remove the message from the queue immediately (don't retry)
"""


class Retry(Exception):
    """
    Exception to retry a message with custom backoff configuration.

    Raise this exception from a task handler to retry the message with different
    backoff parameters than the queue's default values. The message will be made
    invisible for a calculated timeout based on the retry count and backoff config.

    Attributes:
        min_backoff_seconds: Minimum backoff delay in seconds
        max_backoff_seconds: Maximum backoff delay in seconds

    Example:
        >>> def my_task_handler(context, **kwargs):
        ...     try:
        ...         process_data(kwargs)
        ...     except TransientError:
        ...         # Retry with shorter backoff for transient errors
        ...         raise Retry(min_backoff_seconds=5, max_backoff_seconds=60)
        ...     except RateLimitError:
        ...         # Retry with longer backoff for rate limiting
        ...         raise Retry(min_backoff_seconds=300, max_backoff_seconds=3600)
    """

    def __init__(self, min_backoff_seconds: int, max_backoff_seconds: int):
        """
        Initialize the Retry exception with custom backoff parameters.

        Args:
            min_backoff_seconds: Minimum retry delay in seconds (must be >= 0)
            max_backoff_seconds: Maximum retry delay in seconds (must be > 0, max: 43200)

        Note:
            The actual visibility timeout is calculated as:
            min(min_backoff * 2^retries, max_backoff, 43200)
            where retries is the ApproximateReceiveCount from SQS.
        """
        self.min_backoff_seconds = min_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        super().__init__(f"Retry with backoff: min={min_backoff_seconds}s, max={max_backoff_seconds}s")


class NoRetry(Exception):
    """
    Exception to remove a message from the queue without retry.

    Raise this exception from a task handler when you want to acknowledge and
    delete a message even though processing failed. This is useful for messages
    that are malformed, permanently invalid, or have exceeded retry limits.

    Example:
        >>> def my_task_handler(context, order_id, **kwargs):
        ...     order = fetch_order(order_id)
        ...     if order is None:
        ...         # Order doesn't exist, no point retrying
        ...         logger.error("Order %s not found, removing message", order_id)
        ...         raise NoRetry()
        ...     if context['sqs_message']['Attributes']['ApproximateReceiveCount'] > 10:
        ...         # Too many retries, give up
        ...         logger.error("Max retries exceeded for order %s", order_id)
        ...         raise NoRetry()
        ...     process_order(order)

    Warning:
        Use this exception carefully. Messages removed with NoRetry will be
        permanently deleted from the queue and cannot be recovered.
    """

    pass
