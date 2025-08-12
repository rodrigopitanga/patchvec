# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations
import time, threading
from typing import Dict, Any

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

def inc(name: str, value: float = 1.0):
    with _lock:
        _counters[name] = _counters.get(name, 0.0) + value

def set_error(msg: str):
    global _last_error
    with _lock:
        _last_error = msg
        _counters["errors_total"] = _counters.get("errors_total", 0.0) + 1.0

def snapshot(extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    with _lock:
        data = dict(_counters)
        data.update({
            "uptime_seconds": time.time() - _started,
            "last_error": _last_error,
        })
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
