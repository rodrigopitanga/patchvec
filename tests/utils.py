# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

import os, json, shutil
from typing import Iterable, Dict, Any, List, Tuple
from pave.stores.base import BaseStore, Record
from pave.config import get_cfg


class FakeEmbeddings:
    """Tiny in-memory index. Keeps interface you use in tests."""
    def __init__(self, config):  # config unused
        self._docs = {}  # rid -> (text, meta_json)

    def index(self, docs):
        for rid, text, meta_json in docs:
            assert isinstance(meta_json, str)
            self._docs[rid] = (text, meta_json)

    def upsert(self, docs):
        return self.index(docs)

    def search(self, sql, k=5):
        import re
        term = None
        m = re.search(r"similar\('([^']+)'", sql)
        if m:
            term = m.group(1).lower()
        elif "SELECT" not in sql.upper():
            term = sql.lower()

        if not term:
            return []

        hits = [
            {"id": rid, "score": 1.0, "text": txt, "tags": {"docid": "DUMMY"}}
            for rid, (txt, _) in self._docs.items() if term in str(txt).lower()
        ]
        return hits[:10]
        """
        q = (query or "").lower()
        out = []
        for rid, (text, _) in self._docs.items():
            if q in (text or "").lower():
                out.append({"id": rid, "score": float(len(q)), "text": text})
        return out[:k]
        """

    def lookup(self, ids):
        return {rid: self._docs.get(rid, ("", ""))[0] for rid in ids}

    def delete(self, ids):
        for rid in ids:
            self._docs.pop(rid, None)

    def save(self, path):
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(
                path, "_fake_index.json"), "w", encoding="utf-8") as f:
            json.dump(self._docs, f, ensure_ascii=False)

    def load(self, path):
        p = os.path.join(path, "_fake_index.json")
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                self._docs = json.load(f)


class DummyStore(BaseStore):
    def _dir(self, tenant: str, collection: str) -> str:
        return os.path.join(get_cfg().get("data_dir"), tenant, collection)

    def load_or_init(self, tenant: str, collection: str) -> None:
        os.makedirs(os.path.join(self._dir(tenant, collection), "index"), exist_ok=True)

    def save(self, tenant: str, collection: str) -> None:
        cat = os.path.join(self._dir(tenant, collection), "catalog.json")
        if not os.path.isfile(cat):
            with open(cat, "w", encoding="utf-8") as f:
                json.dump({}, f)

    def delete_collection(self, tenant: str, collection: str) -> None:
        shutil.rmtree(self._dir(tenant, collection), ignore_errors=True)

    def purge_doc(self, tenant: str, collection: str, docid: str) -> int:
        cat = os.path.join(self._dir(tenant, collection), "catalog.json")
        try:
            data = json.load(open(cat, "r", encoding="utf-8"))
        except Exception:
            data = {}
        removed = 1 if docid in data else 0
        data.pop(docid, None)
        with open(cat, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return removed

    def has_doc(self, tenant: str, collection: str, docid: str) -> bool:
        cat = os.path.join(self._dir(tenant, collection), "catalog.json")
        try:
            data = json.load(open(cat, "r", encoding="utf-8"))
        except Exception:
            data = {}
        ret = 1 if docid in data else 0
        return bool(ret)

    def index_records(self, tenant: str, collection: str, docid: str,
                      records: Iterable[Record]) -> int:
        cat = os.path.join(self._dir(tenant, collection), "catalog.json")
        try:
            data = json.load(open(cat, "r", encoding="utf-8"))
        except Exception:
            data = {}
        ids: List[str] = []
        for i, (rid, _, _) in enumerate(records):
            ids.append(rid or f"{docid}-{i}")
        data.setdefault(docid, []).extend(ids)
        with open(cat, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return len(ids)

    def search(self, tenant: str, collection: str, text: str, k: int = 5,
               filters: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        cat = os.path.join(self._dir(tenant, collection), "catalog.json")
        if not os.path.isfile(cat):
            return []
        data = json.load(open(cat, "r", encoding="utf-8"))
        hits: List[Dict[str, Any]] = []
        for docid, ids in data.items():
            for cid in ids[:k]:
                hits.append({"id": cid, "score": 1.0, "meta": {"docid": docid}})
        return hits


class SpyStore(BaseStore):
    def __init__(self, impl: BaseStore):
        self.impl = impl
        self.calls: List[Tuple] = []

    def load_or_init(self, tenant: str, collection: str) -> None:
        self.calls.append(("load_or_init", tenant, collection))
        return self.impl.load_or_init(tenant, collection)

    def save(self, tenant: str, collection: str) -> None:
        self.calls.append(("save", tenant, collection))
        return self.impl.save(tenant, collection)

    def delete_collection(self, tenant: str, collection: str) -> None:
        self.calls.append(("delete_collection", tenant, collection))
        return self.impl.delete_collection(tenant, collection)

    def purge_doc(self, tenant: str, collection: str, docid: str) -> int:
        self.calls.append(("purge_doc", tenant, collection, docid))
        return self.impl.purge_doc(tenant, collection, docid)

    def has_doc(self, tenant: str, collection: str, docid: str) -> bool:
        self.calls.append(("has_doc", tenant, collection, docid))
        return self.impl.has_doc(tenant, collection, docid)

    def index_records(self, tenant: str, collection: str, docid: str, records: Iterable[Record]) -> int:
        recs = list(records)
        self.calls.append(("index_records", tenant, collection, docid, len(recs)))
        return self.impl.index_records(tenant, collection, docid, recs)

    def search(self, tenant: str, collection: str, text: str, k: int = 5, filters: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        self.calls.append(("search", tenant, collection, text, k, filters))
        return self.impl.search(tenant, collection, text, k, filters)
