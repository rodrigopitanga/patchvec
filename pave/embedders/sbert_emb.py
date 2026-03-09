# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer

from ..config import CFG


class SbertEmbedder:
    def __init__(self) -> None:
        model_name = CFG.get(
            "embedder.model",
            "sentence-transformers/all-MiniLM-L6-v2",
        )
        device = CFG.get("embedder.device", "auto")
        self.batch_size = int(CFG.get("embedder.batch_size", 64))
        self.model = SentenceTransformer(model_name, device=device)
        try:
            self._dim = int(self.model.get_sentence_embedding_dimension())
        except Exception:
            self._dim = None

    @property
    def dimension(self) -> int:
        if self._dim is None:
            probe = self.encode(["_"])
            self._dim = int(probe.shape[1])
        return int(self._dim)

    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        vecs = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return vecs.astype(np.float32)
