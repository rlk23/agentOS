"""Docker boundary. Generated shell text is passed to a shell ONLY inside a container."""

import asyncio
import json
import re
from dataclasses import dataclass
from uuid import uuid4

import httpx
from agentos_core.config import Settings
from agentos_core.repositories import github_repository


class SandboxError(RuntimeError):
    pass


class CommandTimedOut(SandboxError):
    pass


async def download_repository(url: str) -> bytes:
    owner, name = github_repository(url)
    # Fixed host, no user-controlled redirects, credentials, proxy, or local filesystem URLs.
    async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
        async with client.stream(
            "GET", f"https://codeload.github.com/{owner}/{name}/tar.gz/HEAD"
        ) as r:
            r.raise_for_status()
            archive = bytearray()
            async for chunk in r.aiter_bytes():
                archive.extend(chunk)
                if len(archive) > 20_000_000:
                    raise SandboxError("Repository archive exceeds 20 MB")
    return bytes(archive)


@dataclass
class CommandOutput:
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool

    def as_dict(self) -> dict:
        return vars(self)


async def docker(
    *args: str, stdin: bytes | None = None, timeout: float = 30, output_limit: int = 32000
) -> CommandOutput:
    """Bound memory while draining output; never use a host shell."""
    process = await asyncio.create_subprocess_exec(
        "docker",
        *args,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def read(stream):
        content = bytearray()
        truncated = False
        while chunk := await stream.read(65536):
            available = max(0, output_limit - len(content))
            content.extend(chunk[:available])
            truncated |= len(chunk) > available
        return content.decode("utf-8", errors="replace"), truncated

    async def write():
        if stdin is not None:
            try:
                process.stdin.write(stdin)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()

    readers = [asyncio.create_task(read(process.stdout)), asyncio.create_task(read(process.stderr))]
    writer = asyncio.create_task(write())
    try:
        async with asyncio.timeout(timeout):
            await writer
            await process.wait()
            stdout, stderr = await asyncio.gather(*readers)
        return CommandOutput(process.returncode, stdout[0], stderr[0], stdout[1] or stderr[1])
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        for task in [writer, *readers]:
            if not task.done():
                task.cancel()
        await asyncio.gather(writer, *readers, return_exceptions=True)


class Sandbox:
    def __init__(self, settings: Settings, lifetime_seconds: int):
        self.settings = settings
        self.name = f"agentos-job-{uuid4().hex}"
        self.lifetime = min(lifetime_seconds, settings.agent_max_runtime_seconds)
        self.baseline: str | None = None

    async def __aenter__(self):
        try:
            output = await docker(
                "create",
                "--pull=never",
                "--name",
                self.name,
                "--label",
                "agentos.sandbox=true",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=64",
                "--cpus=1",
                "--memory=512m",
                "--memory-swap=512m",
                "--shm-size=16m",
                "--init",
                "--ulimit",
                "nofile=256:256",
                "--log-driver=none",
                "--tmpfs",
                "/workspace:rw,nosuid,nodev,size=256m,uid=1000,gid=1000,mode=0700",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
                # Only the fixed lifetime supervisor is root. All tools execute as UID 1000.
                "--user=0:0",
                "--workdir=/workspace",
                self.settings.sandbox_image,
                str(self.lifetime),
            )
            if output.exit_code:
                raise SandboxError("Sandbox creation failed; build the configured sandbox image")
            if (await docker("start", self.name)).exit_code:
                raise SandboxError("Sandbox did not start")
            return self
        except BaseException:
            await self.close()
            raise

    async def __aexit__(self, *exc):
        await asyncio.shield(self.close())

    async def close(self):
        output = await docker("rm", "--force", self.name, timeout=10)
        if output.exit_code and "No such container" not in output.stderr:
            raise SandboxError("Sandbox cleanup failed")

    async def execute(
        self,
        *args: str,
        stdin: bytes | None = None,
        timeout: float | None = None,
        output_limit: int = 32000,
    ) -> CommandOutput:
        try:
            output = await docker(
                "exec",
                "--user=1000:1000",
                "--workdir=/workspace",
                *(["-i"] if stdin is not None else []),
                self.name,
                *args,
                stdin=stdin,
                timeout=timeout or self.settings.agent_command_timeout_seconds,
                output_limit=output_limit,
            )
        except TimeoutError as exc:
            # Killing docker-exec alone would leave its process alive inside the container.
            await self.close()
            raise CommandTimedOut("Command exceeded its time limit; sandbox removed") from exc
        return output

    async def prepare(self, archive: bytes):
        output = await self.execute(
            "python", "-I", "/opt/agentos/tools.py", "extract", stdin=archive
        )
        if output.exit_code:
            raise SandboxError("Repository archive could not be safely extracted")
        output = await self.execute(
            "/bin/sh",
            "-c",
            "git init -q && git config user.email agentos@localhost "
            "&& git config user.name AgentOS "
            "&& git add -f . && git -c core.hooksPath=/dev/null commit -qm baseline "
            "--allow-empty && git rev-parse HEAD",
        )
        if output.exit_code or not re.fullmatch(r"[0-9a-f]{40}", output.stdout.strip()):
            raise SandboxError("Could not initialize sandbox baseline")
        self.baseline = output.stdout.strip()

    async def run_command(self, command: str) -> dict:
        return (await self.execute("/bin/sh", "-c", command)).as_dict()

    async def file_tool(self, action: str, path: str, content: str | None = None) -> dict:
        data = json.dumps({"action": action, "path": path, "content": content}).encode()
        output = await self.execute(
            "python", "-I", "/opt/agentos/tools.py", "file", stdin=data, output_limit=650000
        )
        try:
            return json.loads(output.stdout)
        except ValueError:
            return {"error": "File tool failed", "exit_code": output.exit_code}

    async def changes(self) -> dict:
        if self.baseline is None:
            return {"patch": "", "truncated": False}
        staged = await self.execute("git", "-c", "core.hooksPath=/dev/null", "add", "-A")
        if staged.exit_code:
            raise SandboxError("Could not collect changes")
        output = await self.execute(
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "diff",
            "--cached",
            "--binary",
            "--no-ext-diff",
            "--no-textconv",
            self.baseline,
            "--",
            ".",
            output_limit=250000,
        )
        if output.exit_code:
            raise SandboxError("Could not collect changes against the original baseline")
        return {"patch": output.stdout, "truncated": output.truncated}
