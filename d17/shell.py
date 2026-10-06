"""Running git and the GitHub CLI."""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path


class CommandError(Exception):
    pass


def run(args: list[str], cwd: Path | None = None, input: bytes | None = None) -> bytes:
    """Runs a command and returns its output; raises CommandError when it fails."""
    result = subprocess.run(args, cwd=cwd, input=input, capture_output=True)
    if result.returncode != 0:
        message = result.stderr.decode(errors="replace").strip() or result.stdout.decode(errors="replace").strip()
        raise CommandError(f"{' '.join(args[:3])}...: {message}")
    return result.stdout


def succeeds(args: list[str], cwd: Path | None = None) -> bool:
    return subprocess.run(args, cwd=cwd, capture_output=True).returncode == 0


def git(repo: Path, *args: str) -> str:
    return run(["git", *args], cwd=repo).decode(errors="replace").strip()


def git_show(repo: Path, rev: str, path: str) -> bytes | None:
    """Returns a file as it is in a commit, or None when the commit does not have it."""
    try:
        return run(["git", "show", f"{rev}:{path}"], cwd=repo)
    except CommandError:
        return None


def gh_json(*args: str) -> object:
    return json.loads(run(["gh", *args]).decode())


def github_file(repo: str, path: str, ref: str = "main") -> bytes | None:
    """Returns a file from a GitHub repository, or None when it does not exist."""
    try:
        content = gh_json("api", f"repos/{repo}/contents/{path}?ref={ref}")
    except CommandError:
        return None
    return base64.b64decode(content["content"]) if isinstance(content, dict) and "content" in content else None
