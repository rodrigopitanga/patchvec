
def test_create_and_delete_collection(client):
    r = client.post("/collections/acme/invoices")
    assert r.status_code == 200 and r.json()["ok"] is True
    r2 = client.delete("/collections/acme/invoices")
    assert r2.status_code == 200 and r2.json()["deleted"] == "invoices"
