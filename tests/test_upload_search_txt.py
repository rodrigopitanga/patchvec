
import json

def test_upload_txt_and_search_post_get(client):
    client.post("/collections/acme/txts")
    content = b"hello world\nthis is a test of patchvec"
    files = {"file": ("sample.txt", content, "text/plain")}
    data = {"docid": "DOC-TXT", "metadata": json.dumps({"lang": "pt"})}
    r = client.post("/collections/acme/txts/documents", files=files, data=data)
    assert r.status_code == 200

    # GET without filters
    s2 = client.get("/collections/acme/txts/search", params={"q": "patchvec", "k": 3})
    print(s2.status_code, s2.json())
    assert s2.status_code == 200 and len(s2.json()["matches"]) >= 1

    # POST without filters
    body = {"q": "world", "k": 5}
    s = client.post("/collections/acme/txts/search", json=body)
    print(s.status_code, s.json())
    assert s.status_code == 200 and len(s.json()["matches"]) >= 1

    # POST with filters
    body = {"q": "world", "k": 5, "filters": {"docid": "DOC-TXT"}}
    s = client.post("/collections/acme/txts/search", json=body)
    print(s.status_code, s.json())
    assert s.status_code == 200 and len(s.json()["matches"]) >= 1

def test_reupload_same_docid_calls_purge_and_reindexes(client):
    client.post("/collections/acme/reup")
    store = client.app.state.store  # DummyStore injected
    # first upload
    r1 = client.post("/collections/acme/reup/documents",
                     files={"file": ("a.txt", b"alpha bravo charlie", "text/plain")},
                     data={"docid": "R-42"})
    assert r1.status_code == 200
    initial_purge = store.purge_calls

    # second upload with same docid -> must call purge
    r2 = client.post("/collections/acme/reup/documents",
                     files={"file": ("b.txt", b"delta echo foxtrot", "text/plain")},
                     data={"docid": "R-42"})
    assert r2.status_code == 200
    assert store.purge_calls == initial_purge + 1

    # confirm only new content appears
    s = client.post("/collections/acme/reup/search", json={"q": "delta", "k": 5, "filters": {"docid": "R-42"}})
    assert s.status_code == 200
    body = " ".join((m.get("text") or "") for m in s.json()["matches"])
    assert "delta" in body.lower() and "alpha" not in body.lower()
