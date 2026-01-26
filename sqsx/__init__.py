"""
sqsx - Simple, robust, and thread-safe task processor for Amazon SQS.

This package provides two main classes for processing SQS messages:

Classes:
    Queue: Task-oriented queue with named handlers and automatic message routing
    RawQueue: Low-level queue with a single handler for all messages

Features:
    - Thread-safe concurrent message processing
    - Graceful shutdown on SIGINT/SIGTERM
    - Automatic retry with exponential backoff
    - Context manager support
    - SQS API error handling with automatic retry
    - Message size validation (256KB limit)
    - Pydantic-based configuration validation

Quick Example:
    >>> import boto3
    >>> from sqsx import Queue
    >>>
    >>> sqs_client = boto3.client('sqs')
    >>> queue = Queue(
    ...     url='https://sqs.us-east-1.amazonaws.com/123456789012/my-queue',
    ...     sqs_client=sqs_client
    ... )
    >>>
    >>> def process_task(context, **kwargs):
    ...     print(f"Processing: {kwargs}")
    >>>
    >>> queue.add_task_handler('my_task', process_task)
    >>> queue.add_task('my_task', data='example')
    >>> queue.consume_messages()

For more information, see the README and documentation.
"""

from sqsx.queue import Queue, RawQueue  # noqa
