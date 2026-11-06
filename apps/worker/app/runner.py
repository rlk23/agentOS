import asyncio
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from agentos_core.contracts import TaskStatus
from agentos_core.queue import TaskQueue
from agentos_core.scheduler import (
    SessionFactory,
    TaskClaim,
    claim_task,
    finish_task,
    record_progress,
)

from apps.worker.app.executor import ProgressReporter, execute_demo

Executor = Callable[[TaskClaim, ProgressReporter], Awaitable[dict]]
logger = logging.getLogger(__name__)


class Worker:
    def __init__(
        self,
        sessions: SessionFactory,
        queue: TaskQueue,
        worker_id: str,
        executor: Executor = execute_demo,
    ):
        self.sessions = sessions
        self.queue = queue
        self.worker_id = worker_id
        self.executor = executor

    async def run_once(self, *, block: bool = True) -> bool:
        task_id = await self.queue.dequeue(block=block)
        if task_id is None:
            return False
        await self.run_task(task_id)
        return True

    async def run_task(self, task_id: UUID) -> bool:
        claim = await claim_task(self.sessions, task_id, self.worker_id)
        if claim is None:
            return False
        logger.info("Claimed task %s (attempt %s)", claim.id, claim.attempt)

        async def report(message: str) -> None:
            if not await record_progress(self.sessions, claim, message):
                raise RuntimeError("Task ownership lost")

        deadline = asyncio.timeout(claim.max_runtime_seconds)
        try:
            async with deadline:
                result = await self.executor(claim, report)
        except Exception as exc:
            # Do not persist arbitrary exception text that may contain credentials.
            status = TaskStatus.TIMED_OUT if deadline.expired() else TaskStatus.FAILED
            error = (
                "Task runtime limit exceeded"
                if deadline.expired()
                else f"Deterministic job failed ({type(exc).__name__})"
            )
            logger.error("Task %s: %s", claim.id, error)
            await finish_task(self.sessions, claim, status, error=error)
        else:
            await finish_task(self.sessions, claim, TaskStatus.SUCCEEDED, result=result)
        return True
