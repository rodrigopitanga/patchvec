# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations
import time, threading
from collections import deque
from contextlib import contextmanager
from typing import Dict, Any, List

_started = time.time()
_lock = threading.Lock()
_counters: Dict[str, float] = {
    "requests_total": 0.0,
    "collections_created_total": 0.0,
    "collections_deleted_total": 0.0,
    "documents_indexed_total": 0.0,
    "chunks_indexed_total": 0.0,
    "purge_total": 0.0,
    "search_total": 0.0,
    "errors_total": 0.0,
}

_last_error: str | None = None

# Latency tracking: keep last N samples per operation type
_LATENCY_WINDOW = 1000
_latencies: Dict[str, deque] = {
    "search": deque(maxlen=_LATENCY_WINDOW),
    "ingest": deque(maxlen=_LATENCY_WINDOW),
}

def inc(name: str, value: float = 1.0):
    with _lock:
        _counters[name] = _counters.get(name, 0.0) + value

def set_error(msg: str):
    global _last_error
    with _lock:
        _last_error = msg
        _counters["errors_total"] = _counters.get("errors_total", 0.0) + 1.0

def record_latency(op: str, duration_ms: float):
    """Record a latency sample for an operation type (search, ingest)."""
    with _lock:
        if op not in _latencies:
            _latencies[op] = deque(maxlen=_LATENCY_WINDOW)
        _latencies[op].append(duration_ms)

@contextmanager
def timed(op: str):
    """Context manager to time an operation and record its latency."""
    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        record_latency(op, duration_ms)

def _percentile(data: List[float], p: float) -> float:
    """Compute the p-th percentile of a sorted list."""
    if not data:
        return 0.0
    k = (len(data) - 1) * p / 100
    f = int(k)
    c = f + 1 if f + 1 < len(data) else f
    return data[f] + (k - f) * (data[c] - data[f])

def latency_percentiles(op: str) -> Dict[str, float]:
    """Return p50, p95, p99 for an operation type."""
    with _lock:
        samples = list(_latencies.get(op, []))
    if not samples:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "count": 0}
    samples.sort()
    return {
        "p50": round(_percentile(samples, 50), 2),
        "p95": round(_percentile(samples, 95), 2),
        "p99": round(_percentile(samples, 99), 2),
        "count": len(samples),
    }

def snapshot(extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    with _lock:
        data = dict(_counters)
        data.update({
            "uptime_seconds": time.time() - _started,
            "last_error": _last_error,
        })
    # Add latency percentiles for each tracked operation
    for op in ("search", "ingest"):
        pcts = latency_percentiles(op)
        data[f"{op}_latency_p50_ms"] = pcts["p50"]
        data[f"{op}_latency_p95_ms"] = pcts["p95"]
        data[f"{op}_latency_p99_ms"] = pcts["p99"]
        data[f"{op}_latency_count"] = pcts["count"]
    if extra:
        data.update(extra)
    return data

def to_prometheus(extra: Dict[str, Any] | None = None, build: Dict[str, str] | None = None) -> str:
    s = []
    snap = snapshot(extra)
    for k, v in snap.items():
        if isinstance(v, (int, float)):
            s.append(f"patchvec_{k} {float(v)}")
    if build:
        labels = ",".join([f'{key}="{val}"' for key, val in build.items()])
        s.append(f"patchvec_build_info{{{labels}}} 1")
    return "\n".join(s) + "\n"
