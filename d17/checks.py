"""Checks of a plugin commit before it is submitted, as far as they can be made without Plogon: everything is read from the commit itself, not from the working tree."""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from d17 import changelog, manifest, shell
from d17.config import TRACKS, UPSTREAM, Plugin

OK, WARN, ERROR, SKIP = "ok", "warn", "error", "skip"

_FORBIDDEN_JSON_KEYS = ("DalamudApiLevel", "TestingDalamudApiLevel", "ApplicableVersion")
_PACKAGE_REFERENCE = re.compile(r'<PackageReference\s+Include="(?P<name>[^"]+)"\s+Version="(?P<version>[^"]+)"')
_VERSION = re.compile(r"<Version>\s*(?P<version>[^<]*?)\s*</Version>")


@dataclass
class Result:
    name: str
    level: str
    message: str


@dataclass
class Submission:
    """What a submission is about: a plugin at a commit, for a track, and what that track has now."""

    plugin: Plugin
    repo: Path
    sha: str
    track: str
    version: str | None = None
    changelog: str | None = None
    current_manifest: dict | None = None
    current_commit: str | None = None
    current_version: str | None = None
    results: list[Result] = field(default_factory=list)

    def add(self, name: str, level: str, message: str) -> None:
        self.results.append(Result(name, level, message))

    def file(self, path: str) -> bytes | None:
        return shell.git_show(self.repo, self.sha, path)

    @property
    def failed(self) -> bool:
        return any(result.level == ERROR for result in self.results)


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def png_size(data: bytes) -> tuple[int, int] | None:
    """Returns the width and height of a PNG image, or None when the data is not a PNG."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def csproj_version(text: str) -> str | None:
    match = _VERSION.search(text)
    return match.group("version") if match else None


def lock_mismatches(csproj: str, lock: dict) -> list[str]:
    """Returns the package references of the project that the lock file does not pin at the same version."""
    direct: dict[str, str] = {}
    for packages in lock.get("dependencies", {}).values():
        for name, info in packages.items():
            if info.get("type") == "Direct":
                direct[name.lower()] = info.get("resolved", "")
    problems = []
    for match in _PACKAGE_REFERENCE.finditer(csproj):
        name, version = match.group("name"), match.group("version")
        resolved = direct.get(name.lower())
        if resolved is None:
            problems.append(f"{name} is not in the lock file")
        elif re.fullmatch(r"[\d.]+", version) and resolved != version:
            problems.append(f"{name} is {version} in the project but {resolved} in the lock file")
    return problems


def run_all(submission: Submission, *, allow_new_stable: bool = False) -> Submission:
    s = submission
    plugin = s.plugin
    _commit(s)

    csproj = s.file(plugin.csproj)
    if csproj is None:
        s.add("project", ERROR, f"{plugin.csproj} is not in the commit")
        return s
    csproj_text = csproj.decode("utf-8", errors="replace")
    _version(s, csproj_text, allow_new_stable)
    _lock_file(s, csproj_text)
    _json_manifest(s, csproj_text)
    _icon(s)
    _changelog(s)
    _public_texts(s)
    _preflight(s)
    return s


def _commit(s: Submission) -> None:
    repo = s.plugin.github_repo
    if repo is None:
        s.add("commit", WARN, f"{s.sha[:12]}: the repository is not on GitHub, so whether the commit is public is not checked")
    elif shell.succeeds(["gh", "api", f"repos/{repo}/commits/{s.sha}", "--silent"]):
        s.add("commit", OK, f"{s.sha[:12]} is on {repo}")
    else:
        s.add("commit", ERROR, f"{s.sha[:12]} is not on {repo}: push it first, Plogon clones the public repository")


def _version(s: Submission, csproj: str, allow_new_stable: bool) -> None:
    version = csproj_version(csproj)
    if not version or not re.fullmatch(r"\d+(\.\d+){1,3}", version):
        s.add("version", ERROR, f"the csproj Version must be a fixed number, not '{version}': D17 needs the same version from every build of a commit")
        return
    s.version = version
    path = f"{s.plugin.manifest_dir(s.track)}/manifest.toml"
    s.current_manifest = manifest.parse(shell.github_file(UPSTREAM, path))
    if s.current_manifest is None:
        if s.track == "stable" and not allow_new_stable:
            s.add("version", ERROR, f"{version}: the plugin is not on the stable track yet; new plugins go to testing first (promote a testing build to move it)")
        else:
            s.add("version", OK, f"{version}: first submission to the {s.track} track")
        return
    s.current_commit = s.current_manifest.get("plugin", {}).get("commit")
    current = shell.git_show(s.repo, s.current_commit, s.plugin.csproj) if s.current_commit else None
    s.current_version = csproj_version(current.decode("utf-8", errors="replace")) if current else None
    if not s.current_version:
        s.add("version", WARN, f"{version}: could not read the version of the current {s.track} commit {str(s.current_commit)[:12]} (fetch the plugin repository?)")
    elif version_key(version) <= version_key(s.current_version):
        s.add("version", ERROR, f"{version} is not newer than {s.current_version} on the {s.track} track")
    else:
        s.add("version", OK, f"{s.current_version} -> {version} on the {s.track} track")


def _lock_file(s: Submission, csproj: str) -> None:
    lock = s.file(s.plugin.lock_file)
    if lock is None:
        s.add("lock file", ERROR, f"{s.plugin.lock_file} is not committed; Plogon restores packages from it, offline")
        return
    problems = lock_mismatches(csproj, json.loads(lock))
    s.add("lock file", ERROR if problems else OK, "; ".join(problems) if problems else "every package reference is pinned")


def _json_manifest(s: Submission, csproj: str) -> None:
    raw = s.file(s.plugin.json_manifest)
    if raw is None:
        s.add("json manifest", ERROR, f"{s.plugin.json_manifest} is not in the commit")
        return
    data = json.loads(raw.decode("utf-8-sig"))
    forbidden = [key for key in _FORBIDDEN_JSON_KEYS if key in data]
    if forbidden:
        s.add("json manifest", ERROR, f"remove {', '.join(forbidden)}: Plogon sets them")
        return
    missing = [key for key in ("Author", "Name", "Punchline", "Description") if not data.get(key)]
    notes = []
    if missing:
        notes.append(f"missing {', '.join(missing)}")
    if data.get("Changelog"):
        notes.append("has a Changelog; the installer shows the one in manifest.toml, which comes from the changelog file")
    if "<Description>" in csproj:
        notes.append("the csproj has a Description, which can replace the manifest's")
    s.add("json manifest", WARN if notes else OK, "; ".join(notes) if notes else "no fields that Plogon sets itself")


def _icon(s: Submission) -> None:
    data = s.file(s.plugin.icon)
    size = png_size(data) if data else None
    if size is None:
        s.add("icon", ERROR, f"{s.plugin.icon} is missing or not a PNG")
    elif size[0] != size[1] or not 64 <= size[0] <= 512:
        s.add("icon", ERROR, f"{s.plugin.icon} is {size[0]}x{size[1]}; it must be square, from 64 to 512 pixels")
    else:
        s.add("icon", OK, f"{size[0]}x{size[1]} PNG")


def _changelog(s: Submission) -> None:
    raw = s.file(s.plugin.changelog)
    if raw is None:
        s.add("changelog", ERROR, f"{s.plugin.changelog} is not in the commit")
        return
    if s.version is None:
        s.add("changelog", SKIP, "no version to look up")
        return
    s.changelog = changelog.section(raw.decode("utf-8"), s.version)
    if s.changelog is None:
        s.add("changelog", ERROR, f"{s.plugin.changelog} has no '## {s.version}' section")
    else:
        s.add("changelog", OK, f"'## {s.version}': {len(s.changelog.splitlines())} lines")


def _public_texts(s: Submission) -> None:
    if not s.plugin.forbidden_public_words:
        return
    texts = {path: s.file(path) for path in ("README.md", s.plugin.json_manifest)}
    texts[f"{s.plugin.changelog} ({s.version})"] = (s.changelog or "").encode()
    found = []
    for path, raw in texts.items():
        text = (raw or b"").decode("utf-8", errors="replace").lower()
        found += [f"'{word}' in {path}" for word in s.plugin.forbidden_public_words if word.lower() in text]
    s.add("public texts", ERROR if found else OK, "; ".join(found) if found else "no forbidden names")


def _preflight(s: Submission) -> None:
    if not s.plugin.preflight:
        return
    head = shell.git(s.repo, "rev-parse", "HEAD")
    dirty = shell.git(s.repo, "status", "--porcelain")
    if head != s.sha or dirty:
        s.add("preflight", SKIP, "it checks the working tree, which must be clean and at the submitted commit")
        return
    try:
        shell.run(s.plugin.preflight, cwd=s.repo)
        s.add("preflight", OK, " ".join(s.plugin.preflight))
    except shell.CommandError as error:
        s.add("preflight", ERROR, str(error)[-500:])
