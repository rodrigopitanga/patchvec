# (C) 2025 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from pave.main import VERSION

def test_ui_renders_instance_strings(client, app, cfg):
    cfg.set("instance.name", "PV-a-name")
    cfg.set("instance.desc", "PV-a-desc")

    r = client.get("/ui")
    assert r.status_code == 200
    assert "PV-a-name" in r.text
    assert "PV-a-desc" in r.text

    # runtime change should reflect on UI
    cfg.set("instance.name", "PV-Changed")
    cfg.set("instance.desc", "D-Changed")
    r2 = client.get("/ui")
    assert "PV-Changed" in r2.text
    assert "D-Changed" in r2.text

def test_openapi_split_and_security(client, app):
    r = client.get("/openapi-search.json")
    assert r.status_code == 200
    doc = r.json()
    assert doc["info"]["title"] == app.title
    assert doc["info"]["version"] == VERSION
    assert "bearerAuth" in doc.get("components", {}).get("securitySchemes", {})
    assert doc.get("security") == [{"bearerAuth": []}]

def test_favicon_status(client):
    r = client.get("/favicon.ico")
    assert r.status_code == 200
