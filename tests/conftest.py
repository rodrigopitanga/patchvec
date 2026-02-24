# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

import sys
import types
import pytest

_txtai_available = True
try:
    import txtai.embeddings  # type: ignore  # noqa: F401
except ModuleNotFoundError:
    _txtai_available = False
    embeddings_mod = types.ModuleType("txtai.embeddings")

    class _MissingEmbeddings:  # pragma: no cover - test fallback
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "txtai is required for TxtaiStore. Install txtai or monkeypatch Embeddings for tests."
            )

    embeddings_mod.Embeddings = _MissingEmbeddings  # type: ignore[attr-defined]
    txtai_mod = types.ModuleType("txtai")
    txtai_mod.embeddings = embeddings_mod  # type: ignore[attr-defined]
    sys.modules.setdefault("txtai", txtai_mod)
    sys.modules.setdefault("txtai.embeddings", embeddings_mod)

from utils import DummyStore, SpyStore, FakeEmbeddings

if not _txtai_available:
    emb_mod = sys.modules.get("txtai.embeddings")
    if emb_mod is not None:
        emb_mod.Embeddings = FakeEmbeddings  # type: ignore[attr-defined]

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
    for k in ("PATCHVEC_VECTOR_STORE__TYPE", "PATCHVEC_AUTH__MODE"):
        monkeypatch.delenv(k, raising=False)
    reload_cfg()
    cfg = get_cfg()
    cfg.set("data_dir", str(temp_data_dir))
    cfg.set("auth.mode", "none")
    cfg.set("vector_store.type", "default")
    cfg.set("vector_store.txtai.backend", "faiss")
    cfg.set("common_enabled", False)
    is_slow = request.node.get_closest_marker("slow") is not None
    if is_slow:
        # Real embeddings for end-to-end pipeline tests; small fast model.
        cfg.set("vector_store.txtai.embed_model", _FAST_MODEL)
        if not _txtai_available:
            import pave.stores.txtai_store as store_mod
            monkeypatch.setattr(store_mod, "Embeddings", FakeEmbeddings, raising=True)
    else:
        # Fast path: always use FakeEmbeddings; no model loaded.
        cfg.set("vector_store.txtai.embed_model", "fake")
        import pave.stores.txtai_store as store_mod
        monkeypatch.setattr(store_mod, "Embeddings", FakeEmbeddings, raising=True)
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
