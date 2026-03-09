# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import types

import numpy as np

import pave.embedders.txtai_emb as txtai_emb_mod


class _DummyCFG:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def get(self, key: str, default=None):
        return self._values.get(key, default)


def test_encode_returns_float32_ndarray(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeEmb:
        def __init__(self, cfg):
            seen["cfg"] = cfg
            self.model = types.SimpleNamespace(
                get_sentence_embedding_dimension=lambda: 2,
            )

        def batchtransform(self, texts):
            seen["texts"] = list(texts)
            return [[1, 2], [3, 4]]

    monkeypatch.setattr(txtai_emb_mod, "Embeddings", FakeEmb, raising=True)
    monkeypatch.setattr(
        txtai_emb_mod,
        "CFG",
        _DummyCFG({"embedder.txtai": {"path": "m"}}),
        raising=True,
    )

    emb = txtai_emb_mod.TxtaiEmbedder()
    out = emb.encode(["a", "b"])

    assert isinstance(out, np.ndarray)
    assert out.dtype == np.float32
    assert out.shape == (2, 2)
    assert seen["texts"] == ["a", "b"]
    assert seen["cfg"] == {"path": "m"}


def test_dimension_reads_model_dimension_without_probe(monkeypatch) -> None:
    calls = {"batch": 0}

    class FakeEmb:
        def __init__(self, cfg):
            self.model = types.SimpleNamespace(
                get_sentence_embedding_dimension=lambda: 7,
            )

        def batchtransform(self, texts):
            calls["batch"] += 1
            return [[0.0] * 7 for _ in texts]

    monkeypatch.setattr(txtai_emb_mod, "Embeddings", FakeEmb, raising=True)
    monkeypatch.setattr(
        txtai_emb_mod,
        "CFG",
        _DummyCFG({"embedder.txtai": {"path": "m"}}),
        raising=True,
    )

    emb = txtai_emb_mod.TxtaiEmbedder()
    assert emb.dimension == 7
    assert calls["batch"] == 0


def test_dimension_probes_when_model_dimension_missing(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeEmb:
        def __init__(self, cfg):
            self.model = object()

        def batchtransform(self, texts):
            seen["texts"] = list(texts)
            return [[1.0, 2.0, 3.0]]

    monkeypatch.setattr(txtai_emb_mod, "Embeddings", FakeEmb, raising=True)
    monkeypatch.setattr(
        txtai_emb_mod,
        "CFG",
        _DummyCFG({"embedder.txtai": {"path": "m"}}),
        raising=True,
    )

    emb = txtai_emb_mod.TxtaiEmbedder()
    assert emb.dimension == 3
    assert seen["texts"] == ["_"]


def test_path_fallback_uses_embedder_model(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeEmb:
        def __init__(self, cfg):
            seen["cfg"] = cfg
            self.model = object()

        def batchtransform(self, texts):
            return [[1.0]]

    monkeypatch.setattr(txtai_emb_mod, "Embeddings", FakeEmb, raising=True)
    monkeypatch.setattr(
        txtai_emb_mod,
        "CFG",
        _DummyCFG(
            {
                "embedder.txtai": {},
                "embedder.model": "model-from-embedder-model",
            }
        ),
        raising=True,
    )

    txtai_emb_mod.TxtaiEmbedder()
    assert seen["cfg"] == {"path": "model-from-embedder-model"}
