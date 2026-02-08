# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from pave.main import VERSION
from pave import metrics

def test_metrics_json(client):
    r = client.get("/health/metrics")
    assert r.status_code == 200
    assert "uptime_seconds" in r.json()

def test_metrics_counters(client):
    # create, upload, search -> counters move
    r = client.post("/collections/acme/m", headers={})
    assert r.status_code == 200
    r = client.post("/collections/acme/m/documents",
                    files={"file": ("a.txt", b"hello world", "text/plain")},
                    data={"docid": "D1"})
    assert r.status_code == 200

    r = client.get("/collections/acme/m/search", params={"q": "hello", "k": 5})
    assert r.status_code == 200

    snap = client.get("/health/metrics").json()
    assert snap["collections_created_total"] >= 1
    assert snap["documents_indexed_total"] >= 1
    assert snap["chunks_indexed_total"] >= 1
    assert snap["search_total"] >= 1
    assert snap["requests_total"] >= 3  # create + upload + search

def test_metrics_exposes_build_labels(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    txt = r.text
    assert "version" in txt and VERSION in txt

def test_latency_percentiles_in_snapshot(client):
    """After search and ingest, latency percentiles should appear in metrics."""
    # create collection and ingest a document
    client.post("/collections/acme/lat", headers={})
    client.post("/collections/acme/lat/documents",
                files={"file": ("b.txt", b"latency test content", "text/plain")},
                data={"docid": "D2"})
    # perform a search
    client.get("/collections/acme/lat/search", params={"q": "latency", "k": 5})

    snap = client.get("/health/metrics").json()
    # Check search latency fields
    assert "search_latency_p50_ms" in snap
    assert "search_latency_p95_ms" in snap
    assert "search_latency_p99_ms" in snap
    assert "search_latency_count" in snap
    assert snap["search_latency_count"] >= 1
    # Check ingest latency fields
    assert "ingest_latency_p50_ms" in snap
    assert "ingest_latency_p95_ms" in snap
    assert "ingest_latency_p99_ms" in snap
    assert "ingest_latency_count" in snap
    assert snap["ingest_latency_count"] >= 1

def test_latency_prometheus_format(client):
    """Latency percentiles should be exported in Prometheus format."""
    client.post("/collections/acme/prom", headers={})
    client.post("/collections/acme/prom/documents",
                files={"file": ("c.txt", b"prometheus test", "text/plain")},
                data={"docid": "D3"})
    client.get("/collections/acme/prom/search", params={"q": "prometheus", "k": 5})

    r = client.get("/metrics")
    txt = r.text
    assert "patchvec_search_latency_p50_ms" in txt
    assert "patchvec_search_latency_p95_ms" in txt
    assert "patchvec_search_latency_p99_ms" in txt
    assert "patchvec_ingest_latency_p50_ms" in txt
    assert "patchvec_ingest_latency_p95_ms" in txt
    assert "patchvec_ingest_latency_p99_ms" in txt

def test_percentile_calculation():
    """Unit test for percentile calculation."""
    # Clear existing samples
    metrics._latencies["test_op"] = metrics.deque(maxlen=100)
    # Add known samples
    for v in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
        metrics.record_latency("test_op", float(v))
    pcts = metrics.latency_percentiles("test_op")
    assert pcts["count"] == 10
    assert pcts["p50"] == 55.0  # median of 10 values
    assert pcts["p95"] >= 90.0
    assert pcts["p99"] >= 95.0
