import re


def github_repository(url: str) -> tuple[str, str]:
    match = re.fullmatch(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/?", url)
    if not match:
        raise ValueError("Agent tasks require a public https://github.com/owner/repository URL")
    owner, name = match.groups()
    name = name.removesuffix(".git")
    if owner in {".", ".."} or name in {"", ".", ".."}:
        raise ValueError("Invalid GitHub repository")
    return owner, name
