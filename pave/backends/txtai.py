# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import os
from typing import Any, Sequence

from txtai.embeddings import Embeddings

from .base import IndexRecord


class TxtaiVectorBackend:
    """Thin adapter that isolates txtai.Embeddings behind VectorBackend."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        index_path: str,
        models: dict[str, Any] | None = None,
    ) -> None:
        self._index_path = index_path
        shared_models = models if models is not None else {}
        self._emb = Embeddings(config, models=shared_models)
        self._loaded_existing = False

    def initialize(self) -> None:
        embeddings_file = os.path.join(self._index_path, "embeddings")
        if not os.path.isfile(embeddings_file):
            self._loaded_existing = False
            return
        self._emb.load(self._index_path)
        self._loaded_existing = True

    def index(self, records: list[IndexRecord]) -> None:
        # txtai upsert keeps previous behavior for re-indexing existing ids.
        self._emb.upsert(records)

    def upsert(self, records: list[IndexRecord]) -> None:
        # Compatibility for tests and call sites that still use upsert.
        self.index(records)

    def search(
        self,
        query: Sequence[float] | str,
        k: int | None = None,
    ) -> list[tuple[str, float]] | list[dict[str, Any]]:
        if isinstance(query, str):
            return self._emb.search(query)
        raise NotImplementedError(
            "TxtaiVectorBackend only supports SQL-string search in this "
            "transitional path"
        )

    def delete(self, rids: list[str] | str) -> None:
        ids = [rids] if isinstance(rids, str) else rids
        self._emb.delete(ids)

    def lookup(self, rids: list[str]) -> dict[str, Any]:
        return self._emb.lookup(rids)

    def flush(self) -> None:
        os.makedirs(self._index_path, exist_ok=True)
        self._emb.save(self._index_path)

    def close(self) -> None:
        # txtai Embeddings has no explicit close lifecycle.
        return

    @property
    def loaded_existing(self) -> bool:
        return self._loaded_existing

    @property
    def database(self) -> Any:
        return getattr(self._emb, "database", None)

    def __getattr__(self, name: str) -> Any:
        # Preserve compatibility with tests that inspect fake internals.
        return getattr(self._emb, name)
