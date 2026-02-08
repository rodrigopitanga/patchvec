# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any


Record = tuple[str, str, dict[str, Any]]  # (rid, text, meta)

class BaseStore(ABC):
    @abstractmethod
    def load_or_init(self, tenant: str, collection: str) -> None: ...

    @abstractmethod
    def save(self, tenant: str, collection: str) -> None: ...

    @abstractmethod
    def delete_collection(self, tenant: str, collection: str) -> None: ...

    @abstractmethod
    def has_doc(self, tenant: str, collection: str, docid: str) -> bool: ...

    @abstractmethod
    def purge_doc(self, tenant: str, collection: str, docid: str) -> int: ...

    @abstractmethod
    def index_records(self, tenant: str, collection: str, docid: str,
                      records: Iterable[Record]) -> int: ...

    @abstractmethod
    def search(self, tenant: str, collection: str, query: str, k: int = 5,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """
        Search for similar documents.

        Returns a list of dicts, each containing:
          - id, score, text, tenant, collection, meta
          - match_reason: human-readable explanation of why the result matched
        """
        ...
