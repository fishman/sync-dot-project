# cncf-sync-dot-project

A single reusable GitHub Action that syncs a CNCF project's dot-project files to
every repo in its org. One action, one dry-run-by-default pass:

- **Static community files** (`LICENSE`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, ...)
  from a `repo-file-sync.yml` config.
- **Per-repo `OWNERS` + `CONTRIBUTING.md`** generated from a `maintainers.yaml`
  roster (every team except `project-maintainers` maps to an OWNERS section of
  the same name; `project-maintainers` is CNCF metadata and is skipped).

## Usage

```yaml
- uses: your-org/cncf-sync-dot-project@main
  with:
    org: my-org
    token: ${{ secrets.ORG_PAT }}
```

The action is **dry-run by default**: it fetches each repo's current files and
logs member additions/removals (for OWNERS) and which files would change, but
writes and pushes nothing. Set `dry-run: false` to actually push.

## Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `org` | required | GitHub org whose repos receive the files |
| `token` | required | PAT with contents write access - always pass a **secret** (e.g. `${{ secrets.ORG_PAT }}`), never a literal |
| `static-config` | `repo-file-sync.yml` | Static file-sync config (group/files/repos) |
| `maintainers-file` | `maintainers.yaml` | Maintainer roster |
| `contributing-template` | `CONTRIBUTING.md` | CONTRIBUTING template |
| `placeholder` | `Project-HAMi/.project` | String in the template replaced with `{org}/{repo}` |
| `branch` | `main` | Branch to push to |
| `dry-run` | `true` | Log diffs without writing or pushing |

## Config formats

`repo-file-sync.yml` (static files):

```yaml
group:
  - files:
      - source: LICENSE
        dest: LICENSE
      - source: SECURITY.md
        dest: SECURITY.md
    repos:
      - my-org/repo-a
      - my-org/repo-b
```

`maintainers.yaml` (OWNERS + CONTRIBUTING):

```yaml
maintainers:
  - project_id: "repo-a"
    org: "my-org"
    teams:
      - name: "project-maintainers"   # CNCF metadata, not written to OWNERS
        members:
          - alice
      - name: "approvers"
        members:
          - alice
          - bob
      - name: "reviewers"
        members:
          - carol
```

Each repo gets an `OWNERS` with a section per team (minus `project-maintainers`),
and a `CONTRIBUTING.md` rendered from the template with `placeholder` replaced by
`{org}/{repo}`.

See `example/` for starter files to copy and fill in.

## Limitations

The OWNERS generator writes the simple flat form only (`approvers:` /
`reviewers:` sections). Complex OWNERS files are not regenerated:

- **`filters:` blocks** (regex-scoped rules, as used at the root of
  kubernetes/kubernetes) - the sync detects these and leaves the file alone
  rather than overwriting it with a flat one. Verified against
  `kubernetes/kubernetes` OWNERS in `test/`.
- **`OWNERS_ALIASES`** resolution - members must be literal usernames in
  `maintainers.yaml`, not alias references. Alias references, wildcards, and
  nested keys are flagged as complex and skipped.

A target repo with a complex OWNERS is detected and reported as "skipping, not
touching"; the file is never overwritten. Generating complex OWNERS is not
supported yet.
