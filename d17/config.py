"""The plugin registry (plugins/*.toml) and the machine's own settings (local.toml)."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
UPSTREAM = "goatcorp/DalamudPluginsD17"
TRACKS = {"testing": "testing/live", "stable": "stable"}


class ConfigError(Exception):
    pass


@dataclass
class Plugin:
    internal_name: str
    name: str
    repository: str
    project_path: str
    owners: list[str]
    icon: str
    changelog: str = "CHANGELOG.md"
    maintainers: list[str] = field(default_factory=list)
    # From local.toml: the plugin's clone, an optional command run in it before a submission, and words that must not appear in what every user sees (README, changelog, manifest), such as the names of custom-repo plugins the official repository must not point to.
    path: Path | None = None
    preflight: list[str] | None = None
    forbidden_public_words: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self.internal_name.lower()).strip("-")

    @property
    def github_repo(self) -> str | None:
        """Returns "owner/name" when the repository is on GitHub."""
        match = re.match(r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", self.repository)
        return match.group(1) if match else None

    @property
    def csproj(self) -> str:
        return f"{self.project_path}/{self.internal_name}.csproj"

    @property
    def json_manifest(self) -> str:
        return f"{self.project_path}/{self.internal_name}.json"

    @property
    def lock_file(self) -> str:
        return f"{self.project_path}/packages.lock.json"

    def manifest_dir(self, track: str) -> str:
        return f"{TRACKS[track]}/{self.internal_name}"


@dataclass
class Settings:
    fork: str
    d17_clone: Path
    plugins: dict[str, Plugin]

    @property
    def fork_owner(self) -> str:
        return self.fork.split("/")[0]

    def plugin(self, name: str) -> Plugin:
        for plugin in self.plugins.values():
            if name in (plugin.internal_name, plugin.slug) or name.lower() == plugin.name.lower():
                return plugin
        raise ConfigError(f"Unknown plugin '{name}'. Known: {', '.join(sorted(self.plugins))}")


def load(kit_root: Path = KIT_ROOT) -> Settings:
    local_path = kit_root / "local.toml"
    if not local_path.exists():
        raise ConfigError(f"Missing {local_path}; copy local.example.toml and fill it in.")
    local = tomllib.loads(local_path.read_text(encoding="utf-8"))
    plugins: dict[str, Plugin] = {}
    for path in sorted((kit_root / "plugins").glob("*.toml")):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        plugin = Plugin(**data)
        own = local.get("plugins", {}).get(plugin.internal_name, {})
        if "path" in own:
            plugin.path = Path(own["path"])
        plugin.preflight = own.get("preflight")
        plugin.forbidden_public_words = own.get("forbidden_public_words", [])
        plugins[plugin.internal_name] = plugin
    try:
        return Settings(fork=local["fork"], d17_clone=Path(local["d17_clone"]), plugins=plugins)
    except KeyError as missing:
        raise ConfigError(f"local.toml needs {missing}") from None
