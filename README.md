# sqsx
[![Tests](https://github.com/allisson/pysqsx/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/allisson/pysqsx/actions/workflows/tests.yml)
![PyPI - Version](https://img.shields.io/pypi/v/sqsx)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/sqsx)
![GitHub License](https://img.shields.io/github/license/allisson/pysqsx)

A simple task processor for Amazon SQS.

## Quickstart

For this demonstration we will use elasticmq locally using docker:

```bash
docker run --name pysqsx-elasticmq -p 9324:9324 -d softwaremill/elasticmq-native
```

Install the package:

```bash
pip install sqsx
```

### Working with sqsx.Queue

We use sqsx.Queue when we need to work with scheduling and consuming tasks.

Now let's create a script that will create a new task and we will consume them:

```python
# file script.py
import logging

import boto3

from sqsx import Queue

# configure the logging
logging.basicConfig(level=logging.DEBUG)
logging.getLogger('botocore').setLevel(logging.CRITICAL)
logging.getLogger('urllib3').setLevel(logging.CRITICAL)

# create the sqs_client
queue_url = "http://localhost:9324/000000000000/tests"
queue_name = "tests"
sqs_client = boto3.client(
    "sqs",
    endpoint_url="http://localhost:9324",
    region_name="elasticmq",
    aws_secret_access_key="x",
    aws_access_key_id="x",
    use_ssl=False,
)

# create the new sqs queue
sqs_client.create_queue(QueueName=queue_name)

# create the sqsx.Queue
queue = Queue(url=queue_url, sqs_client=sqs_client)

# add a new task
queue.add_task("my_task", a=1, b=2, c=3)

# create the task handler, which must be a simple function like this
def task_handler(context: dict, a: int, b: int, c: int):
    print(f"context={context}, a={a}, b={b}, c={c}")

# add a new task handler
queue.add_task_handler("my_task", task_handler)

# start the consumption of messages, to stop press ctrl+c to exit gracefully
queue.consume_messages()
```

Running the script:

```bash
python script.py
INFO:sqsx.queue:Starting consuming tasks, queue_url=http://localhost:9324/000000000000/tests
context={'queue_url': 'http://localhost:9324/000000000000/tests', 'task_name': 'my_task', 'sqs_message': {'MessageId': '42513c2d-ac93-4701-bb63-83b45e6fe2ca', 'ReceiptHandle': '42513c2d-ac93-4701-bb63-83b45e6fe2ca#6eb5443b-a2eb-454e-8619-86f6d2e67561', 'MD5OfBody': '8087eb7436895841c5d646156a8a469f', 'Body': 'eyJrd2FyZ3MiOiB7ImEiOiAxLCAiYiI6IDIsICJjIjogM319', 'Attributes': {'SentTimestamp': '1702573178736', 'ApproximateReceiveCount': '1', 'ApproximateFirstReceiveTimestamp': '1702573178740', 'SenderId': '127.0.0.1'}, 'MD5OfMessageAttributes': '5346f2cd7c539a880febaf9112a86921', 'MessageAttributes': {'TaskName': {'StringValue': 'my_task', 'DataType': 'String'}}}}, a=1, b=2, c=3
DEBUG:sqsx.queue:Waiting some seconds because no message was received, seconds=10, queue_url=http://localhost:9324/000000000000/tests
DEBUG:sqsx.queue:Waiting some seconds because no message was received, seconds=10, queue_url=http://localhost:9324/000000000000/tests
^CINFO:sqsx.queue:Starting graceful shutdown process
INFO:sqsx.queue:Stopping consuming tasks, queue_url=http://localhost:9324/000000000000/tests
```

### Working with sqsx.RawQueue

We use sqsx.RawQueue when we need to work with one handler consuming all the queue messages.

Now let's create a script that will create a new message and we will consume them:

```python
# file raw_script.py
import logging

import boto3

from sqsx import RawQueue

# configure the logging
logging.basicConfig(level=logging.DEBUG)
logging.getLogger('botocore').setLevel(logging.CRITICAL)
logging.getLogger('urllib3').setLevel(logging.CRITICAL)

# create the sqs_client
queue_url = "http://localhost:9324/000000000000/tests"
queue_name = "tests"
sqs_client = boto3.client(
    "sqs",
    endpoint_url="http://localhost:9324",
    region_name="elasticmq",
    aws_secret_access_key="x",
    aws_access_key_id="x",
    use_ssl=False,
)

# create the new sqs queue
sqs_client.create_queue(QueueName=queue_name)

# create the message handler, which must be a simple function like this
def message_handler(queue_url: str, sqs_message: dict):
    print(f"queue_url={queue_url}, sqs_message={sqs_message}")

# create the sqsx.Queue
queue = RawQueue(url=queue_url, message_handler_function=message_handler, sqs_client=sqs_client)

# add a new message
queue.add_message(
    message_body="My Message",
    message_attributes={"Attr1": {"DataType": "String", "StringValue": "Attr1"}},
)

# start the consumption of messages, to stop press ctrl+c to exit gracefully
queue.consume_messages()
```

Running the script:

```bash
INFO:sqsx.queue:Starting consuming tasks, queue_url=http://localhost:9324/000000000000/tests
queue_url=http://localhost:9324/000000000000/tests, sqs_message={'MessageId': 'fb2ed6cf-9346-4ded-8cfe-4fc297f95928', 'ReceiptHandle': 'fb2ed6cf-9346-4ded-8cfe-4fc297f95928#bd9f27a6-0a73-4d27-9c1e-0947f21d3c02', 'MD5OfBody': '069840f6917e85a02167febb964f0041', 'Body': 'My Message', 'Attributes': {'SentTimestamp': '1702573585302', 'ApproximateReceiveCount': '1', 'ApproximateFirstReceiveTimestamp': '1702573585306', 'SenderId': '127.0.0.1'}, 'MD5OfMessageAttributes': '90f34a800b9d242c1b32320e4a3ed630', 'MessageAttributes': {'Attr1': {'StringValue': 'Attr1', 'DataType': 'String'}}}
DEBUG:sqsx.queue:Waiting some seconds because no message was received, seconds=10, queue_url=http://localhost:9324/000000000000/tests
DEBUG:sqsx.queue:Waiting some seconds because no message was received, seconds=10, queue_url=http://localhost:9324/000000000000/tests
^CINFO:sqsx.queue:Starting graceful shutdown process
INFO:sqsx.queue:Stopping consuming tasks, queue_url=http://localhost:9324/000000000000/tests
```

### Working with exceptions

The default behavior is to retry the message when an exception is raised, you can change this behavior using the exceptions sqsx.exceptions.Retry and sqsx.exceptions.NoRetry.

If you want to change the backoff policy, use the sqsx.exceptions.Retry like this:

```python
from sqsx.exceptions import Retry

# to use with sqsx.Queue and change the default backoff policy
def task_handler(context: dict, a: int, b: int, c: int):
    raise Retry(min_backoff_seconds=100, max_backoff_seconds=200)

# to use with sqsx.RawQueue and change the default backoff policy
def message_handler(queue_url: str, sqs_message: dict):
    raise Retry(min_backoff_seconds=100, max_backoff_seconds=200)
```

If you want to remove the task or message from the queue use the sqsx.exceptions.NoRetry like this:

```python
from sqsx.exceptions import NoRetry

# to use with sqsx.Queue and remove the task
def task_handler(context: dict, a: int, b: int, c: int):
    raise NoRetry()

# to use with sqsx.RawQueue and remove the message
def message_handler(queue_url: str, sqs_message: dict):
    raise NoRetry()
```
