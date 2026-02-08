# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
from typing import Any
from txtai.embeddings import Embeddings
from ..config import CFG

class TxtaiEmbedder:
    """
    Generic txtai-powered embedder.
    Uses txtai.Embeddings under the hood just for embedding (no indexing here).
    You can switch models/backends via config.

    Config (examples):
      embedder:
        type: txtai
        txtai:
          # simplest: sentence-transformers model path (default)
          path: sentence-transformers/all-MiniLM-L6-v2

          # or explicit method + path
          # method: transformers        # or 'sentence-transformers'
          # path: sentence-transformers/paraphrase-MiniLM-L3-v2

          # any other txtai Embeddings config fields can be passed through here.
    """
    def __init__(self):
        # Back-compat: fall back to top-level embed_model if txtai section missing
        section = CFG.get("embedder.txtai", {}) or {}
        path = section.get("path") or CFG.get("embedder.model") or CFG.get("embed_model")

        # Build the embeddings config for txtai
        cfg: dict[str, Any] = dict(section)
        if "path" not in cfg and path:
            cfg["path"] = path
        # If method omitted, txtai will infer based on path; that’s fine.

        # Ensure we’re only using txtai to embed (no index path persistence here)
        # txtai will lazy-load the model as needed.
        self._emb = Embeddings(cfg)

        # Try to capture dim if available (not guaranteed)
        try:
            # Some txtai models expose : self._emb.model.get_sentence_embedding_dimension()
            # We don’t rely on it; just best-effort.
            dim = getattr(getattr(self._emb, "model", None), "get_sentence_embedding_dimension", None)
            self._dim = int(dim()) if callable(dim) else None
        except Exception:
            self._dim = None

    @property
    def dim(self) -> int | None:
        return self._dim

    def encode(self, texts: list[str]) -> list[list[float]]:
        # txtai expects list[str], returns list[list[float]]
        return self._emb.embed(texts)
