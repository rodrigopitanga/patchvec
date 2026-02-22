# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from pave.stores.txtai_store import TxtaiStore
from pave.config import get_cfg

@pytest.fixture()
def store(request):
    s = TxtaiStore()
    # Use unique collection per test to avoid conflicts
    tenant, coll = "t1", f"c_{request.node.name}"
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
    return [r.id.split("::")[-1] for r in results]

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


def test_negation_prefilter(store):
    """Negation !value should be pushed to SQL pre-filter for performance."""
    s, tenant, coll = store
    # Exclude name=zulu, should return r1, r2, r3
    f = {"name": ["!zulu"]}
    res = s.search(tenant, coll, "foo", 10, filters=f)
    ids = _ids(res)
    assert "r4" not in ids
    assert "r1" in ids or "r2" in ids  # at least some non-zulu results


def test_negation_in_split_filters(store):
    """Verify !value goes to pre-filter, not post-filter."""
    s, _, _ = store
    f = {"name": ["!excluded", "exact"], "size": ["!50"]}
    pre, post = s._split_filters(f)
    # Both negation and exact values should be in pre-filter
    assert "name" in pre
    assert "!excluded" in pre["name"]
    assert "exact" in pre["name"]
    assert "size" in pre
    assert "!50" in pre["size"]
    # Post-filter should be empty for these
    assert "name" not in post
    assert "size" not in post


def test_negation_sql_generation(store):
    """Verify SQL generates <> for negation values."""
    s, _, _ = store
    sql = s._build_sql("test", 10, {"name": ["!excluded"]}, ["id", "text"])
    assert "[name] <> 'excluded'" in sql
    assert "[name] = '!excluded'" not in sql


def test_negation_combined_with_exact(store):
    """Negation combined with exact match in OR."""
    s, tenant, coll = store
    # name=foobar OR name!=zulu -> should match r1 (foobar) plus others not zulu
    f = {"name": ["foobar", "!zulu"]}
    res = s.search(tenant, coll, "foo", 10, filters=f)
    ids = _ids(res)
    assert "r1" in ids  # foobar matches
    assert "r4" not in ids  # zulu excluded


@pytest.fixture()
def multilingual_store(request):
    """Store with multilingual content for testing non-English retrieval."""
    s = TxtaiStore()
    tenant, coll = "t1", f"ml_{request.node.name}"
    s.load_or_init(tenant, coll)

    records = [
        ("pt1", "O gato preto dormiu no sofá", {"lang": "pt"}),
        ("pt2", "A casa amarela tem um jardim bonito", {"lang": "pt"}),
        ("it1", "Il gatto nero dorme sul divano", {"lang": "it"}),
        ("de1", "Die schwarze Katze schläft auf dem Sofa", {"lang": "de"}),
        ("en1", "The black cat sleeps on the sofa", {"lang": "en"}),
    ]
    s.index_records(tenant, coll, "multilang", records)
    s.load_or_init(tenant, coll)
    yield s, tenant, coll


def test_multilingual_portuguese_query(multilingual_store):
    """Search in Portuguese should retrieve Portuguese and semantically similar results."""
    s, tenant, coll = multilingual_store
    res = s.search(tenant, coll, "gato preto", 5)
    ids = _ids(res)
    # Portuguese query should find Portuguese cat text first
    assert "pt1" in ids


def test_multilingual_cross_language(multilingual_store):
    """Multilingual model should retrieve semantically similar texts across languages."""
    s, tenant, coll = multilingual_store
    # English query about black cat should find all cat-related texts
    res = s.search(tenant, coll, "black cat sleeping", 5)
    ids = _ids(res)
    # Should retrieve the cat/sofa texts in multiple languages
    assert "en1" in ids
    # At least one non-English cat text should appear
    assert any(rid in ids for rid in ["pt1", "it1", "de1"])


def test_match_reason_semantic_only(store):
    """Search without filters should show semantic similarity in match_reason."""
    s, tenant, coll = store
    res = s.search(tenant, coll, "foo bar", 5)
    assert len(res) > 0
    for r in res:
        assert r.match_reason
        assert "semantic similarity" in r.match_reason
        # Should include percentage
        assert "%" in r.match_reason


def test_match_reason_with_filters(store):
    """Search with filters should show both similarity and filter info."""
    s, tenant, coll = store
    f = {"name": ["foobar"]}
    res = s.search(tenant, coll, "alpha", 5, filters=f)
    assert len(res) > 0
    r = res[0]
    assert r.match_reason
    assert "semantic similarity" in r.match_reason
    assert "filters:" in r.match_reason
    assert "name=foobar" in r.match_reason


def test_match_reason_multiple_filters(store):
    """Match reason should show all filter fields that matched."""
    s, tenant, coll = store
    # Use two string filters that can both be pre-filtered
    f = {"name": ["fooqux"], "docid": ["filterdoc"]}
    res = s.search(tenant, coll, "beta", 5, filters=f)
    ids = _ids(res)
    assert "r2" in ids
    r2 = next(r for r in res if r.id.endswith("r2"))
    reason = r2.match_reason
    assert "name=fooqux" in reason
    assert "docid=filterdoc" in reason
