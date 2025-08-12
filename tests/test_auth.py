
from pave.config import CFG
from pave.main import build_app
from fastapi.testclient import TestClient
from conftest import DummyStore

def test_static_auth_global_key(temp_data_dir):
    CFG._data["auth"]["mode"] = "static"
    CFG._data["auth"]["global_key"] = "sekret"
    app = build_app(CFG)
    app.state.store = DummyStore()
    client = TestClient(app)

    r = client.post("/collections/acme/invoices")
    assert r.status_code == 401

    r2 = client.post("/collections/acme/invoices", headers={"Authorization": "Bearer nope"})
    assert r2.status_code == 403

    r3 = client.post("/collections/acme/invoices", headers={"Authorization": "Bearer sekret"})
    assert r3.status_code == 200
