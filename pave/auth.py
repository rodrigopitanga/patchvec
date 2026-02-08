# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

# pave/auth.py

from __future__ import annotations
from dataclasses import dataclass
# typing imports removed
from fastapi import HTTPException, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from . import config as cfg

bearer = HTTPBearer(auto_error=False)

@dataclass
class AuthContext:
    tenant: str | None
    is_admin: bool

def _raise_401():
    raise HTTPException(
        status_code=401,
        detail="missing or invalid authorization header",
        headers={"WWW-Authenticate": 'Bearer realm="patchvec", error="invalid_token"'},
    )

def _raise_403():
    raise HTTPException(
        status_code=403,
        detail="forbidden",
        headers={"WWW-Authenticate": 'Bearer realm="patchvec", error="insufficient_scope"'},
    )

def auth_ctx(credentials: HTTPAuthorizationCredentials | None = Security(bearer)) -> AuthContext:
    # read from CFG.get so tests and env overrides work
    mode = str(cfg.CFG.get("auth.mode", "none")).strip().lower()

    if mode == "none":
        # open mode (dev): treat as admin
        return AuthContext(tenant=str(cfg.CFG.get("auth.default_access_tenant", None)), is_admin=True)

    if mode == "static":
        token = credentials.credentials.strip() if credentials and credentials.scheme == "Bearer" else None
        if not token:
            _raise_401()

        # global key
        global_key = cfg.CFG.get("auth.global_key")
        if global_key and token == str(global_key):
            return AuthContext(tenant=None, is_admin=True)

        # per-tenant keys
        api_keys: dict[str, str] = cfg.CFG.get("auth.api_keys", {}) or {}
        for t, expected in api_keys.items():
            if token == str(expected):
                return AuthContext(tenant=t, is_admin=False)

        _raise_403()

    raise HTTPException(status_code=500, detail=f"unknown auth mode: {mode}")

def authorize_tenant(tenant: str, ctx: AuthContext = Depends(auth_ctx)) -> AuthContext:
    if ctx.is_admin or ctx.tenant == tenant:
        return ctx
    _raise_403()


# --- Startup security policy -------------------------------------------------

def _is_dev(cfg) -> bool:
    # check dev flag (CFG or PATCHVEC_DEV)
    return bool(cfg.get("dev", False)) or str(cfg.get("PATCHVEC_DEV", "0")) == "1"

def enforce_policy(cfg) -> None:
    """
    Fail fast if auth is not configured in prod.
    Allow auth=none only in dev mode, force loopback bind.
    """
    mode = str(cfg.get("auth.mode", "none")).strip().lower()
    dev = _is_dev(cfg)

    if mode == "none":
        if not dev:
            raise RuntimeError(
                "auth.mode=none not allowed in production. "
                "Set auth.mode=static with a key or run with PATCHVEC_DEV=1 for dev."
            )
        host = str(cfg.get("server.host", "127.0.0.1")).strip()
        if host not in ("127.0.0.1", "localhost"):
            # enforce loopback in dev
            try:
                cfg._data["server.host"] = "127.0.0.1"
            except Exception:
                pass

    if mode == "static":
        has_global = bool(cfg.get("auth.global_key"))
        has_map = bool(cfg.get("auth.api_keys"))
        if not (has_global or has_map):
            raise RuntimeError(
                "auth.mode=static requires global_key or api_keys"
            )

def resolve_bind(cfg) -> tuple[str, int]:
    # return host/port after policy enforcement
    host = str(cfg.get("server.host", "127.0.0.1"))
    port = int(cfg.get("server.port", 8086))
    return host, port
