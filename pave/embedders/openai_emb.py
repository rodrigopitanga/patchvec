# (C) 2025 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
import os
from openai import OpenAI
from ..config import CFG

class OpenAIEmbedder:
    def __init__(self):
        self.model = CFG.get("embedder.model", "text-embedding-3-small")
        self.batch_size = int(CFG.get("embedder.batch_size", 256))
        self._dim = CFG.get("embedder.dim")
        api_key = CFG.get("embedder.api_key") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OpenAI API key not configured")
        self.client = OpenAI(api_key=api_key)

    @property
    def dim(self) -> int | None:
        try:
            return int(self._dim) if self._dim is not None else None
        except Exception:
            return None

    def encode(self, texts: list[str]) -> list[list[float]]:
        kwargs = {"model": self.model, "input": texts}
        if self._dim is not None:
            kwargs["dimensions"] = int(self._dim)
        res = self.client.embeddings.create(**kwargs)
        return [d.embedding for d in res.data]
