from collections.abc import Awaitable, Callable
from hashlib import sha256

from agentos_core.scheduler import TaskClaim

ProgressReporter = Callable[[str], Awaitable[None]]


async def execute_demo(claim: TaskClaim, report: ProgressReporter) -> dict:
    """Trusted, bounded in-process job. Never interpret prompts or access repositories."""
    await report("Inspecting task input; no repository access or command execution")
    result = {
        "job": "deterministic_demo",
        "prompt_sha256": sha256(claim.prompt.encode()).hexdigest(),
        "character_count": len(claim.prompt),
        "word_count": len(claim.prompt.split()),
        "repository": claim.repository,
    }
    await report("Input summary computed")
    return result
