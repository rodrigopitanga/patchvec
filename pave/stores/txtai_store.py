# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
import os, json, operator
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
from threading import Lock
from contextlib import contextmanager
from txtai.embeddings import Embeddings
from pave.stores.base import BaseStore, Record
from pave.config import CFG as c, LOG as log

_LOCKS: dict[str, Lock] = {}
_LOCKS_GUARD = Lock()  # Protects _LOCKS dictionary creation
_SQL_TRANS = str.maketrans({
    ";": " ",
    '"': " ",
    "`": " ",
    "\\": " ",
    "\x00": "",
})

def get_lock(key: str) -> Lock:
    """Get or create a lock for a given key, thread-safe."""
    if key not in _LOCKS:
        with _LOCKS_GUARD:
            if key not in _LOCKS:  # double-check after acquiring guard
                _LOCKS[key] = Lock()
    return _LOCKS[key]

@contextmanager
def collection_lock(tenant: str, collection: str):
    lock = get_lock(f"t_{tenant}:c_{collection}")
    lock.acquire()
    try:
        yield
    finally:
        lock.release()

class TxtaiStore(BaseStore):
    # Maximum depth for recursive collection traversal in filter matching
    _FILTER_MATCH_MAX_DEPTH = 10

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

    @staticmethod
    def _config():
        model = c.get(
            "vector_store.txtai.embed_model",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
        backend = c.get("vector_store.txtai.backend", "faiss")
        return {
            "path": model,
            "backend": backend,
            "content": True,
            "store": True,
            "dynamic": True
        }

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

        with collection_lock(tenant, collection):
        # remove only this docid's metadata and sidecars
            for urid in ids:
                meta.pop(urid, None)
                p = os.path.join(
                    self._chunks_dir(tenant, collection),
                    self._urid_to_fname(urid)
                )
                if os.path.isfile(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            # remove docid from catalog.json
            del cat[docid]

            self._save_meta(tenant, collection, meta)
            self._save_catalog(tenant, collection, cat)

            # delete vectors for these chunk ids
            self.load_or_init(tenant, collection)
            em = self._emb.get((tenant, collection))
            if em and ids:
                try:
                    em.delete(ids)  # txtai embeddings supports deleting by ids
                except Exception:
                    # if the installed txtai doesn't expose delete(ids),
                    # skip silently. index still consistent via sidecars;
                    # searches hydrate from saved text
                    pass

            self.save(tenant, collection)
        return len(ids)

    def _chunks_dir(self, tenant: str, collection: str) -> str:
        return os.path.join(self._base_path(tenant, collection), "chunks")

    def _urid_to_fname(self, urid: str) -> str:
        return urid.replace("/", "_").replace("\\", "_").replace(":", "_") + ".txt"

    def _save_chunk_text(self, tenant: str, collection: str,
                         urid: str, t: str) -> None:
        p = os.path.join(self._chunks_dir(tenant, collection),
                         self._urid_to_fname(urid))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        data = (t or "").encode("utf-8")
        with open(p, "wb") as f:
            f.write(data)
            f.flush()

    def _load_chunk_text(self, tenant: str, collection: str, urid: str) -> str | None:
        p = os.path.join(self._chunks_dir(tenant, collection),
                         self._urid_to_fname(urid))
        if os.path.isfile(p):
            with open(p, "rb") as f:
                return f.read().decode("utf-8")
        return None

    def index_records(self, tenant: str, collection: str, docid: str,
                      records: Iterable[Record]) -> int:
        """
        Ingests records as (rid, text, meta). Guarantees non-null text, coerces
        dict-records, updates catalog/meta, saves index, and verifies content
        storage via a quick lookup. Thread critical.
        """
        self.load_or_init(tenant, collection)
        catalog = self._load_catalog(tenant, collection)
        meta_side = self._load_meta(tenant, collection)
        em = self._emb[(tenant, collection)]
        prepared: list[tuple[str, Any, str]] = []
        record_ids: list[str] = []

        with collection_lock(tenant, collection):

            for r in records:
                if isinstance(r, dict):
                    rid = r.get("rid") or r.get("id") or r.get("uid")
                    txt = r.get("text") or r.get("content")
                    md = r.get("meta") or r.get("metadata") or r.get("tags") or {}
                else:
                    try:
                        rid, txt, md = r
                    except Exception:
                        continue

                if not rid or txt is None:
                    continue

                if not isinstance(md, dict):
                    if isinstance(md, str):
                        try:
                            md = json.loads(md)
                        except:
                            md = {}
                    else:
                        try:
                            md = dict(md)
                        except:
                            md = {}

                md["docid"] = docid
                try:
                    safe_meta = self._sanit_meta_dict(md)
                    meta_json = json.dumps(safe_meta, ensure_ascii=False)
                except Exception:
                    safe_meta = {}
                    meta_json = ""

                rid = str(rid)
                txt = str(txt)
                if not rid.startswith(f"{docid}::"):
                    rid = f"{docid}::{rid}"

                md_for_index = {k: v for k, v in safe_meta.items() if k != "text"}

                meta_side[rid] = safe_meta
                record_ids.append(rid)
                prepared.append((rid, {"text": txt, **md_for_index}, meta_json))

                self._save_chunk_text(tenant, collection, rid, txt)
                assert txt == (self._load_chunk_text(tenant, collection, rid) or "")

            if not prepared:
                return 0

            catalog[docid] = record_ids
            self._save_catalog(tenant, collection, catalog)
            self._save_meta(tenant, collection, meta_side)
            em.upsert(prepared)
            self.save(tenant, collection)
            log.debug(f"PREPARED {len(prepared)} upserts: {prepared}")
        return len(prepared)

    @staticmethod
    def _matches_filters(m: Dict[str, Any],
                         filters: Dict[str, Any] | None) -> bool:
        """
        Evaluates whether metadata `m` satisfies all filter conditions.
        Supports:
          - wildcards (*xyz / xyz*)
          - numeric comparisons (>, <, >=, <=, !=)
          - datetime comparisons (ISO 8601)
        Multiple values in the same key act as OR; multiple keys act as AND.
        """
        log.debug(f"POS FILTERS: {filters}")
        if not filters:
            return True

        def match(have: Any, cond: Any, depth: int = 0) -> bool:
            # Prevent infinite recursion with deeply nested collections
            if depth >= TxtaiStore._FILTER_MATCH_MAX_DEPTH:
                log.warning(f"Filter match depth limit ({TxtaiStore._FILTER_MATCH_MAX_DEPTH}) exceeded for value: {type(have)}")
                return False

            if have is None:
                return False
            if isinstance(have, (list, tuple, set)):
                return any(match(item, cond, depth + 1) for item in have)
            if isinstance(cond, str):
                s = TxtaiStore._sanit_sql(cond)
            else:
                s = str(cond)
            hv = str(have)
            # Numeric/date ops
            for op in (">=", "<=", "!=", ">", "<"):
                if s.startswith(op):
                    val = s[len(op):].strip()
                    try:
                        hvn, vvn = float(have), float(val)
                        return eval(f"hvn {op} vvn")
                    except Exception:
                        try:
                            hd = datetime.fromisoformat(str(have))
                            vd = datetime.fromisoformat(val)
                            return eval(f"hd {op} vd")
                        except Exception:
                            return False
            # Wildcards
            if s == "*":
                return True
            if s.startswith("*") and s.endswith("*") and s[1:-1] in hv:
                return True
            if s.startswith("*") and hv.endswith(s[1:]):
                return True
            if s.endswith("*") and hv.startswith(s[:-1]):
                return True
            if s.startswith("!") and len(s)>1:
                return hv != s[1:]
            return hv == s

        for k, vals in filters.items():
            if not any(match(TxtaiStore._lookup_meta(m, k), v) for v in vals):
                return False
        return True

    @staticmethod
    def _split_filters(filters: dict[str, Any] | None) -> tuple[dict, dict]:
        """Split filters into pre (handled by txtai) and post (handled in Python)."""
        if not filters:
            return {}, {}

        pre_f, pos_f = {}, {}
        for key, vals in (filters or {}).items():
            safe_key = TxtaiStore._sanit_field(key)
            if not safe_key:
                continue
            if not isinstance(vals, list):
                vals = [vals]
            exacts, extended = [], []
            for v in vals:
                # Wildcards and comparison ops => post-filter (Python)
                if isinstance(v, str) and (
                    v.startswith("*") or v.endswith("*") or
                    any(v.startswith(op) for op in (">=", "<=", ">", "<", "!="))
                ):
                    extended.append(v)
                # Simple negation !value => pre-filter (SQL <>)
                elif isinstance(v, str) and v.startswith("!") and len(v) > 1:
                    exacts.append(v)
                else:
                    exacts.append(v)
            if exacts:
                pre_f[safe_key] = exacts
            if extended:
                pos_f[safe_key] = extended
        log.debug(f"after split: PRE {pre_f} POS {pos_f}")
        return pre_f, pos_f

    @staticmethod
    def _lookup_meta(meta: Dict[str, Any] | None, key: str) -> Any:
        if not meta:
            return None
        if key in meta:
            return meta.get(key)
        for raw_key, value in meta.items():
            if TxtaiStore._sanit_field(raw_key) == key:
                return value
        return None

    @staticmethod
    def _sanit_meta_value(value: Any) -> Any:
        if isinstance(value, dict):
            return TxtaiStore._sanit_meta_dict(value)
        if isinstance(value, (list, tuple, set)):
            return [TxtaiStore._sanit_meta_value(v) for v in value]
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return TxtaiStore._sanit_sql(value)

    @staticmethod
    def _sanit_meta_dict(meta: Dict[str, Any] | None) -> Dict[str, Any]:
        safe: Dict[str, Any] = {}
        if not isinstance(meta, dict):
            return safe
        for raw_key, raw_value in meta.items():
            safe_key = TxtaiStore._sanit_field(raw_key)
            if not safe_key or safe_key == "text":
                continue
            safe[safe_key] = TxtaiStore._sanit_meta_value(raw_value)
        return safe

    @staticmethod
    def _sanit_sql(value: Any, *, max_len: Optional[int] = None) -> str:
        if value is None:
            return ""
        text = str(value).translate(_SQL_TRANS)
        for token in ("--", "/*", "*/"):
            if token in text:
                text = text.split(token, 1)[0]
        text = text.strip()
        if max_len is not None and max_len > 0 and len(text) > max_len:
            text = text[:max_len]
        return text.replace("'", "''")

    @staticmethod
    def _sanit_field(name: Any) -> str:
        if not isinstance(name, str):
            name = str(name)
        safe = []
        for ch in name:
            if ch.isalnum() or ch in {"_", "-"}:
                safe.append(ch)
        return "".join(safe)

    @staticmethod
    def _build_sql(query: str, k: int, filters: dict[str, Any], columns: list[str],
                   with_similarity: bool = True, avoid_duplicates = True) -> str:
        """
        Builds a generic txtai >=8 query
        Eg SELECT id, text, score FROM txtai WHERE similar('foo') AND (t1='x' OR t1='y')
        """
        cols = ", ".join(columns or ["id", "docid", "text", "score"])
        sql = f"SELECT {cols} FROM txtai"

        wheres = []
        if with_similarity and query:
            max_len_cfg = c.get("vector_store.txtai.max_query_chars", 512)
            try:
                max_len = int(max_len_cfg)
            except (TypeError, ValueError):
                max_len = 512
            limit = max_len if max_len > 0 else None
            q_safe = TxtaiStore._sanit_sql(query, max_len=limit)
            wheres.append(f"similar('{q_safe}')")

        for key, vals in filters.items():
            safe_key = TxtaiStore._sanit_field(key)
            if not safe_key:
                continue
            ors = []
            for v in vals:
                # Handle negation: !value => [field] <> 'value'
                if isinstance(v, str) and v.startswith("!") and len(v) > 1:
                    safe_v = TxtaiStore._sanit_sql(v[1:])
                    ors.append(f"[{safe_key}] <> '{safe_v}'")
                else:
                    safe_v = TxtaiStore._sanit_sql(v)
                    ors.append(f"[{safe_key}] = '{safe_v}'")
            or_safe = " OR ".join(ors)
            wheres.append(f"({or_safe})")

        if wheres:
            sql += " WHERE " + " AND ".join(wheres) + " AND id <> '' "
        else:
            sql += " WHERE id <> '' "

        if avoid_duplicates and cols:
            sql += " GROUP by " + cols

        if k is not None:
            sql += f" LIMIT {int(k)}"

        log.debug(f"debug:: QUERY: {query} SQL: {sql}")
        return sql

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
        pre_f, pos_f = self._split_filters(filters)
        cols = ["id", "text", "score", "docid"]
        sql = self._build_sql(query, fetch_k, pre_f, cols)
        raw = em.search(sql)

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
            if self._matches_filters(meta.get(rid, {}), pos_f):
                kept.append((rid, score, txt))
                if txt is None:
                    need_lookup_ids.append(rid)
                if len(kept) >= kk:
                    break

        lookup: dict[str, Any] = {}
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
                "text": txt.get("text") if isinstance (txt, dict) else txt,
                "tenant": tenant,
                "collection": collection,
                "meta": meta.get(rid) or {},
                "match_reason": self._build_match_reason(
                    query, score, filters, meta.get(rid)
                ),
            })
        log.info(f"SEARCH-OUT: {out}")
        return out

    def _build_match_reason(self, query: str, score: float,
                            filters: Dict[str, Any] | None,
                            meta: Dict[str, Any] | None) -> str:
        """Build a human-readable explanation of why a result matched."""
        parts = []

        # Similarity component
        pct = int(score * 100)
        if query:
            parts.append(f"semantic similarity {pct}%")

        # Filter matches - show which filter conditions were satisfied
        if filters:
            filter_parts = []
            for key, vals in filters.items():
                meta_val = self._lookup_meta(meta, key)
                if meta_val is not None:
                    # Show the actual value that matched
                    filter_parts.append(f"{key}={meta_val}")
            if filter_parts:
                parts.append("filters: " + ", ".join(filter_parts))

        return "; ".join(parts) if parts else "matched"
