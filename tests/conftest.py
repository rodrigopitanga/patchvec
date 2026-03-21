# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

import os

import pytest

from utils import SpyStore, FakeEmbedder

from fastapi.testclient import TestClient
from pave.config import get_cfg, reload_cfg
from pave.main import build_app, VERSION
from pave.ui import attach_ui

@pytest.fixture(scope="session")
def temp_data_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("pvdata")

_FAST_MODEL = "sentence-transformers/paraphrase-MiniLM-L3-v2"

@pytest.fixture(autouse=True)
def _reset_cfg_between_tests(monkeypatch, temp_data_dir, request):
    for k in tuple(os.environ):
        if k.startswith("PATCHVEC_"):
            monkeypatch.delenv(k, raising=False)
    for k in ("PATCHVEC_VECTOR_STORE__TYPE", "PATCHVEC_AUTH__MODE"):
        monkeypatch.delenv(k, raising=False)
    reload_cfg()
    cfg = get_cfg()
    cfg.set("data_dir", str(temp_data_dir))
    cfg.set("auth.mode", "none")
    cfg.set("vector_store.type", "faiss")
    cfg.set("embedder.type", "sbert")
    cfg.set("common_enabled", False)
    is_slow = request.node.get_closest_marker("slow") is not None
    if is_slow:
        # Real embeddings for end-to-end pipeline tests; small fast model.
        cfg.set("embedder.sbert.model", _FAST_MODEL)
    else:
        # Fast path: deterministic fake embedder, no model load.
        cfg.set("embedder.sbert.model", "fake")
        import pave.stores.faiss as store_mod

        monkeypatch.setattr(
            store_mod,
            "get_embedder",
            lambda: FakeEmbedder(),
            raising=True,
        )
    yield

@pytest.fixture()
def app(temp_data_dir):
    cfg = get_cfg()
    app = build_app(cfg)
    try:
        attach_ui(app)
    except Exception:
        pass
    app.state.store = SpyStore(app.state.store)
    return app

@pytest.fixture()
def client(app):
    return TestClient(app)

@pytest.fixture()
def cfg(app):
    return app.state.cfg
