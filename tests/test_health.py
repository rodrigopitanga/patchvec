
def test_health_endpoints(client):
    r = client.get("/health/live")
    assert r.status_code == 200 and r.json()["ok"] is True

    r2 = client.get("/health")
    assert r2.status_code == 200 and "version" in r2.json()

    r3 = client.get("/health/ready")
    assert r3.status_code in (200, 503)
    assert "vector_store_type" in r3.json()

def test_metrics_json(client):
    r = client.get("/health/metrics")
    assert r.status_code == 200
    assert "uptime_seconds" in r.json()
