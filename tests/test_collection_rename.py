# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest


def test_rename_collection_basic(client):
    """Basic rename: collection data stays intact after rename."""
    # Create and populate collection
    r = client.post("/collections/acme/invoices")
    assert r.status_code == 201 and r.json()["ok"] is True

    # Upload a document
    r = client.post(
        "/collections/acme/invoices/documents",
        files={"file": ("test.txt", b"Captain Nemo submarine voyage", "text/plain")},
        data={"docid": "verne"},
    )
    assert r.status_code == 201 and r.json()["ok"] is True

    # Search before rename
    r = client.post(
        "/collections/acme/invoices/search",
        json={"q": "submarine", "k": 2},
    )
    assert r.status_code == 200
    matches_before = r.json()["matches"]
    assert len(matches_before) > 0

    # Rename collection
    r = client.put(
        "/collections/acme/invoices",
        json={"new_name": "bills"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["old_name"] == "invoices"
    assert data["new_name"] == "bills"

    # Search under new name returns same results
    r = client.post(
        "/collections/acme/bills/search",
        json={"q": "submarine", "k": 2},
    )
    assert r.status_code == 200
    matches_after = r.json()["matches"]
    assert len(matches_after) == len(matches_before)

    # Old name should no longer work (collection doesn't exist)
    r = client.post(
        "/collections/acme/invoices/search",
        json={"q": "submarine", "k": 2},
    )
    # This should return empty results (fresh empty collection created on access)
    assert r.status_code == 200
    assert len(r.json()["matches"]) == 0


def test_rename_nonexistent_collection(client):
    """Rename non-existent collection should fail with 404."""
    r = client.put(
        "/collections/acme/nonexistent",
        json={"new_name": "something"},
    )
    assert r.status_code == 404
    data = r.json()
    assert data["code"] == "collection_not_found"
    assert "does not exist" in data["error"]


def test_rename_to_same_name(client):
    """Rename to same name should fail with 400."""
    # Create collection first
    r = client.post("/collections/acme/samename")
    assert r.status_code == 201

    r = client.put(
        "/collections/acme/samename",
        json={"new_name": "samename"},
    )
    assert r.status_code == 400
    data = r.json()
    assert data["code"] == "rename_invalid"
    assert "same" in data["error"].lower()


def test_rename_collision_sequence(client):
    """Collision test: rename to existing name should fail gracefully."""
    # 1. Create two collections: foo and bar
    r = client.post("/collections/acme/foo")
    assert r.status_code == 201 and r.json()["ok"] is True

    r = client.post("/collections/acme/bar")
    assert r.status_code == 201 and r.json()["ok"] is True

    # 2. Rename bar -> foo (should fail - foo exists)
    r = client.put(
        "/collections/acme/bar",
        json={"new_name": "foo"},
    )
    assert r.status_code == 409
    data = r.json()
    assert data["code"] == "collection_conflict"
    assert "already exists" in data["error"]

    # 3. Delete foo
    r = client.delete("/collections/acme/foo")
    assert r.status_code == 200

    # 4. Now rename bar -> foo (should succeed)
    r = client.put(
        "/collections/acme/bar",
        json={"new_name": "foo"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 5. Create new bar
    r = client.post("/collections/acme/bar")
    assert r.status_code == 201 and r.json()["ok"] is True

    # 6. Try to rename bar -> foo again (should fail)
    r = client.put(
        "/collections/acme/bar",
        json={"new_name": "foo"},
    )
    assert r.status_code == 409
    data = r.json()
    assert data["code"] == "collection_conflict"
    assert "already exists" in data["error"]
