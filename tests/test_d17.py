import struct
import tempfile
import tomllib
import unittest
import zlib
from pathlib import Path

from d17 import changelog, checks, draft, manifest

CHANGELOG = """# Changelog

## 1.2.0.0

Big update.

- First item.
- Second item.

## v1.1.3.0 (2026-05-13)

Window resizing update.

- Resizable.

## 1.0.0.0
"""


def png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) + chunk(b"IEND", b"")


class ChangelogTests(unittest.TestCase):
    def test_section_is_the_text_under_the_version_heading(self):
        self.assertEqual(changelog.section(CHANGELOG, "1.2.0.0"), "Big update.\n\n- First item.\n- Second item.")

    def test_headings_may_have_a_v_and_a_date(self):
        self.assertEqual(changelog.section(CHANGELOG, "1.1.3.0"), "Window resizing update.\n\n- Resizable.")
        self.assertEqual(changelog.versions(CHANGELOG), ["1.2.0.0", "1.1.3.0", "1.0.0.0"])

    def test_missing_or_empty_sections_are_none(self):
        self.assertIsNone(changelog.section(CHANGELOG, "9.9.9.9"))
        self.assertIsNone(changelog.section(CHANGELOG, "1.0.0.0"))


class ManifestTests(unittest.TestCase):
    CURRENT = {"plugin": {"repository": "https://github.com/a/b.git", "commit": "old", "owners": ["a"], "project_path": "B", "changelog": "old notes", "secrets": {"KEY": "x"}}}

    def test_update_keeps_unmanaged_keys_and_replaces_commit_and_changelog(self):
        data = manifest.updated(self.CURRENT, repository="ignored", commit="new", owners=["ignored"], maintainers=[], project_path="ignored", changelog="Line one.\n\n- Item")
        self.assertEqual(data["plugin"]["commit"], "new")
        self.assertEqual(data["plugin"]["owners"], ["a"])
        self.assertEqual(data["plugin"]["secrets"], {"KEY": "x"})
        self.assertEqual(self.CURRENT["plugin"]["commit"], "old")

    def test_render_round_trips_through_toml(self):
        data = manifest.updated(self.CURRENT, repository="", commit="abc", owners=[], maintainers=[], project_path="", changelog="Quotes \"here\" and 'there'.\n\n- Item \\ with backslash")
        text = manifest.render(data)
        self.assertTrue(text.startswith('[plugin]\nrepository = "https://github.com/a/b.git"\ncommit = "abc"'))
        self.assertEqual(tomllib.loads(text), data)

    def test_changelog_with_triple_single_quotes_still_round_trips(self):
        data = manifest.updated(None, repository="r", commit="c", owners=["o"], maintainers=[], project_path="p", changelog="It's '''odd'''\nsecond \"\"\" line")
        self.assertEqual(tomllib.loads(manifest.render(data)), data)

    def test_new_manifest_without_changelog(self):
        data = manifest.updated(None, repository="r", commit="c", owners=["o"], maintainers=["m"], project_path="p", changelog=None)
        self.assertEqual(data, {"plugin": {"repository": "r", "commit": "c", "owners": ["o"], "maintainers": ["m"], "project_path": "p"}})


class CheckHelperTests(unittest.TestCase):
    def test_png_size(self):
        self.assertEqual(checks.png_size(png(512, 512)), (512, 512))
        self.assertIsNone(checks.png_size(b"GIF89a..."))

    def test_csproj_version(self):
        self.assertEqual(checks.csproj_version("<PropertyGroup>\n  <Version>1.2.0.0</Version>\n</PropertyGroup>"), "1.2.0.0")
        self.assertIsNone(checks.csproj_version("<Project />"))

    def test_versions_compare_as_numbers(self):
        self.assertGreater(checks.version_key("1.10.0.0"), checks.version_key("1.9.0.0"))

    def test_lock_file_must_pin_every_reference(self):
        csproj = '<PackageReference Include="A" Version="1.0.0" />\n<PackageReference Include="B" Version="2.0.0" />\n<PackageReference Include="C" Version="3.0.0" />'
        lock = {"dependencies": {"net10.0-windows7.0": {
            "A": {"type": "Direct", "resolved": "1.0.0"},
            "B": {"type": "Direct", "resolved": "2.1.0"},
            "DalamudPackager": {"type": "Direct", "resolved": "15.0.0"},
        }}}
        self.assertEqual(checks.lock_mismatches(csproj, lock), ["B is 2.0.0 in the project but 2.1.0 in the lock file", "C is not in the lock file"])


class DraftTests(unittest.TestCase):
    def test_only_the_description_is_sent_and_placeholders_block_it(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "draft.md"
            draft.write(path, title="My Plugin 1.0.0.0", branch="my-plugin/testing/1.0.0.0", notes=["- Commit: abc"])
            with self.assertRaises(draft.DraftError):
                draft.read(path)

            text = path.read_text(encoding="utf-8")
            start = text.index(draft.DESCRIPTION_MARKER) + len(draft.DESCRIPTION_MARKER)
            end = text.index(draft.NOTES_MARKER)
            path.write_text(text[:start] + "\n\nWritten by me.\n\n" + text[end:], encoding="utf-8")
            result = draft.read(path)
            self.assertEqual((result.title, result.branch, result.description), ("My Plugin 1.0.0.0", "my-plugin/testing/1.0.0.0", "Written by me."))

    def test_a_description_longer_than_discord_takes_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "draft.md"
            draft.write(path, title="My Plugin 1.0.0.0", branch="my-plugin/testing/1.0.0.0", notes=[])
            text = path.read_text(encoding="utf-8")
            start = text.index(draft.DESCRIPTION_MARKER) + len(draft.DESCRIPTION_MARKER)
            end = text.index(draft.NOTES_MARKER)

            def with_description(description: str) -> None:
                path.write_text(text[:start] + "\n\n" + description + "\n\n" + text[end:], encoding="utf-8")

            with_description("a" * draft.MAX_DESCRIPTION)
            self.assertEqual(len(draft.read(path).description), draft.MAX_DESCRIPTION)

            with_description("a" * (draft.MAX_DESCRIPTION - 1) + "🎵")
            with self.assertRaisesRegex(draft.DraftError, f"{draft.MAX_DESCRIPTION + 1} characters"):
                draft.read(path)


if __name__ == "__main__":
    unittest.main()
