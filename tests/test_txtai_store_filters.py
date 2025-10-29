# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from pave.stores.txtai_store import TxtaiStore
from pave.config import get_cfg

@pytest.fixture(scope="module", autouse=True)
def store():
    s = TxtaiStore()
    tenant, coll = "t1", "c1"
    s.load_or_init(tenant, coll)

    # insert minimal dataset
    records = [
        ("r1", "alpha foo bar", {"name": "foobar", "size": 50, "created": "2024-05-01"}),
        ("r2", "beta foo", {"name": "fooqux", "size": 150, "created": "2025-01-10"}),
        ("r3", "gamma bar", {"name": "bazbar", "size": 250, "created": "2025-02-01"}),
        ("r4", "delta", {"name": "zulu", "size": 5, "created": "2023-12-31"}),
    ]
    s.index_records(tenant, coll, "filterdoc", records)
    s.load_or_init(tenant, coll)
    yield s, tenant, coll

def _ids(results):
    return [r["id"].split("::")[-1] for r in results]

def test_split_filters_basic(store):
    s, _, _ = store
    f = {
        "name": ["foo", "*bar", "baz*"],
        "size": [">100"],
        "x": ["!=9"]
    }
    pre, post = s._split_filters(f)
    assert "name" in pre and "name" in post
    assert "size" not in pre and "x" not in pre
    assert any(v.startswith(">") for v in post["size"]) or "size" not in post

def test_prefilter(store):
    s, tenant, coll = store
    f1 = {"name": ["fooqux"]}
    res = s.search(tenant, coll, "foo", 10, filters=f1)
    ids1 = _ids(res)
    assert "r2" in ids1
    assert "r1" not in ids1 and "r3" not in ids1 and "r4" not in ids1
    f1 = {"name": ["zulu"]}
    res = s.search(tenant, coll, "alpha", 10, filters=f1)
    ids2 = _ids(res)
    assert "r4" in ids2
    assert "r1" not in ids2 and "r2" not in ids2 and "r3" not in ids2

def test_prepostfilter(store):
    s, tenant, coll = store
    f = {
        "name": ["fooqux"],
        "size": ["<200"],
    }
    res = s.search(tenant, coll, "foo", 10, filters=f)
    ids = _ids(res)
    assert "r2" in ids
    assert "r1" not in ids and "r3" not in ids and "r4" not in ids

def test_postfilter_stars_or(store):
    s, tenant, coll = store
    f = {"name": ["*azba*","foo*"]}
    res = s.search(tenant, coll, "foo", 10, filters=f)
    ids = _ids(res)
    assert "r1" in ids and "r2" in ids and "r3" in ids
    assert "r4" not in ids

def test_postfilter_endswith(store):
    s, tenant, coll = store
    f = {"name": ["*bar"]}
    res = s.search(tenant, coll, "bar", 10, filters=f)
    ids = _ids(res)
    assert "r1" in ids and "r3" in ids
    assert "r2" not in ids

def test_postfilter_numeric_gt(store):
    s, tenant, coll = store
    f = {"size": [">100"]}
    res = s.search(tenant, coll, "foo", 10, filters=f)
    ids = _ids(res)
    assert set(ids) == {"r2", "r3"}

def test_postfilter_datetime_gte(store):
    s, tenant, coll = store
    f = {"created": [">=2025-01-01"]}
    res = s.search(tenant, coll, "bar", 10, filters=f)
    ids = _ids(res)
    assert set(ids) == {"r2", "r3"}

def test_combined_filters(store):
    s, tenant, coll = store
    f = {
        "name": ["foo*", "*bar"],    # OR within key
        "size": [">100"],            # AND across keys
    }
    res = s.search(tenant, coll, "foo", 10, filters=f)
    ids = _ids(res)
    # size>100 keeps r2,r3; name cond keeps r1,r2,r3 -> intersect = r2,r3
    assert set(ids) == {"r2", "r3"}

def test_no_filters_returns_all(store):
    s, tenant, coll = store
    res = s.search(tenant, coll, "foo", 10, filters=None)
    assert len(res) >= 4

