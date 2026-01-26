# Examples

This directory contains example scripts demonstrating various sqsx usage patterns.

## stress_test.py

Comprehensive stress test for validating queue performance and stability.

### Features

- **Memory stability testing**: Monitors memory usage over extended periods
- **Concurrency testing**: Validates thread safety with multiple workers
- **Performance metrics**: Tracks throughput, latency, and error rates
- **Graceful shutdown**: Tests clean shutdown under load
- **Configurable load**: Adjustable message count, threads, and duration

### Prerequisites

**Option 1: Local Testing (Recommended)**

Start elasticmq with Docker:
```bash
docker run --name sqsx-elasticmq -p 9324:9324 -d softwaremill/elasticmq-native
```

**Option 2: AWS SQS**

Configure AWS credentials and create a queue, then use the `--aws` flag.

### Installation

Install required dependencies:
```bash
pip install sqsx psutil
```

### Usage Examples

**Basic stress test (5 minutes, 1000 messages, 5 threads):**
```bash
python stress_test.py
```

**Extended test (1 hour, 10 threads, 5000 messages):**
```bash
python stress_test.py --duration 3600 --threads 10 --messages 5000
```

**Continuous test (run until manually stopped):**
```bash
python stress_test.py --duration 0 --threads 5 --messages 10000
```

**With AWS SQS:**
```bash
python stress_test.py --aws --queue-url https://sqs.us-east-1.amazonaws.com/123456789012/my-queue
```

**All options:**
```bash
python stress_test.py \
  --queue-url http://localhost:9324/000000000000/stress-test \
  --duration 1800 \
  --threads 8 \
  --messages 2000 \
  [--aws]
```

### What It Tests

1. **Thread Safety**
   - Concurrent message processing with multiple workers
   - Thread-safe metrics collection
   - No race conditions or deadlocks

2. **Memory Stability**
   - Reports memory usage throughout test
   - Validates no memory leaks over extended periods
   - Tests with thousands of messages

3. **Performance**
   - Messages processed per second (throughput)
   - Average task processing duration
   - Periodic statistics reporting (every 30 seconds)

4. **Error Handling**
   - Simulates task failures (1% error rate)
   - Tracks error types and counts
   - Validates retry behavior

5. **Graceful Shutdown**
   - Tests clean shutdown via timeout or Ctrl+C
   - Ensures all active tasks complete
   - Proper resource cleanup

### Output

The script provides detailed metrics during and after the test:

```
==============================================================
STRESS TEST METRICS
==============================================================
Elapsed Time: 301.45 seconds (5.02 minutes)
Messages Processed: 1000
Errors: 10
Throughput: 3.32 messages/sec
Avg Task Duration: 0.0042 seconds
Error Breakdown:
  - ValueError: 10
==============================================================
Final Memory Usage: 45.23 MB
==============================================================
```

### Interpreting Results

**Good Results:**
- Throughput remains stable throughout test
- Memory usage stays constant (no steady increase)
- Error count matches expected rate (~1%)
- Clean shutdown within 10 seconds

**Warning Signs:**
- Decreasing throughput over time (potential resource leak)
- Steadily increasing memory (memory leak)
- High error rates (> 5%)
- Delayed shutdown (> 30 seconds)

### Recommended Test Scenarios

**Development Testing:**
```bash
python stress_test.py --duration 300 --threads 3 --messages 500
```

**Pre-Production Validation:**
```bash
python stress_test.py --duration 3600 --threads 10 --messages 5000
```

**Long-Running Stability Test (24 hours):**
```bash
python stress_test.py --duration 86400 --threads 5 --messages 50000
```

**High Concurrency Test:**
```bash
python stress_test.py --duration 600 --threads 20 --messages 2000
```

### Troubleshooting

**Connection Errors:**
- Ensure elasticmq is running: `docker ps | grep elasticmq`
- Check port 9324 is accessible: `curl http://localhost:9324`

**Performance Issues:**
- Increase boto3 connection pool: Edit script to set `max_pool_connections=threads`
- Reduce message count or threads to isolate bottlenecks

**Memory Issues:**
- Install psutil: `pip install psutil`
- Monitor with system tools: `top -pid $(pgrep -f stress_test.py)`

### Customization

Edit the script to customize test behavior:

1. **Message Size**: Modify `payload=f"data_{i}" * 100` (line ~158)
2. **Error Rate**: Change `random.random() < 0.01` (line ~95)
3. **Slow Task Rate**: Adjust `random.random() < 0.2` (line ~92)
4. **Reporting Interval**: Change `time.sleep(30)` (line ~175)

### Integration with CI/CD

Add to your test pipeline:

```yaml
# GitHub Actions example
- name: Run stress test
  run: |
    docker run -d -p 9324:9324 softwaremill/elasticmq-native
    python examples/stress_test.py --duration 180 --threads 5 --messages 500
```

### Notes

- The script uses simulated work (random sleep) to mimic real-world task processing
- 20% of tasks are "slow" (100-500ms delay) to test mixed workloads
- 1% of tasks fail to validate error handling
- Statistics are reported every 30 seconds during execution
- Memory is measured using `psutil` at the end of the test
