# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .base import Embedder
from ..config import CFG


def get_embedder(cfg: CFG = CFG) -> Embedder:
    etype = (cfg.get("embedder.type", "sbert") or "sbert").lower()
    match etype:
        case "sbert":
            from .sbert import SbertEmbedder

            return SbertEmbedder()
        case "openai":
            from .openai import OpenAIEmbedder

            return OpenAIEmbedder()
        case _:
            raise RuntimeError(f"Unknown embedder.type: {etype}")
