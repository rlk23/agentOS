# Milestone 3: isolated coding agent

The implementation is ready for a live-model acceptance run. Automated tests exercise the real
OpenAI Python SDK with scripted HTTP responses and run all repository tools in real Docker
containers. The explicit live test requires your own API key and is not part of the default suite.

## Start

From the repository root:

```bash
make install
make db
make sandbox-image
make migrate
```

Set `OPENAI_API_KEY` in your local `.env` (ignored by Git), or export it in the worker's terminal.
`OPENAI_MODEL` defaults to `gpt-4.1-mini` and can be changed to a Responses API model that supports
function calling. This uses your API account, independently of this Codex conversation.
Restart the API, dispatcher, and worker after upgrading. Run each in a separate terminal:

```bash
make dev
make dispatcher
make worker
```

The worker reads settings at startup. Restart it after changing the key or model. An agent task
submitted without a configured key ends `FAILED` with an actionable error; it never silently
falls back to the demo. Existing tasks and submissions without `execution_mode` remain demos.

## Submit a task

```bash
curl --fail http://127.0.0.1:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{
    "execution_mode": "agent",
    "prompt": "Create calculator.py with an add(a, b) function and a pytest test for it. Run the test and explain the result.",
    "repository": "https://github.com/octocat/Hello-World",
    "max_runtime_seconds": 300
  }'
```

Only public `https://github.com/owner/repository` URLs are supported. The worker downloads a
snapshot of the default branch from a fixed GitHub archive host. There is no host-side clone
or checkout, and repository files are never executed on the host. Private repositories,
credentials in URLs, arbitrary hosts, custom refs, submodules, Git LFS downloads, and symlinks
in repository archives are not supported in this milestone.

The image provides Python 3.12, Git, and pytest. It does not install repository dependencies
at runtime; execution has no network access. Start with small Python repositories. An operator
can build a trusted image with additional dependencies before running other projects. Agent
tasks cannot choose a different image or supply Docker options.

## Results

Read `GET /tasks/<id>` for `status`, `error`, and `result`. Successful agent results contain:

- `job: coding_agent`, model name, final `summary`, model turns, tool calls, and token usage.
- `changes.patch`: a Git patch including edits and newly added non-ignored files.
- `changes.truncated`: whether the patch exceeded its 250,000-byte output limit.
- `baseline_commit`: a synthetic sandbox commit for the downloaded files, not the upstream SHA.
- `source_archive_sha256`: fingerprint of the exact downloaded archive.

The patch is returned as data and is not automatically applied, committed, or pushed anywhere.
Review it before applying it. A truncated patch is not a complete artifact. Ignored generated
files such as pytest caches are not added to the patch.

`SUCCEEDED` means the agent returned a final explanation and its result was saved. It does not
independently certify that repository tests passed; inspect the command output and summary.
If a run fails, its committed progress and tool events remain available, but a final patch
may not be available because the disposable workspace is removed.

Poll `GET /tasks/<id>/events?after_id=<last_id>` for `TOOL_CALL`, `TOOL_RESULT`, and
`AGENT_SUMMARY` events in addition to the lifecycle events. Tool results include command exit
codes, stdout, stderr, and truncation flags. These are action logs and evidence, not private
model reasoning. API output, patches, and repository text should be treated as untrusted data.

## Execution boundary

Each attempt gets a fresh container with:

- No network, published ports, host mounts, Docker socket, or injected API key.
- A read-only root filesystem, dropped Linux capabilities, and `no-new-privileges`.
- Tool processes running as UID/GID 1000. A fixed root-owned lifetime supervisor is the only
  privileged-UID process; it has no Linux capabilities and cannot be signalled by tool processes.
- One CPU, 512 MiB memory with no additional swap, and a 64-process limit.
- A 256 MiB ephemeral workspace and 64 MiB temporary directory.
- A bounded lifetime and cleanup after normal completion, failure, or worker-side cancellation.

The worker runs only trusted orchestration and Docker client commands on the host. Generated
shell text is passed as an argument to `/bin/sh` inside the container, never a host shell.
File tools reject traversal, symlinks, `.git`, and special-file access. Shell commands have
broader access inside the container; the container is the actual security boundary.

Repository archives are capped at 20 MB compressed, 50 MB extracted, 10 MB per extracted file,
and 10,000 entries. Archive extraction happens inside the sandbox and rejects link and special
entries. The API key is available only to the trusted worker and OpenAI client.

Defaults: at most 12 model turns, 24 tool calls, 4,096 output tokens per model turn, 180,000
serialized history characters, 30 seconds per command, and 600 seconds per agent task.
Limits are configurable through the documented environment variables, within validation bounds.
Command stdout and stderr are each capped at 32,000 bytes. Event strings and model tool results
are clipped further to bound database and context usage. A command timeout removes the whole
container; killing the Docker client alone would not stop the command.

The supervisor stops execution at its deadline even if the worker disappears. A hard worker
crash may leave a stopped, labelled container record and a task stuck `RUNNING`; automatic
task recovery and garbage collection are not implemented. This remains a single-owner local
development system. Multi-tenant deployments need a stronger sandbox/runtime and access controls.

## Verification

```bash
make test                 # API, scheduler, and SDK contract tests; no model charges
make test-sandbox         # also builds the image and tests actual Docker execution
make test-live            # explicit real model call, requires OPENAI_API_KEY; incurs API usage
```

The live test supplies a fixed tiny repository with a broken addition function. It asks the
real model to repair it, then checks saved results, a code patch, and passing test output.
The non-live equivalent uses scripted model responses through the real SDK, real containers,
PostgreSQL, and Redis. Sandbox tests also verify isolation settings, read-only filesystem,
missing credentials, network denial, output bounds, archive rejection, timeout cleanup,
cancellation cleanup, and the independent lifetime supervisor.

Implementation references: [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling),
[Docker runtime controls](https://docs.docker.com/engine/containers/run/).
