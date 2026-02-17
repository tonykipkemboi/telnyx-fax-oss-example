from __future__ import annotations

from fastapi import FastAPI, Request

from app.api.routes import router as api_router
from app.config import Settings, get_settings
from app.db import Database
from app.services.fax_provider import FaxProvider
from app.services.rate_limit import SlidingWindowRateLimiter
from app.services.storage_backend import create_storage_backend


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()

    if active_settings.is_production and active_settings.app_secret_key == "dev-insecure-change-me":
        raise RuntimeError("Set TELNYX_FAX_APP_SECRET_KEY for production deployments")

    database = Database(active_settings)
    if active_settings.auto_create_schema:
        database.init_db()

    app = FastAPI(title=active_settings.app_name)

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    app.state.settings = active_settings
    app.state.database = database
    app.state.rate_limiter = SlidingWindowRateLimiter()
    app.state.fax_provider = FaxProvider(active_settings)
    app.state.storage_backend = create_storage_backend(active_settings)

    app.include_router(api_router)
    return app


app = create_app()
