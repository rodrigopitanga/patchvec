# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import os
import re
import yaml
from pathlib import Path
from typing import Any, Dict
from dotenv import load_dotenv

load_dotenv()

DEFAULT_CONFIG_PATH = os.environ.get("PATCHVEC_CONFIG", "./config.yml")
ENV_PREFIX = "PATCHVEC_"

DEFAULTS = {
  "data_dir": "./data",
  "auth": {"mode": "none", "api_keys": {}, "tenants_file": None},
}

# ---------------- utils ----------------

def _deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        elif v is not None:
            out[k] = v
    return out

def _coerce(s: str) -> Any:
    if isinstance(s, str):
        low = s.lower()
        if low in {"true", "false"}:
            return low == "true"
        try:
            if s.isdigit():
                return int(s)
            return float(s)
        except Exception:
            return s
    return s

_ENV_PATTERN = re.compile(r"\$\{([^}:|]+)(?:\|([^}]*))?\}")

def _subst_env(value: Any) -> Any:
    """
    Replace ${VAR} or ${VAR|default} in strings.
    Returns non-strings unchanged.
    """
    if not isinstance(value, str):
        return value

    def repl(m: re.Match) -> str:
        key = m.group(1)
        default = m.group(2) if m.group(2) is not None else ""
        return os.environ.get(key, default)

    return _ENV_PATTERN.sub(repl, value)

def _resolve_env_in_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _resolve_env_in_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_in_obj(v) for v in obj]
    return _subst_env(obj)

def _env_to_dict(prefix: str = ENV_PREFIX) -> Dict[str, Any]:
    """
    Build nested dict from env vars like:
      PATCHVEC_AUTH__MODE=static  -> {"auth": {"mode": "static"}}
      PATCHVEC_SERVER__PORT=8081  -> {"server": {"port": 8081}}
    """
    envmap: Dict[str, Any] = {}
    for k, v in os.environ.items():
        if not k.startswith(prefix):
            continue
        path = k[len(prefix):].lower().split("__")
        cur = envmap
        for part in path[:-1]:
            cur = cur.setdefault(part, {})
        cur[path[-1]] = _coerce(v)
    return envmap

def _load_yaml(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if p.is_file():
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data
    return {}

# ---------------- loader ----------------

def load_config(path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    # 1) Base from file (if any)
    file_cfg: Dict[str, Any] = _load_yaml(path)

    # 2) Expand ${ENV} placeholders in file config
    file_cfg = _resolve_env_in_obj(file_cfg)

    # 3) Optionally load tenants file and deep-merge (overrides inline api_keys)
    tenants_file = None
    try:
        tenants_file = file_cfg.get("auth", {}).get("tenants_file")
    except Exception:
        tenants_file = None

    if tenants_file:
        tcfg = _load_yaml(tenants_file)
        tcfg = _resolve_env_in_obj(tcfg)
        # Deep-merge entire tcfg under root (covers `auth.api_keys` and any other overrides)
        file_cfg = _deep_merge(file_cfg, tcfg)

    # 4) Env overlay (highest precedence)
    env_cfg = _env_to_dict()

    # 5) Merge: defaults < file_cfg (with tenants merged) < env_cfg
    merged = _deep_merge(DEFAULTS, file_cfg)
    merged = _deep_merge(merged, env_cfg)

    return merged

# --------------- wrapper ----------------

class Config:
    def __init__(self, data: Dict[str, Any]):
        self._data = data

    def __getattr__(self, item):
        val = self._data.get(item)
        if isinstance(val, dict):
            return Config(val)
        return val

    def get(self, path: str, default: Any = None) -> Any:
        cur: Any = self._data
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def as_dict(self) -> Dict[str, Any]:
        return self._data

CFG = Config(load_config())
