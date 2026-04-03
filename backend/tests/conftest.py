import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.domain.models  # noqa: F401 — import all models so Base.metadata is fully populated
from app.api.deps import get_db, get_db_session
from app.domain.models import Base
from app.domain.services.jwt_auth_service import JWTAuthService
from app.infrastructure.config.settings import settings
from app.main import app

# ---------------------------------------------------------------------------
# Simple client (no DB) — for health checks and endpoints that don't hit DB
# ---------------------------------------------------------------------------


@pytest.fixture
async def client() -> AsyncClient:
    """Test client without database override. Use for health/smoke tests."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Database fixtures — for integration tests that need a real DB session
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
async def test_engine():
    """Create all tables before any test and tear them down after the session.

    Autouse ensures that tests using ``api_client`` (which bypasses the
    db_session override and hits the app's own engine on the same DB URL)
    always find the schema ready.
    """
    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine):
    """Per-test database session that rolls back after each test."""
    session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def auth_headers():
    """JWT auth headers using the actual JWTAuthService."""
    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(user_id="test-user-uuid", email="test@example.com")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def authenticated_client(db_session):
    """Test client with DB override and auth headers. Use for integration tests."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_db_session] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
