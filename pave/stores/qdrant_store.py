# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations
from typing import Iterable, Dict, Any, List
from .base import BaseStore, Record

class QdrantStore(BaseStore):
    """Stub adapter for Qdrant. To be implemented."""

    def load_or_init(self, tenant: str, collection: str) -> None:
        raise NotImplementedError("to be implemented")

    def save(self, tenant: str, collection: str) -> None:
        raise NotImplementedError("to be implemented")

    def delete_collection(self, tenant: str, collection: str) -> None:
        raise NotImplementedError("to be implemented")

    def purge_doc(self, tenant: str, collection: str, docid: str) -> int:
        raise NotImplementedError("to be implemented")

    def index_records(self, tenant: str, collection: str, docid: str, records: Iterable[Record]) -> int:
        raise NotImplementedError("to be implemented")

    def search(self, tenant: str, collection: str, text: str, k: int = 5, filters: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        raise NotImplementedError("to be implemented")
