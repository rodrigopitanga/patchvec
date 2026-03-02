# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
import json, os, tempfile, time, threading
from collections import deque
from contextlib import contextmanager
from typing import Any

_started = time.time()
_lock = threading.Lock()
_data_dir: str | None = None
_dirty = False
_METRICS_FILE = "metrics.json"

_counters: dict[str, float] = {
    "requests_total": 0.0,
    "collections_created_total": 0.0,
    "collections_deleted_total": 0.0,
    "documents_indexed_total": 0.0,
    "documents_deleted_total": 0.0,
    "chunks_indexed_total": 0.0,
    "purge_total": 0.0,
    "search_total": 0.0,
    "errors_total": 0.0,
}

_last_error: str | None = None

# Latency tracking: keep last N samples per operation type
_LATENCY_WINDOW = 1000
_latencies: dict[str, deque] = {
    "search": deque(maxlen=_LATENCY_WINDOW),
    "ingest": deque(maxlen=_LATENCY_WINDOW),
}

def _metrics_path() -> str | None:
    if not _data_dir:
        return None
    return os.path.join(_data_dir, _METRICS_FILE)

def set_data_dir(path: str) -> None:
    """Set the data directory for metrics persistence and load existing metrics."""
    global _data_dir
    _data_dir = path
    load()

def load() -> None:
    """Load metrics from disk if available."""
    global _counters, _last_error, _latencies
    path = _metrics_path()
    if not path or not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        with _lock:
            for k, v in data.get("counters", {}).items():
                if k in _counters:
                    _counters[k] = float(v)
            _last_error = data.get("last_error")
            for op, samples in data.get("latencies", {}).items():
                if op not in _latencies:
                    _latencies[op] = deque(maxlen=_LATENCY_WINDOW)
                else:
                    _latencies[op].clear()
                for s in samples[-_LATENCY_WINDOW:]:
                    _latencies[op].append(float(s))
    except Exception:
        pass  # ignore load errors, start fresh

def save() -> None:
    """Persist metrics to disk (atomic write via temp file + rename)."""
    global _dirty
    path = _metrics_path()
    if not path:
        return
    try:
        d = os.path.dirname(path)
        os.makedirs(d, exist_ok=True)
        with _lock:
            data = {
                "counters": dict(_counters),
                "last_error": _last_error,
                "latencies": {op: list(samples) for op, samples in _latencies.items()},
            }
            _dirty = False
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:
        pass  # ignore save errors

def flush() -> None:
    """Persist metrics only if changed since last save."""
    if _dirty:
        save()

def reset() -> dict[str, Any]:
    """Reset all metrics to initial state and persist."""
    global _counters, _last_error, _latencies, _started
    with _lock:
        _counters = {k: 0.0 for k in _counters}
        _last_error = None
        for op in _latencies:
            _latencies[op].clear()
        _started = time.time()
    save()
    return {"ok": True, "reset_at": time.time()}

def inc(name: str, value: float = 1.0):
    global _dirty
    with _lock:
        _counters[name] = _counters.get(name, 0.0) + value
        _dirty = True

def set_error(msg: str):
    global _last_error, _dirty
    with _lock:
        _last_error = msg
        _counters["errors_total"] = _counters.get("errors_total", 0.0) + 1.0
        _dirty = True

def record_latency(op: str, duration_ms: float):
    """Record a latency sample for an operation type (search, ingest)."""
    global _dirty
    with _lock:
        if op not in _latencies:
            _latencies[op] = deque(maxlen=_LATENCY_WINDOW)
        _latencies[op].append(duration_ms)
        _dirty = True

@contextmanager
def timed(op: str):
    """Context manager to time an operation and record its latency."""
    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        record_latency(op, duration_ms)

def _percentile(data: list[float], p: float) -> float:
    """Compute the p-th percentile of a sorted list."""
    if not data:
        return 0.0
    k = (len(data) - 1) * p / 100
    f = int(k)
    c = f + 1 if f + 1 < len(data) else f
    return data[f] + (k - f) * (data[c] - data[f])

def latency_percentiles(op: str) -> dict[str, float]:
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

def snapshot(extra: dict[str, Any] | None = None) -> dict[str, Any]:
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

def to_prometheus(extra: dict[str, Any] | None = None, build: dict[str, str] | None = None) -> str:
    s = []
    snap = snapshot(extra)
    for k, v in snap.items():
        if isinstance(v, (int, float)):
            s.append(f"patchvec_{k} {float(v)}")
    if build:
        labels = ",".join([f'{key}="{val}"' for key, val in build.items()])
        s.append(f"patchvec_build_info{{{labels}}} 1")
    return "\n".join(s) + "\n"
