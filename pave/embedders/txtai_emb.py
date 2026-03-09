# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray
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

    def __init__(self) -> None:
        section = CFG.get("embedder.txtai", {}) or {}
        path = (
            section.get("path")
            or CFG.get("embedder.model")
            or CFG.get("embed_model")
        )

        cfg: dict[str, Any] = dict(section)
        if "path" not in cfg and path:
            cfg["path"] = path

        self._emb = Embeddings(cfg)

        try:
            dim_fn = getattr(
                getattr(self._emb, "model", None),
                "get_sentence_embedding_dimension",
                None,
            )
            self._dim = int(dim_fn()) if callable(dim_fn) else None
        except Exception:
            self._dim = None

    @property
    def dimension(self) -> int:
        if self._dim is None:
            probe = self.encode(["_"])
            self._dim = int(probe.shape[1])
        return int(self._dim)

    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        raw = self._emb.batchtransform(texts)
        return np.array(raw, dtype=np.float32)
