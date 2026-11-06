import argparse
import asyncio
import logging
import signal
from uuid import uuid4

from agentos_core.config import Settings
from agentos_core.queue import TaskQueue
from agentos_core.scheduler import dispatch_once
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.worker.app.runner import Worker

logger = logging.getLogger(__name__)


async def pause(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def serve(role: str) -> None:
    settings = Settings()
    engine = create_async_engine(
        str(settings.database_url), pool_pre_ping=True, connect_args={"timeout": 5}
    )
    redis = Redis.from_url(
        str(settings.redis_url), socket_connect_timeout=2, socket_timeout=3, decode_responses=True
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    queue = TaskQueue(redis, settings.redis_queue_key)
    worker = Worker(sessions, queue, worker_id=f"worker-{uuid4().hex}")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    logger.info("Starting %s%s", role, f" {worker.worker_id}" if role == "worker" else "")
    try:
        while not stop.is_set():
            try:
                if role == "dispatcher":
                    count = await dispatch_once(
                        sessions,
                        queue,
                        batch_size=settings.dispatch_batch_size,
                        redispatch_seconds=settings.redispatch_seconds,
                    )
                    if count:
                        logger.info("Dispatched %s queued task(s)", count)
                    await pause(stop, settings.dispatch_interval_seconds)
                else:
                    await worker.run_once()
            except Exception as exc:
                logger.error(
                    "%s cycle failed (%s); retrying in 2 seconds", role, type(exc).__name__
                )
                await pause(stop, 2)
    finally:
        await redis.aclose()
        await engine.dispose()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
        logger.info("Stopped %s", role)


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentOS deterministic worker and dispatcher")
    parser.add_argument("role", choices=["worker", "dispatcher"])
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(serve(args.role))


if __name__ == "__main__":
    main()
