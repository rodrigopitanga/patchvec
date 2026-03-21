# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import importlib
import zipfile
from pathlib import Path

import pytest
from pave.config import get_cfg
from pave.stores import factory as store_factory
from utils import DummyStore, SpyStore

@pytest.fixture
def cli_env(temp_data_dir, tmp_path, monkeypatch):
    store = SpyStore(DummyStore())
    monkeypatch.setattr(
        store_factory,
        "get_store",
        lambda *_args, **_kwargs: store,
        raising=True,
    )
    from pave import cli as pvcli_mod

    pvcli = importlib.reload(pvcli_mod)
    pvcli.store = store
    return pvcli, store, tmp_path

def test_cli_ingest_on_fresh_collection_with_empty_index_dir(cli_env, tmp_path):
    pvcli, store, _ = cli_env
    tenant, coll = "acme", "invoices"
    sample = tmp_path / "s.txt"
    sample.write_text("one two three quatro cinco", encoding="utf-8")

    pvcli.main_cli(["create-collection", tenant, coll])
    pvcli.main_cli(["ingest", tenant, coll, str(sample), "--docid", "DOC1", "--metadata", '{"lang":"pt"}'])

    assert ("load_or_init", tenant, coll) in store.calls
    assert ("has_doc", tenant, coll, "DOC1") in store.calls
    assert ("purge_doc", tenant, coll, "DOC1") not in store.calls
    assert any(c[0] == "index_records" and c[1] == tenant and c[2] == coll \
               and c[3] == "DOC1" for c in store.calls)
    assert ("save", tenant, coll) in store.calls


def test_cli_ingest_passes_doc_meta_through_wrapper(cli_env, tmp_path):
    pvcli, store, _ = cli_env
    tenant, coll = "acme", "metawrap"
    sample = tmp_path / "meta.txt"
    sample.write_text("conteúdo de teste", encoding="utf-8")

    pvcli.main_cli(["create-collection", tenant, coll])
    pvcli.main_cli(
        [
            "ingest", tenant, coll, str(sample),
            "--docid", "DOCMETA",
            "--metadata", '{"lang":"pt","source":"cli"}',
        ]
    )

    calls = [
        c for c in store.calls
        if c[0] == "index_records" and c[1] == tenant
        and c[2] == coll and c[3] == "DOCMETA"
    ]
    assert calls
    doc_meta = calls[-1][5]
    assert isinstance(doc_meta, dict)
    assert doc_meta["docid"] == "DOCMETA"
    assert doc_meta["lang"] == "pt"
    assert doc_meta["source"] == "cli"
    assert doc_meta["filename"].endswith("meta.txt")
    assert doc_meta["ingested_at"].endswith("Z")


def test_cli_reingest_same_docid_triggers_purge(cli_env, tmp_path):
    pvcli, store, _ = cli_env
    tenant, coll = "acme", "reupcli"
    sample = tmp_path / "reup.txt"
    sample.write_text("alpha bravo", encoding="utf-8")

    pvcli.main_cli(["create-collection", tenant, coll])
    pvcli.main_cli(["ingest", tenant, coll, str(sample), "--docid", "DOC-REUP"])

    sample.write_text("delta echo", encoding="utf-8")
    pvcli.main_cli(["ingest", tenant, coll, str(sample), "--docid", "DOC-REUP"])

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
    pvcli.main_cli(["ingest", tenant, coll, str(sample), "--docid", "DOC2"])
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


def test_cli_list_tenants(cli_env, tmp_path, capsys, monkeypatch):
    pvcli, _, _ = cli_env
    from pave.config import get_cfg
    cfg = get_cfg()
    monkeypatch.setattr(cfg, "_cfg", {**cfg._cfg, "data_dir": str(tmp_path)})

    (tmp_path / "t_beta").mkdir(parents=True, exist_ok=True)
    (tmp_path / "t_alpha").mkdir(parents=True, exist_ok=True)

    pvcli.main_cli(["list-tenants"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["tenants"] == ["alpha", "beta"]
    assert out["count"] == 2


def test_cli_list_tenants_accepts_home_flag(cli_env, tmp_path, capsys):
    pvcli, _, _ = cli_env
    home = tmp_path / "instance"
    (home / "data" / "t_beta").mkdir(parents=True, exist_ok=True)
    (home / "data" / "t_alpha").mkdir(parents=True, exist_ok=True)

    pvcli.main_cli(["list-tenants", "--home", str(home)])
    out = json.loads(capsys.readouterr().out)

    assert out["ok"] is True
    assert out["tenants"] == ["alpha", "beta"]


def test_cli_init_writes_default_instance_files(cli_env, monkeypatch, tmp_path, capsys):
    pvcli, _, _ = cli_env
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    pvcli.main_cli(["init"])
    out = json.loads(capsys.readouterr().out)
    instance = home / "patchvec"
    config_path = instance / "config.yml"
    tenants_path = instance / "tenants.yml"

    assert out["ok"] is True
    assert Path(out["config"]) == config_path
    assert Path(out["tenants"]) == tenants_path
    assert Path(out["data_dir"]) == instance / "data"
    assert config_path.is_file()
    assert tenants_path.is_file()
    assert "tenants_file:" in config_path.read_text(encoding="utf-8")
    assert "data_dir:" in config_path.read_text(encoding="utf-8")
