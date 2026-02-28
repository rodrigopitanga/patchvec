# (C) 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import asyncio, functools, json, sys, threading, time
from datetime import datetime, timezone
from typing import Any

_dest: str | None = None
_handle = None
_lock = threading.Lock()


def configure(dest: str | None) -> None:
    """
    Called once from build_app(). dest is None/null, 'stdout', or a file path.
    Opens the file handle if needed. No-op if dest is None/null.
    """
    global _dest, _handle
    with _lock:
        if _handle is not None:
            try:
                _handle.flush()
                _handle.close()
            finally:
                _handle = None
        _dest = None

    if not dest or str(dest).strip().lower() in ("null", "none", ""):
        return

    _dest = str(dest).strip()
    if _dest != "stdout":
        with _lock:
            _handle = open(_dest, "a", encoding="utf-8", buffering=1)


def emit(**fields) -> None:
    """
    Write one JSON line. No-op if not configured. Thread-safe:
    - stdout: single sys.stdout.write() call (atomic under GIL for small lines)
    - file: protected by a module-level threading.Lock()
    None values are dropped before serialisation.
    """
    if _dest is None:
        return
    ts = (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    payload: dict = {"ts": ts}
    payload.update({k: v for k, v in fields.items() if v is not None})
    line = json.dumps(payload, separators=(",", ":")) + "\n"
    if _dest == "stdout":
        sys.stdout.write(line)
    else:
        with _lock:
            if _handle is not None:
                _handle.write(line)


def close() -> None:
    """Flush and close the file handle if open. Called from lifespan shutdown."""
    global _handle
    with _lock:
        if _handle is not None:
            try:
                _handle.flush()
                _handle.close()
            finally:
                _handle = None


def _result_status(result: Any) -> tuple[str, str | None]:
    """Return (status, error_code) from a handler return value."""
    sc = getattr(result, "status_code", None)
    if sc is not None:
        if sc >= 400:
            try:
                code = json.loads(result.body).get("code")
            except Exception:
                code = None
            return "error", code
        return "ok", None
    if isinstance(result, dict):
        if not result.get("ok", True):
            return "error", result.get("code")
        return "ok", None
    return "ok", None


def ops_event(
    op: str,
    *,
    coll: str | None = "name",
    **extra_keys,
):
    """
    Route decorator: times the call and emits one ops_log line.
    Works for both sync and async handlers.

    Parameters
    ----------
    op:
        Operation name emitted in the ``op`` field (e.g. ``"search"``).
    coll:
        Name of the kwargs key that holds the collection path parameter.
        ``None`` to omit the ``collection`` field (e.g. for list_collections).
    **extra_keys:
        Additional event fields.
        - str value  → resolved as ``kwargs[value]``
        - callable   → called as ``fn(kwargs, result)`` after the handler returns
    """
    def _extras(kwargs: dict, result: Any) -> dict:
        out: dict = {}
        for field, src in extra_keys.items():
            try:
                out[field] = src(kwargs, result) if callable(src) else kwargs.get(src)
            except Exception:
                out[field] = None
        return out

    def decorator(fn):
        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def awrapper(*args, **kwargs):
                _t0 = time.perf_counter()
                _s, _c = "error", None
                result = None
                try:
                    result = await fn(*args, **kwargs)
                    _s, _c = _result_status(result)
                    return result
                finally:
                    emit(
                        op=op,
                        tenant=kwargs.get("tenant"),
                        collection=kwargs.get(coll) if coll else None,
                        latency_ms=round((time.perf_counter() - _t0) * 1000, 2),
                        status=_s, error_code=_c,
                        **_extras(kwargs, result),
                    )
            return awrapper
        else:
            @functools.wraps(fn)
            def swrapper(*args, **kwargs):
                _t0 = time.perf_counter()
                _s, _c = "error", None
                result = None
                try:
                    result = fn(*args, **kwargs)
                    _s, _c = _result_status(result)
                    return result
                finally:
                    emit(
                        op=op,
                        tenant=kwargs.get("tenant"),
                        collection=kwargs.get(coll) if coll else None,
                        latency_ms=round((time.perf_counter() - _t0) * 1000, 2),
                        status=_s, error_code=_c,
                        **_extras(kwargs, result),
                    )
            return swrapper
    return decorator
