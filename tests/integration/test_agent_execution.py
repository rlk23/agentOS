import asyncio
import json
from uuid import UUID

import httpx
import pytest
from agentos_core.config import Settings
from agentos_core.scheduler import dispatch_once
from openai import AsyncOpenAI

from apps.worker.app import agent
from apps.worker.app.runner import Worker
from apps.worker.app.sandbox import docker

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


async def submit_agent(client):
    response = await client.post(
        "/tasks",
        json={
            "prompt": "Fix the failing addition test and explain the change",
            "repository": "https://github.com/example/demo",
            "execution_mode": "agent",
        },
    )
    assert response.status_code == 201
    return UUID(response.json()["task_id"])


async def test_agent_requires_key_without_falling_back_to_demo(client, sessions, queue):
    task_id = await submit_agent(client)
    settings = Settings(_env_file=None, openai_api_key=None)
    worker = Worker(
        sessions,
        queue,
        "agent-worker",
        agent_executor=agent.create_agent_executor(sessions, settings),
    )
    await worker.run_task(task_id)
    task = (await client.get(f"/tasks/{task_id}")).json()
    assert task["execution_mode"] == "agent"
    assert task["status"] == "FAILED"
    assert "OPENAI_API_KEY" in task["error"]
    assert task["result"] is None


async def test_unconfigured_worker_cannot_silently_run_agent_as_demo(client, sessions, queue):
    task_id = await submit_agent(client)
    await Worker(sessions, queue, "worker").run_task(task_id)
    task = (await client.get(f"/tasks/{task_id}")).json()
    assert task["status"] == "FAILED"
    assert "not configured" in task["error"]


@pytest.mark.sandbox
async def test_api_agent_edits_repository_in_real_container(
    client, sessions, queue, repository_archive, monkeypatch
):
    calls = [
        ("run_command", {"command": "python -m pytest -q"}),
        ("read_file", {"path": "calculator.py"}),
        ("write_file", {"path": "calculator.py", "content": "def add(a, b):\n    return a + b\n"}),
        ("run_command", {"command": "python -m pytest -q"}),
    ]
    requests = []
    names = []

    async def fake_download(url):
        assert url == "https://github.com/example/demo"
        return repository_archive

    async def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        index = len(requests) - 1
        if index < len(calls):
            name, arguments = calls[index]
            output = [
                {
                    "type": "function_call",
                    "id": f"fc_{index}",
                    "call_id": f"call_{index}",
                    "name": name,
                    "arguments": json.dumps(arguments),
                }
            ]
        else:
            outputs = [
                json.loads(item["output"])
                for item in payload["input"]
                if item.get("type") == "function_call_output"
            ]
            assert outputs[0]["exit_code"] == 1
            assert "1 failed" in outputs[0]["stdout"]
            assert outputs[-1]["exit_code"] == 0
            assert "1 passed" in outputs[-1]["stdout"]
            output = [
                {
                    "type": "message",
                    "id": "msg_final",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Fixed addition; 1 test passed.",
                            "annotations": [],
                        }
                    ],
                }
            ]
        return httpx.Response(
            200,
            json={
                "id": f"resp_{index}",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "gpt-4.1-mini",
                "output": output,
                "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
            },
        )

    class TrackingSandbox(agent.Sandbox):
        async def __aenter__(self):
            names.append(self.name)
            return await super().__aenter__()

    def fake_openai(**kwargs):
        return AsyncOpenAI(
            api_key="test-only",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

    monkeypatch.setattr(agent, "download_repository", fake_download)
    monkeypatch.setattr(agent, "AsyncOpenAI", fake_openai)
    monkeypatch.setattr(agent, "Sandbox", TrackingSandbox)
    settings = Settings(_env_file=None, openai_api_key="test-only")
    task_id = await submit_agent(client)
    assert await dispatch_once(sessions, queue) == 1
    worker = Worker(
        sessions,
        queue,
        "agent-worker",
        agent_executor=agent.create_agent_executor(sessions, settings),
    )
    assert await worker.run_once(block=False)
    task = (await client.get(f"/tasks/{task_id}")).json()
    assert task["status"] == "SUCCEEDED", task["error"]
    assert task["result"]["summary"] == "Fixed addition; 1 test passed."
    assert "+    return a + b" in task["result"]["changes"]["patch"]
    assert task["result"]["tool_calls"] == 4
    assert task["attempts"] == 1
    events = (await client.get(f"/tasks/{task_id}/events")).json()
    assert len([event for event in events if event["type"] == "TOOL_CALL"]) == 4
    results = [event["data"]["output"] for event in events if event["type"] == "TOOL_RESULT"]
    assert "1 failed" in results[0]["stdout"]
    assert "1 passed" in results[-1]["stdout"]
    assert any(event["type"] == "AGENT_SUMMARY" for event in events)
    for name in names:
        assert (await docker("inspect", name)).exit_code != 0


@pytest.mark.sandbox
@pytest.mark.live
async def test_live_openai_repairs_small_repository(
    client, sessions, queue, repository_archive, monkeypatch
):
    settings = Settings()
    assert settings.openai_api_key and settings.openai_api_key.get_secret_value().strip(), (
        "Set OPENAI_API_KEY in .env before running the explicit live test"
    )

    async def fixture_download(url):
        return repository_archive

    # Use a fixed small repository so the live test does not depend on third-party changes.
    monkeypatch.setattr(agent, "download_repository", fixture_download)
    task_id = await submit_agent(client)
    worker = Worker(
        sessions,
        queue,
        "live-agent-worker",
        agent_executor=agent.create_agent_executor(sessions, settings),
    )
    await worker.run_task(task_id)
    task = (await client.get(f"/tasks/{task_id}")).json()
    assert task["status"] == "SUCCEEDED", task["error"]
    assert task["result"]["changes"]["patch"]
    events = (await client.get(f"/tasks/{task_id}/events")).json()
    assert any(
        event["type"] == "TOOL_RESULT" and "1 passed" in str(event["data"].get("output", {}))
        for event in events
    )


async def test_agent_runtime_cap_is_reported_as_timeout(client, sessions, queue, monkeypatch):
    async def blocked_download(url):
        await asyncio.Event().wait()

    monkeypatch.setattr(agent, "download_repository", blocked_download)
    settings = Settings(_env_file=None, openai_api_key="test-only", agent_max_runtime_seconds=1)
    task_id = await submit_agent(client)
    worker = Worker(
        sessions, queue, "worker", agent_executor=agent.create_agent_executor(sessions, settings)
    )
    await worker.run_task(task_id)
    task = (await client.get(f"/tasks/{task_id}")).json()
    assert task["status"] == "TIMED_OUT"
    assert task["error"] == "Agent runtime limit exceeded"
