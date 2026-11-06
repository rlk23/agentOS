import asyncio
import io
import json
import tarfile

import pytest
from agentos_core.config import Settings

from apps.worker.app.sandbox import CommandTimedOut, Sandbox, SandboxError, docker

pytestmark = [pytest.mark.anyio, pytest.mark.sandbox]


async def test_isolated_files_tests_edits_and_patch(repository_archive, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-enter-container")
    marker = tmp_path / "host-marker"
    async with Sandbox(Settings(_env_file=None), 60) as sandbox:
        name = sandbox.name
        await sandbox.prepare(repository_archive)
        info = json.loads((await docker("inspect", name)).stdout)[0]
        assert info["HostConfig"]["NetworkMode"] == "none"
        assert info["HostConfig"]["ReadonlyRootfs"] is True
        assert info["HostConfig"]["CapDrop"] == ["ALL"]
        assert "no-new-privileges" in info["HostConfig"]["SecurityOpt"]
        assert info["HostConfig"]["Memory"] == 512 * 1024**2
        assert info["HostConfig"]["MemorySwap"] == 512 * 1024**2
        assert info["HostConfig"]["NanoCpus"] == 1_000_000_000
        assert info["HostConfig"]["PidsLimit"] == 64
        assert not info["HostConfig"]["Binds"]
        assert not any(mount["Type"] == "bind" for mount in info["Mounts"])
        identity = await sandbox.run_command(
            "id -u; printenv OPENAI_API_KEY; test -S /var/run/docker.sock"
        )
        assert identity["stdout"].strip() == "1000"
        assert "must-not-enter-container" not in str(identity)
        assert (await sandbox.run_command("touch /root/not-allowed"))["exit_code"] != 0
        assert (await sandbox.run_command(f"touch '{marker}'"))["exit_code"] != 0
        assert not marker.exists()
        network = await sandbox.run_command(
            "python -c 'import socket; socket.create_connection((\"1.1.1.1\",443),1)'"
        )
        assert network["exit_code"] != 0
        failed = await sandbox.run_command("python -m pytest -q")
        assert failed["exit_code"] == 1 and "1 failed" in failed["stdout"]
        assert "return a - b" in (await sandbox.file_tool("read", "calculator.py"))["content"]
        await sandbox.file_tool("write", "calculator.py", "def add(a, b):\n    return a + b\n")
        passed = await sandbox.run_command("python -m pytest -q")
        assert passed["exit_code"] == 0 and "1 passed" in passed["stdout"]
        changes = await sandbox.changes()
        assert "+    return a + b" in changes["patch"]
        assert "-    return a - b" in changes["patch"]
        assert changes["truncated"] is False
        assert "error" in await sandbox.file_tool("read", "../etc/passwd")
        await sandbox.run_command("ln -s /etc/passwd passwd-link")
        assert "error" in await sandbox.file_tool("read", "passwd-link")
    assert (await docker("inspect", name)).exit_code != 0


async def test_output_is_bounded_and_command_timeout_removes_sandbox(repository_archive):
    settings = Settings(_env_file=None, agent_command_timeout_seconds=1)
    async with Sandbox(settings, 60) as sandbox:
        await sandbox.prepare(repository_archive)
        output = await sandbox.run_command("python -c 'print(\"x\" * 1000000)' ")
        assert output["truncated"] and len(output["stdout"]) == 32000
        with pytest.raises(CommandTimedOut):
            await sandbox.run_command("sleep 30")
        assert (await docker("inspect", sandbox.name)).exit_code != 0


async def test_task_cancellation_removes_container(repository_archive):
    entered = asyncio.Event()
    sandbox = Sandbox(Settings(_env_file=None), 60)

    async def run():
        async with sandbox:
            await sandbox.prepare(repository_archive)
            entered.set()
            await sandbox.run_command("sleep 30")

    task = asyncio.create_task(run())
    await asyncio.wait_for(entered.wait(), timeout=15)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await docker("inspect", sandbox.name)).exit_code != 0


@pytest.mark.parametrize("bad_entry", ["traversal", "symlink", "hardlink"])
async def test_unsafe_archives_are_rejected_inside_container(bad_entry):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        entry = tarfile.TarInfo("demo/../../escape" if bad_entry == "traversal" else "demo/link")
        if bad_entry != "traversal":
            entry.type = tarfile.SYMTYPE if bad_entry == "symlink" else tarfile.LNKTYPE
            entry.linkname = "/etc/passwd"
        archive.addfile(entry)
    async with Sandbox(Settings(_env_file=None), 30) as sandbox:
        with pytest.raises(SandboxError, match="safely extracted"):
            await sandbox.prepare(stream.getvalue())


async def test_lifetime_supervisor_stops_container_without_worker():
    async with Sandbox(Settings(_env_file=None), 2) as sandbox:
        result = await docker("wait", sandbox.name, timeout=10)
        assert result.exit_code == 0
        info = json.loads((await docker("inspect", sandbox.name)).stdout)[0]
        assert info["State"]["Running"] is False
