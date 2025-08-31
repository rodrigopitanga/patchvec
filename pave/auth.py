# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

# pave/auth.py

from dataclasses import dataclass
from typing import Optional, Dict
from fastapi import HTTPException, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from . import config as cfg

bearer = HTTPBearer(auto_error=False)

@dataclass
class AuthContext:
    tenant: Optional[str]
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
        api_keys: Dict[str, str] = cfg.CFG.get("auth.api_keys", {}) or {}
        for t, expected in api_keys.items():
            if token == str(expected):
                return AuthContext(tenant=t, is_admin=False)

        _raise_403()

    raise HTTPException(status_code=500, detail=f"unknown auth mode: {mode}")

def authorize_tenant(tenant: str, ctx: AuthContext = Depends(auth_ctx)) -> AuthContext:
    if ctx.is_admin or ctx.tenant == tenant:
        return ctx
    _raise_403()
