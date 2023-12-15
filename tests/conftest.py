import boto3
import pytest

from sqsx.queue import Queue, RawQueue


@pytest.fixture
def sqs_client():
    return boto3.client(
        "sqs",
        endpoint_url="http://localhost:9324",
        region_name="elasticmq",
        aws_secret_access_key="x",
        aws_access_key_id="x",
        use_ssl=False,
    )


@pytest.fixture
def queue_url():
    return "http://localhost:9324/000000000000/tests"


@pytest.fixture
def raw_queue_url():
    return "http://localhost:9324/000000000000/raw_tests"


@pytest.fixture
def queue(sqs_client, queue_url, caplog):
    caplog.set_level("INFO")
    sqs_client.create_queue(QueueName=queue_url.split("/")[-1])
    yield Queue(url=queue_url, sqs_client=sqs_client)
    sqs_client.delete_queue(QueueUrl=queue_url)


@pytest.fixture
def raw_queue(sqs_client, raw_queue_url, caplog):
    def task_handler_function(queue_url, sqs_message):
        print(f"queue_url={queue_url}, sqs_message={sqs_message}")

    caplog.set_level("INFO")
    sqs_client.create_queue(QueueName=raw_queue_url.split("/")[-1])
    yield RawQueue(url=raw_queue_url, message_handler_function=task_handler_function, sqs_client=sqs_client)
    sqs_client.delete_queue(QueueUrl=raw_queue_url)


@pytest.fixture
def sqs_message():
    return {
        "MessageId": "33425f12-50e6-4f93-ac26-7ae7a069cf88",
        "ReceiptHandle": "33425f12-50e6-4f93-ac26-7ae7a069cf88#d128816c-aea8-406b-bbdd-1edbacb5573f",
        "MD5OfBody": "8087eb7436895841c5d646156a8a469f",
        "Body": "eyJrd2FyZ3MiOiB7ImEiOiAxLCAiYiI6IDIsICJjIjogM319",
        "Attributes": {
            "SentTimestamp": "1702512255653",
            "ApproximateReceiveCount": "1",
            "ApproximateFirstReceiveTimestamp": "1702512255660",
            "SenderId": "127.0.0.1",
        },
        "MD5OfMessageAttributes": "5346f2cd7c539a880febaf9112a86921",
        "MessageAttributes": {"TaskName": {"StringValue": "my_task", "DataType": "String"}},
    }
