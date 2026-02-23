# (C) 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later


def test_search_failure_returns_code(client, app, monkeypatch):
    client.post("/collections/acme/failsearch")

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(app.state.store, "search", boom, raising=True)
    r = client.post(
        "/collections/acme/failsearch/search",
        json={"q": "x", "k": 1},
    )
    assert r.status_code == 500
    data = r.json()
    assert data["ok"] is False
    assert data["code"] == "search_failed"
