<!-- (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

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
# run with defaults (1200 queries, 42 concurrent)
make benchmark-latency

# or customize
make benchmark-latency BENCH_QUERIES=500 BENCH_CONCUR=20
```

### PyPI / evaluation workflow

```bash
pip install httpx
python benchmarks/search_latency.py --url http://localhost:8086 \
  --queries 1200 --concurrency 42
```

### Options

* `--url` - PatchVec base URL (default: http://localhost:8086)
* `--queries` - Number of queries to run (default: 1200)
* `--concurrency` - Concurrent requests (default: 42)
* `--debug` - Print stack traces for setup failures

### Output

Reports min, max, mean, p50, p95, p99 latencies in milliseconds.
Setup requests (collection create + seed ingest) retry a few times before
failing. Timed queries are not retried.

---

## stress.py

Fires random concurrent operations (collection create/delete, document ingest/delete,
search, health checks, archive download/restore) and reports per-operation latency
percentiles plus error rates.

### Developer workflow

```bash
# run with defaults (300s duration, 24 concurrent)
make benchmark-stress

# or customize
make benchmark-stress STRESS_DURATION=60 STRESS_CONCUR=30
```

### PyPI / evaluation workflow

```bash
pip install httpx
python benchmarks/stress.py --url http://localhost:8086 --duration 300 \
  --concurrency 24
```

### Options

* `--url` - PatchVec base URL (default: http://localhost:8086)
* `--duration` - Test duration in seconds (default: 300)
* `--concurrency` - Max concurrent operations (default: 24)
* `--debug` - Print stack traces for setup failures

### Output

Reports per-operation counts, error rates, and p50/p95/p99/max latencies.
Seed collection + ingest steps retry a few times before aborting. Timed
ingest/search operations during the run are not retried.

## Saving results

To save outputs with a UTC timestamp and tag:

```bash
make benchmark BENCH_SAVE=1 BENCH_TAG=baseline
```

If `BENCH_TAG` is omitted, a `<branch>-<shortsha>` tag is used. Outputs are saved
under `benchmarks/results/` as:

```
{latency,stress}-YYYY-MM-DD_HHmmss[_tag].txt
```
