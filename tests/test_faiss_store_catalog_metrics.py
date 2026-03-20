# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from pathlib import Path

from pave.stores.faiss import FaissStore


def test_catalog_metrics_counts_docs_and_chunks(cfg, tmp_path):
    cfg.set("data_dir", str(tmp_path))
    store = FaissStore()
    store.index_records(
        "acme",
        "c1",
        "doc1",
        [("0", "alpha", {"lang": "en"}), ("1", "beta", {"lang": "en"})],
    )
    store.index_records(
        "acme",
        "c1",
        "doc2",
        [("0", "gamma", {"lang": "en"})],
    )
    store.index_records(
        "acme",
        "c2",
        "doc3",
        [("0", "delta", {"lang": "en"})],
    )

    # Keep parity with list_tenants: tenant directories count even if empty.
    data_dir = Path(cfg.get("data_dir"))
    (data_dir / "t_empty").mkdir(parents=True, exist_ok=True)

    snap = store.catalog_metrics(str(data_dir))
    assert snap["tenant_count"] == 2
    assert snap["collection_count"] == 2
    assert snap["doc_count"] == 3
    assert snap["chunk_count"] == 4
