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
    assert caplog.record_tuples == [
        (
            "sqsx.queue",
            40,
            "Invalid message body, message_id=33425f12-50e6-4f93-ac26-7ae7a069cf88, task_name=my_task",
        )
    ]


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

    queue.consume_messages(wait_seconds=1, polling_wait_seconds=0, run_forever=True)

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

    raw_queue.consume_messages(wait_seconds=1, polling_wait_seconds=0, run_forever=True)

    assert handler.call_count == 3
