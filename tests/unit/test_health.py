import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.app.core.database import get_session
from apps.api.app.main import create_app

pytestmark = pytest.mark.anyio


async def test_health_returns_503_when_database_unavailable():
    class UnavailableSession:
        async def execute(self, statement):
            raise ConnectionError("private database connection details")

    async def unavailable_session():
        yield UnavailableSession()

    app = create_app()
    app.dependency_overrides[get_session] = unavailable_session
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


@pytest.mark.parametrize("path", ["/tasks", "/tasks/00000000-0000-0000-0000-000000000000"])
async def test_no_task_update_endpoint(path):
    # Tasks can only be created as QUEUED; callers cannot set lifecycle state.
    app = create_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.patch(path, json={"status": "SUCCEEDED"})).status_code == 405
