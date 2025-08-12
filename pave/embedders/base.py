# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations
from abc import ABC, abstractmethod

class BaseEmbedder(ABC):
    @abstractmethod
    def encode(self, texts: list[str]) -> list[list[float]]: ...

    @property
    @abstractmethod
    def dim(self) -> int | None: ...
