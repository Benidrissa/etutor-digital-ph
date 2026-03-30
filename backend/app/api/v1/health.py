import time
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.infrastructure.cache.redis import redis_client
from app.infrastructure.persistence.database import async_session_factory

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Basic health check endpoint."""
    return {"status": "healthy", "service": "santepublique-aof-api"}


@router.get("/health/detailed")
async def detailed_health() -> dict[str, Any]:
    """Detailed health check including Redis, database, and Celery status."""
    start_time = time.time()
    health_status = {
        "status": "healthy",
        "service": "santepublique-aof-api",
        "timestamp": int(time.time()),
        "checks": {},
    }

    # Check database connection
    try:
        async with async_session_factory() as session:
            result = await session.execute(text("SELECT 1"))
            result.fetchone()

        health_status["checks"]["database"] = {
            "status": "healthy",
            "message": "PostgreSQL connection OK",
        }
    except Exception as exc:
        logger.error("Database health check failed", exception=str(exc))
        health_status["checks"]["database"] = {
            "status": "unhealthy",
            "message": f"Database error: {str(exc)}",
        }
        health_status["status"] = "unhealthy"

    # Check Redis connection
    try:
        await redis_client.ping()
        redis_info = await redis_client.info("memory")

        health_status["checks"]["redis"] = {
            "status": "healthy",
            "message": "Redis connection OK",
            "memory_usage_mb": round(redis_info.get("used_memory", 0) / 1024 / 1024, 2),
            "connected_clients": redis_info.get("connected_clients", 0),
        }
    except Exception as exc:
        logger.error("Redis health check failed", exception=str(exc))
        health_status["checks"]["redis"] = {
            "status": "unhealthy",
            "message": f"Redis error: {str(exc)}",
        }
        health_status["status"] = "unhealthy"

    # Check Celery workers (by checking Redis for worker heartbeat)
    try:
        # Check if any Celery workers are active
        celery_active_key = "celery:worker:*"
        worker_keys = []
        async for key in redis_client.scan_iter(match=celery_active_key):
            worker_keys.append(key)

        health_status["checks"]["celery"] = {
            "status": "healthy" if worker_keys else "warning",
            "message": f"Found {len(worker_keys)} active workers",
            "active_workers": len(worker_keys),
        }

        # If no workers but Redis is healthy, it's a warning not error
        if not worker_keys and health_status["status"] == "healthy":
            health_status["status"] = "degraded"

    except Exception as exc:
        logger.error("Celery health check failed", exception=str(exc))
        health_status["checks"]["celery"] = {
            "status": "unhealthy",
            "message": f"Celery check error: {str(exc)}",
        }

    # Calculate response time
    health_status["response_time_ms"] = round((time.time() - start_time) * 1000, 2)

    # Return appropriate HTTP status
    if health_status["status"] == "unhealthy":
        raise HTTPException(status_code=503, detail=health_status)

    return health_status


@router.get("/health/redis")
async def redis_health() -> dict[str, Any]:
    """Redis-specific health check and statistics."""
    try:
        start_time = time.time()

        # Basic ping
        await redis_client.ping()

        # Get Redis info
        info = await redis_client.info()
        memory_info = await redis_client.info("memory")

        return {
            "status": "healthy",
            "ping_time_ms": round((time.time() - start_time) * 1000, 2),
            "redis_version": info.get("redis_version"),
            "connected_clients": info.get("connected_clients", 0),
            "used_memory_mb": round(memory_info.get("used_memory", 0) / 1024 / 1024, 2),
            "memory_usage_percent": memory_info.get("used_memory_rss_human", "N/A"),
            "keyspace": {
                db: stats
                for db, stats in info.items()
                if db.startswith("db") and isinstance(stats, dict)
            },
        }
    except Exception as exc:
        logger.error("Redis health check failed", exception=str(exc))
        raise HTTPException(
            status_code=503, detail={"status": "unhealthy", "message": f"Redis error: {str(exc)}"}
        )
