"""All HTTP routes, mounted under /api.

Each feature module defines its own `router` with a prefix and tags,
and is included here, e.g. /api/health, /api/uploads, /api/jobs.
"""

from fastapi import APIRouter

from api.routes import health, uploads

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(uploads.router)
