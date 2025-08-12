# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations
import os, json
from typing import Dict, Iterable, List, Any
from txtai.embeddings import Embeddings
from .base import BaseStore, Record
from ..config import CFG

class TxtaiStore(BaseStore):
    def __init__(self):
        self._emb: Dict[tuple[str, str], Embeddings] = {}

    def _base_path(self, tenant: str, collection: str) -> str:
        return os.path.join(CFG.data_dir, tenant, collection)

    def _catalog_path(self, tenant: str, collection: str) -> str:
        return os.path.join(self._base_path(tenant, collection), "catalog.json")

    def _meta_path(self, tenant: str, collection: str) -> str:
        return os.path.join(self._base_path(tenant, collection), "meta.json")

    def _load_json(self, path: str):
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f) or {}
            except Exception:
                return {}
        return {}

    def _save_json(self, path: str, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def _load_catalog(self, tenant: str, collection: str) -> Dict[str, List[str]]:
        return self._load_json(self._catalog_path(tenant, collection))

    def _save_catalog(self, tenant: str, collection: str, cat: Dict[str, List[str]]) -> None:
        self._save_json(self._catalog_path(tenant, collection), cat)

    def _load_meta(self, tenant: str, collection: str) -> Dict[str, Dict[str, Any]]:
        return self._load_json(self._meta_path(tenant, collection))

    def _save_meta(self, tenant: str, collection: str, meta: Dict[str, Dict[str, Any]]) -> None:
        self._save_json(self._meta_path(tenant, collection), meta)

    def _config(self):
        model = CFG.get("vector_store.txtai.embed_model", CFG.get("embed_model", "sentence-transformers/paraphrase-MiniLM-L3-v2"))
        backend = CFG.get("vector_store.txtai.backend", CFG.get("vector_backend", "faiss"))
        return {"path": model, "backend": backend}

    def load_or_init(self, tenant: str, collection: str) -> None:
        key = (tenant, collection)
        if key in self._emb:
            return
        os.makedirs(self._base_path(tenant, collection), exist_ok=True)
        em = Embeddings(self._config())
        idxpath = os.path.join(self._base_path(tenant, collection), "index")
        if os.path.isdir(idxpath):
            em.load(idxpath)
        self._emb[key] = em

    def save(self, tenant: str, collection: str) -> None:
        key = (tenant, collection)
        em = self._emb.get(key)
        if not em:
            return
        idxpath = os.path.join(self._base_path(tenant, collection), "index")
        em.save(idxpath)

    def delete_collection(self, tenant: str, collection: str) -> None:
        import shutil
        key = (tenant, collection)
        if key in self._emb:
            del self._emb[key]
        p = self._base_path(tenant, collection)
        if os.path.isdir(p):
            shutil.rmtree(p)

    def purge_doc(self, tenant: str, collection: str, docid: str) -> int:
        cat = self._load_catalog(tenant, collection)
        meta = self._load_meta(tenant, collection)
        ids = cat.get(docid, [])
        if not ids:
            return 0
        self.load_or_init(tenant, collection)
        em = self._emb[(tenant, collection)]
        removed = 0
        if hasattr(em, "delete") and ids:
            try:
                em.delete(ids)
                removed = len(ids)
            except Exception:
                removed = 0
        for rid in ids:
            if rid in meta:
                del meta[rid]
        if docid in cat:
            del cat[docid]
        self._save_meta(tenant, collection, meta)
        self._save_catalog(tenant, collection, cat)
        self.save(tenant, collection)
        return removed

    def index_records(self, tenant: str, collection: str, docid: str, records: Iterable[Record]) -> int:
        self.load_or_init(tenant, collection)
        em = self._emb[(tenant, collection)]
        rlist = list(records)
        em.index(rlist)
        cat = self._load_catalog(tenant, collection)
        meta = self._load_meta(tenant, collection)
        chunk_ids = [rid for rid, _, _ in rlist]
        cat[docid] = chunk_ids
        for rid, _, m in rlist:
            meta[rid] = m
        self._save_catalog(tenant, collection, cat)
        self._save_meta(tenant, collection, meta)
        self.save(tenant, collection)
        return len(rlist)

    def _matches_filters(self, m: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        if not filters:
            return True
        for k, want in filters.items():
            have = m.get(k)
            if isinstance(want, list):
                if have not in want:
                    return False
            else:
                if have != want:
                    return False
        return True

    def search(self, tenant: str, collection: str, text: str, k: int = 5, filters: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        self.load_or_init(tenant, collection)
        em = self._emb[(tenant, collection)]
        results = em.similarity(text, max(50, k * 5))
        ids = [rid for rid, _ in results]
        lookup = em.lookup(ids) if hasattr(em, "lookup") else {}
        meta = self._load_meta(tenant, collection)
        filtered = []
        for rid, score in results:
            m = meta.get(rid, {})
            if self._matches_filters(m, filters or {}):
                filtered.append({
                    "id": rid,
                    "score": float(score),
                    "text": lookup.get(rid),
                    "tenant": tenant,
                    "collection": collection,
                    "meta": m,
                })
            if len(filtered) >= k:
                break
        return filtered
