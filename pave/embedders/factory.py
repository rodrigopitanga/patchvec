# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
from .base import BaseEmbedder
from ..config import CFG

def get_embedder(cfg: CFG = CFG) -> BaseEmbedder:
    etype = (cfg.get("embedder.type", "default") or "default").lower()
    match etype:
        case "default" | "txtai":  # vendor-neutral; bw compatible with 'txtai'
            from .txtai_emb import TxtaiEmbedder
            return TxtaiEmbedder()
        case "sbert":
            from .sbert_emb import SbertEmbedder
            return SbertEmbedder()
        case "openai":
            from .openai_emb import OpenAIEmbedder
            return OpenAIEmbedder()
        case _:
            raise RuntimeError(f"Unknown embedder.type: {etype}")
