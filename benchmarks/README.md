# Benchmarks

Performance benchmarks for PatchVec.

## search_latency.py

Measures search latency under concurrent load.

### Requirements

```bash
pip install httpx
```

### Usage

Start PatchVec server first:
```bash
PATCHVEC_DEV=1 python -m pave.main
```

Run benchmark:
```bash
python benchmarks/search_latency.py --url http://localhost:8086 --queries 100 --concurrency 10
```

### Options

* `--url` - PatchVec base URL (default: http://localhost:8086)
* `--queries` - Number of queries to run (default: 100)
* `--concurrency` - Concurrent requests (default: 10)

### Output

Reports min, max, mean, p50, p95, p99 latencies in milliseconds.
