import os
import re
import signal
import threading
import time
from unittest import mock

import pytest

from sqsx.exceptions import NoRetry, Retry
from sqsx.queue import queue_url_regex


def task_handler(context, a, b, c):
    print(f"context={context}, a={a}, b={b}, c={c}")


def exception_handler(context, a, b, c):
    raise Exception("BOOM!")


def retry_exception_handler(context, a, b, c):
    raise Retry(min_backoff_seconds=100, max_backoff_seconds=200)


def no_retry_exception_handler(context, a, b, c):
    raise NoRetry()


def raw_exception_handler(queue_url, sqs_message):
    raise Exception("BOOM!")


def raw_retry_exception_handler(queue_url, sqs_message):
    raise Retry(min_backoff_seconds=100, max_backoff_seconds=200)


def raw_no_retry_exception_handler(queue_url, sqs_message):
    raise NoRetry()


def trigger_signal():
    pid = os.getpid()
    time.sleep(0.2)
    os.kill(pid, signal.SIGINT)


class SumHandler:
    result_sum = 0

    def __call__(self, context, a, b, c):
        self.result_sum += a + b + c


class CallCountHandler:
    call_count = 0

    def __call__(self, queue_url, sqs_message):
        self.call_count += 1


@pytest.mark.parametrize(
    "queue_url,expected",
    [
        ("https://sqs.us-east-1.amazonaws.com/177715257436", False),
        ("https://sqs.us-east-1.amazonaws.com/1/MyQueue", False),
        ("https://sqs.us-east-1.amazonaws.com/MyQueue", False),
        ("http://localhost:9324/000000000000/tests", True),
        ("https://localhost:9324/000000000000/tests", True),
        ("https://sqs.us-east-1.amazonaws.com/177715257436/MyQueue", True),
    ],
)
def test_queue_url_regex(queue_url, expected):
    result = True if re.search(queue_url_regex, queue_url) else False
    assert result == expected


def test_queue_add_task_handler(queue):
    assert queue._handlers == {}

    queue.add_task_handler("my_task", task_handler)
    assert queue._handlers == {"my_task": task_handler}

    queue.add_task_handler("my_other_task", task_handler)
    assert queue._handlers == {"my_task": task_handler, "my_other_task": task_handler}

    queue.add_task_handler("my_task", task_handler)
    assert queue._handlers == {"my_task": task_handler, "my_other_task": task_handler}


def test_queue_add_task(queue):
    expected_md5_message_body = "8087eb7436895841c5d646156a8a469f"
    expected_md5_message_attribute = "5346f2cd7c539a880febaf9112a86921"
    response = queue.add_task("my_task", a=1, b=2, c=3)

    assert response["ResponseMetadata"]["HTTPStatusCode"] == 200
    assert response["MD5OfMessageBody"] == expected_md5_message_body
    assert response["MD5OfMessageAttributes"] == expected_md5_message_attribute


def test_queue_consume_message_without_task_name_attribute(queue, sqs_message, caplog):
    queue._message_nack = mock.MagicMock()
    sqs_message["MessageAttributes"].pop("TaskName")

    queue._consume_message(sqs_message)

    queue._message_nack.assert_called_once_with(sqs_message)
    assert caplog.record_tuples == [
        (
            "sqsx.queue",
            30,
            "Message without TaskName attribute, message_id=33425f12-50e6-4f93-ac26-7ae7a069cf88",
        )
    ]


def test_queue_consume_message_without_task_handler(queue, sqs_message, caplog):
    queue._message_nack = mock.MagicMock()

    queue._consume_message(sqs_message)

    queue._message_nack.assert_called_once_with(sqs_message)
    assert caplog.record_tuples == [
        (
            "sqsx.queue",
            30,
            "Task handler not found, message_id=33425f12-50e6-4f93-ac26-7ae7a069cf88, task_name=my_task",
        )
    ]


def test_queue_consume_message_with_invalid_body(queue, sqs_message, caplog):
    queue._message_nack = mock.MagicMock()
    sqs_message["Body"] = "invalid-body"

    queue.add_task_handler("my_task", task_handler)
    queue._consume_message(sqs_message)

    queue._message_nack.assert_called_once_with(sqs_message)
    # Check that error was logged with error type
    assert len(caplog.record_tuples) == 1
    log_name, log_level, log_message = caplog.record_tuples[0]
    assert log_name == "sqsx.queue"
    assert log_level == 40  # ERROR
    assert "Invalid message body" in log_message
    assert "message_id=33425f12-50e6-4f93-ac26-7ae7a069cf88" in log_message
    assert "task_name=my_task" in log_message
    assert "error=" in log_message  # Now includes error type


def test_queue_consume_message_with_task_handler_exception(queue, sqs_message, caplog):
    queue._message_nack = mock.MagicMock()

    queue.add_task_handler("my_task", exception_handler)
    queue._consume_message(sqs_message)

    queue._message_nack.assert_called_once_with(sqs_message)
    assert caplog.record_tuples == [
        (
            "sqsx.queue",
            40,
            "Error while processing, message_id=33425f12-50e6-4f93-ac26-7ae7a069cf88, task_name=my_task",
        )
    ]


def test_queue_consume_messages(queue):
    handler = SumHandler()

    queue.add_task_handler("my_task", handler)
    queue.add_task("my_task", a=1, b=2, c=3)
    queue.add_task("my_task", a=1, b=2, c=3)

    queue.consume_messages(max_messages=2, max_threads=2, run_forever=False)

    assert handler.result_sum == 12


def test_queue_consume_messages_with_task_handler_exception(queue, caplog):
    queue.add_task_handler("my_task", exception_handler)
    queue.add_task("my_task", a=1, b=2, c=3)

    queue.consume_messages(run_forever=False)

    assert caplog.record_tuples[1][0] == "sqsx.queue"
    assert caplog.record_tuples[1][1] == 40
    assert "Error while processing" in caplog.record_tuples[1][2]


def test_queue_consume_messages_with_task_handler_retry_exception(queue, caplog):
    queue.add_task_handler("my_task", retry_exception_handler)
    queue.add_task("my_task", a=1, b=2, c=3)

    queue.consume_messages(run_forever=False)

    assert caplog.record_tuples[1][0] == "sqsx.queue"
    assert caplog.record_tuples[1][1] == 20
    assert "Received an sqsx.Retry, setting a custom backoff policy" in caplog.record_tuples[1][2]


def test_queue_consume_messages_with_task_handler_no_retry_exception(queue, caplog):
    queue.add_task_handler("my_task", no_retry_exception_handler)
    queue.add_task("my_task", a=1, b=2, c=3)

    queue.consume_messages(run_forever=False)

    assert caplog.record_tuples[1][0] == "sqsx.queue"
    assert caplog.record_tuples[1][1] == 20
    assert "Received an sqsx.NoRetry, removing the task" in caplog.record_tuples[1][2]


def test_queue_exit_gracefully(queue):
    thread = threading.Thread(target=trigger_signal)
    thread.daemon = True
    thread.start()
    handler = SumHandler()

    queue.add_task_handler("my_task", handler)
    queue.add_task("my_task", a=1, b=2, c=3)

    queue.consume_messages(
        wait_seconds=1, polling_wait_seconds=0, run_forever=True, enable_signal_to_exit_gracefully=True
    )

    assert handler.result_sum == 6


def test_raw_queue_add_message(raw_queue):
    expected_md5_message_body = "069840f6917e85a02167febb964f0041"
    expected_md5_message_attribute = "90f34a800b9d242c1b32320e4a3ed630"
    response = raw_queue.add_message(
        message_body="My Message",
        message_attributes={"Attr1": {"DataType": "String", "StringValue": "Attr1"}},
    )

    assert response["ResponseMetadata"]["HTTPStatusCode"] == 200
    assert response["MD5OfMessageBody"] == expected_md5_message_body
    assert response["MD5OfMessageAttributes"] == expected_md5_message_attribute


def test_raw_queue_consume_messages(raw_queue):
    handler = CallCountHandler()
    raw_queue.message_handler_function = handler

    raw_queue.add_message(message_body="Message Body")
    raw_queue.add_message(message_body="Message Body")
    raw_queue.add_message(message_body="Message Body")

    raw_queue.consume_messages(max_messages=3, max_threads=3, run_forever=False)

    assert handler.call_count == 3


def test_raw_queue_consume_messages_with_message_handler_exception(raw_queue, caplog):
    raw_queue.message_handler_function = raw_exception_handler

    raw_queue.add_message(message_body="Message Body")
    raw_queue.consume_messages(run_forever=False)

    assert caplog.record_tuples[1][0] == "sqsx.queue"
    assert caplog.record_tuples[1][1] == 40
    assert "Error while processing" in caplog.record_tuples[1][2]


def test_raw_queue_consume_messages_with_message_handler_retry_exception(raw_queue, caplog):
    raw_queue.message_handler_function = raw_retry_exception_handler

    raw_queue.add_message(message_body="Message Body")
    raw_queue.consume_messages(run_forever=False)

    assert caplog.record_tuples[1][0] == "sqsx.queue"
    assert caplog.record_tuples[1][1] == 20
    assert "Received an sqsx.Retry, setting a custom backoff policy" in caplog.record_tuples[1][2]


def test_raw_queue_consume_messages_with_message_handler_no_retry_exception(raw_queue, caplog):
    raw_queue.message_handler_function = raw_no_retry_exception_handler

    raw_queue.add_message(message_body="Message Body")
    raw_queue.consume_messages(run_forever=False)

    assert caplog.record_tuples[1][0] == "sqsx.queue"
    assert caplog.record_tuples[1][1] == 20
    assert "Received an sqsx.NoRetry, removing the message" in caplog.record_tuples[1][2]


def test_raw_queue_exit_gracefully(raw_queue):
    thread = threading.Thread(target=trigger_signal)
    thread.daemon = True
    thread.start()
    handler = handler = CallCountHandler()
    raw_queue.message_handler_function = handler

    raw_queue.add_message(message_body="Message Body")
    raw_queue.add_message(message_body="Message Body")
    raw_queue.add_message(message_body="Message Body")

    raw_queue.consume_messages(
        wait_seconds=1, polling_wait_seconds=0, run_forever=True, enable_signal_to_exit_gracefully=True
    )

    assert handler.call_count == 3


# New tests for improvements


def test_queue_thread_safety_concurrent_handlers(sqs_client, queue_url):
    """Test thread safety when processing multiple messages concurrently."""
    from sqsx.queue import Queue

    sqs_client.create_queue(QueueName=queue_url.split("/")[-1])
    queue = Queue(url=queue_url, sqs_client=sqs_client)

    results = []
    lock = threading.Lock()

    def thread_safe_handler(context, value):
        with lock:
            results.append(value)

    queue.add_task_handler("my_task", thread_safe_handler)

    # Add many tasks
    for i in range(20):
        queue.add_task("my_task", value=i)

    # Process in batches until all are done
    while len(results) < 20:
        queue.consume_messages(max_messages=10, max_threads=5, run_forever=False, polling_wait_seconds=0)
        if len(results) == 0:  # No messages received, stop trying
            break

    # All tasks should be processed exactly once
    assert len(results) == 20
    assert sorted(results) == list(range(20))

    sqs_client.delete_queue(QueueUrl=queue_url)


def test_queue_thread_safety_add_handler_during_processing(sqs_client, queue_url):
    """Test thread safety when adding handlers while messages are being processed."""
    from sqsx.queue import Queue

    sqs_client.create_queue(QueueName=queue_url.split("/")[-1])
    queue = Queue(url=queue_url, sqs_client=sqs_client)

    results = []
    lock = threading.Lock()

    def handler1(context, value):
        with lock:
            results.append(("handler1", value))
        time.sleep(0.1)  # Simulate work

    def handler2(context, value):
        with lock:
            results.append(("handler2", value))

    queue.add_task_handler("task1", handler1)
    queue.add_task("task1", value=1)
    queue.add_task("task1", value=2)

    # Start consuming in a thread - disable signal handlers since they don't work in threads
    def consume():
        queue.consume_messages(
            max_messages=2, max_threads=2, run_forever=False, enable_signal_to_exit_gracefully=False
        )

    consumer_thread = threading.Thread(target=consume)
    consumer_thread.start()

    # Add another handler while processing
    time.sleep(0.05)
    queue.add_task_handler("task2", handler2)

    consumer_thread.join(timeout=5)

    # Should have processed both messages
    assert len(results) == 2

    sqs_client.delete_queue(QueueUrl=queue_url)


def test_queue_handles_sqs_client_error(queue, caplog):
    """Test that SQS ClientError is handled gracefully."""
    from botocore.exceptions import ClientError

    original_receive = queue.sqs_client.receive_message
    call_count = [0]

    def mock_receive(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            # Simulate throttling error
            error_response = {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}}
            raise ClientError(error_response, "ReceiveMessage")
        return original_receive(*args, **kwargs)

    queue.sqs_client.receive_message = mock_receive
    queue.add_task_handler("my_task", task_handler)
    queue.add_task("my_task", a=1, b=2, c=3)

    # Should recover from error and process message
    queue.consume_messages(run_forever=False)

    assert call_count[0] >= 2  # At least one error + one success
    # Check that error was logged
    assert any("SQS API error" in record[2] for record in caplog.record_tuples)


def test_queue_handles_network_error(queue, caplog):
    """Test that network errors (BotoCoreError) are handled gracefully."""
    from botocore.exceptions import EndpointConnectionError

    original_receive = queue.sqs_client.receive_message
    call_count = [0]

    def mock_receive(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            # Simulate network error
            raise EndpointConnectionError(endpoint_url="http://test")
        return original_receive(*args, **kwargs)

    queue.sqs_client.receive_message = mock_receive
    queue.add_task_handler("my_task", task_handler)
    queue.add_task("my_task", a=1, b=2, c=3)

    # Should recover from error and process message
    queue.consume_messages(run_forever=False)

    assert call_count[0] >= 2
    # Check that error was logged
    assert any(
        "Network/connection error" in record[2] or "Unexpected error" in record[2]
        for record in caplog.record_tuples
    )


def test_queue_context_manager(sqs_client, queue_url):
    """Test that Queue works as a context manager."""
    from sqsx.queue import Queue

    sqs_client.create_queue(QueueName=queue_url.split("/")[-1])

    with Queue(url=queue_url, sqs_client=sqs_client) as queue:
        queue.add_task_handler("my_task", task_handler)
        assert "my_task" in queue._handlers

    # After exiting context, handlers should be cleared
    assert queue._handlers == {}
    assert queue._should_consume_tasks_stop is True

    sqs_client.delete_queue(QueueUrl=queue_url)


def test_raw_queue_context_manager(sqs_client, raw_queue_url):
    """Test that RawQueue works as a context manager."""
    from sqsx.queue import RawQueue

    sqs_client.create_queue(QueueName=raw_queue_url.split("/")[-1])

    def handler(url, msg):
        pass

    with RawQueue(url=raw_queue_url, sqs_client=sqs_client, message_handler_function=handler) as queue:
        assert queue._should_consume_tasks_stop is False

    # After exiting context, should be stopped
    assert queue._should_consume_tasks_stop is True

    sqs_client.delete_queue(QueueUrl=raw_queue_url)


def test_queue_close_method(sqs_client, queue_url):
    """Test that Queue.close() properly cleans up resources."""
    from sqsx.queue import Queue

    sqs_client.create_queue(QueueName=queue_url.split("/")[-1])
    queue = Queue(url=queue_url, sqs_client=sqs_client)
    queue.add_task_handler("my_task", task_handler)

    assert queue._handlers == {"my_task": task_handler}
    assert queue._should_consume_tasks_stop is False

    queue.close()

    assert queue._handlers == {}
    assert queue._should_consume_tasks_stop is True

    sqs_client.delete_queue(QueueUrl=queue_url)


def test_queue_validation_invalid_url(sqs_client):
    """Test that Queue validates URL format."""
    from pydantic import ValidationError

    from sqsx.queue import Queue

    # Missing protocol - should fail regex pattern first
    with pytest.raises(ValidationError) as exc_info:
        Queue(url="sqs.us-east-1.amazonaws.com/123456789012/MyQueue", sqs_client=sqs_client)

    # Check that it's a validation error about the URL pattern
    assert "url" in str(exc_info.value).lower()


def test_queue_validation_invalid_sqs_client():
    """Test that Queue validates sqs_client."""
    from pydantic import ValidationError

    from sqsx.queue import Queue

    # Invalid client (missing receive_message method)
    with pytest.raises(ValidationError) as exc_info:
        Queue(url="http://localhost:9324/000000000000/tests", sqs_client="not a client")

    assert "sqs_client must be a valid boto3 SQS client" in str(exc_info.value)


def test_queue_validation_backoff_consistency(sqs_client):
    """Test that Queue validates backoff configuration consistency."""
    from pydantic import ValidationError

    from sqsx.queue import Queue

    # min_backoff > max_backoff
    with pytest.raises(ValidationError) as exc_info:
        Queue(
            url="http://localhost:9324/000000000000/tests",
            sqs_client=sqs_client,
            min_backoff_seconds=1000,
            max_backoff_seconds=100,
        )

    assert "min_backoff_seconds must be <= max_backoff_seconds" in str(exc_info.value)


def test_queue_validation_backoff_sqs_limit(sqs_client):
    """Test that Queue validates max_backoff against SQS limit."""
    from pydantic import ValidationError

    from sqsx.queue import Queue

    # max_backoff exceeds SQS limit (43200 seconds / 12 hours)
    with pytest.raises(ValidationError) as exc_info:
        Queue(
            url="http://localhost:9324/000000000000/tests", sqs_client=sqs_client, max_backoff_seconds=50000
        )

    assert "max_backoff_seconds" in str(exc_info.value).lower()


def test_queue_interruptible_sleep_on_no_messages(sqs_client, queue_url):
    """Test that queue checks stop flag during sleep when no messages received."""
    from sqsx.queue import Queue

    sqs_client.create_queue(QueueName=queue_url.split("/")[-1])
    queue = Queue(url=queue_url, sqs_client=sqs_client)

    def consume_and_stop():
        # Wait a bit then trigger stop
        time.sleep(0.3)
        queue.exit_gracefully()

    stopper = threading.Thread(target=consume_and_stop)
    stopper.start()

    start_time = time.time()
    # This would normally wait 10 seconds (default wait_seconds)
    # But with interruptible sleep, it should stop much faster
    queue.consume_messages(
        wait_seconds=10, polling_wait_seconds=0, run_forever=True, enable_signal_to_exit_gracefully=False
    )
    elapsed = time.time() - start_time

    stopper.join()

    # Should exit in less than 2 seconds (not the full 10 seconds)
    assert elapsed < 2.0

    sqs_client.delete_queue(QueueUrl=queue_url)


def test_queue_consume_message_missing_message_attributes():
    """Test that missing MessageAttributes doesn't crash."""
    import boto3

    sqs_client = boto3.client("sqs", endpoint_url="http://localhost:9324", region_name="us-east-1")
    queue_url = "http://localhost:9324/000000000000/tests"

    from sqsx.queue import Queue

    queue = Queue(url=queue_url, sqs_client=sqs_client)
    queue._message_nack = mock.MagicMock()

    # Create a message without MessageAttributes
    sqs_message = {"MessageId": "test-id", "Body": "test body", "ReceiptHandle": "test-receipt"}

    queue._consume_message(sqs_message)

    # Should call nack because TaskName is missing
    queue._message_nack.assert_called_once_with(sqs_message)


def test_queue_signal_handler_cleanup(sqs_client, queue_url):
    """Test that signal handlers are properly restored after consume_messages."""
    from sqsx.queue import Queue

    sqs_client.create_queue(QueueName=queue_url.split("/")[-1])
    queue = Queue(url=queue_url, sqs_client=sqs_client)

    # Store original handlers
    original_sigint = signal.signal(signal.SIGINT, signal.SIG_DFL)
    original_sigterm = signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, original_sigint)
    signal.signal(signal.SIGTERM, original_sigterm)

    # Add a task and consume
    queue.add_task_handler("my_task", task_handler)
    queue.add_task("my_task", a=1, b=2, c=3)

    queue.consume_messages(run_forever=False, enable_signal_to_exit_gracefully=True)

    # After consuming, signal handlers should be restored
    current_sigint = signal.signal(signal.SIGINT, signal.SIG_DFL)
    current_sigterm = signal.signal(signal.SIGTERM, signal.SIG_DFL)

    # Restore them again
    signal.signal(signal.SIGINT, current_sigint)
    signal.signal(signal.SIGTERM, current_sigterm)

    # The handlers should be the same as before
    assert current_sigint == original_sigint
    assert current_sigterm == original_sigterm

    sqs_client.delete_queue(QueueUrl=queue_url)


def test_queue_graceful_shutdown_waits_for_active_tasks(sqs_client, queue_url):
    """Test that graceful shutdown waits for active tasks to complete."""
    from sqsx.queue import Queue

    sqs_client.create_queue(QueueName=queue_url.split("/")[-1])
    queue = Queue(url=queue_url, sqs_client=sqs_client)

    completed = []

    def slow_handler(context, value):
        time.sleep(0.5)  # Simulate slow task
        completed.append(value)

    queue.add_task_handler("my_task", slow_handler)

    # Add multiple tasks
    for i in range(3):
        queue.add_task("my_task", value=i)

    def trigger_stop():
        time.sleep(0.1)  # Let tasks start
        queue.exit_gracefully()

    stopper = threading.Thread(target=trigger_stop)
    stopper.start()

    queue.consume_messages(
        max_messages=3, max_threads=3, run_forever=True, enable_signal_to_exit_gracefully=False
    )

    stopper.join()

    # All submitted tasks should complete
    assert len(completed) == 3

    sqs_client.delete_queue(QueueUrl=queue_url)


def test_raw_queue_validation(sqs_client):
    """Test that RawQueue validates configuration."""
    from pydantic import ValidationError

    from sqsx.queue import RawQueue

    def handler(url, msg):
        pass

    # Invalid backoff configuration
    with pytest.raises(ValidationError):
        RawQueue(
            url="http://localhost:9324/000000000000/tests",
            sqs_client=sqs_client,
            message_handler_function=handler,
            min_backoff_seconds=1000,
            max_backoff_seconds=100,
        )


def test_queue_message_ack_handles_errors(queue, sqs_message, caplog):
    """Test that _message_ack handles SQS errors gracefully."""
    from botocore.exceptions import ClientError

    original_delete = queue.sqs_client.delete_message

    def mock_delete(*args, **kwargs):
        error_response = {"Error": {"Code": "ServiceUnavailable"}}
        raise ClientError(error_response, "DeleteMessage")

    queue.sqs_client.delete_message = mock_delete

    # Should not raise exception
    queue._message_ack(sqs_message)

    # Should log error
    assert any("Failed to delete message" in record[2] for record in caplog.record_tuples)

    # Restore original
    queue.sqs_client.delete_message = original_delete


def test_queue_message_nack_handles_errors(queue, sqs_message, caplog):
    """Test that _message_nack handles SQS errors gracefully."""
    from botocore.exceptions import ClientError

    original_change = queue.sqs_client.change_message_visibility

    def mock_change(*args, **kwargs):
        error_response = {"Error": {"Code": "ServiceUnavailable"}}
        raise ClientError(error_response, "ChangeMessageVisibility")

    queue.sqs_client.change_message_visibility = mock_change

    # Should not raise exception
    queue._message_nack(sqs_message)

    # Should log error
    assert any("Failed to change message visibility" in record[2] for record in caplog.record_tuples)

    # Restore original
    queue.sqs_client.change_message_visibility = original_change
