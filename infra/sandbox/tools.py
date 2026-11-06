"""Runs only inside the sandbox. Input is JSON (or a bounded tarball for extract)."""

import json
import stat
import sys
import tarfile
from pathlib import Path

ROOT = Path("/workspace")
MAX_FILE = 100_000


def safe_path(raw):
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute():
        raise ValueError("Use a relative workspace path")
    parts = Path(raw).parts
    if ".." in parts or ".git" in parts:
        raise ValueError("Path traversal and .git access are not allowed by file tools")
    path = ROOT.joinpath(raw)
    # Refuse symlinks, including parents, and special files rather than following them.
    current = ROOT
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink paths are not allowed")
    if path.exists() and not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("Expected a regular file")
    return path


def extract():
    total = count = 0
    prefix = None
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|gz") as archive:
        for member in archive:
            count += 1
            if count > 10000:
                raise ValueError("Repository has too many entries")
            parts = Path(member.name).parts
            if not parts or Path(member.name).is_absolute() or ".." in parts:
                raise ValueError("Unsafe archive path")
            prefix = prefix or parts[0]
            if parts[0] != prefix or ".git" in parts:
                raise ValueError("Unexpected archive root or Git metadata")
            if len(parts) == 1:
                if not member.isdir():
                    raise ValueError("Archive root must be a directory")
                continue
            path = ROOT.joinpath(*parts[1:])
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                total += member.size
                if total > 50_000_000 or member.size > 10_000_000:
                    raise ValueError("Repository exceeds extraction limit")
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, path.open("xb") as target:
                    while chunk := source.read(65536):
                        target.write(chunk)
                path.chmod(0o755 if member.mode & 0o111 else 0o644)
            else:
                raise ValueError("Symlinks, hardlinks, and special archive entries are unsupported")
    print(json.dumps({"files_and_directories": count, "bytes": total}))


def file_tool():
    data = json.load(sys.stdin)
    path = safe_path(data["path"])
    if data["action"] == "read":
        with path.open("rb") as file:
            content = file.read(MAX_FILE + 1)
        print(
            json.dumps(
                {
                    "content": content[:MAX_FILE].decode("utf-8", errors="replace"),
                    "truncated": len(content) > MAX_FILE,
                }
            )
        )
    elif data["action"] == "write":
        content = data["content"].encode("utf-8")
        if len(content) > MAX_FILE:
            raise ValueError("File write exceeds 100000 bytes")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as file:
            file.write(content)
        print(json.dumps({"written_bytes": len(content)}))
    else:
        raise ValueError("Unknown file action")


if __name__ == "__main__":
    try:
        if sys.argv[1] == "extract":
            extract()
        else:
            file_tool()
    except (ValueError, OSError, KeyError, tarfile.TarError) as exc:
        print(json.dumps({"error": str(exc)[:500]}))
        sys.exit(1)
