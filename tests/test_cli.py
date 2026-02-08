# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import zipfile
from pathlib import Path

import pytest
from pave import cli as pvcli
from pave.config import get_cfg
from utils import DummyStore, SpyStore

@pytest.fixture
def cli_env(temp_data_dir, tmp_path):
    store = SpyStore(DummyStore())
    pvcli.store = store
    return pvcli, store, tmp_path

def test_cli_upload_on_fresh_collection_with_empty_index_dir(cli_env, tmp_path):
    pvcli, store, _ = cli_env
    tenant, coll = "acme", "invoices"
    sample = tmp_path / "s.txt"
    sample.write_text("one two three quatro cinco", encoding="utf-8")

    pvcli.main_cli(["create-collection", tenant, coll])
    pvcli.main_cli(["upload", tenant, coll, str(sample), "--docid", "DOC1", "--metadata", '{"lang":"pt"}'])

    assert ("load_or_init", tenant, coll) in store.calls
    assert ("has_doc", tenant, coll, "DOC1") in store.calls
    assert ("purge_doc", tenant, coll, "DOC1") not in store.calls
    assert any(c[0] == "index_records" and c[1] == tenant and c[2] == coll \
               and c[3] == "DOC1" for c in store.calls)
    assert ("save", tenant, coll) in store.calls

def test_cli_reupload_same_docid_triggers_purge(cli_env, tmp_path):
    pvcli, store, _ = cli_env
    tenant, coll = "acme", "reupcli"
    sample = tmp_path / "reup.txt"
    sample.write_text("alpha bravo", encoding="utf-8")

    pvcli.main_cli(["create-collection", tenant, coll])
    pvcli.main_cli(["upload", tenant, coll, str(sample), "--docid", "DOC-REUP"])

    sample.write_text("delta echo", encoding="utf-8")
    pvcli.main_cli(["upload", tenant, coll, str(sample), "--docid", "DOC-REUP"])

    assert ("purge_doc", tenant, coll, "DOC-REUP") in store.calls

def test_cli_search_returns_matches(cli_env, tmp_path):
    pvcli, store, _ = cli_env
    tenant, coll = "acme", "invoices"
    sample = tmp_path / "s2.txt"
    sample.write_text(
        "O avião sobrevoa o oceano. Mapas e correntes.",
        encoding="utf-8"
    )

    pvcli.main_cli(["create-collection", tenant, coll])
    pvcli.main_cli(["upload", tenant, coll, str(sample), "--docid", "DOC2"])
    pvcli.main_cli(["search", tenant, coll, "avião", "-k", "5"])

    assert any(c[0] == "search" and c[1] == tenant and c[2] == coll \
               and c[3] == "avião" and c[4] == 5 for c in store.calls)


def test_cli_dump_archive_creates_zip(cli_env, tmp_path, capsys):
    pvcli, _, _ = cli_env
    data_dir = Path(get_cfg().get("data_dir"))
    sample = data_dir / "sample.txt"
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_text("hello", encoding="utf-8")

    target = tmp_path / "export.zip"
    pvcli.main_cli(["dump-archive", "--output", str(target)])

    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert Path(out["archive"]) == target

    with zipfile.ZipFile(target) as zf:
        assert "sample.txt" in zf.namelist()
        with zf.open("sample.txt") as f:
            assert f.read().decode("utf-8") == "hello"
