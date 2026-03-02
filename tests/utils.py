# (C) 2025 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

import os, json, shutil
from collections.abc import Iterable
from typing import Any
from pave.stores.base import BaseStore, Record, SearchResult
from pave.config import get_cfg


class FakeEmbeddings:
    """Tiny in-memory index. Keeps interface you use in tests."""
    def __init__(self, config, **kwargs):  # config/kwargs unused
        self._docs = {}  # rid -> {"text": str, "meta_json": str, "meta": dict}
        self.last_sql = None

    def index(self, docs):
        for rid, payload, meta_json in docs:
            assert isinstance(meta_json, str)
            if isinstance(payload, dict):
                text = payload.get("text")
                meta = {k: v for k, v in payload.items() if k != "text"}
            else:
                text = payload
                meta = {}
            self._docs[rid] = {"text": text, "meta_json": meta_json, "meta": meta}

    def upsert(self, docs):
        return self.index(docs)

    def search(self, sql, k=5):
        import re
        self.last_sql = sql
        term = None
        m = re.search(r"similar\('([^']+)'", sql)
        if m:
            term = m.group(1).lower()
        elif "SELECT" not in sql.upper():
            term = sql.lower()

        if not term:
            return []

        filter_pairs = re.findall(r"\[([^\]]+)\]\s*=\s*'((?:''|[^'])*)'", sql)

        hits = []
        for rid, entry in self._docs.items():
            text = entry.get("text")
            if text is None:
                continue
            if term not in str(text).lower():
                continue

            metadata = entry.get("meta") or {}
            include = True
            for field, raw_val in filter_pairs:
                stored = metadata.get(field)
                if stored is None:
                    include = False
                    break
                expected = raw_val
                if isinstance(stored, (list, tuple, set)):
                    options = {str(v) for v in stored}
                    if expected not in options:
                        include = False
                        break
                else:
                    if str(stored) != expected:
                        include = False
                        break
            if not include:
                continue

            hits.append({
                "id": rid,
                "score": 1.0,
                "text": text,
                "docid": metadata.get("docid"),
            })
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
        return {rid: (self._docs.get(rid) or {}).get("text") for rid in ids}

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

    def rename_collection(self, tenant: str, old_name: str, new_name: str) -> None:
        if old_name == new_name:
            raise ValueError(f"old and new collection names are the same: {old_name}")
        old_path = self._dir(tenant, old_name)
        new_path = self._dir(tenant, new_name)
        if not os.path.isdir(old_path):
            raise ValueError(f"collection '{old_name}' does not exist")
        if os.path.exists(new_path):
            raise ValueError(f"collection '{new_name}' already exists")
        os.rename(old_path, new_path)

    def list_collections(self, tenant: str) -> list[str]:
        tenant_path = os.path.join(get_cfg().get("data_dir"), tenant)
        if not os.path.isdir(tenant_path):
            return []
        collections: list[str] = []
        for entry in os.listdir(tenant_path):
            entry_path = os.path.join(tenant_path, entry)
            if os.path.isdir(entry_path):
                # Check for catalog.json existence
                catalog_path = os.path.join(entry_path, "catalog.json")
                if os.path.isfile(catalog_path):
                    collections.append(entry)
        return collections

    def list_tenants(self, data_dir: str) -> list[str]:
        from pathlib import Path
        data_dir_path = Path(data_dir).resolve()
        if not data_dir_path.is_dir():
            return []
        tenants: list[str] = []
        for entry in data_dir_path.iterdir():
            if not entry.is_dir():
                continue
            name = entry.name
            if not name.startswith("t_"):
                continue
            tenant = name[2:]
            if tenant:
                tenants.append(tenant)
        return tenants

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
        ids: list[str] = []
        for i, (rid, _, _) in enumerate(records):
            ids.append(rid or f"{docid}-{i}")
        data.setdefault(docid, []).extend(ids)
        with open(cat, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return len(ids)

    def search(self, tenant: str, collection: str, text: str, k: int = 5,
               filters: dict[str, Any] | None = None) -> list[SearchResult]:
        cat = os.path.join(self._dir(tenant, collection), "catalog.json")
        if not os.path.isfile(cat):
            return []
        data = json.load(open(cat, "r", encoding="utf-8"))
        hits: list[SearchResult] = []
        for docid, ids in data.items():
            for cid in ids[:k]:
                hits.append(SearchResult(
                    id=cid, score=1.0, text=None, tenant=tenant,
                    collection=collection, meta={"docid": docid},
                    match_reason="matched"))
        return hits


class SpyStore(BaseStore):
    def __init__(self, impl: BaseStore):
        self.impl = impl
        self.calls: list[tuple] = []

    def load_or_init(self, tenant: str, collection: str) -> None:
        self.calls.append(("load_or_init", tenant, collection))
        return self.impl.load_or_init(tenant, collection)

    def save(self, tenant: str, collection: str) -> None:
        self.calls.append(("save", tenant, collection))
        return self.impl.save(tenant, collection)

    def delete_collection(self, tenant: str, collection: str) -> None:
        self.calls.append(("delete_collection", tenant, collection))
        return self.impl.delete_collection(tenant, collection)

    def rename_collection(self, tenant: str, old_name: str, new_name: str) -> None:
        self.calls.append(("rename_collection", tenant, old_name, new_name))
        return self.impl.rename_collection(tenant, old_name, new_name)

    def list_collections(self, tenant: str) -> list[str]:
        self.calls.append(("list_collections", tenant))
        return self.impl.list_collections(tenant)

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

    def search(self, tenant: str, collection: str, text: str, k: int = 5,
               filters: dict[str, Any] | None = None) -> list[SearchResult]:
        self.calls.append(("search", tenant, collection, text, k, filters))
        return self.impl.search(tenant, collection, text, k, filters)

    def list_tenants(self, data_dir: str) -> list[str]:
        self.calls.append(("list_tenants", data_dir))
        return self.impl.list_tenants(data_dir)
