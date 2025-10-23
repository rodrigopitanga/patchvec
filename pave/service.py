# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
import uuid, json, re
from typing import Dict, Any, Iterable, Tuple, List
from datetime import datetime, timezone as tz
from pave.preprocess import preprocess
from pave.metrics import inc as m_inc

# Pure-ish service functions operating on a store adapter

def create_collection(store, tenant: str, name: str) -> Dict[str, Any]:
    store.load_or_init(tenant, name)
    store.save(tenant, name)
    m_inc("collections_created_total", 1.0)
    return {"ok": True, "tenant": tenant, "collection": name}

def delete_collection(store, tenant: str, name: str) -> Dict[str, Any]:
    store.delete_collection(tenant, name)
    m_inc("collections_deleted_total", 1.0)
    return {"ok": True, "tenant": tenant, "deleted": name}

def _default_docid(filename: str) -> str:
    # Uppercase
    base = filename.upper()
    # replace space and dot with underscore
    base = base.replace(" ", "_").replace(".", "_")
    # replace all non A-Z0-9_ with underscore
    base = re.sub(r"[^A-Z0-9_]", "_", base)
    # collapse multiple underscores
    base = re.sub(r"_+", "_", base)
    return base.strip("_") or ("PVDOC_"+str(uuid.uuid4()))

def ingest_document(store, tenant: str, name: str, filename: str, content: bytes,
                    docid: str | None, metadata: Dict[str, Any] | None,
                    csv_options: Dict[str, Any] | None = None) -> Dict[str, Any]:
    baseid = docid or _default_docid(filename)
    store.purge_doc(tenant, name, baseid)

    meta_doc = metadata or {}
    records = []
    for local_id, text, extra in preprocess(filename, content, csv_options=csv_options):
        rid = f"{baseid}::{local_id}"
        now = datetime.now(tz.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        meta = {"docid": baseid, "filename": filename, "ingested_at": now}
        meta.update(meta_doc)
        meta.update(extra)
        records.append((rid, text, meta))
    if not records:
        return {"ok": False, "error": "no text extracted"}
    count = store.index_records(tenant, name, baseid, records)
    m_inc("documents_indexed_total", 1.0)
    m_inc("chunks_indexed_total", float(count or 0))
    return {"ok": True, "tenant": tenant, "collection": name, "docid": baseid, "chunks": count}

def do_search(store, tenant: str, name: str, q: str, k: int = 5, filters: Dict[str, Any] | None = None,
              include_common: bool = False, common_tenant: str | None = None, common_collection: str | None = None) -> Dict[str, Any]:
    m_inc("search_total", 1.0)
    if include_common and common_tenant and common_collection:
        matches: List[Dict[str, Any]] = []
        matches.extend(store.search(tenant, name, q, max(10, k * 2), filters=filters))
        matches.extend(store.search(common_tenant, common_collection, q, max(10, k * 2), filters=filters))
        from heapq import nlargest
        top = nlargest(k, matches, key=lambda x: x["score"])
        m_inc("matches_total", float(len(top) or 0))
        return {"matches": top}
    top = store.search(tenant, name, q, k, filters=filters)
    m_inc("matches_total", float(len(top) or 0))
    return {"matches": top}
