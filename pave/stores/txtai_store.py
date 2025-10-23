# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
import os, json
from typing import Dict, Iterable, List, Any
from txtai.embeddings import Embeddings
from pave.stores.base import BaseStore, Record
from pave.config import CFG as c


class TxtaiStore(BaseStore):
    def __init__(self):
        self._emb: Dict[tuple[str, str], Embeddings] = {}

    def _base_path(self, tenant: str, collection: str) -> str:
        return os.path.join(c.get("data_dir"), f"t_{tenant}", f"c_{collection}")

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

    def _save_catalog(self, tenant: str, collection: str,
                      cat: Dict[str, List[str]]) -> None:
        self._save_json(self._catalog_path(tenant, collection), cat)

    def _load_meta(self, tenant: str, collection: str) -> Dict[str, Dict[str, Any]]:
        return self._load_json(self._meta_path(tenant, collection))

    def _save_meta(self, tenant: str, collection: str,
                   meta: Dict[str, Dict[str, Any]]) -> None:
        self._save_json(self._meta_path(tenant, collection), meta)

    def _config(self):
        model = c.get("vector_store.txtai.embed_model",
                      "sentence-transformers/paraphrase-MiniLM-L3-v2")
        backend = c.get("vector_store.txtai.backend", "faiss")
        return {"path": model, "backend": backend, "content": True}

    def load_or_init(self, tenant: str, collection: str) -> None:
        key = (tenant, collection)
        if key in self._emb:
            return

        base = self._base_path(tenant, collection)
        os.makedirs(base, exist_ok=True)

        em = Embeddings(self._config())
        idxpath = os.path.join(base, "index")
        # consider (existing) index valid only if embeddings file exists
        embeddings_file = os.path.join(idxpath, "embeddings")

        if os.path.isfile(embeddings_file):
            try:
                em.load(idxpath)
            except Exception:
                # broken index -> start clean
                em = Embeddings(self._config())

        self._emb[key] = em

    def save(self, tenant: str, collection: str) -> None:
        key = (tenant, collection)
        em = self._emb.get(key)
        if not em:
            return
        idxpath = os.path.join(self._base_path(tenant, collection), "index")
        os.makedirs(idxpath, exist_ok=True)  # ensure target dir
        em.save(idxpath)

    def delete_collection(self, tenant: str, collection: str) -> None:
        import shutil
        key = (tenant, collection)
        if key in self._emb:
            del self._emb[key]
        p = self._base_path(tenant, collection)
        if os.path.isdir(p):
            shutil.rmtree(p)

    def has_doc(self, tenant: str, collection: str, docid: str) -> bool:
        cat = self._load_catalog(tenant, collection)
        ids = cat.get(docid)
        return bool(ids)

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

    def _chunks_dir(self, tenant: str, collection: str) -> str:
        return os.path.join(self._base_path(tenant, collection), "chunks")

    def _rid_to_fname(self, rid: str) -> str:
        return rid.replace("/", "_").replace("\\", "_").replace(":", "_") + ".txt"

    def _load_chunk_text(self, tenant: str, collection: str, rid: str) -> str | None:
        p = os.path.join(self._chunks_dir(tenant, collection), self._rid_to_fname(rid))
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
        return None

    def index_records(self, tenant: str, collection: str, docid: str,
                      records: Iterable[Record]) -> int:
        """
        Ingests records as (rid, text, meta). Guarantees non-null text, coerces
        dict-records, updates catalog/meta, saves index, and verifies content
        storage via a quick lookup.
        """
        self.load_or_init(tenant, collection)
        em = self._emb[(tenant, collection)]

        rlist: list[tuple[str, str, str]] = []  # (id, text, meta_json)

        for r in records:
            if isinstance(r, dict):
                rid = r.get("rid") or r.get("id") or r.get("uid")
                txt = r.get("text") or r.get("content")
                meta = r.get("meta") or r.get("metadata") or r.get("tags") or {}
            else:
                try:
                    rid, txt, meta = r
                except Exception:
                    continue

            if not rid or txt is None:
                continue

            try:
                meta_json = json.dumps(meta or {}, ensure_ascii=False)
            except Exception:
                meta_json = "{}"

            rlist.append((str(rid), str(txt), meta_json))

        if not rlist:
            return 0

        # index into txtai (content=True in _config())
        em.index(rlist)

        # update catalog + meta sidecars
        cat = self._load_catalog(tenant, collection)
        meta = self._load_meta(tenant, collection)
        chunk_ids = [rid for rid, _, _ in rlist]
        cat[docid] = chunk_ids
        for rid, _, meta_json in rlist:
            try:
                meta[rid] = json.loads(meta_json) if meta_json else {}
            except Exception:
                meta[rid] = {}
        self._save_catalog(tenant, collection, cat)
        self._save_meta(tenant, collection, meta)

        # persist index files
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
    
    def search(self, tenant: str, collection: str, query: str, k: int = 5,
               filters: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        """
        Queries txtai for top-k, keeps overfetch inside the store, preserves text
        from em.search when present, and falls back to lookup if missing.
        """
        kk = max(1, int(k))
        self.load_or_init(tenant, collection)
        em = self._emb[(tenant, collection)]

        fetch_k = max(50, kk * 5)
        raw = em.search(query, fetch_k)

        # Normalize to (id, score, maybe_text)
        if raw and isinstance(raw[0], dict):
            triples = [
                (r.get("id"), float(r.get("score", 0.0)), r.get("text"))
                for r in raw
            ]
        else: # if raw is a tuple:
            triples = [
                (rid, float(score), None)
                for rid, score in (raw or [])
            ]

        meta = self._load_meta(tenant, collection)

        kept: list[tuple[str, float, Any]] = []
        need_lookup_ids: list[str] = []

        for rid, score, txt in triples:
            if not rid:
                continue
            if self._matches_filters(meta.get(rid, {}), filters or {}):
                kept.append((rid, score, txt))
                if txt is None:
                    need_lookup_ids.append(rid)
                if len(kept) >= kk:
                    break

        lookup: Dict[str, str] = {}
        if need_lookup_ids and hasattr(em, "lookup"):
            lookup = em.lookup(need_lookup_ids) or {}

        out: List[Dict[str, Any]] = []
        for rid, score, txt in kept:
            if txt is None:
                txt = lookup.get(rid)
            if txt is None:
                txt = self._load_chunk_text(tenant, collection, rid)
            out.append({
                "id": rid,
                "score": score,
                "text": txt,
                "tenant": tenant,
                "collection": collection,
                "meta": meta.get(rid, {}),
            })
        return out
