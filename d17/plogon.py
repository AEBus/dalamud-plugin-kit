"""Building a plugin commit with Plogon, the builder D17 uses, on this machine: same container image, no network during the build, packages from the lock file. Needs Docker and the .NET SDK."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from d17 import manifest, shell
from d17.config import KIT_ROOT, TRACKS, Plugin

PLOGON_REPO = "https://github.com/goatcorp/Plogon.git"


def prepare_manifests(folder: Path, plugin: Plugin, sha: str, icon: bytes, track: str = "testing") -> Path:
    """Writes a manifests repository in D17's layout with this one plugin; Plogon reads commit dates from its history, so it is committed."""
    target = folder / TRACKS[track] / plugin.internal_name
    (target / "images").mkdir(parents=True)
    data = manifest.updated(None, repository=plugin.repository, commit=sha, owners=plugin.owners, maintainers=[], project_path=plugin.project_path, changelog=None)
    (target / "manifest.toml").write_text(manifest.render(data), encoding="utf-8")
    (target / "images" / "icon.png").write_bytes(icon)
    shell.git(folder, "init", "-q")
    shell.git(folder, "add", ".")
    shell.git(folder, "-c", "user.name=d17", "-c", "user.email=d17@localhost", "commit", "-q", "-m", "manifest")
    return target


def build(plugin: Plugin, sha: str, icon: bytes) -> tuple[bool, Path]:
    """Builds the commit; returns whether it succeeded and where the artifacts are."""
    if not shell.succeeds(["docker", "version"]):
        raise shell.CommandError("Docker is not running")
    plogon = KIT_ROOT / ".cache" / "Plogon"
    if (plogon / ".git").exists():
        shell.git(plogon, "fetch", "-q", "origin")
        shell.git(plogon, "reset", "-q", "--hard", "origin/HEAD")
    else:
        plogon.parent.mkdir(parents=True, exist_ok=True)
        shell.run(["git", "clone", "-q", PLOGON_REPO, str(plogon)])

    work = Path(tempfile.mkdtemp(prefix="d17-plogon-"))
    manifests = work / "manifests"
    manifests.mkdir()
    prepare_manifests(manifests, plugin, sha, icon)
    for name in ("output", "work", "artifacts"):
        (work / name).mkdir()
    command = [
        "dotnet", "run", "-c", "Release", "--project", str(plogon / "Plogon" / "Plogon.csproj"), "--",
        f"--manifest-folder={manifests}",
        f"--output-folder={work / 'output'}",
        f"--work-folder={work / 'work'}",
        f"--static-folder={plogon / 'Plogon' / 'static'}",
        f"--artifact-folder={work / 'artifacts'}",
        f"--build-overrides-file={work / 'overrides.toml'}",
        "--mode=Development",
        "--build-all",
    ]
    result = subprocess.run(command, cwd=plogon / "Plogon")
    return result.returncode == 0, work / "artifacts"
