import logging
from time import time
from uuid import UUID

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class TaskQueue:
    """Redis delivery hints, deduplicated while waiting. PostgreSQL owns task state."""

    def __init__(self, redis: Redis, key: str = "agentos:tasks"):
        self.redis = redis
        self.key = key

    async def enqueue(self, task_id: UUID) -> None:
        await self.redis.zadd(self.key, {str(task_id): time()}, nx=True)

    async def dequeue(self, *, block: bool = True) -> UUID | None:
        if block:
            item = await self.redis.bzpopmin(self.key, timeout=1)
            raw = item[1] if item else None
        else:
            items = await self.redis.zpopmin(self.key)
            raw = items[0][0] if items else None
        if raw is None:
            return None
        try:
            return UUID(raw.decode() if isinstance(raw, bytes) else raw)
        except (ValueError, TypeError):
            logger.warning("Discarding malformed task ID from delivery queue")
            return None
