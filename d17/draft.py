"""Pull request drafts: a file the author writes the description in, with notes below that are never sent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from d17.config import KIT_ROOT

DESCRIPTION_MARKER = "===== Pull request description (sent as written) ====="
NOTES_MARKER = "===== Notes for you (not sent) ====="
PLACEHOLDER = "<!-- d17:"
TEMPLATE = KIT_ROOT / "templates" / "pr-body.md"


class DraftError(Exception):
    pass


@dataclass
class Draft:
    title: str
    branch: str
    description: str


def write(path: Path, *, title: str, branch: str, notes: list[str], template: Path = TEMPLATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = template.read_text(encoding="utf-8").strip()
    lines = [f"title: {title}", f"branch: {branch}", "", DESCRIPTION_MARKER, "", body, "", NOTES_MARKER, "", *notes, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def read(path: Path) -> Draft:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    header, _, rest = text.partition(DESCRIPTION_MARKER)
    if not rest:
        raise DraftError(f"{path} has no '{DESCRIPTION_MARKER}' line")
    description = rest.partition(NOTES_MARKER)[0].strip()
    fields = dict(line.split(":", 1) for line in header.splitlines() if ":" in line)
    title, branch = fields.get("title", "").strip(), fields.get("branch", "").strip()
    if not title or not branch:
        raise DraftError(f"{path} needs 'title:' and 'branch:' lines at the top")
    if PLACEHOLDER in description:
        raise DraftError("the description still has '<!-- d17:' placeholders; write those parts yourself (D17 wants the description and the AI disclosure written by a person) and delete the placeholders")
    if not description:
        raise DraftError("the description is empty")
    return Draft(title, branch, description)


def path_for(slug: str, track: str, version: str) -> Path:
    return KIT_ROOT / "drafts" / f"{slug}-{track}-{version}.md"


def latest_for(slug: str) -> Path:
    drafts = sorted((KIT_ROOT / "drafts").glob(f"{slug}-*.md"), key=lambda draft: draft.stat().st_mtime)
    if not drafts:
        raise DraftError(f"no draft for {slug}; run 'prepare' first")
    return drafts[-1]
