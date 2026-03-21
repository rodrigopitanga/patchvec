# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from pathlib import Path

from pave.config import Config


def _write(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_tenants_sidecar_is_opt_in(monkeypatch, tmp_path):
    monkeypatch.delenv("PATCHVEC_AUTH__TENANTS_FILE", raising=False)
    home = tmp_path / "home"
    sidecar = home / "patchvec" / "tenants.yml"
    sidecar.parent.mkdir(parents=True)
    _write(
        sidecar,
        """
        auth:
          api_keys:
            acme: sidecar-key
        tenants:
          acme:
            max_concurrent: 9
        """,
    )
    monkeypatch.setenv("HOME", str(home))

    config_path = tmp_path / "config.yml"
    _write(
        config_path,
        """
        auth:
          mode: static
        """,
    )

    cfg = Config(path=config_path)

    assert cfg.get("auth.tenants_file") is None
    assert cfg.get("auth.api_keys") == {}
    assert cfg.get("tenants.acme.max_concurrent") is None


def test_dev_mode_skips_default_user_config(monkeypatch, tmp_path):
    home = tmp_path / "home"
    default_cfg = home / "patchvec" / "config.yml"
    default_cfg.parent.mkdir(parents=True)
    _write(
        default_cfg,
        """
        auth:
          mode: static
        vector_store:
          type: qdrant
        """,
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("PATCHVEC_CONFIG", raising=False)
    monkeypatch.setenv("PATCHVEC_DEV", "1")

    cfg = Config()

    assert cfg.get("auth.mode") == "none"
    assert cfg.get("vector_store.type") == "faiss"


def test_explicit_config_path_still_wins_in_dev(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    _write(
        config_path,
        """
        auth:
          mode: static
        vector_store:
          type: qdrant
        """,
    )
    monkeypatch.setenv("PATCHVEC_DEV", "1")
    monkeypatch.setenv("PATCHVEC_CONFIG", str(config_path))

    cfg = Config()

    assert cfg.get("auth.mode") == "static"
    assert cfg.get("vector_store.type") == "qdrant"


def test_env_tenants_file_selects_sidecar_over_config_value(monkeypatch, tmp_path):
    sidecar_a = tmp_path / "tenants-a.yml"
    sidecar_b = tmp_path / "tenants-b.yml"
    _write(
        sidecar_a,
        """
        auth:
          api_keys:
            acme: config-sidecar-key
        tenants:
          acme:
            max_concurrent: 1
        """,
    )
    _write(
        sidecar_b,
        """
        auth:
          api_keys:
            acme: env-sidecar-key
        tenants:
          acme:
            max_concurrent: 7
        """,
    )

    config_path = tmp_path / "config.yml"
    _write(
        config_path,
        f"""
        auth:
          mode: static
          tenants_file: {sidecar_a}
        """,
    )
    monkeypatch.setenv("PATCHVEC_AUTH__TENANTS_FILE", str(sidecar_b))

    cfg = Config(path=config_path)

    assert cfg.get("auth.api_keys.acme") == "env-sidecar-key"
    assert cfg.get("tenants.acme.max_concurrent") == 7


def test_inline_tenant_values_override_sidecar(tmp_path):
    sidecar = tmp_path / "tenants.yml"
    _write(
        sidecar,
        """
        auth:
          api_keys:
            acme: sidecar-key
        tenants:
          acme:
            max_concurrent: 1
        """,
    )

    config_path = tmp_path / "config.yml"
    _write(
        config_path,
        f"""
        auth:
          mode: static
          tenants_file: {sidecar}
          api_keys:
            acme: inline-key
        tenants:
          acme:
            max_concurrent: 2
        """,
    )

    cfg = Config(path=config_path)

    assert cfg.get("auth.api_keys.acme") == "inline-key"
    assert cfg.get("tenants.acme.max_concurrent") == 2


def test_env_tenant_values_override_inline_and_sidecar(monkeypatch, tmp_path):
    sidecar = tmp_path / "tenants.yml"
    _write(
        sidecar,
        """
        auth:
          api_keys:
            acme: sidecar-key
        tenants:
          acme:
            max_concurrent: 1
        """,
    )

    config_path = tmp_path / "config.yml"
    _write(
        config_path,
        f"""
        auth:
          mode: static
          tenants_file: {sidecar}
          api_keys:
            acme: inline-key
        tenants:
          acme:
            max_concurrent: 2
        """,
    )
    monkeypatch.setenv("PATCHVEC_AUTH__API_KEYS__acme", "env-key")
    monkeypatch.setenv("PATCHVEC_TENANTS__acme__MAX_CONCURRENT", "3")

    cfg = Config(path=config_path)

    assert cfg.get("auth.api_keys.acme") == "env-key"
    assert cfg.get("tenants.acme.max_concurrent") == 3


def test_tenants_sidecar_only_overlays_tenant_keys(tmp_path):
    sidecar = tmp_path / "tenants.yml"
    _write(
        sidecar,
        """
        auth:
          mode: none
          api_keys:
            acme: sidecar-key
        search:
          max_concurrent: 1
        tenants:
          acme:
            max_concurrent: 4
        """,
    )

    config_path = tmp_path / "config.yml"
    _write(
        config_path,
        f"""
        auth:
          mode: static
          tenants_file: {sidecar}
        search:
          max_concurrent: 42
        """,
    )

    cfg = Config(path=config_path)

    assert cfg.get("auth.mode") == "static"
    assert cfg.get("search.max_concurrent") == 42
    assert cfg.get("auth.api_keys.acme") == "sidecar-key"
    assert cfg.get("tenants.acme.max_concurrent") == 4
