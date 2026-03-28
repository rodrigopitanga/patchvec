# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "benchmarks"),
)

import search_latency  # type: ignore[import-not-found]


def test_latency_slo_violation_returns_message():
    violation = search_latency._latency_slo_violation(
        [10.0, 100.0],
        50.0,
    )

    assert violation is not None
    assert violation.startswith("SLO VIOLATION: p99=")
    assert violation.endswith(" > 50.0ms")


def test_latency_slo_disabled_returns_none():
    assert search_latency._latency_slo_violation(
        [10.0, 100.0],
        0,
    ) is None


def test_main_exits_1_on_slo_failure(monkeypatch):
    async def fake_run_benchmark(*args, **kwargs):
        return None

    monkeypatch.setattr(
        search_latency,
        "run_benchmark",
        fake_run_benchmark,
        raising=True,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["search_latency.py", "--slo-p99-ms", "10"],
    )

    with pytest.raises(SystemExit) as exc:
        search_latency.main()

    assert exc.value.code == 1
