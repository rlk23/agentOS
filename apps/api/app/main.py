from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from apps.api.app.api.routes import health, tasks
from apps.api.app.core.config import Settings


def create_app(settings: Settings | None = None, *, engine: AsyncEngine | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = engine
        if database is None:
            config = settings or Settings()
            database = create_async_engine(
                str(config.database_url), pool_pre_ping=True, connect_args={"timeout": 5}
            )
        app.state.session_factory = async_sessionmaker(database, expire_on_commit=False)
        try:
            yield
        finally:
            if engine is None:
                await database.dispose()

    application = FastAPI(title="AgentOS", version="0.1.0", lifespan=lifespan)
    application.include_router(health.router)
    application.include_router(tasks.router)
    return application


app = create_app()
