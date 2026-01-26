"""
Stress Test for sqsx Queue

This script performs a comprehensive stress test to validate:
- Memory stability over long periods
- Thread safety with high concurrency
- Graceful shutdown behavior under load
- Error recovery and resilience

Usage:
    # Run for 1 hour with 10 threads processing 1000 messages
    python stress_test.py --duration 3600 --threads 10 --messages 1000

    # Run indefinitely until manually stopped
    python stress_test.py --duration 0 --threads 5 --messages 5000

Requirements:
    - Docker running elasticmq: docker run -p 9324:9324 -d softwaremill/elasticmq-native
    - Or configure AWS SQS credentials in the script
"""

import argparse
import logging
import random
import sys
import threading
import time
from collections import defaultdict

import boto3

from sqsx import Queue

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


class StressTestMetrics:
    """Thread-safe metrics collector for stress testing."""

    def __init__(self):
        self.lock = threading.Lock()
        self.processed = 0
        self.errors = 0
        self.start_time = time.time()
        self.task_durations = []
        self.error_types = defaultdict(int)

    def record_success(self, duration: float):
        with self.lock:
            self.processed += 1
            self.task_durations.append(duration)

    def record_error(self, error_type: str):
        with self.lock:
            self.errors += 1
            self.error_types[error_type] += 1

    def get_stats(self) -> dict:
        with self.lock:
            elapsed = time.time() - self.start_time
            throughput = self.processed / elapsed if elapsed > 0 else 0
            avg_duration = sum(self.task_durations) / len(self.task_durations) if self.task_durations else 0

            return {
                "elapsed_seconds": elapsed,
                "processed": self.processed,
                "errors": self.errors,
                "throughput_per_sec": throughput,
                "avg_task_duration": avg_duration,
                "error_breakdown": dict(self.error_types),
            }

    def print_stats(self):
        stats = self.get_stats()
        logger.info("=" * 60)
        logger.info("STRESS TEST METRICS")
        logger.info("=" * 60)
        logger.info(
            "Elapsed Time: %.2f seconds (%.2f minutes)",
            stats["elapsed_seconds"],
            stats["elapsed_seconds"] / 60,
        )
        logger.info("Messages Processed: %d", stats["processed"])
        logger.info("Errors: %d", stats["errors"])
        logger.info("Throughput: %.2f messages/sec", stats["throughput_per_sec"])
        logger.info("Avg Task Duration: %.4f seconds", stats["avg_task_duration"])
        if stats["error_breakdown"]:
            logger.info("Error Breakdown:")
            for error_type, count in stats["error_breakdown"].items():
                logger.info("  - %s: %d", error_type, count)
        logger.info("=" * 60)


def create_task_handler(metrics: StressTestMetrics, simulate_slow: bool = False):
    """Create a task handler with configurable behavior."""

    def handler(context: dict, task_id: int, payload: str):
        start_time = time.time()

        try:
            # Simulate work
            if simulate_slow and random.random() < 0.2:  # 20% of tasks are slow
                time.sleep(random.uniform(0.1, 0.5))

            # Simulate occasional errors (1%)
            if random.random() < 0.01:
                raise ValueError(f"Simulated error for task {task_id}")

            duration = time.time() - start_time
            metrics.record_success(duration)

            if task_id % 100 == 0:  # Log progress every 100 tasks
                logger.info("Processed task %d (duration: %.4fs)", task_id, duration)

        except Exception as exc:
            metrics.record_error(type(exc).__name__)
            raise

    return handler


def setup_queue(queue_url: str, use_local: bool = True):
    """Set up SQS client and create queue."""

    if use_local:
        # Use local elasticmq
        sqs_client = boto3.client(
            "sqs",
            endpoint_url="http://localhost:9324",
            region_name="elasticmq",
            aws_secret_access_key="x",
            aws_access_key_id="x",
            use_ssl=False,
        )
        queue_name = queue_url.split("/")[-1]
        try:
            sqs_client.create_queue(QueueName=queue_name)
            logger.info("Created local queue: %s", queue_name)
        except Exception:
            logger.info("Queue already exists: %s", queue_name)
    else:
        # Use AWS SQS (configure credentials via environment or AWS config)
        from botocore.config import Config

        config = Config(
            max_pool_connections=20,  # Support high concurrency
            retries={"max_attempts": 3, "mode": "standard"},
        )
        sqs_client = boto3.client("sqs", config=config)
        logger.info("Using AWS SQS with queue: %s", queue_url)

    return sqs_client


def run_stress_test(
    queue_url: str,
    duration_seconds: int,
    num_threads: int,
    num_messages: int,
    use_local: bool = True,
):
    """Run the stress test."""

    logger.info("=" * 60)
    logger.info("STARTING STRESS TEST")
    logger.info("=" * 60)
    logger.info("Queue URL: %s", queue_url)
    logger.info("Duration: %s", "Indefinite" if duration_seconds == 0 else f"{duration_seconds}s")
    logger.info("Threads: %d", num_threads)
    logger.info("Messages: %d", num_messages)
    logger.info("=" * 60)

    # Setup
    metrics = StressTestMetrics()
    sqs_client = setup_queue(queue_url, use_local)
    queue = Queue(
        url=queue_url,
        sqs_client=sqs_client,
        min_backoff_seconds=10,
        max_backoff_seconds=300,
    )

    # Add task handler
    task_handler = create_task_handler(metrics, simulate_slow=True)
    queue.add_task_handler("stress_task", task_handler)

    # Add initial messages
    logger.info("Adding %d messages to queue...", num_messages)
    for i in range(num_messages):
        queue.add_task("stress_task", task_id=i, payload=f"data_{i}" * 100)
        if i % 500 == 0 and i > 0:
            logger.info("Added %d messages...", i)
    logger.info("All messages added!")

    # Set up periodic stats reporting
    stop_reporting = threading.Event()

    def report_stats():
        while not stop_reporting.is_set():
            time.sleep(30)  # Report every 30 seconds
            if not stop_reporting.is_set():
                metrics.print_stats()

    stats_thread = threading.Thread(target=report_stats, daemon=True)
    stats_thread.start()

    # Set up timeout if duration is specified
    if duration_seconds > 0:

        def timeout_shutdown():
            time.sleep(duration_seconds)
            logger.info("Duration elapsed, triggering graceful shutdown...")
            queue.exit_gracefully()

        timeout_thread = threading.Thread(target=timeout_shutdown, daemon=True)
        timeout_thread.start()

    # Start consuming
    try:
        logger.info("Starting message consumption...")
        queue.consume_messages(
            max_messages=10,
            max_threads=num_threads,
            wait_seconds=5,
            polling_wait_seconds=10,
            run_forever=True,
        )
    except KeyboardInterrupt:
        logger.info("Received interrupt, shutting down...")
    finally:
        stop_reporting.set()
        logger.info("Cleanup complete")

    # Final stats
    logger.info("\n")
    logger.info("=" * 60)
    logger.info("STRESS TEST COMPLETE")
    logger.info("=" * 60)
    metrics.print_stats()

    # Memory check (basic)
    import os

    import psutil

    process = psutil.Process(os.getpid())
    memory_mb = process.memory_info().rss / 1024 / 1024
    logger.info("Final Memory Usage: %.2f MB", memory_mb)
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Stress test for sqsx Queue",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--queue-url",
        default="http://localhost:9324/000000000000/stress-test",
        help="SQS queue URL (default: local elasticmq)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=300,
        help="Test duration in seconds (0 = indefinite, default: 300)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=5,
        help="Number of worker threads (default: 5)",
    )
    parser.add_argument(
        "--messages",
        type=int,
        default=1000,
        help="Number of messages to process (default: 1000)",
    )
    parser.add_argument(
        "--aws",
        action="store_true",
        help="Use AWS SQS instead of local elasticmq",
    )

    args = parser.parse_args()

    try:
        run_stress_test(
            queue_url=args.queue_url,
            duration_seconds=args.duration,
            num_threads=args.threads,
            num_messages=args.messages,
            use_local=not args.aws,
        )
    except Exception as exc:
        logger.error("Stress test failed: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
