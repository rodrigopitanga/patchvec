# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from pave.main import VERSION

def test_health_endpoints(client):
    r = client.get("/health/live")
    assert r.status_code == 200 and r.json()["ok"] is True

    r2 = client.get("/health")
    assert r2.status_code == 200 and "version" in r2.json()

    r3 = client.get("/health/ready")
    assert r3.status_code in (200, 503)
    assert "vector_store" in r3.json()

def test_health_defaults(client):
    r = client.get("/health")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] in (True, False)
    assert j["version"] == VERSION

def test_health_ready_contains_effective_fields(client):
    r = client.get("/health/ready")
    assert r.status_code in (200, 503)
    j = r.json()
    # never None; when config.yml absent, code defaults fill in
    assert j.get("data_dir") is not None
    assert j.get("vector_store") == "default"
    assert "writable" in j and isinstance(j["writable"], bool)
    assert "vector_backend_init" in j and isinstance(j["vector_backend_init"], bool)
