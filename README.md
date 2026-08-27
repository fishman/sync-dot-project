# sync-dot-project

A reusable GitHub Action that keeps a CNCF project's dot-project files in sync
using the safe pull model: the action runs in **each** target repo, reads FROM
a source dot-project repo, and proposes changes as a **reviewed pull request**
instead of pushing them. Dry-run by default.

## Why pull, not push

Pushing to every repo from one workflow requires an org-wide write PAT held in
a single place. Compromise that repo or leak the token and an attacker writes
the default branch of the whole org with zero review. The pull model collapses
the blast radius to one repo:

- The action runs per target repo with the repo-scoped default `GITHUB_TOKEN`.
  No org-wide secret exists anywhere.
- A compromised source can at most *propose* a PR. Changes pass the target
  repo's normal review and required checks before merge.
- Changes are auditable, revertible, and gated.

Cost: the workflow lives in every repo you want synced (one workflow file per
repo). That is the price of repo-scoped tokens.

## How it works

```
[source dot-project repo]  --read-->  [this action in each target repo]  --PR-->  [target default branch]
```

The action reads a `sync-dot-project.yml` config that names the source
(`org/repo@branch`) and the files to sync. For each file:

- `OWNERS` is generated from the source's `maintainers.yaml`, filtered to this
  repo (every team except `project-maintainers`, which is CNCF metadata).
- `CONTRIBUTING.md` is rendered from the source's CONTRIBUTING template, with
  `@ORG@` / `@REPO@` substituted for this repo.
- any other file (LICENSE, CODE_OF_CONDUCT.md, SECURITY.md) is copied verbatim.

The generated files land in the working tree; `peter-evans/create-pull-request`
turns them into a PR. It no-ops when there is no change.

## Usage

Add this workflow to each repo you want synced:

```yaml
# .github/workflows/sync.yml
name: Sync Dot-Project
on:
  schedule:
    - cron: "0 7 * * 1"
  workflow_dispatch:
permissions:
  contents: write
  pull-requests: write
jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: your-org/sync-dot-project@v1
        with:
          config: sync-dot-project.yml
```

And a config at the repo root:

```yaml
# sync-dot-project.yml
source: my-org/dot-project@main
files:
  - LICENSE
  - CODE_OF_CONDUCT.md
  - SECURITY.md
  - OWNERS
  - CONTRIBUTING.md
```

The `source` is `org/repo@branch`. The branch matters: it is how you point the
action at a specific revision (including test branches) rather than always the
live default.

The action is **dry-run by default**: it writes the generated files and lets
`create-pull-request` report the diff without opening a PR. Set `dry-run: false`
once you have reviewed a dry-run log.

## Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `config` | `sync-dot-project.yml` | Path to the config (source + files list) |
| `dry-run` | `true` | Log the proposed diff without opening a PR |
| `pr-branch` | `sync-dot-project` | Branch the PR is based on |
| `title` | `chore: sync dot-project files` | PR title |
| `commit-message` | `chore: sync dot-project files` | Commit message |
| `placeholder` | `` (disabled) | Legacy: a literal `{org}/{repo}` string in the CONTRIBUTING template replaced with this repo, for templates that hardcode one (e.g. `Project-HAMi/.project`). Prefer `@ORG@/@REPO@` |

There is no `token` input: the action uses the repo-scoped `GITHUB_TOKEN`.

## The source repo

The source dot-project repo holds the canonical files the action pulls:

- `maintainers.yaml` - the org-wide roster, with an entry per repo
  (`project_id`). OWNERS is generated from the entry matching this repo.
- `CONTRIBUTING.md` - a template using `@ORG@/@REPO@` (see below).
- `LICENSE`, `CODE_OF_CONDUCT.md`, `SECURITY.md` - copied verbatim.

### Variables

Templates use `@ORG@` / `@REPO@`, substituted per target repo, so one template
serves every repo:

```markdown
Issues live at https://github.com/@ORG@/@REPO@/issues
```

Rendered for `my-org/repo-a`: `https://github.com/my-org/repo-a/issues`.

If you are migrating a template that hardcodes a literal `{org}/{repo}` string
(e.g. `Project-HAMi/.project`), set the `placeholder` input to that string to
keep it working. It is disabled by default; new templates use `@ORG@/@REPO@`.

## Limitations

The OWNERS generator writes the simple flat form only (`approvers:` /
`reviewers:` sections). Complex OWNERS files are not regenerated:

- **`filters:` blocks** (regex-scoped rules, as used at the root of
  kubernetes/kubernetes) - the action detects these and leaves the file alone
  rather than overwriting it with a flat one. Verified against
  `kubernetes/kubernetes` OWNERS in `test/`.
- **`OWNERS_ALIASES`** resolution - members must be literal usernames in
  `maintainers.yaml`, not alias references. Alias references, wildcards, and
  nested keys are flagged as complex and skipped.

A target repo with a complex OWNERS is reported as "skipping, not touching";
the file is never overwritten. Generating complex OWNERS is not supported yet.

See `example/` for starter files to copy and fill in.
