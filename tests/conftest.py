# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

import sys
import types

if "txtai.embeddings" not in sys.modules:
    txtai_stub = types.ModuleType("txtai")
    embeddings_stub = types.ModuleType("txtai.embeddings")

    class _StubEmbeddings:  # pragma: no cover - stub for optional dependency
        def __init__(self, *args, **kwargs):
            pass

    embeddings_stub.Embeddings = _StubEmbeddings
    txtai_stub.embeddings = embeddings_stub
    sys.modules.setdefault("txtai", txtai_stub)
    sys.modules.setdefault("txtai.embeddings", embeddings_stub)

import pytest
from fastapi.testclient import TestClient
from pave.config import get_cfg, reload_cfg
from pave.main import build_app, VERSION
from pave.ui import attach_ui
from utils import DummyStore, SpyStore

@pytest.fixture(scope="session")
def temp_data_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("pvdata")

@pytest.fixture(autouse=True)
def _reset_cfg_between_tests(monkeypatch, temp_data_dir):
    for k in ("PATCHVEC_VECTOR_STORE__TYPE", "PATCHVEC_AUTH__MODE"):
        monkeypatch.delenv(k, raising=False)
    reload_cfg()
    cfg = get_cfg()
    cfg.set("data_dir", str(temp_data_dir))
    cfg.set("auth.mode", "none")
    cfg.set("vector_store.type", "default")
    cfg.set("vector_store.txtai.backend", "faiss")
    cfg.set("vector_store.txtai.embed_model",
            "sentence-transformers/paraphrase-MiniLM-L3-v2")
    cfg.set("common_enabled", False)
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
