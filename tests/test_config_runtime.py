# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

def test_overlay_get_set_snapshot(cfg):
    # baseline efetivo (sem depender de arquivo em dev)
    assert cfg.get("auth.mode", "none") == "none"
    assert cfg.get("vector_store.type", "xpto") == "default"

    # runtime overlay supersedes codebase and data
    cfg.set("auth.mode", "static")
    cfg.set("vector_store.type", "qdrant")
    assert cfg.get("auth.mode") == "static"
    assert cfg.get("vector_store.type") == "qdrant"

    snap = cfg.snapshot()
    assert snap["auth"]["mode"] == "static"
    assert snap["vector_store"]["type"] == "qdrant"
    cfg.set("auth.mode", "none")
    cfg.set("vector_store.type", "default")


def test_runtime_overlay_reflected_in_app(app, client):
    # muda runtime no cfg do app e checa que /health reflete esses valores
    app.state.cfg.set("auth.mode", "static")
    app.state.cfg.set("vector_store.type", "qdrant")

    r = client.get("/health/metrics")
    assert r.status_code == 200
    j = r.json()
    assert j["auth"] == "static"
    assert j["vector_store"] == "qdrant"


def test_effective_defaults_when_missing(cfg, app, client):
    # se não houver config file, build_app aplica defaults efetivos
    # garante que nunca seja None nos endpoints
    r = client.get("/health/metrics")
    assert r.status_code == 200
    j = r.json()
    assert j["auth"] == "none"
    assert j["vector_store"] == "default"
