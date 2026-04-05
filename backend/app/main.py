from contextlib import asynccontextmanager

import sentry_sdk
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware.rate_limit import RateLimitMiddleware
from app.api.middleware.security_headers import SecurityHeadersMiddleware
from app.api.v1.router import api_v1_router
from app.data.seeder import seed_module_units
from app.domain.services.platform_settings_service import SettingsCache
from app.infrastructure.config.settings import settings
from app.infrastructure.persistence.database import async_session_factory


def _scrub_pii(event, hint):
    """Strip PII from Sentry events for GDPR compliance."""
    if "user" in event:
        event["user"].pop("ip_address", None)
        event["user"].pop("email", None)
    request = event.get("request", {})
    headers = request.get("headers", {})
    for sensitive in ("Authorization", "Cookie", "X-Forwarded-For"):
        headers.pop(sensitive, None)
    return event


if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        release="santepublique-aof-backend@0.1.0",
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        send_default_pii=False,
        before_send=_scrub_pii,
    )

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
        if settings.app_env == "development"
        else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log = structlog.get_logger(__name__)
    try:
        async with async_session_factory() as session:
            await seed_module_units(session)
    except Exception as exc:
        log.warning("module_units seed skipped", error=str(exc))

    try:
        SettingsCache.instance().refresh()
    except Exception as exc:
        log.warning("settings_cache load skipped", error=str(exc))

    yield


app = FastAPI(
    title="Sira API",
    description="Adaptive bilingual learning platform for public health in West Africa",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# Add rate limiting middleware
app.add_middleware(RateLimitMiddleware, global_rate_limit=100)


# Root health check
@app.get("/health")
async def root_health() -> dict[str, str]:
    return {"status": "healthy", "service": "santepublique-aof-api"}


# API v1 routes
app.include_router(api_v1_router, prefix=settings.api_v1_prefix)
