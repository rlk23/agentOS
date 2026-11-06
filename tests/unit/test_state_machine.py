import pytest
from agentos_core.contracts import TaskStatus
from agentos_core.state_machine import require_transition


@pytest.mark.parametrize(
    "terminal",
    [TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.TIMED_OUT],
)
def test_terminal_states_cannot_be_restarted(terminal):
    with pytest.raises(ValueError, match="Invalid task transition"):
        require_transition(terminal, TaskStatus.RUNNING)


def test_queued_task_cannot_skip_execution():
    with pytest.raises(ValueError, match="Invalid task transition"):
        require_transition(TaskStatus.QUEUED, TaskStatus.SUCCEEDED)
