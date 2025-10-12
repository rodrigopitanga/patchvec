# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Iterable, Dict, Any, List


Record = tuple[str, str, Dict[str, Any]]  # (rid, text, meta)

class BaseStore(ABC):
    @abstractmethod
    def load_or_init(self, tenant: str, collection: str) -> None: ...

    @abstractmethod
    def save(self, tenant: str, collection: str) -> None: ...

    @abstractmethod
    def delete_collection(self, tenant: str, collection: str) -> None: ...

    @abstractmethod
    def purge_doc(self, tenant: str, collection: str, docid: str) -> int: ...

    @abstractmethod
    def index_records(self, tenant: str, collection: str, docid: str, records: Iterable[Record]) -> int: ...

    @abstractmethod
    def search(self, tenant: str, collection: str, text: str, k: int = 5, filters: Dict[str, Any] | None = None) -> List[Dict[str, Any]]: ...
