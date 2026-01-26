"""
Task queue processing for Amazon SQS with thread-safe concurrent execution.

This module provides two queue classes for processing SQS messages:

- Queue: Task-oriented queue with named handlers and automatic message routing
- RawQueue: Low-level queue with a single handler function for all messages

Both classes support:
- Concurrent message processing with ThreadPoolExecutor
- Graceful shutdown on SIGINT/SIGTERM
- Automatic retry with exponential backoff
- Thread-safe operations
- Context manager support
- SQS API error handling with automatic retry

Example:
    >>> import boto3
    >>> from sqsx import Queue
    >>>
    >>> sqs_client = boto3.client('sqs')
    >>> queue = Queue(url='https://sqs.us-east-1.amazonaws.com/123/my-queue', sqs_client=sqs_client)
    >>>
    >>> def handler(context, **kwargs):
    ...     print(f"Processing: {kwargs}")
    >>>
    >>> queue.add_task_handler('my_task', handler)
    >>> queue.add_task('my_task', data='example')
    >>> queue.consume_messages()
"""

import logging
import signal
import time
from concurrent.futures import as_completed, ThreadPoolExecutor
from threading import Lock, RLock
from types import FrameType
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field, field_validator, model_validator, PrivateAttr

from sqsx.exceptions import NoRetry, Retry
from sqsx.helper import backoff_calculator_seconds, base64_to_dict, dict_to_base64

try:
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:
    # For testing or when boto3 is not installed
    BotoCoreError = Exception
    ClientError = Exception

logger = logging.getLogger(__name__)
queue_url_regex = r"(http|https)[:][\/]{2}[a-zA-Z0-9-_:.]+[\/][0-9]{12}[\/]{1}[a-zA-Z0-9-_]{0,80}"

# Constants
SQS_MAX_MESSAGES_PER_BATCH = 10
SQS_MAX_VISIBILITY_TIMEOUT = 43200  # 12 hours in seconds
SQS_MIN_VISIBILITY_TIMEOUT = 0


class BaseQueueMixin:
    """
    Base mixin class providing core message consumption and lifecycle management.

    This mixin provides the fundamental queue operations including message polling,
    concurrent processing, graceful shutdown, and automatic retry with exponential backoff.
    All SQS API errors are handled gracefully with automatic retry.

    Attributes:
        url: SQS queue URL (http:// or https://)
        sqs_client: Boto3 SQS client instance
        min_backoff_seconds: Minimum retry delay in seconds (default: 30)
        max_backoff_seconds: Maximum retry delay in seconds (default: 900, max: 43200)
        _consume_message: Internal method to process individual messages
        _should_consume_tasks_stop: Thread-safe flag for graceful shutdown
        _stop_lock: Lock for synchronizing shutdown operations

    Thread Safety:
        All public methods are thread-safe. The stop flag is protected by locks
        and can be safely set from signal handlers or other threads.
    """

    url: str
    sqs_client: Any
    min_backoff_seconds: int
    max_backoff_seconds: int
    _consume_message: Any
    _should_consume_tasks_stop: bool
    _stop_lock: Lock

    def consume_messages(
        self,
        max_messages: int = 1,
        max_threads: int = 1,
        wait_seconds: int = 10,
        polling_wait_seconds: int = 10,
        run_forever: bool = True,
        enable_signal_to_exit_gracefully: bool = True,
    ) -> None:
        """
        Start consuming messages from the SQS queue with concurrent processing.

        This method blocks until stopped via signal or exit_gracefully(). Messages
        are polled from SQS using long polling and processed concurrently using
        ThreadPoolExecutor when max_threads > 1. Messages are acknowledged as they
        complete (not waiting for the slowest message in the batch).

        All SQS API errors (throttling, network errors, service unavailable) are
        handled gracefully with automatic retry. Signal handlers (SIGINT/SIGTERM)
        are registered and properly restored when the method exits.

        Args:
            max_messages: Maximum number of messages to receive per batch (1-10).
                AWS SQS allows up to 10 messages per request.
            max_threads: Number of worker threads for parallel processing.
                Set to 1 for sequential processing. For optimal performance with
                values > 1, configure boto3 connection pooling to match.
            wait_seconds: Sleep duration (in seconds) when no messages are received.
                Uses interruptible sleep that checks the stop flag every 100ms for
                fast response to shutdown requests.
            polling_wait_seconds: SQS long polling wait time (0-20 seconds).
                Reduces API calls and improves efficiency. Recommended: 10-20.
            run_forever: If False, consume only one batch and return.
                Useful for testing or single-batch processing.
            enable_signal_to_exit_gracefully: If True, register SIGINT/SIGTERM
                handlers for graceful shutdown. Original handlers are restored
                when this method exits.

        Raises:
            No exceptions are raised. All errors are logged and retried automatically.

        Note:
            This method blocks until stopped via signal or exit_gracefully().
            Messages are processed in parallel when max_threads > 1.

        Example:
            >>> queue.consume_messages(
            ...     max_messages=10,
            ...     max_threads=5,
            ...     polling_wait_seconds=20,
            ... )
        """
        logger.info("Starting consuming tasks, queue_url=%s", self.url)

        original_sigint = None
        original_sigterm = None

        try:
            if enable_signal_to_exit_gracefully:
                original_sigint = signal.signal(signal.SIGINT, self._exit_gracefully_from_signal)
                original_sigterm = signal.signal(signal.SIGTERM, self._exit_gracefully_from_signal)

            while True:
                # Check stop flag with lock
                with self._stop_lock:
                    if self._should_consume_tasks_stop:
                        logger.info("Stopping consuming tasks, queue_url=%s", self.url)
                        break

                # Receive messages from SQS with error handling
                try:
                    response = self.sqs_client.receive_message(
                        QueueUrl=self.url,
                        AttributeNames=["All"],
                        MaxNumberOfMessages=min(max_messages, SQS_MAX_MESSAGES_PER_BATCH),
                        MessageAttributeNames=["All"],
                        WaitTimeSeconds=polling_wait_seconds,
                    )
                except ClientError as exc:
                    error_code = getattr(exc, "response", {}).get("Error", {}).get("Code", "Unknown")
                    logger.error("SQS API error: %s, queue_url=%s, retrying...", error_code, self.url)
                    time.sleep(min(wait_seconds, 5))
                    continue
                except BotoCoreError as exc:
                    logger.error(
                        "Network/connection error: %s, queue_url=%s, retrying...",
                        type(exc).__name__,
                        self.url,
                    )
                    time.sleep(min(wait_seconds, 5))
                    continue
                except Exception as exc:
                    logger.error(
                        "Unexpected error receiving messages: %s, queue_url=%s, retrying...",
                        type(exc).__name__,
                        self.url,
                    )
                    time.sleep(min(wait_seconds, 5))
                    continue

                sqs_messages = response.get("Messages", [])
                if not sqs_messages:
                    logger.debug(
                        "Waiting some seconds because no message was received, wait_seconds=%s, "
                        "polling_wait_seconds=%s, queue_url=%s",
                        wait_seconds,
                        polling_wait_seconds,
                        self.url,
                    )
                    # Interruptible sleep - check stop flag every 100ms
                    for _ in range(wait_seconds * 10):
                        with self._stop_lock:
                            if self._should_consume_tasks_stop:
                                break
                        time.sleep(0.1)
                    continue

                with ThreadPoolExecutor(max_workers=max_threads) as executor:
                    futures = []
                    for sqs_message in sqs_messages:
                        # Check stop flag before submitting new tasks
                        with self._stop_lock:
                            if self._should_consume_tasks_stop:
                                break
                        futures.append(executor.submit(self._consume_message, sqs_message))

                    # Process and acknowledge messages as they complete (faster than wait())
                    if futures:
                        for future in as_completed(futures):
                            try:
                                future.result()  # Raise any exceptions that occurred
                            except Exception as exc:
                                logger.error(
                                    "Unexpected error in message processing future: %s",
                                    type(exc).__name__,
                                )

                if not run_forever:
                    break

        finally:
            # Restore original signal handlers
            if enable_signal_to_exit_gracefully:
                if original_sigint is not None:
                    signal.signal(signal.SIGINT, original_sigint)
                if original_sigterm is not None:
                    signal.signal(signal.SIGTERM, original_sigterm)

    def exit_gracefully(self) -> None:
        """
        Request graceful shutdown of message consumption.

        Sets a thread-safe stop flag that is checked by the consume_messages loop.
        Active tasks will complete before shutdown. No new message batches will be
        fetched after this is called.

        This method is thread-safe and can be called from signal handlers or other
        threads while consume_messages is running.

        Note:
            - Does not immediately stop processing
            - Currently processing messages will complete
            - No new messages will be fetched after this is called
            - Stop flag is checked every 100ms during idle periods

        Example:
            >>> # In another thread or signal handler
            >>> queue.exit_gracefully()
        """
        logger.info("Starting graceful shutdown process, queue_url=%s", self.url)
        with self._stop_lock:
            self._should_consume_tasks_stop = True

    def _exit_gracefully_from_signal(self, signal: int, frame: Optional[FrameType]):
        """
        Signal handler wrapper for graceful shutdown.

        Called when SIGINT (Ctrl+C) or SIGTERM is received. Delegates to
        exit_gracefully() to set the stop flag.

        Args:
            signal: Signal number (SIGINT or SIGTERM)
            frame: Current stack frame (unused)
        """
        self.exit_gracefully()

    def _message_ack(self, sqs_message: dict) -> None:
        """
        Acknowledge successful message processing by deleting from SQS.

        Removes the message from the queue, indicating successful processing.
        If deletion fails (network error, SQS error), logs the error but does
        not raise an exception.

        Args:
            sqs_message: SQS message dictionary containing ReceiptHandle

        Note:
            Errors during deletion are logged but not raised to avoid
            disrupting message processing flow.
        """
        receipt_handle = sqs_message["ReceiptHandle"]
        try:
            self.sqs_client.delete_message(QueueUrl=self.url, ReceiptHandle=receipt_handle)
        except (ClientError, BotoCoreError) as exc:
            logger.error(
                "Failed to delete message: %s, message_id=%s",
                type(exc).__name__,
                sqs_message.get("MessageId"),
            )

    def _message_nack(
        self,
        sqs_message: dict,
        min_backoff_seconds: Optional[int] = None,
        max_backoff_seconds: Optional[int] = None,
    ) -> None:
        """
        Negative acknowledge: retry message with exponential backoff.

        Changes the message visibility timeout to retry the message after a delay.
        Uses exponential backoff based on the number of receive attempts:
        timeout = min(min_backoff * 2^retries, max_backoff)

        If visibility timeout change fails (network error, SQS error), logs the
        error but does not raise an exception. The message will become visible
        again after the original visibility timeout expires.

        Args:
            sqs_message: SQS message dictionary containing ReceiptHandle and Attributes
            min_backoff_seconds: Override minimum backoff (uses instance default if None)
            max_backoff_seconds: Override maximum backoff (uses instance default if None)

        Note:
            - Maximum visibility timeout is capped at 43200 seconds (12 hours) by SQS
            - Errors during visibility change are logged but not raised
            - ApproximateReceiveCount is used to calculate backoff
        """
        min_backoff_seconds = min_backoff_seconds if min_backoff_seconds else self.min_backoff_seconds
        max_backoff_seconds = max_backoff_seconds if max_backoff_seconds else self.max_backoff_seconds
        receipt_handle = sqs_message["ReceiptHandle"]
        receive_count = int(sqs_message["Attributes"]["ApproximateReceiveCount"]) - 1
        timeout = backoff_calculator_seconds(receive_count, min_backoff_seconds, max_backoff_seconds)
        try:
            self.sqs_client.change_message_visibility(
                QueueUrl=self.url, ReceiptHandle=receipt_handle, VisibilityTimeout=timeout
            )
        except (ClientError, BotoCoreError) as exc:
            logger.error(
                "Failed to change message visibility: %s, message_id=%s",
                type(exc).__name__,
                sqs_message.get("MessageId"),
            )


class Queue(BaseModel, BaseQueueMixin):
    """
    Task-based SQS queue consumer with named task handlers.

    Queue provides a task-oriented interface where messages are tagged with a
    task name and routed to corresponding handler functions. This is ideal for
    job queues where different message types need different processing logic.

    Attributes:
        url: SQS queue URL matching pattern (http|https)://host/account-id/queue-name
        sqs_client: Boto3 SQS client instance (validated to have receive_message method)
        min_backoff_seconds: Minimum retry delay in seconds (default: 30, min: 0)
        max_backoff_seconds: Maximum retry delay in seconds (default: 900, max: 43200)
        _handlers: Thread-safe dictionary mapping task names to handler functions
        _should_consume_tasks_stop: Thread-safe graceful shutdown flag
        _stop_lock: Lock for synchronizing shutdown operations
        _handlers_lock: RLock for protecting handlers dictionary

    Thread Safety:
        All public methods are thread-safe. Handlers can be added during message
        processing, and the handlers dictionary is protected by an RLock.

    Example:
        >>> import boto3
        >>> from sqsx import Queue
        >>>
        >>> sqs_client = boto3.client('sqs')
        >>> queue = Queue(
        ...     url='https://sqs.us-east-1.amazonaws.com/123456789012/my-queue',
        ...     sqs_client=sqs_client
        ... )
        >>>
        >>> def process_email(context, to, subject, body):
        ...     send_email(to, subject, body)
        >>>
        >>> queue.add_task_handler('send_email', process_email)
        >>> queue.add_task('send_email', to='user@example.com', subject='Hello', body='World')
        >>> queue.consume_messages()
    """

    url: str = Field(pattern=queue_url_regex)
    sqs_client: Any
    min_backoff_seconds: int = Field(default=30, ge=0)
    max_backoff_seconds: int = Field(default=900, gt=0, le=SQS_MAX_VISIBILITY_TIMEOUT)
    _handlers: dict[str, Callable] = PrivateAttr(default_factory=dict)
    _should_consume_tasks_stop: bool = PrivateAttr(default=False)
    _stop_lock: Lock = PrivateAttr(default_factory=Lock)
    _handlers_lock: RLock = PrivateAttr(default_factory=RLock)

    @field_validator("sqs_client")
    @classmethod
    def validate_sqs_client(cls, v):
        """
        Validate that sqs_client has required boto3 SQS client methods.

        Args:
            v: SQS client to validate

        Returns:
            The validated SQS client

        Raises:
            ValueError: If sqs_client doesn't have receive_message method
        """
        if not hasattr(v, "receive_message"):
            raise ValueError("sqs_client must be a valid boto3 SQS client with receive_message method")
        return v

    @field_validator("url")
    @classmethod
    def validate_url_format(cls, v):
        """
        Validate that the queue URL starts with http:// or https://.

        Args:
            v: URL string to validate

        Returns:
            The validated URL

        Raises:
            ValueError: If URL doesn't start with http:// or https://
        """
        if not v.startswith(("http://", "https://")):
            raise ValueError("Queue URL must start with http:// or https://")
        return v

    @model_validator(mode="after")
    def validate_config(self) -> "Queue":
        """
        Validate that backoff configuration is consistent.

        Returns:
            The validated Queue instance

        Raises:
            ValueError: If min_backoff_seconds > max_backoff_seconds
        """
        if self.min_backoff_seconds > self.max_backoff_seconds:
            raise ValueError("min_backoff_seconds must be <= max_backoff_seconds")
        return self

    def add_task(self, task_name: str, **task_kwargs) -> dict:
        """
        Add a task to the queue for processing.

        Creates an SQS message with the task name as a message attribute and
        the task arguments encoded in the message body as base64-encoded JSON.

        Args:
            task_name: Name of the task handler to invoke (must match a registered handler)
            **task_kwargs: Keyword arguments to pass to the task handler function

        Returns:
            SQS send_message response dictionary containing MessageId, MD5OfMessageBody, etc.

        Raises:
            ValueError: If the encoded message exceeds 256KB (SQS limit)
            ClientError: If SQS API call fails (boto3 exception)

        Example:
            >>> queue.add_task('process_order', order_id=123, priority='high')
            {'MessageId': '...', 'MD5OfMessageBody': '...', ...}
        """
        return self.sqs_client.send_message(
            QueueUrl=self.url,
            MessageAttributes={"TaskName": {"DataType": "String", "StringValue": task_name}},
            MessageBody=dict_to_base64({"kwargs": task_kwargs}),
        )

    def add_task_handler(self, task_name: str, task_handler_function: Callable) -> None:
        """
        Register a handler function for a specific task name.

        The handler function will be called when a message with the matching task
        name is consumed. Handlers can be added at any time, even during message
        processing (thread-safe).

        Args:
            task_name: Unique identifier for this task handler
            task_handler_function: Callable with signature (context: dict, **kwargs)
                - context: Dictionary containing queue_url, task_name, sqs_message
                - **kwargs: Task-specific arguments from add_task()

        Thread Safety:
            This method is thread-safe and can be called concurrently with
            consume_messages().

        Example:
            >>> def process_email(context, to, subject, body):
            ...     print(f"Sending to {to}: {subject}")
            ...     send_email(to, subject, body)
            >>>
            >>> queue.add_task_handler('send_email', process_email)

        Note:
            If a message is received for an unregistered task name, it will be
            retried with exponential backoff (treated as a failed message).
        """
        with self._handlers_lock:
            self._handlers[task_name] = task_handler_function

    def close(self) -> None:
        """
        Clean up queue resources and prepare for shutdown.

        Clears all registered task handlers and sets the graceful shutdown flag.
        This method is called automatically when using the queue as a context manager
        or during garbage collection.

        Thread Safety:
            This method is thread-safe and uses locks to protect shared state.

        Note:
            After calling close(), no new messages will be processed, but currently
            running message handlers will complete.

        Example:
            >>> queue = Queue(url=queue_url, sqs_client=sqs_client)
            >>> queue.add_task_handler('my_task', handler)
            >>> # ... process messages ...
            >>> queue.close()  # Clean up
        """
        with self._handlers_lock:
            self._handlers.clear()
        with self._stop_lock:
            self._should_consume_tasks_stop = True

    def __enter__(self):
        """
        Enter the context manager.

        Returns:
            The Queue instance

        Example:
            >>> with Queue(url=queue_url, sqs_client=sqs_client) as queue:
            ...     queue.add_task_handler('my_task', handler)
            ...     queue.consume_messages(run_forever=False)
            # Automatically calls close() on exit
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exit the context manager and clean up resources.

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred

        Returns:
            False to propagate any exception that occurred

        Note:
            Always calls close() to ensure proper cleanup, even if an exception occurred.
        """
        self.close()
        return False

    def __del__(self):
        """
        Destructor to ensure cleanup during garbage collection.

        Attempts to call close() when the Queue object is being garbage collected.
        Exceptions are silently caught to avoid issues during interpreter shutdown.

        Note:
            Relying on __del__ for cleanup is not recommended. Use context managers
            or explicit close() calls instead.
        """
        try:
            self.close()
        except Exception:
            pass  # Avoid exceptions during garbage collection

    def _consume_message(self, sqs_message: dict) -> None:
        """
        Internal method to process a single SQS message for Queue.

        Extracts the task name from message attributes, validates the message format,
        looks up the corresponding handler, and invokes it with the message data.
        Handles Retry, NoRetry, and general exceptions appropriately.

        Args:
            sqs_message: SQS message dictionary from receive_message API

        Behavior:
            - Missing TaskName attribute: NACK (retry with backoff)
            - Handler not found: NACK (retry with backoff)
            - Invalid message body: NACK (retry with backoff)
            - Handler raises Retry: NACK with custom backoff
            - Handler raises NoRetry: ACK (remove from queue)
            - Handler raises other exception: NACK (retry with backoff)
            - Handler succeeds: ACK (remove from queue)

        Note:
            This method is called concurrently by ThreadPoolExecutor when
            max_threads > 1. The _handlers dictionary is protected by RLock.
        """
        message_id = sqs_message["MessageId"]
        task_name_attribute = sqs_message.get("MessageAttributes", {}).get("TaskName")
        if task_name_attribute is None:
            logger.warning("Message without TaskName attribute, message_id=%s", message_id)
            return self._message_nack(sqs_message)

        task_name = task_name_attribute["StringValue"]

        # Get handler with lock
        with self._handlers_lock:
            task_handler_function = self._handlers.get(task_name)

        if task_handler_function is None:
            logger.warning("Task handler not found, message_id=%s, task_name=%s", message_id, task_name)
            return self._message_nack(sqs_message)

        try:
            message_data = base64_to_dict(sqs_message["Body"])
        except (ValueError, KeyError, UnicodeDecodeError) as exc:
            logger.exception(
                "Invalid message body, message_id=%s, task_name=%s, error=%s",
                message_id,
                task_name,
                type(exc).__name__,
            )
            return self._message_nack(sqs_message)

        kwargs = message_data["kwargs"]
        context = {
            "queue_url": self.url,
            "task_name": task_name,
            "sqs_message": sqs_message,
        }

        try:
            task_handler_function(context, **kwargs)
        except Retry as exc:
            logger.info(
                "Received an sqsx.Retry, setting a custom backoff policy, message_id=%s, task_name=%s",
                message_id,
                task_name,
            )
            return self._message_nack(
                sqs_message,
                min_backoff_seconds=exc.min_backoff_seconds,
                max_backoff_seconds=exc.max_backoff_seconds,
            )
        except NoRetry:
            logger.info(
                "Received an sqsx.NoRetry, removing the task, message_id=%s, task_name=%s",
                message_id,
                task_name,
            )
            return self._message_ack(sqs_message)
        except Exception:
            logger.exception("Error while processing, message_id=%s, task_name=%s", message_id, task_name)
            return self._message_nack(sqs_message)

        self._message_ack(sqs_message)


class RawQueue(BaseModel, BaseQueueMixin):
    """
    Low-level SQS queue consumer with a single message handler function.

    RawQueue provides direct access to SQS messages without task routing or message
    encoding. This is ideal for integrating with existing SQS queues or when you need
    full control over message format and processing.

    Unlike Queue, RawQueue:
    - Uses a single handler function for all messages (no task routing)
    - Passes raw SQS message dictionaries to the handler
    - Doesn't encode/decode message bodies
    - Doesn't use TaskName message attributes

    Attributes:
        url: SQS queue URL matching pattern (http|https)://host/account-id/queue-name
        message_handler_function: Callable to process all messages
        sqs_client: Boto3 SQS client instance (validated to have receive_message method)
        min_backoff_seconds: Minimum retry delay in seconds (default: 30, min: 0)
        max_backoff_seconds: Maximum retry delay in seconds (default: 900, max: 43200)
        _should_consume_tasks_stop: Thread-safe graceful shutdown flag
        _stop_lock: Lock for synchronizing shutdown operations

    Thread Safety:
        All public methods are thread-safe. The message handler function may be
        called concurrently when max_threads > 1, so it should be thread-safe.

    Example:
        >>> import boto3
        >>> from sqsx import RawQueue
        >>>
        >>> sqs_client = boto3.client('sqs')
        >>>
        >>> def process_message(queue_url, sqs_message):
        ...     body = sqs_message['Body']
        ...     message_id = sqs_message['MessageId']
        ...     print(f"Processing {message_id}: {body}")
        >>>
        >>> queue = RawQueue(
        ...     url='https://sqs.us-east-1.amazonaws.com/123456789012/my-queue',
        ...     message_handler_function=process_message,
        ...     sqs_client=sqs_client
        ... )
        >>>
        >>> queue.add_message('Hello, World!')
        >>> queue.consume_messages()
    """

    url: str = Field(pattern=queue_url_regex)
    message_handler_function: Callable
    sqs_client: Any
    min_backoff_seconds: int = Field(default=30, ge=0)
    max_backoff_seconds: int = Field(default=900, gt=0, le=SQS_MAX_VISIBILITY_TIMEOUT)
    _should_consume_tasks_stop: bool = PrivateAttr(default=False)
    _stop_lock: Lock = PrivateAttr(default_factory=Lock)

    @field_validator("sqs_client")
    @classmethod
    def validate_sqs_client(cls, v):
        """
        Validate that sqs_client has required boto3 SQS client methods.

        Args:
            v: SQS client to validate

        Returns:
            The validated SQS client

        Raises:
            ValueError: If sqs_client doesn't have receive_message method
        """
        if not hasattr(v, "receive_message"):
            raise ValueError("sqs_client must be a valid boto3 SQS client with receive_message method")
        return v

    @field_validator("url")
    @classmethod
    def validate_url_format(cls, v):
        """
        Validate that the queue URL starts with http:// or https://.

        Args:
            v: URL string to validate

        Returns:
            The validated URL

        Raises:
            ValueError: If URL doesn't start with http:// or https://
        """
        if not v.startswith(("http://", "https://")):
            raise ValueError("Queue URL must start with http:// or https://")
        return v

    @model_validator(mode="after")
    def validate_config(self) -> "RawQueue":
        """
        Validate that backoff configuration is consistent.

        Returns:
            The validated RawQueue instance

        Raises:
            ValueError: If min_backoff_seconds > max_backoff_seconds
        """
        if self.min_backoff_seconds > self.max_backoff_seconds:
            raise ValueError("min_backoff_seconds must be <= max_backoff_seconds")
        return self

    def add_message(self, message_body: str, message_attributes: Optional[dict] = None) -> dict:
        """
        Add a raw message to the queue.

        Sends a message to SQS with the provided body and optional attributes.
        No encoding or special formatting is applied.

        Args:
            message_body: Raw message body string (must be < 256KB)
            message_attributes: Optional SQS message attributes dictionary.
                Format: {'AttrName': {'DataType': 'String', 'StringValue': 'value'}}

        Returns:
            SQS send_message response dictionary containing MessageId, MD5, etc.

        Raises:
            ClientError: If SQS API call fails (boto3 exception)

        Example:
            >>> queue.add_message(
            ...     message_body='{"order_id": 123}',
            ...     message_attributes={'Priority': {'DataType': 'String', 'StringValue': 'high'}}
            ... )
            {'MessageId': '...', 'MD5OfMessageBody': '...', ...}
        """
        if message_attributes is None:
            message_attributes = {}
        return self.sqs_client.send_message(
            QueueUrl=self.url,
            MessageAttributes=message_attributes,
            MessageBody=message_body,
        )

    def close(self) -> None:
        """
        Clean up queue resources and prepare for shutdown.

        Sets the graceful shutdown flag. This method is called automatically when
        using the queue as a context manager or during garbage collection.

        Thread Safety:
            This method is thread-safe and uses locks to protect shared state.

        Note:
            After calling close(), no new messages will be processed, but currently
            running message handlers will complete.

        Example:
            >>> queue = RawQueue(url=queue_url, message_handler_function=handler, sqs_client=sqs_client)
            >>> # ... process messages ...
            >>> queue.close()  # Clean up
        """
        with self._stop_lock:
            self._should_consume_tasks_stop = True

    def __enter__(self):
        """
        Enter the context manager.

        Returns:
            The RawQueue instance

        Example:
            >>> with RawQueue(url=queue_url, message_handler_function=handler, sqs_client=sqs_client) as queue:
            ...     queue.add_message('test message')
            ...     queue.consume_messages(run_forever=False)
            # Automatically calls close() on exit
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exit the context manager and clean up resources.

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred

        Returns:
            False to propagate any exception that occurred

        Note:
            Always calls close() to ensure proper cleanup, even if an exception occurred.
        """
        self.close()
        return False

    def __del__(self):
        """
        Destructor to ensure cleanup during garbage collection.

        Attempts to call close() when the RawQueue object is being garbage collected.
        Exceptions are silently caught to avoid issues during interpreter shutdown.

        Note:
            Relying on __del__ for cleanup is not recommended. Use context managers
            or explicit close() calls instead.
        """
        try:
            self.close()
        except Exception:
            pass  # Avoid exceptions during garbage collection

    def _consume_message(self, sqs_message: dict) -> None:
        """
        Internal method to process a single SQS message for RawQueue.

        Calls the message_handler_function with the queue URL and raw SQS message.
        Handles Retry, NoRetry, and general exceptions appropriately.

        Args:
            sqs_message: SQS message dictionary from receive_message API

        Behavior:
            - Handler raises Retry: NACK with custom backoff
            - Handler raises NoRetry: ACK (remove from queue)
            - Handler raises other exception: NACK (retry with backoff)
            - Handler succeeds: ACK (remove from queue)

        Note:
            This method is called concurrently by ThreadPoolExecutor when
            max_threads > 1. The message_handler_function should be thread-safe.
        """
        message_id = sqs_message["MessageId"]

        try:
            self.message_handler_function(self.url, sqs_message)
        except Retry as exc:
            logger.info("Received an sqsx.Retry, setting a custom backoff policy, message_id=%s", message_id)
            return self._message_nack(
                sqs_message,
                min_backoff_seconds=exc.min_backoff_seconds,
                max_backoff_seconds=exc.max_backoff_seconds,
            )
        except NoRetry:
            logger.info("Received an sqsx.NoRetry, removing the message, message_id=%s", message_id)
            return self._message_ack(sqs_message)
        except Exception:
            logger.exception("Error while processing, message_id=%s", message_id)
            return self._message_nack(sqs_message)

        self._message_ack(sqs_message)
