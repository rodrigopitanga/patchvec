<!-- (C) 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net> -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Benchmarks

Performance benchmarks for PatchVec.

## Quick start

```bash
# start the server in dev mode (separate terminal)
USE_CPU=1 make serve

# run all benchmarks (latency + stress)
make benchmark

# or run individually
make benchmark-latency
make benchmark-stress
```

---

## search_latency.py

Measures search latency under concurrent load.

### Developer workflow

```bash
# run with defaults (100 queries, 10 concurrent)
make benchmark-latency

# or customize
make benchmark-latency BENCH_QUERIES=500 BENCH_CONCUR=20
```

### PyPI / evaluation workflow

```bash
pip install httpx
python benchmarks/search_latency.py --url http://localhost:8086 \
  --queries 100 --concurrency 10
```

### Options

* `--url` - PatchVec base URL (default: http://localhost:8086)
* `--queries` - Number of queries to run (default: 100)
* `--concurrency` - Concurrent requests (default: 10)

### Output

Reports min, max, mean, p50, p95, p99 latencies in milliseconds.

---

## stress.py

Fires random concurrent operations (collection create/delete, document ingest/delete,
search, health checks, archive download/restore) and reports per-operation latency
percentiles plus error rates.

### Developer workflow

```bash
# run with defaults (30s duration, 15 concurrent)
make benchmark-stress

# or customize
make benchmark-stress STRESS_DURATION=60 STRESS_CONCUR=30
```

### PyPI / evaluation workflow

```bash
pip install httpx
python benchmarks/stress.py --url http://localhost:8086 --duration 30 --concurrency 15
```

### Options

* `--url` - PatchVec base URL (default: http://localhost:8086) * `--duration` - Test
duration in seconds (default: 30) * `--concurrency` - Max concurrent operations
(default: 15)

### Output

Reports per-operation counts, error rates, and p50/p95/p99/max latencies.
