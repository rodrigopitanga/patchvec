# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from pave.routes.admin import build_admin_router
from pave.routes.collections import build_collections_router
from pave.routes.documents import build_documents_router
from pave.routes.health import build_health_router
from pave.routes.search import build_search_router

__all__ = [
    "build_admin_router",
    "build_collections_router",
    "build_documents_router",
    "build_health_router",
    "build_search_router",
]
