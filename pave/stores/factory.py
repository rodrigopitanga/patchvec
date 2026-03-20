# (C) 2025 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations
from .base import BaseStore
from ..config import CFG

def get_store(cfg: CFG = CFG) -> BaseStore:
    stype = (cfg.get("vector_store.type", "faiss") or "faiss").lower()
    match stype:
        case "faiss":
            from .faiss import FaissStore
            return FaissStore()
        case "qdrant":
            from .qdrant_store import QdrantStore
            return QdrantStore()
        case _:
            raise RuntimeError(f"Unknown vector_store.type: {stype}")
