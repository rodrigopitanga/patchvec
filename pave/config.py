# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
import json
import os, re, threading, logging
from pathlib import Path
from typing import Any

try:  # pragma: no cover - optional dependency guard
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover
    def load_dotenv(*_args, **_kwargs):
        return False

try:  # pragma: no cover - simple import guard
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    class _YamlFallback:
        """Very small subset YAML loader fallback using JSON semantics."""

        @staticmethod
        def safe_load(stream):  # type: ignore[override]
            if hasattr(stream, "read"):
                text = stream.read()
            else:
                text = stream
            if not text:
                return {}
            try:
                return json.loads(text)
            except Exception as exc:  # pragma: no cover - exercised if invalid
                raise RuntimeError(
                    "yaml module not available and fallback JSON parsing failed"
                ) from exc

    yaml = _YamlFallback()  # type: ignore

load_dotenv()

_ENV_PREFIX = "PATCHVEC_"

_DEFAULT_CONFIG_PATH = os.environ.get(_ENV_PREFIX + "CONFIG", "./config.yml")

_DEFAULTS = {
    "data_dir": "./data",
    "auth": {"mode": "none", "api_keys": {}, "tenants_file": None},
    "vector_store": {"type": "default"},
    "ingest": {"max_file_size_mb": 500},
    "server": {"timeout_keep_alive": 75},
}

_ENV_PATTERN = re.compile(r"\$\{([^}:|]+)(?:\|([^}]*))?\}")

# ---------------- utils ----------------
def _deep_merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
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

def _env_to_dict(prefix: str = _ENV_PREFIX) -> dict[str, Any]:
    envmap: dict[str, Any] = {}
    for k, v in os.environ.items():
        if not k.startswith(prefix):
            continue
        path = k[len(prefix):].lower().split("__")
        cur = envmap
        for part in path[:-1]:
            cur = cur.setdefault(part, {})
        cur[path[-1]] = _coerce(v)
    return envmap

def _load_yaml(path: str | Path) -> dict[str, Any]:
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
            data: dict[str, Any] | None = None,
            path: str | Path | None = None):
        self._lock = threading.RLock()
        if data is None:
            data = self._load_dict(path or _DEFAULT_CONFIG_PATH)
        self._cfg: dict[str, Any] = dict(data)
        self._data = self._cfg  # back-compat alias for old tests

    # --- main loader, now a static/class member ---
    @staticmethod
    def _load_dict(path: str | Path) -> dict[str, Any]:
        file_cfg = _resolve_env_in_obj(_load_yaml(path))
        tenants_file = file_cfg.get("auth", {}).get("tenants_file") \
            if isinstance(file_cfg.get("auth"), dict) else None
        if tenants_file:
            tcfg = _resolve_env_in_obj(_load_yaml(tenants_file))
            file_cfg = _deep_merge(file_cfg, tcfg)
        env_cfg = _env_to_dict()
        return _deep_merge(_deep_merge(_DEFAULTS, file_cfg), env_cfg)

    # -------- path ops --------
    def _get_from(self, store: dict[str, Any], path: str):
        cur: Any = store
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur

    def _set_into(self, store: dict[str, Any], path: str, value: Any) -> None:
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

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            # shallow copy is enough for read-only views in tests/health
            return _deep_merge({}, self._cfg)

    def snapshot(self) -> dict[str, Any]:
        return self.as_dict()

    # replace all config in place (keeps object identity for back-compat)
    def replace(self, data: dict[str, Any] | None = None,
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

# --- singleton logger ---
class _ColorFormatter(logging.Formatter):
    """Formatter with ANSI colors for terminal output."""
    COLORS = {
        logging.DEBUG:    "\033[36m",   # cyan
        logging.INFO:     "\033[32m",   # green
        logging.WARNING:  "\033[33m",   # yellow
        logging.ERROR:    "\033[31m",   # red
        logging.CRITICAL: "\033[35m",   # magenta
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"

    def __init__(self, fmt: str, datefmt: str, use_color: bool = True):
        super().__init__(fmt, datefmt)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        if self.use_color:
            color = self.COLORS.get(record.levelno, "")
            # Highlight pave logs with bold
            if record.name.startswith("pave"):
                record.name = f"{self.BOLD}pave{self.RESET}{color}"
            record.levelname = f"{color}{record.levelname}{self.RESET}"
            record.msg = f"{color}{record.msg}{self.RESET}"
        return super().format(record)


def _init_logger() -> logging.Logger:
    """
    Initializes hierarchical logging levels:
      - pave (base) → bold + colored
      - watch namespaces (base -1 → more verbose)
      - quiet namespaces (base +1 → less verbose)
      - all others (base +2)
    """
    import sys
    cfg = get_cfg()
    base_level = getattr(logging, cfg.get("loglevel", "INFO").upper(), logging.INFO)

    def shift(level: int, delta: int) -> int:
        """Moves numeric loglevel by ±10 per step."""
        return min(logging.CRITICAL, max(logging.DEBUG, level + 10 * delta))

    # Configure root logger - set high level to quiet unknown libs
    root = logging.getLogger()
    root.setLevel(shift(base_level, +2))  # Unknown libs are quietest
    root.handlers.clear()

    # Create console handler with colors - allow all through, filter at logger level
    use_color = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.DEBUG)  # Handler allows all, loggers filter
    handler.setFormatter(_ColorFormatter(
        "%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        "%H:%M:%S",
        use_color=use_color
    ))
    root.addHandler(handler)

    # pave logger - our main logger, always at configured level
    pave_log = logging.getLogger("pave")
    pave_log.setLevel(logging.DEBUG if cfg.get("dev", 0) else base_level)

    # Namespaces fixed to DEBUG
    for ns in cfg.get("log.debug", []):
        logging.getLogger(ns).setLevel(logging.DEBUG)

    # Namespaces that should be more verbose (e.g., txtai)
    for ns in cfg.get("log.watch", []):
        logging.getLogger(ns).setLevel(shift(base_level, -1))

    # Namespaces that should be quieter
    for ns in cfg.get("log.quiet", ["uvicorn", "uvicorn.access", "uvicorn.error",
                                     "fastapi", "sqlalchemy", "urllib3", "httpx"]):
        logging.getLogger(ns).setLevel(shift(base_level, +1))

    return pave_log

_LOGGER_SINGLETON = _init_logger()

def get_logger() -> logging.Logger:
    """Returns global PatchVec logger"""
    return _LOGGER_SINGLETON

LOG = _LOGGER_SINGLETON
