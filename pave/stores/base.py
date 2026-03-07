# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, asdict
from typing import Any


Record = tuple[str, str, dict[str, Any]]  # (rid, text, meta)


@dataclass(frozen=True)
class SearchResult:
    """Store-layer search result."""
    id: str
    score: float
    text: str | None
    tenant: str
    collection: str
    meta: dict[str, Any]
    match_reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

class BaseStore(ABC):
    @abstractmethod
    def load_or_init(self, tenant: str, collection: str) -> None: ...

    @abstractmethod
    def save(self, tenant: str, collection: str) -> None: ...

    @abstractmethod
    def delete_collection(self, tenant: str, collection: str) -> None: ...

    @abstractmethod
    def rename_collection(self, tenant: str, old_name: str, new_name: str) -> None:
        """Rename a collection. Raises ValueError if old/new name invalid."""
        ...

    @abstractmethod
    def list_collections(self, tenant: str) -> list[str]:
        """List all collections for a tenant."""
        ...

    @abstractmethod
    def list_tenants(self, data_dir: str) -> list[str]:
        """List all tenants."""
        ...

    @abstractmethod
    def has_doc(self, tenant: str, collection: str, docid: str) -> bool: ...

    @abstractmethod
    def purge_doc(self, tenant: str, collection: str, docid: str) -> int: ...

    @abstractmethod
    def index_records(self, tenant: str, collection: str, docid: str,
                      records: Iterable[Record],
                      doc_meta: dict[str, Any] | None = None
                      ) -> int: ...

    @abstractmethod
    def search(self, tenant: str, collection: str, query: str, k: int = 5,
               filters: dict[str, Any] | None = None) -> list[SearchResult]:
        """Search for similar documents. Returns a list of SearchResult entries."""
        ...

    def catalog_metrics(self, data_dir: str) -> dict[str, int]:
        """Return store-level catalog counters for admin/metrics endpoints.

        Default implementation provides tenant/collection counts only via the
        existing listing APIs. Backends with richer metadata stores should
        override this to include document/chunk counts.
        """
        tenants = self.list_tenants(data_dir)
        collection_count = 0
        for tenant in tenants:
            collection_count += len(self.list_collections(tenant))
        return {
            "tenant_count": len(tenants),
            "collection_count": collection_count,
            "doc_count": 0,
            "chunk_count": 0,
        }
