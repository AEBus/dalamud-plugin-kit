"""Reading a plugin's CHANGELOG.md: one "## <version>" section per release, newest first."""

from __future__ import annotations

import re

_HEADING = re.compile(r"^##\s+v?(?P<version>\d+(?:\.\d+){1,3})\b.*$", re.MULTILINE)


def versions(text: str) -> list[str]:
    return [match.group("version") for match in _HEADING.finditer(text)]


def section(text: str, version: str) -> str | None:
    """Returns the text of a version's section without its heading, or None when there is none.

    The plugin installer shows this text as written, so it should read well without Markdown rendering: a summary line and "- " items.
    """
    text = text.replace("\r\n", "\n")
    headings = list(_HEADING.finditer(text))
    for index, heading in enumerate(headings):
        if heading.group("version") == version:
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            body = text[heading.end():end].strip()
            return body or None
    return None
