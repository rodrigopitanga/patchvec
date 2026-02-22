# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

import json

import pytest

from pave.stores import txtai_store as store_mod
from pave.stores.txtai_store import TxtaiStore
from pave.config import get_cfg
from utils import FakeEmbeddings


@pytest.fixture(autouse=True)
def _fake_embeddings(monkeypatch):
    monkeypatch.setattr(store_mod, "Embeddings", FakeEmbeddings, raising=True)


@pytest.fixture()
def store():
    return TxtaiStore()


def _extract_similarity_term(sql: str) -> str:
    marker = "similar('"
    if marker not in sql:
        raise AssertionError(f"similar() clause missing in SQL: {sql!r}")
    rest = sql.split(marker, 1)[1]
    return rest.split("')", 1)[0]


def test_build_sql_sanitizes_similarity_term(store):
    raw_query = "foo'; DROP TABLE users; -- comment"
    sql = store._build_sql(raw_query, 5, {}, ["id", "text"])
    term = _extract_similarity_term(sql)

    # injection primitives are stripped or neutralised
    assert ";" not in term
    assert "--" not in term
    # original alpha characters remain so search still works
    assert "foo" in term


def test_build_sql_sanitizes_filter_values(store):
    filters = {"lang": ["en'; DELETE FROM x;"], "tags": ['alpha"beta']}
    sql = store._build_sql("foo", 5, filters, ["id", "text"])

    # filter clause should not leak dangerous characters
    assert ";" not in sql
    assert '"' not in sql
    assert "--" not in sql


def test_build_sql_normalises_filter_keys(store):
    filters = {"lang]; DROP": ["en"], 123: ["x"]}
    sql = store._build_sql("foo", 5, filters, ["id"])
    assert "[langDROP]" in sql
    assert "[123]" in sql


def test_build_sql_applies_query_length_limit(store):
    cfg = get_cfg()
    snapshot = cfg.snapshot()
    try:
        cfg.set("vector_store.txtai.max_query_chars", 8)
        sql = store._build_sql("abcdefghijklmno", 5, {}, ["id"])
        term = _extract_similarity_term(sql)

        # collapse the doubled quotes to measure the original payload length
        collapsed = term.replace("''", "'")
        assert len(collapsed) == 8
    finally:
        cfg.replace(data=snapshot)


def test_search_handles_special_characters(store):
    tenant, collection = "tenant", "coll"
    store.load_or_init(tenant, collection)

    records = [("r1", "hello world", {"lang": "en"})]
    store.index_records(tenant, collection, "doc", records)

    hits = store.search(tenant, collection, "world; -- comment", k=5)
    assert hits
    assert hits[0].id.endswith("::r1")


def test_round_trip_with_weird_metadata_field(store):
    tenant, collection = "tenant", "coll"
    store.load_or_init(tenant, collection)

    weird_key = "meta;`DROP"
    weird_value = "val'u"
    records = [("r2", "strange world", {weird_key: weird_value})]
    store.index_records(tenant, collection, "doc2", records)

    filters = {weird_key: weird_value}
    hits = store.search(tenant, collection, "strange", k=5, filters=filters)

    assert hits
    assert hits[0].id.endswith("::r2")

    emb = store._emb[(tenant, collection)]
    safe_key = TxtaiStore._sanit_field(weird_key)
    assert emb.last_sql and f"[{safe_key}]" in emb.last_sql

    rid = hits[0].id
    stored_meta = store._load_meta(tenant, collection).get(rid) or {}
    assert safe_key in stored_meta
    assert stored_meta[safe_key] == TxtaiStore._sanit_sql(weird_value)

    doc = emb._docs[rid]
    assert doc["meta"].get(safe_key) == TxtaiStore._sanit_sql(weird_value)
    serialized = json.loads(doc["meta_json"]) if doc.get("meta_json") else {}
    assert serialized.get(safe_key) == TxtaiStore._sanit_sql(weird_value)
    assert hits[0].meta.get(safe_key) == TxtaiStore._sanit_sql(weird_value)
