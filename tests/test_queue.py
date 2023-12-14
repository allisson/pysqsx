import os
import signal
import threading
import time
from unittest import mock

import pytest
from pydantic_core import ValidationError

from sqsx.queue import Queue


def task_handler(context, a, b, c):
    print(f"context={context}, a={a}, b={b}, c={c}")


def exception_handler(context, a, b, c):
    raise Exception("BOOM!")


class SumHandler:
    result_sum = 0

    def __call__(self, context, a, b, c):
        self.result_sum += a + b + c


@pytest.mark.parametrize(
    "queue_url",
    [
        ("https://sqs.us-east-1.amazonaws.com/177715257436"),
        ("https://sqs.us-east-1.amazonaws.com/1/MyQueue"),
        ("https://sqs.us-east-1.amazonaws.com/MyQueue"),
    ],
)
def test_queue_invalid_url(queue_url, sqs_client):
    expected_error = [
        {
            "type": "string_pattern_mismatch",
            "loc": ("url",),
            "msg": "String should match pattern '(http|https)[:][\\/]{2}[a-zA-Z0-9-_:.]+[\\/][0-9]{12}[\\/]{1}[a-zA-Z0-9-_]{0,80}'",
            "input": queue_url,
            "ctx": {
                "pattern": "(http|https)[:][\\/]{2}[a-zA-Z0-9-_:.]+[\\/][0-9]{12}[\\/]{1}[a-zA-Z0-9-_]{0,80}"
            },
            "url": "https://errors.pydantic.dev/2.5/v/string_pattern_mismatch",
        }
    ]

    with pytest.raises(ValidationError) as excinfo:
        Queue(url=queue_url, sqs_client=sqs_client)

    assert excinfo.value.errors() == expected_error


@pytest.mark.parametrize(
    "queue_url",
    [
        ("http://localhost:9324/000000000000/tests"),
        ("https://localhost:9324/000000000000/tests"),
        ("https://sqs.us-east-1.amazonaws.com/177715257436/MyQueue"),
    ],
)
def test_queue_valid_url(queue_url, sqs_client):
    queue = Queue(url=queue_url, sqs_client=sqs_client)
    assert queue.url == queue_url


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


def test_queue_consume_task_without_task_name_attribute(queue, sqs_message, caplog):
    queue._message_nack = mock.MagicMock()
    sqs_message["MessageAttributes"].pop("TaskName")

    queue._consume_task(sqs_message)

    queue._message_nack.assert_called_once_with(sqs_message)
    assert caplog.record_tuples == [
        (
            "sqsx.queue",
            30,
            "Message without TaskName attribute, message_id=33425f12-50e6-4f93-ac26-7ae7a069cf88",
        )
    ]


def test_queue_consume_task_without_task_handler(queue, sqs_message, caplog):
    queue._message_nack = mock.MagicMock()

    queue._consume_task(sqs_message)

    queue._message_nack.assert_called_once_with(sqs_message)
    assert caplog.record_tuples == [
        (
            "sqsx.queue",
            30,
            "Task handler not found, message_id=33425f12-50e6-4f93-ac26-7ae7a069cf88, task_name=my_task",
        )
    ]


def test_queue_consume_task_with_invalid_body(queue, sqs_message, caplog):
    queue._message_nack = mock.MagicMock()
    sqs_message["Body"] = "invalid-body"

    queue.add_task_handler("my_task", task_handler)
    queue._consume_task(sqs_message)

    queue._message_nack.assert_called_once_with(sqs_message)
    assert caplog.record_tuples == [
        (
            "sqsx.queue",
            40,
            "Invalid message body, message_id=33425f12-50e6-4f93-ac26-7ae7a069cf88, task_name=my_task",
        )
    ]


def test_queue_consume_task_with_task_handler_exception(queue, sqs_message, caplog):
    queue._message_nack = mock.MagicMock()

    queue.add_task_handler("my_task", exception_handler)
    queue._consume_task(sqs_message)

    queue._message_nack.assert_called_once_with(sqs_message)
    assert caplog.record_tuples == [
        (
            "sqsx.queue",
            40,
            "Error while processing, message_id=33425f12-50e6-4f93-ac26-7ae7a069cf88, task_name=my_task",
        )
    ]


def test_queue_consume_tasks(queue):
    handler = SumHandler()

    queue.add_task_handler("my_task", handler)
    queue.add_task("my_task", a=1, b=2, c=3)
    queue.add_task("my_task", a=1, b=2, c=3)

    queue.consume_tasks(max_tasks=2, max_threads=2, run_forever=False)

    assert handler.result_sum == 12


def test_queue_consume_tasks_with_task_handler_exception(queue, caplog):
    queue.add_task_handler("my_task", exception_handler)
    queue.add_task("my_task", a=1, b=2, c=3)

    queue.consume_tasks(run_forever=False)

    assert caplog.record_tuples[0][0] == "sqsx.queue"
    assert caplog.record_tuples[0][1] == 40
    assert "Error while processing" in caplog.record_tuples[0][2]


def test_queue_exit_gracefully(queue):
    def trigger_signal():
        pid = os.getpid()
        time.sleep(0.2)
        os.kill(pid, signal.SIGINT)

    thread = threading.Thread(target=trigger_signal)
    thread.daemon = True
    thread.start()
    handler = SumHandler()

    queue.add_task_handler("my_task", handler)
    queue.add_task("my_task", a=1, b=2, c=3)

    queue.consume_tasks(wait_seconds=1, run_forever=True)

    assert handler.result_sum == 6
