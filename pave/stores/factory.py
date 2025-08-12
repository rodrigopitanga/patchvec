# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
from .base import BaseStore
from ..config import CFG

def get_store(cfg: CFG = CFG) -> BaseStore:
    stype = (cfg.get("vector_store.type", "default") or "default").lower()
    match stype:
        case "default" | "txtai":  # vendor-neutral default; bw compatible with 'txtai'
            from .txtai_store import TxtaiStore
            return TxtaiStore()
        case "qdrant":
            from .qdrant_store import QdrantStore
            return QdrantStore()
        case _:
            raise RuntimeError(f"Unknown vector_store.type: {stype}")
