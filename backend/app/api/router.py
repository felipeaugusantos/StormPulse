"""Aggregate API router.

Health lives at the root (``/health``, ``/ready``) for orchestrators.
Versioned domain routers (auth, users, locations, storms, alerts) are mounted
under the API v1 prefix in later phases.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.alerts.router import router as alerts_router
from app.api import health
from app.auth.router import router as auth_router
from app.locations.router import router as locations_router
from app.public.router import router as public_router
from app.storms.router import router as storms_router
from app.users.router import router as users_router

root_router = APIRouter()
root_router.include_router(health.router)

# Versioned domain routers (mounted under settings.api_v1_prefix).
v1_router = APIRouter()
v1_router.include_router(auth_router, prefix="/auth")
v1_router.include_router(users_router, prefix="/users")
v1_router.include_router(locations_router, prefix="/locations")
v1_router.include_router(storms_router, prefix="/storms")
v1_router.include_router(alerts_router, prefix="/alerts")

# Unauthenticated "visitor mode" endpoints (FASE 15) — mounted separately by
# main.py under /public with its own (stricter) rate limit, not included
# here, so it doesn't inherit v1_router's dependency list at import time.
public_v1_router = APIRouter()
public_v1_router.include_router(public_router, prefix="/public")
