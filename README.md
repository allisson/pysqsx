# sqsx 🚀
[![Tests](https://github.com/allisson/pysqsx/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/allisson/pysqsx/actions/workflows/tests.yml)
![PyPI - Version](https://img.shields.io/pypi/v/sqsx)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/sqsx)
![GitHub License](https://img.shields.io/github/license/allisson/pysqsx)

A simple, robust, and thread-safe task processor for Amazon SQS. 💪

## ✨ Features

- 🔒 **Thread-Safe**: Built-in locks protect shared state in multi-threaded environments
- 🔄 **Resilient**: Automatic retry with exponential backoff for transient failures
- 🛑 **Graceful Shutdown**: Clean shutdown on SIGINT/SIGTERM with proper resource cleanup
- 📦 **Context Manager Support**: Use `with` statements for automatic cleanup
- 📏 **Message Size Validation**: Enforces SQS 256KB message limit
- 🏭 **Production Ready**: Comprehensive error handling for SQS API failures
- ✅ **Type Validated**: Pydantic-based configuration validation
- ⚡ **High Performance**: Messages acknowledged as they complete (not batch-blocked)
- 📚 **Well Documented**: Comprehensive docstrings for all public APIs
- 🧪 **Fully Tested**: 59 tests with 100% pass rate

## 🚀 Quickstart

For this demonstration we will use elasticmq locally using docker:

```bash
docker run --name pysqsx-elasticmq -p 9324:9324 -d softwaremill/elasticmq-native
```

Install the package:

```bash
pip install sqsx
```

### 📋 Working with sqsx.Queue

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

### 🔧 Working with sqsx.RawQueue

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

## 🎯 Advanced Usage

### 🗂️ Using Context Managers

Both `Queue` and `RawQueue` support context managers for automatic resource cleanup:

```python
from sqsx import Queue

# Context manager ensures proper cleanup
with Queue(url=queue_url, sqs_client=sqs_client) as queue:
    queue.add_task_handler("my_task", task_handler)
    queue.add_task("my_task", a=1, b=2, c=3)
    queue.consume_messages(run_forever=False)
# Resources are automatically cleaned up when exiting the context
```

### ⚡ Concurrent Processing

Process multiple messages concurrently using threads:

```python
# Process up to 10 messages at once with 5 worker threads
queue.consume_messages(
    max_messages=10,        # Fetch up to 10 messages per batch
    max_threads=5,          # Process with 5 concurrent threads
    run_forever=True
)
```

**🚀 Performance Optimization**: Messages are acknowledged as they complete (using `as_completed()`), not waiting for the slowest message. This means fast messages are acknowledged immediately, improving overall throughput.

**⚠️ Important**: For optimal performance with `max_threads > 1`, configure boto3 connection pooling:

```python
from botocore.config import Config

config = Config(
    max_pool_connections=5,  # Match your max_threads value
    retries={'max_attempts': 3, 'mode': 'standard'}
)
sqs_client = boto3.client('sqs', config=config, ...)
```

Without connection pooling, threads will compete for a single connection, reducing throughput. Always set `max_pool_connections` to at least your `max_threads` value. 📊

### 🛑 Programmatic Graceful Shutdown

Trigger graceful shutdown programmatically:

```python
import threading

def shutdown_after_delay():
    import time
    time.sleep(30)  # Wait 30 seconds
    queue.exit_gracefully()

# Start consumer
shutdown_thread = threading.Thread(target=shutdown_after_delay)
shutdown_thread.start()

queue.consume_messages(
    run_forever=True,
    enable_signal_to_exit_gracefully=False  # Disable signal handlers
)

shutdown_thread.join()
```

### ⚙️ Configuration Options

Configure backoff behavior and queue parameters:

```python
queue = Queue(
    url=queue_url,
    sqs_client=sqs_client,
    min_backoff_seconds=30,    # Minimum retry delay (default: 30)
    max_backoff_seconds=900,   # Maximum retry delay (default: 900, max: 43200)
)
```

The backoff calculator uses exponential backoff: `timeout = min(min_backoff * 2^retries, max_backoff)`

### 🎛️ consume_messages() Parameters

Fine-tune message consumption behavior:

```python
queue.consume_messages(
    max_messages=1,              # Messages per batch (1-10, default: 1)
    max_threads=1,               # Worker threads (default: 1)
    wait_seconds=10,             # Sleep when no messages (default: 10)
    polling_wait_seconds=10,     # SQS long polling timeout (default: 10)
    run_forever=True,            # Continue until stopped (default: True)
    enable_signal_to_exit_gracefully=True  # Handle SIGINT/SIGTERM (default: True)
)
```

### ⚠️ Working with exceptions

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

## 🛡️ Error Handling & Resilience

### 🔄 Automatic Retry on Transient Failures

sqsx automatically handles and retries transient SQS API failures:

- **⏱️ Throttling errors**: Automatically retried with a 5-second delay
- **🌐 Network errors**: Connection issues are logged and retried
- **☁️ Service unavailable**: Temporary AWS outages are handled gracefully

```python
# No special code needed - automatic retry is built-in
queue.consume_messages()
```

Error logs will show retry attempts:

```
ERROR:sqsx.queue:SQS API error: ThrottlingException, queue_url=..., retrying...
ERROR:sqsx.queue:Network/connection error: EndpointConnectionError, queue_url=..., retrying...
```

### 📏 Message Size Limits

Messages are automatically validated against SQS limits (256KB):

```python
# Will raise ValueError if message exceeds 256KB
try:
    queue.add_task("my_task", large_data=huge_string)
except ValueError as e:
    print(f"Message too large: {e}")
```

### 🔄 Graceful Shutdown Behavior

When shutdown is triggered (SIGINT, SIGTERM, or `exit_gracefully()`):

1. ⛔ **Stop flag is set**: No new message batches are fetched
2. ✅ **Active tasks complete**: All currently processing messages finish
3. 🧹 **Clean resource cleanup**: Handlers are cleared, signal handlers restored
4. ⚡ **Fast response**: Stop flag checked every 100ms during idle periods

This ensures no messages are lost or left in a processing state during shutdown.

## 🔒 Thread Safety

sqsx is fully thread-safe for concurrent message processing:

- 🔐 **Shared state protection**: All shared data structures use locks
- ✅ **Safe handler registration**: Handlers can be added during message processing
- 🤝 **Coordinated shutdown**: Stop flag properly synchronized across threads

Example with concurrent processing:

```python
# Safe to use with multiple threads
queue.consume_messages(max_messages=10, max_threads=5)

# Safe to add handlers while processing (in another thread)
queue.add_task_handler("new_task", new_handler)
```

## 💡 Best Practices

1. **🗂️ Use context managers** for automatic cleanup:
   ```python
   with Queue(url=queue_url, sqs_client=sqs_client) as queue:
       # Your code here
       pass
   # Automatically cleaned up
   ```

2. **🔌 Configure connection pooling** for concurrent processing:
   ```python
   config = Config(max_pool_connections=max_threads)
   sqs_client = boto3.client('sqs', config=config, ...)
   ```

3. **📦 Keep messages small** (under 256KB) for better performance

4. **⏱️ Use appropriate backoff values** for your use case:
   - Short-lived tasks: `min_backoff_seconds=10, max_backoff_seconds=300`
   - Long-running tasks: `min_backoff_seconds=60, max_backoff_seconds=3600`

5. **🛡️ Monitor and handle exceptions** appropriately in your handlers

6. **🧪 Test graceful shutdown** in your deployment process

## 📦 Requirements

- Python 3.10+
- boto3
- pydantic

## 📄 License

This project is licensed under the MIT License.
