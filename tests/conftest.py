
import pytest
from fastapi.testclient import TestClient
from pave.config import CFG
from pave.main import build_app
from pave.stores.base import BaseStore

class DummyStore(BaseStore):
    def __init__(self):
        self.db = {}
        self.purge_calls = 0

    def _key(self, tenant, collection):
        return (tenant, collection)

    def _ensure(self, tenant, collection):
        key = self._key(tenant, collection)
        if key not in self.db:
            self.db[key] = {"meta": {}, "texts": {}, "catalog": {}}
        return self.db[key]

    def load_or_init(self, tenant: str, collection: str) -> None:
        self._ensure(tenant, collection)

    def save(self, tenant: str, collection: str) -> None:
        return

    def delete_collection(self, tenant: str, collection: str) -> None:
        self.db.pop(self._key(tenant, collection), None)

    def purge_doc(self, tenant: str, collection: str, docid: str) -> int:
        self.purge_calls += 1
        s = self._ensure(tenant, collection)
        ids = list(s["catalog"].get(docid, []))
        for rid in ids:
            s["meta"].pop(rid, None)
            s["texts"].pop(rid, None)
        s["catalog"].pop(docid, None)
        return len(ids)

    def index_records(self, tenant: str, collection: str, docid: str, records):
        s = self._ensure(tenant, collection)
        ids = []
        for rid, text, meta in records:
            s["texts"][rid] = text
            s["meta"][rid] = meta or {}
            ids.append(rid)
        s["catalog"][docid] = ids
        return len(ids)

    def _matches_filters(self, m, filters):
        if not filters:
            return True
        for k, want in (filters or {}).items():
            have = m.get(k)
            if isinstance(want, list):
                if have not in want:
                    return False
            else:
                if have != want:
                    return False
        return True

    def search(self, tenant: str, collection: str, text: str, k: int = 5, filters=None):
        s = self._ensure(tenant, collection)
        results = []
        q = (text or "").lower()
        for rid, body in s["texts"].items():
            score = 1.0 if q and q in (body or "").lower() else 0.2
            m = s["meta"].get(rid, {})
            if self._matches_filters(m, filters):
                results.append({
                    "id": rid,
                    "score": float(score),
                    "text": body,
                    "tenant": tenant,
                    "collection": collection,
                    "meta": m,
                })
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:k]

@pytest.fixture(scope="session")
def temp_data_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("pvdata")
    CFG._data["data_dir"] = str(d)
    return d

@pytest.fixture()
def app(temp_data_dir):
    CFG._data.setdefault("auth", {})
    CFG._data["auth"]["mode"] = "none"
    CFG._data["common_enabled"] = False
    application = build_app(CFG)
    application.state.store = DummyStore()
    return application

@pytest.fixture()
def client(app):
    return TestClient(app)
