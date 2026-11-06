import json
from types import SimpleNamespace

import httpx
import pytest
from agentos_core.config import Settings
from agentos_core.repositories import github_repository
from openai import AsyncOpenAI

from apps.api.app.schemas.task import TaskCreate
from apps.worker.app.agent import AgentError, AgentLimitExceeded, call_tool, run_agent

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b",
        "https://127.0.0.1/a/b",
        "https://github.com.evil.test/a/b",
        "https://token@github.com/a/b",
        "https://github.com/a/b?ref=main",
        "https://github.com/a/b#branch",
        "https://github.com:443/a/b",
        "file:///tmp/repo",
        "https://github.com/a/b/tree/main",
        "https://github.com/a/..",
    ],
)
def test_repository_policy_rejects_unsupported_sources(url):
    with pytest.raises(ValueError):
        github_repository(url)


def test_agent_mode_is_explicit_and_validated():
    payload = {"prompt": "Run tests", "repository": "https://github.com/example/demo"}
    assert TaskCreate(**payload).execution_mode == "demo"
    assert TaskCreate(**payload, execution_mode="agent").execution_mode == "agent"
    with pytest.raises(ValueError):
        TaskCreate(**payload, execution_mode="agent", max_runtime_seconds=601)
    with pytest.raises(ValueError):
        TaskCreate(
            prompt="Run tests", repository="https://internal.test/repo", execution_mode="agent"
        )
    assert github_repository("https://github.com/example/demo.git/") == ("example", "demo")


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("host_shell", '{"command":"echo unsafe"}'),
        ("run_command", "not-json"),
        ("run_command", '{"command":"echo hi","host":true}'),
        ("run_command", '{"command":7}'),
        ("write_file", '{"path":"x"}'),
    ],
)
async def test_invalid_tools_never_execute(name, arguments):
    assert "error" in await call_tool(name, arguments, SimpleNamespace())


def fake_response(output, status="completed"):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": "gpt-4.1-mini",
        "output": output,
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    }


def message(text):
    return {
        "type": "message",
        "id": "msg_test",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


async def test_real_sdk_tool_roundtrip_preserves_call_id_and_uses_no_host_shell():
    requests = []
    events = []

    async def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json=fake_response(
                    [
                        {
                            "type": "function_call",
                            "id": "fc_1",
                            "call_id": "call_1",
                            "name": "read_file",
                            "arguments": '{"path":"README.md"}',
                        }
                    ]
                ),
            )
        outputs = [item for item in payload["input"] if item.get("type") == "function_call_output"]
        assert outputs == [
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": '{"content": "fixture readme"}',
            }
        ]
        return httpx.Response(200, json=fake_response([message("Read the README.")]))

    class StubSandbox:
        async def file_tool(self, action, path):
            assert (action, path) == ("read", "README.md")
            return {"content": "fixture readme"}

    async def emit(*args):
        events.append(args)

    async with AsyncOpenAI(
        api_key="test-secret", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ) as client:
        result = await run_agent(
            client, Settings(_env_file=None), StubSandbox(), "Read README", emit
        )
    assert result["summary"] == "Read the README."
    assert result["tool_calls"] == 1
    assert result["usage"] == {"input_tokens": 20, "output_tokens": 10}
    assert [str(event[0]) for event in events] == ["TOOL_CALL", "TOOL_RESULT", "AGENT_SUMMARY"]
    assert all(r["store"] is False and r["parallel_tool_calls"] is False for r in requests)
    assert "test-secret" not in json.dumps(requests)


@pytest.mark.parametrize("case", ["turn_budget", "tool_budget", "incomplete", "empty_final"])
async def test_model_cannot_bypass_budgets_or_fake_completion(case):
    settings = Settings(_env_file=None, agent_max_turns=1, agent_max_tool_calls=1)
    calls = []

    async def handler(request):
        if case in {"incomplete", "empty_final"}:
            return httpx.Response(
                200, json=fake_response([], "incomplete" if case == "incomplete" else "completed")
            )
        tool = {
            "type": "function_call",
            "id": "fc",
            "call_id": "call",
            "name": "run_command",
            "arguments": '{"command":"true"}',
        }
        return httpx.Response(200, json=fake_response([tool] * (2 if case == "tool_budget" else 1)))

    async def command(script):
        calls.append(script)
        return {"exit_code": 0}

    async def emit(*args):
        pass

    async with AsyncOpenAI(
        api_key="test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ) as client:
        with pytest.raises(AgentLimitExceeded if case.endswith("budget") else AgentError):
            await run_agent(client, settings, SimpleNamespace(run_command=command), "Do work", emit)
    assert len(calls) <= 1
