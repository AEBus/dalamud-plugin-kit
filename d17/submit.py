"""Submitting: a branch in the D17 fork with the updated manifest and icon, a draft for the pull request, and the pull request itself."""

from __future__ import annotations

import tempfile
from pathlib import Path

from d17 import draft, facts, manifest, shell
from d17.checks import Submission
from d17.config import UPSTREAM, Settings


class SubmitError(Exception):
    pass


def branch_name(s: Submission) -> str:
    return f"{s.plugin.slug}/{s.track}/{s.version}"


def manifest_text(s: Submission) -> str:
    data = manifest.updated(
        s.current_manifest,
        repository=s.plugin.repository,
        commit=s.sha,
        owners=s.plugin.owners,
        maintainers=s.plugin.maintainers,
        project_path=s.plugin.project_path,
        changelog=s.changelog,
    )
    return manifest.render(data)


def prepare(settings: Settings, s: Submission, *, push: bool = True) -> tuple[str, Path]:
    """Creates the branch from upstream main, commits the manifest and icon, pushes it to the fork and writes the draft. Returns the branch and the draft's path."""
    clone = settings.d17_clone
    if shell.git(clone, "status", "--porcelain"):
        raise SubmitError(f"{clone} has uncommitted changes")
    branch = branch_name(s)
    shell.git(clone, "fetch", "-q", "upstream", "main")
    shell.git(clone, "fetch", "-q", "origin")
    if shell.succeeds(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=clone) or shell.git(clone, "ls-remote", "--heads", "origin", branch):
        raise SubmitError(f"branch {branch} already exists; every submission gets a new branch (delete the old one if it was never opened)")
    shell.git(clone, "switch", "-q", "--no-track", "-c", branch, "upstream/main")

    target = clone / s.plugin.manifest_dir(s.track)
    (target / "images").mkdir(parents=True, exist_ok=True)
    (target / "manifest.toml").write_text(manifest_text(s), encoding="utf-8", newline="\n")
    icon = s.file(s.plugin.icon)
    if icon is not None:
        (target / "images" / "icon.png").write_bytes(icon)
    shell.git(clone, "add", "--", s.plugin.manifest_dir(s.track))
    if not shell.git(clone, "status", "--porcelain"):
        raise SubmitError("the manifest and icon are already as they would be; nothing to submit")
    shell.git(clone, "commit", "-q", "-m", f"{s.plugin.name} {s.version} ({s.track})")
    if push:
        shell.git(clone, "push", "-q", "-u", "origin", branch)

    path = draft.path_for(s.plugin.slug, s.track, s.version or "unknown")
    notes = [
        "The description above goes to the pull request exactly as you write it; nothing below this line is sent.",
        "D17 asks that the description and the AI disclosure are written by a person: https://dalamud.dev/plugin-publishing/ai-policy",
        f"Keep the description within {draft.MAX_DESCRIPTION} characters; D17 posts it to Discord on the first build. Details can go in a comment after opening.",
        "",
        "Facts:",
        *(f"- {fact}" for fact in facts.collect(s)),
        "",
        "Changelog shown in the plugin installer (from the changelog file):",
        "",
        s.changelog or "(none)",
        "",
        f"Open it with: python -m d17 open {s.plugin.internal_name}",
    ]
    draft.write(path, title=f"{s.plugin.name} {s.version}", branch=branch, notes=notes)
    return branch, path


def open_pull_request(settings: Settings, draft_path: Path) -> str:
    d = draft.read(draft_path)
    if not shell.git(settings.d17_clone, "ls-remote", "--heads", "origin", d.branch):
        raise SubmitError(f"branch {d.branch} is not on {settings.fork}; run prepare without --no-push, or push it")
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as body:
        body.write(d.description + "\n")
    try:
        output = shell.run(["gh", "pr", "create", "-R", UPSTREAM, "--base", "main", "--head", f"{settings.fork_owner}:{d.branch}", "--title", d.title, "--body-file", body.name])
    finally:
        Path(body.name).unlink(missing_ok=True)
    return output.decode().strip()


def status(settings: Settings, slug: str | None) -> list[str]:
    pulls = shell.gh_json("pr", "list", "-R", UPSTREAM, "--author", settings.fork_owner, "--state", "all", "--limit", "30",
                          "--json", "number,title,state,headRefName,url,updatedAt")
    lines = []
    for pull in pulls:
        if slug and not pull["headRefName"].startswith(slug):
            continue
        line = f"#{pull['number']} {pull['state'].lower():7} {pull['updatedAt'][:10]}  {pull['title']}  {pull['url']}"
        if pull["state"] == "OPEN":
            comments = shell.gh_json("api", f"repos/{UPSTREAM}/issues/{pull['number']}/comments")
            bot = [c for c in comments if c["user"]["login"] == "bleatbot"]
            people = [c for c in comments if c["user"]["login"] not in ("bleatbot", settings.fork_owner)]
            if bot:
                line += "\n    bleatbot: " + _summary(bot[-1]["body"])
            for comment in people[-3:]:
                line += f"\n    {comment['user']['login']}: " + _summary(comment["body"])
        lines.append(line)
    return lines


def _summary(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith(("<", "|", "```")):
            return line[:160]
    return text.strip()[:160]
