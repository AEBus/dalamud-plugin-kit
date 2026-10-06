"""Facts about a submission for its author: what changed since the build the track has now. They are notes to write the pull request from, not text for it."""

from __future__ import annotations

import re

from d17 import shell
from d17.checks import Submission

_HOST = re.compile(r"https?://([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
_PACKAGE = re.compile(r'<PackageReference\s+Include="([^"]+)"\s+Version="([^"]+)"')


def collect(s: Submission) -> list[str]:
    facts = [f"Commit: {s.sha}", f"Version: {s.current_version or '(new)'} -> {s.version}", f"Track: {s.track}"]
    repo = s.plugin.github_repo
    old = s.current_commit if s.current_commit and shell.succeeds(["git", "cat-file", "-e", f"{s.current_commit}^{{commit}}"], cwd=s.repo) else None
    if old is None:
        return facts + ["No earlier build on this track to compare with."]

    if repo:
        facts.append(f"Changes: https://github.com/{repo}/compare/{old[:12]}...{s.sha[:12]}")
    facts.append("Diff: " + shell.git(s.repo, "diff", "--shortstat", old, s.sha))

    old_packages = dict(_PACKAGE.findall((shell.git_show(s.repo, old, s.plugin.csproj) or b"").decode()))
    new_packages = dict(_PACKAGE.findall((shell.git_show(s.repo, s.sha, s.plugin.csproj) or b"").decode()))
    added = [f"{name} {version}" for name, version in new_packages.items() if name not in old_packages]
    removed = [name for name in old_packages if name not in new_packages]
    changed = [f"{name} {old_packages[name]} -> {version}" for name, version in new_packages.items() if name in old_packages and old_packages[name] != version]
    facts.append("NuGet packages: " + ("; ".join(filter(None, [
        "added " + ", ".join(added) if added else "",
        "removed " + ", ".join(removed) if removed else "",
        "updated " + ", ".join(changed) if changed else "",
    ])) or "no changes"))

    new_hosts = _hosts(s, s.sha) - _hosts(s, old)
    facts.append("Hosts newly named in the code: " + (", ".join(sorted(new_hosts)) or "none"))
    return facts


def _hosts(s: Submission, rev: str) -> set[str]:
    try:
        text = shell.git(s.repo, "grep", "-h", "-o", "-I", "-E", r"https?://[A-Za-z0-9.-]+", rev, "--", "*.cs")
    except shell.CommandError:
        return set()
    return {match.group(1).lower() for match in _HOST.finditer(text)}
