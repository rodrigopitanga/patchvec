# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from typing import Protocol


SearchHit = tuple[str, float]


class VectorBackend(Protocol):
    def initialize(self) -> None: ...

    def add(self, rids: list[str], vectors: NDArray[np.float32]) -> None: ...

    def search(
        self,
        vector: NDArray[np.float32],
        k: int,
    ) -> list[SearchHit]: ...

    def delete(self, rids: list[str]) -> None: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...
