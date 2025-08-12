# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
import uuid, json
from typing import Dict, Any, Iterable, Tuple, List
from .preprocess import preprocess

# Pure-ish service functions operating on a store adapter

def create_collection(store, tenant: str, name: str) -> Dict[str, Any]:
    store.load_or_init(tenant, name)
    store.save(tenant, name)
    return {"ok": True, "tenant": tenant, "collection": name}


def delete_collection(store, tenant: str, name: str) -> Dict[str, Any]:
    store.delete_collection(tenant, name)
    return {"ok": True, "tenant": tenant, "deleted": name}


def ingest_document(store, tenant: str, name: str, filename: str, content: bytes, docid: str | None, metadata: Dict[str, Any] | None) -> Dict[str, Any]:
    baseid = docid or str(uuid.uuid4())
    store.purge_doc(tenant, name, baseid)

    meta_doc = metadata or {}
    records = []
    for local_id, text, extra in preprocess(filename, content):
        rid = f"{baseid}::{local_id}"
        m = {"docid": baseid, "filename": filename}
        m.update(meta_doc)
        m.update(extra)
        records.append((rid, text, m))
    if not records:
        return {"ok": False, "error": "no text extracted"}
    count = store.index_records(tenant, name, baseid, records)
    return {"ok": True, "tenant": tenant, "collection": name, "docid": baseid, "chunks": count}


def do_search(store, tenant: str, name: str, q: str, k: int = 5, filters: Dict[str, Any] | None = None,
              include_common: bool = False, common_tenant: str | None = None, common_collection: str | None = None) -> Dict[str, Any]:
    if include_common and common_tenant and common_collection:
        matches: List[Dict[str, Any]] = []
        matches.extend(store.search(tenant, name, q, max(10, k * 2), filters=filters))
        matches.extend(store.search(common_tenant, common_collection, q, max(10, k * 2), filters=filters))
        from heapq import nlargest
        top = nlargest(k, matches, key=lambda x: x["score"])
        return {"matches": top}
    return {"matches": store.search(tenant, name, q, k, filters=filters)}
