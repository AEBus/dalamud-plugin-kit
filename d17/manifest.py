"""D17 manifest.toml files: reading the current one and writing an updated one."""

from __future__ import annotations

import json
import tomllib

# The order D17's own manifests use; other keys follow in their own order.
_PLUGIN_KEY_ORDER = ["repository", "commit", "owners", "maintainers", "project_path", "version", "changelog"]


def parse(text: str | bytes | None) -> dict | None:
    if text is None:
        return None
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    return tomllib.loads(text)


def updated(current: dict | None, *, repository: str, commit: str, owners: list[str], maintainers: list[str], project_path: str, changelog: str | None) -> dict:
    """Returns the manifest for a submission: the current one (keeping keys the kit does not manage, such as secrets) with the commit and changelog replaced."""
    data = {key: dict(value) if isinstance(value, dict) else value for key, value in (current or {}).items()}
    plugin = data.setdefault("plugin", {})
    plugin["repository"] = plugin.get("repository") or repository
    plugin["commit"] = commit
    plugin["owners"] = plugin.get("owners") or owners
    if maintainers and not plugin.get("maintainers"):
        plugin["maintainers"] = maintainers
    plugin["project_path"] = plugin.get("project_path") or project_path
    if changelog:
        plugin["changelog"] = changelog
    else:
        plugin.pop("changelog", None)
    return data


def render(data: dict) -> str:
    lines: list[str] = []
    for table in sorted(data, key=lambda name: (name != "plugin", name)):
        values = data[table]
        if lines:
            lines.append("")
        lines.append(f"[{table}]")
        position = {key: index for index, key in enumerate(values)}
        keys = list(values)
        if table == "plugin":
            keys = sorted(keys, key=lambda key: (_PLUGIN_KEY_ORDER.index(key) if key in _PLUGIN_KEY_ORDER else len(_PLUGIN_KEY_ORDER), position[key]))
        for key in keys:
            value = values[key]
            if isinstance(value, dict):
                continue
            lines.append(f"{_key(key)} = {_value(value)}")
        for key in keys:
            if isinstance(values[key], dict):
                lines.append("")
                lines.append(f"[{table}.{_key(key)}]")
                lines.extend(f"{_key(sub)} = {_value(item)}" for sub, item in values[key].items())
    return "\n".join(lines) + "\n"


def _key(key: str) -> str:
    return key if key.replace("_", "").replace("-", "").isalnum() else json.dumps(key)


def _value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    text = str(value)
    if "\n" in text:
        # A multi-line literal string keeps the changelog exactly as written, unless it contains the closing quotes.
        if "'''" not in text and not text.endswith("'"):
            return "'''\n" + text + "'''"
        return '"""\n' + text.replace("\\", "\\\\").replace('"', '\\"') + '"""'
    return json.dumps(text, ensure_ascii=False)
