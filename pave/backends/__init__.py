# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from .base import IndexRecord, SearchHit, VectorBackend
from .txtai import TxtaiVectorBackend

__all__ = [
    "IndexRecord",
    "SearchHit",
    "TxtaiVectorBackend",
    "VectorBackend",
]
