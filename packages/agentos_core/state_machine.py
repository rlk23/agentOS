from agentos_core.contracts import TaskStatus

# Only transitions supported by the current worker. Retry and cancellation are deferred.
ALLOWED_TRANSITIONS = {
    TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING}),
    TaskStatus.RUNNING: frozenset({TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.TIMED_OUT}),
}


def require_transition(source: TaskStatus, target: TaskStatus) -> None:
    if target not in ALLOWED_TRANSITIONS.get(source, ()):
        raise ValueError(f"Invalid task transition: {source} -> {target}")
