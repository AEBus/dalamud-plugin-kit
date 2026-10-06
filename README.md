# dalamud-plugin-kit

Tools for publishing Dalamud plugins in the official repository, [goatcorp/DalamudPluginsD17](https://github.com/goatcorp/DalamudPluginsD17): CI workflows that build a plugin the way D17 does, and a small command line tool, `d17`, that checks a release and prepares its pull request.

The tool never writes the pull request description. D17's [AI usage policy](https://dalamud.dev/plugin-publishing/ai-policy) asks that the description and the AI disclosure are written by a person, so `d17 prepare` leaves a draft with placeholders and notes, and `d17 open` refuses to open the pull request while a placeholder is left.

## Workflows for plugin repositories

Copy [`templates/plugin-ci.yml`](templates/plugin-ci.yml) to `.github/workflows/ci.yml` in the plugin's repository and fill in the paths. It calls two reusable workflows:

- [`build.yml`](.github/workflows/build.yml) restores packages strictly from the committed `packages.lock.json` (`--locked-mode`), as D17 builds offline from it, and builds Release against the stable Dalamud release.
- [`plogon.yml`](.github/workflows/plogon.yml) builds the pushed commit with [Plogon](https://github.com/goatcorp/Plogon), D17's builder, in development mode: the same container image, no network during the build, and the icon checked. A green run means D17's bot will build the same commit.

Plugins in D17 are built from source, so there is no need to publish zip files in GitHub releases.

## The `d17` command

Needs Python 3.11 or newer, git and an authenticated [GitHub CLI](https://cli.github.com/) (`gh auth login`). For `--plogon`, also Docker and the .NET SDK.

Setup:

1. Fork goatcorp/DalamudPluginsD17 once (one fork serves every plugin), clone it, and add the original as the `upstream` remote.
2. Copy `local.example.toml` to `local.toml` and set your fork, its clone, and where each plugin is cloned.
3. Add a file to `plugins/` for each plugin (see the existing ones).

A release, from the plugin's repository to the pull request:

1. Bump the version in the `.csproj`, add a `## <version>` section to the plugin's `CHANGELOG.md`, commit and push.
2. `python -m d17 check <plugin> [--ref <commit or tag>] [--track testing|stable] [--plogon]` checks that commit:
   - it is in the public repository, which Plogon clones;
   - its version is a fixed number, newer than the build the track has now;
   - the lock file pins every package reference;
   - the json manifest has no fields Plogon sets itself (`DalamudApiLevel`, `TestingDalamudApiLevel`, `ApplicableVersion`);
   - the icon is a square PNG from 64 to 512 pixels;
   - the changelog has a section for the version;
   - optionally, that the README, changelog and manifest do not name things they must not, and that the plugin's own check command passes.
3. `python -m d17 prepare <plugin>` runs the checks, then creates a new branch `<plugin>/<track>/<version>` from upstream `main` in your fork, writes `manifest.toml` (the commit, the changelog section, the icon), pushes it and writes `drafts/<plugin>-<track>-<version>.md`.
4. Write the description in the draft yourself. The notes below it (what changed since the last build, new packages, newly named hosts, the changelog) are never sent.
5. `python -m d17 open <plugin>` opens the pull request with your description.
6. `python -m d17 status [<plugin>]` lists your pull requests with the bot's build result and reviewers' comments. To rebuild a pull request, comment `bleatbot, rebuild` on it.
7. After some time in testing, `python -m d17 promote <plugin>` submits the testing build to stable.

## The changelog

The plugin installer shows the `changelog` of `manifest.toml` as plain text, so write each version's section as a summary line followed by `- ` items. `d17 prepare` copies the section of the submitted version into the manifest; the plugin itself can embed the same `CHANGELOG.md` and show it in its settings.

## Tests

```
python -m unittest discover -s tests
```

## License

[GPL-3.0](LICENSE), with one exception: the files in [`templates/`](templates) are meant to be copied into your own repositories, so they are released under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) (public domain). Copy and change them under any license, without attribution.

Calling the reusable workflows or running `d17` places no license terms on your plugin.
