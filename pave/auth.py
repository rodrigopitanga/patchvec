# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from dataclasses import dataclass
from typing import Optional
from fastapi import HTTPException, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .config import CFG

bearer = HTTPBearer(auto_error=False)

@dataclass
class AuthContext:
    tenant: str | None
    is_admin: bool

def auth_ctx(credentials: HTTPAuthorizationCredentials | None = Security(bearer)) -> AuthContext:
    mode = (CFG.auth.mode or "none").lower().strip()

    if mode == "none":
        # open mode: treat as admin; single-tenant deployments stay simple
        return AuthContext(tenant=CFG.auth.default_access_tenant, is_admin=True)

    if mode == "static":
        token = credentials.credentials.strip() if credentials else None
        if not token:
            raise HTTPException(status_code=401, detail="missing or invalid authorization header")

        # admin/global
        if CFG.auth.global_key and token == str(CFG.auth.global_key):
            return AuthContext(tenant=CFG.default_acess_tenant, is_admin=True)

        # per-tenant keys
        api_keys = CFG.get("auth.api_keys", {}) or {}
        for t, expected in api_keys.items():
            if token == str(expected):
                return AuthContext(tenant=t, is_admin=False)

        raise HTTPException(status_code=403, detail="forbidden")

    raise HTTPException(status_code=500, detail=f"unknown auth mode: {mode}")

def authorize_tenant(tenant: str, ctx: AuthContext = Depends(auth_ctx)) -> AuthContext:
    if ctx.is_admin or ctx.tenant == tenant:
        return ctx
    raise HTTPException(status_code=403, detail="forbidden (tenant mismatch)")
