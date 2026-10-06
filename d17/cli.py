"""Command line: python -m d17 <command> ..."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from d17 import checks, config, draft, manifest, plogon, shell, submit
from d17.checks import ERROR, OK, SKIP, WARN, Submission

_MARKS = {OK: "ok  ", WARN: "warn", ERROR: "FAIL", SKIP: "skip"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="d17", description="Submit Dalamud plugins to the official repository (goatcorp/DalamudPluginsD17).")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="check a plugin commit before submitting it")
    _add_plugin_args(check)
    check.add_argument("--plogon", action="store_true", help="also build it with Plogon locally (needs Docker)")

    prepare = commands.add_parser("prepare", help="check, then create the branch in your fork and a draft for the pull request")
    _add_plugin_args(prepare)
    prepare.add_argument("--plogon", action="store_true", help="also build it with Plogon locally first (needs Docker)")
    prepare.add_argument("--no-push", action="store_true", help="commit the branch but do not push it")
    prepare.add_argument("--dry-run", action="store_true", help="only print the manifest that would be submitted")

    promote = commands.add_parser("promote", help="submit the build on the testing track to stable")
    promote.add_argument("plugin")
    promote.add_argument("--no-push", action="store_true")

    open_ = commands.add_parser("open", help="open the pull request from a draft you have written")
    open_.add_argument("plugin")
    open_.add_argument("--draft", help="the draft file (default: the plugin's newest)")

    status = commands.add_parser("status", help="your pull requests on D17, with bot results and review comments")
    status.add_argument("plugin", nargs="?")

    args = parser.parse_args(argv)
    try:
        settings = config.load()
        return _COMMANDS[args.command](settings, args)
    except (config.ConfigError, shell.CommandError, submit.SubmitError, draft.DraftError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _add_plugin_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("plugin", help="internal name, slug or name from plugins/")
    parser.add_argument("--ref", default="HEAD", help="commit, tag or branch in the plugin's clone (default: HEAD)")
    parser.add_argument("--track", choices=sorted(config.TRACKS), default="testing")


def _submission(settings: config.Settings, name: str, ref: str, track: str) -> Submission:
    plugin = settings.plugin(name)
    if plugin.path is None:
        raise config.ConfigError(f"local.toml has no path for {plugin.internal_name}")
    sha = shell.git(plugin.path, "rev-parse", f"{ref}^{{commit}}")
    return Submission(plugin=plugin, repo=plugin.path, sha=sha, track=track)


def _report(s: Submission) -> None:
    print(f"{s.plugin.name} at {s.sha[:12]} for {s.track}")
    for result in s.results:
        print(f"  {_MARKS[result.level]}  {result.name}: {result.message}")


def _run_checks(s: Submission, with_plogon: bool, allow_new_stable: bool = False) -> bool:
    checks.run_all(s, allow_new_stable=allow_new_stable)
    if with_plogon and not s.failed:
        icon = s.file(s.plugin.icon) or b""
        ok, artifacts = plogon.build(s.plugin, s.sha, icon)
        s.add("plogon", OK if ok else ERROR, f"artifacts in {artifacts}")
    _report(s)
    return not s.failed


def _check(settings: config.Settings, args: argparse.Namespace) -> int:
    s = _submission(settings, args.plugin, args.ref, args.track)
    return 0 if _run_checks(s, args.plogon) else 1


def _prepare(settings: config.Settings, args: argparse.Namespace, s: Submission | None = None, allow_new_stable: bool = False) -> int:
    s = s or _submission(settings, args.plugin, args.ref, args.track)
    if not _run_checks(s, getattr(args, "plogon", False), allow_new_stable):
        print("Not prepared: fix the failures above.")
        return 1
    if getattr(args, "dry_run", False):
        print(f"\n{s.plugin.manifest_dir(s.track)}/manifest.toml on branch {submit.branch_name(s)}:\n")
        print(submit.manifest_text(s))
        return 0
    branch, path = submit.prepare(settings, s, push=not args.no_push)
    print(f"\nBranch {branch} is {'pushed to ' + settings.fork if not args.no_push else 'committed locally'}.")
    print(f"Write the pull request description in {path}, then run: python -m d17 open {s.plugin.internal_name}")
    return 0


def _promote(settings: config.Settings, args: argparse.Namespace) -> int:
    plugin = settings.plugin(args.plugin)
    testing = manifest.parse(shell.github_file(config.UPSTREAM, f"{plugin.manifest_dir('testing')}/manifest.toml"))
    commit = (testing or {}).get("plugin", {}).get("commit")
    if not commit:
        raise submit.SubmitError(f"{plugin.internal_name} has no build on the testing track")
    s = _submission(settings, args.plugin, commit, "stable")
    return _prepare(settings, args, s, allow_new_stable=True)


def _open(settings: config.Settings, args: argparse.Namespace) -> int:
    plugin = settings.plugin(args.plugin)
    path = Path(args.draft) if args.draft else draft.latest_for(plugin.slug)
    print(submit.open_pull_request(settings, path))
    return 0


def _status(settings: config.Settings, args: argparse.Namespace) -> int:
    slug = settings.plugin(args.plugin).slug if args.plugin else None
    for line in submit.status(settings, slug) or ["No pull requests."]:
        print(line)
    return 0


_COMMANDS = {"check": _check, "prepare": _prepare, "promote": _promote, "open": _open, "status": _status}
