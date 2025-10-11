# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
import os, re, yaml, threading
from pathlib import Path
from typing import Any, Dict
from dotenv import load_dotenv

load_dotenv()

_ENV_PREFIX = "PATCHVEC_"

_DEFAULT_CONFIG_PATH = os.environ.get(_ENV_PREFIX + "CONFIG", "./config.yml")

_DEFAULTS = {
    "data_dir": "./data",
    "auth": {"mode": "none", "api_keys": {}, "tenants_file": None},
    "vector_store": {"type": "default"},
}

_ENV_PATTERN = re.compile(r"\$\{([^}:|]+)(?:\|([^}]*))?\}")

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

def _subst_env(value: Any) -> Any:
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

def _env_to_dict(prefix: str = _ENV_PREFIX) -> Dict[str, Any]:
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
            return yaml.safe_load(f) or {}
    return {}

# --------------- singleton wrapper ----------------
class Config:
    """
    Single backing dict; thread-safe. Can be constructed from a file path
    or from a pre-built dict. `get(path, default)` persists default.
    """
    def __init__(
            self,
            data: Dict[str, Any] | None = None,
            path: str | Path | None = None):
        self._lock = threading.RLock()
        if data is None:
            data = self._load_dict(path or _DEFAULT_CONFIG_PATH)
        self._cfg: Dict[str, Any] = dict(data)
        self._data = self._cfg  # back-compat alias for old tests

    # --- main loader, now a static/class member ---
    @staticmethod
    def _load_dict(path: str | Path) -> Dict[str, Any]:
        file_cfg = _resolve_env_in_obj(_load_yaml(path))
        tenants_file = file_cfg.get("auth", {}).get("tenants_file") \
            if isinstance(file_cfg.get("auth"), dict) else None
        if tenants_file:
            tcfg = _resolve_env_in_obj(_load_yaml(tenants_file))
            file_cfg = _deep_merge(file_cfg, tcfg)
        env_cfg = _env_to_dict()
        return _deep_merge(_deep_merge(_DEFAULTS, file_cfg), env_cfg)

    # -------- path ops --------
    def _get_from(self, store: Dict[str, Any], path: str):
        cur: Any = store
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur

    def _set_into(self, store: Dict[str, Any], path: str, value: Any) -> None:
        cur = store
        parts = path.split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value

    # -------- public API --------
    def get(self, path: str, default: Any = None) -> Any:
        with self._lock:
            val = self._get_from(self._cfg, path)
            if val is not None:
                return val
            if default is not None:
                # persist default on first read (previous behavior)
                self._set_into(self._cfg, path, default)
                return default
            return None

    def set(self, path: str, value: Any) -> None:
        with self._lock:
            self._set_into(self._cfg, path, value)

    def as_dict(self) -> Dict[str, Any]:
        with self._lock:
            # shallow copy is enough for read-only views in tests/health
            return _deep_merge({}, self._cfg)

    def snapshot(self) -> Dict[str, Any]:
        return self.as_dict()

    # replace all config in place (keeps object identity for back-compat)
    def replace(self, data: Dict[str, Any] | None = None,
                path: str | Path | None = None) -> None:
        fresh = Config(data=data, path=path)
        with self._lock:
            self._cfg.clear()
            self._cfg.update(fresh._cfg)
            self._data = self._cfg  # keep the back-compat alias valid

    # attribute sugar (cfg.instance_name, cfg.auth, ...)
    def __getattr__(self, item):
        with self._lock:
            v = self._cfg.get(item)
            if isinstance(v, dict):
                # lightweight view (shares the same store via a child Config)
                child = Config({})
                # point child to the same backing dict (no copy)
                child._cfg = v
                return child
            return v

# --- singleton access (API + CLI + tests share this) ---
_CFG_SINGLETON = Config()

def get_cfg() -> Config:
    return _CFG_SINGLETON

def reload_cfg(path: str | None = None) -> Config:
    # hard reload from disk/env; keep the same object for back-compat
    _CFG_SINGLETON.replace(path=path)
    return _CFG_SINGLETON

CFG = _CFG_SINGLETON
