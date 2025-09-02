import json

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
