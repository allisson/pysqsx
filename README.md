# pysqsx
[![Tests](https://github.com/allisson/pysqsx/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/allisson/pysqsx/actions/workflows/tests.yml)
![PyPI - Version](https://img.shields.io/pypi/v/sqsx)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/sqsx)
![GitHub License](https://img.shields.io/github/license/allisson/pysqsx)

A simple task processor for Amazon SQS.

## quickstart

For this demonstration we will use elasticmq locally using docker:

```bash
docker run --name pysqsx-elasticmq -p 9324:9324 -d softwaremill/elasticmq-native
```

Install the package:

```bash
pip install sqsx
```

Now let's create a script that will create some tasks and we will consume them:

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

# create the task handler, the first argument must be the context
def task_handler(context, a, b, c):
    print(f"context={context}, a={a}, b={b}, c={c}")

# add a new task handler
queue.add_task_handler("my_task", task_handler)

# start the consumption of tasks, to stop press ctrl+c to exit gracefully
queue.consume_tasks()
```

Running the script:

```bash
python script.py
INFO:sqsx.queue:Starting consuming tasks, queue_url=http://localhost:9324/000000000000/tests
context={'queue_url': 'http://localhost:9324/000000000000/tests', 'task_name': 'my_task', 'sqs_message': {'MessageId': '0c126462-0184-485b-b66f-77ed0b6f3780', 'ReceiptHandle': '0c126462-0184-485b-b66f-77ed0b6f3780#2959620c-7ead-4e12-80a7-672530c43f26', 'MD5OfBody': '8087eb7436895841c5d646156a8a469f', 'Body': 'eyJrd2FyZ3MiOiB7ImEiOiAxLCAiYiI6IDIsICJjIjogM319', 'Attributes': {'SentTimestamp': '1702527171600', 'ApproximateReceiveCount': '1', 'ApproximateFirstReceiveTimestamp': '1702527171603', 'SenderId': '127.0.0.1'}, 'MD5OfMessageAttributes': '5346f2cd7c539a880febaf9112a86921', 'MessageAttributes': {'TaskName': {'StringValue': 'my_task', 'DataType': 'String'}}}}, a=1, b=2, c=3
DEBUG:sqsx.queue:Waiting some seconds because no message was received, seconds=10, queue_url=http://localhost:9324/000000000000/tests
DEBUG:sqsx.queue:Waiting some seconds because no message was received, seconds=10, queue_url=http://localhost:9324/000000000000/tests
^CINFO:sqsx.queue:Starting graceful shutdown process
INFO:sqsx.queue:Stopping consuming tasks, queue_url=http://localhost:9324/000000000000/tests
```
