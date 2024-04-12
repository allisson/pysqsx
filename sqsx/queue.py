import logging
import signal
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, Callable, Dict, Optional

from pydantic import BaseModel, Field, PrivateAttr

from sqsx.exceptions import NoRetry, Retry
from sqsx.helper import backoff_calculator_seconds, base64_to_dict, dict_to_base64

logger = logging.getLogger(__name__)
queue_url_regex = r"(http|https)[:][\/]{2}[a-zA-Z0-9-_:.]+[\/][0-9]{12}[\/]{1}[a-zA-Z0-9-_]{0,80}"


class BaseQueueMixin:
    def consume_messages(
        self,
        max_messages: int = 1,
        max_threads: int = 1,
        wait_seconds: int = 10,
        polling_wait_seconds: int = 10,
        run_forever: bool = True,
    ) -> None:
        logger.info(f"Starting consuming tasks, queue_url={self.url}")
        signal.signal(signal.SIGINT, self._exit_gracefully)
        signal.signal(signal.SIGTERM, self._exit_gracefully)

        while True:
            if self._should_consume_tasks_stop:
                logger.info(f"Stopping consuming tasks, queue_url={self.url}")
                break

            response = self.sqs_client.receive_message(
                QueueUrl=self.url,
                AttributeNames=["All"],
                MaxNumberOfMessages=min(max_messages, 10),
                MessageAttributeNames=["All"],
                WaitTimeSeconds=polling_wait_seconds,
            )

            sqs_messages = response.get("Messages", [])
            if not sqs_messages:
                logger.debug(
                    f"Waiting some seconds because no message was received, seconds={wait_seconds}, queue_url={self.url}"
                )
                time.sleep(wait_seconds)
                continue

            with ThreadPoolExecutor(max_workers=max_threads) as executor:
                futures = []
                for sqs_message in sqs_messages:
                    futures.append(executor.submit(self._consume_message, sqs_message))
                wait(futures)

            if not run_forever:
                break

    def _exit_gracefully(self, signal_num, current_stack_frame) -> None:
        logger.info("Starting graceful shutdown process")
        self._should_consume_tasks_stop = True

    def _message_ack(self, sqs_message: dict) -> None:
        receipt_handle = sqs_message["ReceiptHandle"]
        self.sqs_client.delete_message(QueueUrl=self.url, ReceiptHandle=receipt_handle)

    def _message_nack(
        self,
        sqs_message: dict,
        min_backoff_seconds: Optional[int] = None,
        max_backoff_seconds: Optional[int] = None,
    ) -> None:
        min_backoff_seconds = min_backoff_seconds if min_backoff_seconds else self.min_backoff_seconds
        max_backoff_seconds = max_backoff_seconds if max_backoff_seconds else self.max_backoff_seconds
        receipt_handle = sqs_message["ReceiptHandle"]
        receive_count = int(sqs_message["Attributes"]["ApproximateReceiveCount"]) - 1
        timeout = backoff_calculator_seconds(receive_count, min_backoff_seconds, max_backoff_seconds)
        self.sqs_client.change_message_visibility(
            QueueUrl=self.url, ReceiptHandle=receipt_handle, VisibilityTimeout=timeout
        )


class Queue(BaseModel, BaseQueueMixin):
    url: str = Field(pattern=queue_url_regex)
    sqs_client: Any
    min_backoff_seconds: int = Field(default=30)
    max_backoff_seconds: int = Field(default=900)
    _handlers: Dict[str, Callable] = PrivateAttr(default={})
    _should_consume_tasks_stop: bool = PrivateAttr(default=False)

    def add_task(self, task_name: str, **task_kwargs) -> dict:
        return self.sqs_client.send_message(
            QueueUrl=self.url,
            MessageAttributes={"TaskName": {"DataType": "String", "StringValue": task_name}},
            MessageBody=dict_to_base64({"kwargs": task_kwargs}),
        )

    def add_task_handler(self, task_name: str, task_handler_function: Callable) -> None:
        self._handlers.update({task_name: task_handler_function})

    def _consume_message(self, sqs_message: dict) -> None:
        message_id = sqs_message["MessageId"]
        task_name_attribute = sqs_message["MessageAttributes"].get("TaskName")
        if task_name_attribute is None:
            logger.warning(f"Message without TaskName attribute, message_id={message_id}")
            return self._message_nack(sqs_message)

        task_name = task_name_attribute["StringValue"]
        task_handler_function = self._handlers.get(task_name)
        if task_handler_function is None:
            logger.warning(f"Task handler not found, message_id={message_id}, task_name={task_name}")
            return self._message_nack(sqs_message)

        try:
            message_data = base64_to_dict(sqs_message["Body"])
        except Exception:
            logger.exception(f"Invalid message body, message_id={message_id}, task_name={task_name}")
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
                f"Received an sqsx.Retry, setting a custom backoff policy, message_id={message_id}, task_name={task_name}"
            )
            return self._message_nack(
                sqs_message,
                min_backoff_seconds=exc.min_backoff_seconds,
                max_backoff_seconds=exc.max_backoff_seconds,
            )
        except NoRetry:
            logger.info(
                f"Received an sqsx.NoRetry, removing the task, message_id={message_id}, task_name={task_name}"
            )
            return self._message_ack(sqs_message)
        except Exception:
            logger.exception(f"Error while processing, message_id={message_id}, task_name={task_name}")
            return self._message_nack(sqs_message)

        self._message_ack(sqs_message)


class RawQueue(BaseModel, BaseQueueMixin):
    url: str = Field(pattern=queue_url_regex)
    message_handler_function: Callable
    sqs_client: Any
    min_backoff_seconds: int = Field(default=30)
    max_backoff_seconds: int = Field(default=900)
    _should_consume_tasks_stop: bool = PrivateAttr(default=False)

    def add_message(self, message_body: str, message_attributes: dict = {}) -> dict:
        return self.sqs_client.send_message(
            QueueUrl=self.url,
            MessageAttributes=message_attributes,
            MessageBody=message_body,
        )

    def _consume_message(self, sqs_message: dict) -> None:
        message_id = sqs_message["MessageId"]

        try:
            self.message_handler_function(self.url, sqs_message)
        except Retry as exc:
            logger.info(f"Received an sqsx.Retry, setting a custom backoff policy, message_id={message_id}")
            return self._message_nack(
                sqs_message,
                min_backoff_seconds=exc.min_backoff_seconds,
                max_backoff_seconds=exc.max_backoff_seconds,
            )
        except NoRetry:
            logger.info(f"Received an sqsx.NoRetry, removing the message, message_id={message_id}")
            return self._message_ack(sqs_message)
        except Exception:
            logger.exception(f"Error while processing, message_id={message_id}")
            return self._message_nack(sqs_message)

        self._message_ack(sqs_message)
