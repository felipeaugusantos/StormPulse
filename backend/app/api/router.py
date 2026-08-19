"""Aggregate API router.

Health lives at the root (``/health``, ``/ready``) for orchestrators.
Versioned domain routers (auth, users, locations, storms, alerts) are mounted
under the API v1 prefix in later phases.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import health

root_router = APIRouter()
root_router.include_router(health.router)

# Domain routers land here from FASE 3 onward, e.g.:
#   from app.auth.router import router as auth_router
#   v1_router.include_router(auth_router, prefix="/auth")
v1_router = APIRouter()
