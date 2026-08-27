#!/usr/bin/env python3
"""Sync a CNCF project's dot-project files into this repo from a source.

Pull model, not push: reads a sync-dot-project.yml config (a source repo
org/repo@branch plus a list of files), fetches those files from the source,
generates OWNERS (from the source's maintainers.yaml, filtered to this repo)
and CONTRIBUTING.md (rendered from the source template), and writes them into
the working tree. A peter-evans/create-pull-request step then proposes the
changes as a reviewed PR. Dry-run by default: the script logs what would
change, the action opens nothing.

A complex OWNERS in this repo (filters, aliases, wildcards) is left alone,
never overwritten.
"""
import argparse
import base64
import os
import subprocess
import sys
import yaml
from pathlib import Path

# project-maintainers is CNCF-backed metadata, not an OWNERS role.
SKIP_TEAMS = {"project-maintainers"}


def gh_api(url):
    return subprocess.run(
        ["gh", "api", url, "--jq", ".content"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def gh_content(org, repo, branch, path):
    try:
        b64 = gh_api(f"repos/{org}/{repo}/contents/{path}?ref={branch}")
        return base64.b64decode(b64).decode()
    except subprocess.CalledProcessError:
        return None


def parse_source(source):
    org, _, rest = source.partition("/")
    repo, _, branch = rest.partition("@")
    return org, repo, branch or "main"


def is_simple_owners(text):
    """True if the OWNERS is the flat role->usernames form we can regenerate.
    Anything else (filters, aliases, wildcards, nested keys) is complex and
    must not be overwritten."""
    if text is None:
        return True
    for line in text.splitlines():
        s = line.rstrip()
        if not s.strip() or s.strip().startswith("#"):
            continue
        if not line.startswith(" "):
            if not s.endswith(":") or not s.strip().rstrip(":").isidentifier():
                return False
        else:
            if not s.lstrip().startswith("- "):
                return False
            member = s.lstrip()[2:].strip()
            if not member or "/" in member or "*" in member or member.endswith(":"):
                return False
    return True


def parse_owners(text):
    roles, role = {}, None
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if not line.startswith(" "):
            role = line.rstrip(":")
        else:
            roles.setdefault(role, []).append(line.strip().lstrip("- "))
    return roles


def gen_owners(local):
    lines = []
    for role, members in local.items():
        if not members:
            continue
        lines.append(f"{role}:")
        lines += [f"  - {m}" for m in members]
    return "\n".join(lines) + "\n"


def render(text, org, repo, placeholder):
    out = text.replace("@ORG@", org).replace("@REPO@", repo)
    return out.replace(placeholder, f"{org}/{repo}") if placeholder else out


def generate(config, src_org, src_repo, branch, this_org, this_repo,
             placeholder, fetch, cur_owners):
    """Return (ops, skipped): ops is a list of (path, content) to write, skipped
    lists OWNERS paths left alone because the current file is complex."""
    files = config.get("files", [])
    ops, skipped = [], []

    local = {}
    if "OWNERS" in files:
        src = fetch(src_org, src_repo, branch, "maintainers.yaml") or ""
        roster = yaml.safe_load(src) or {}
        entry = next((e for e in roster.get("maintainers", [])
                      if e.get("project_id") == this_repo), {})
        teams = {t["name"]: t.get("members", [])
                 for t in entry.get("teams", [])}
        local = {k: v for k, v in teams.items() if k not in SKIP_TEAMS}

    for path in files:
        if path == "OWNERS":
            if cur_owners is not None and not is_simple_owners(cur_owners):
                skipped.append(path)
                continue
            content = gen_owners(local)
            if content.strip():
                ops.append((path, content))
        elif path == "CONTRIBUTING.md":
            tmpl = fetch(src_org, src_repo, branch, "CONTRIBUTING.md")
            if tmpl is not None:
                ops.append((path, render(tmpl, this_org, this_repo, placeholder)))
        else:
            content = fetch(src_org, src_repo, branch, path)
            if content is not None:
                ops.append((path, content))
    return ops, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="sync-dot-project.yml")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--placeholder", default="")
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text()) or {}
    if not args.repo or "/" not in args.repo:
        print("GITHUB_REPOSITORY (org/repo) not set and --repo not given",
              file=sys.stderr)
        sys.exit(1)
    this_org, _, this_repo = args.repo.partition("/")
    src_org, src_repo, branch = parse_source(config["source"])

    cur_owners = None
    if Path("OWNERS").exists():
        cur_owners = Path("OWNERS").read_text()

    ops, skipped = generate(config, src_org, src_repo, branch,
                            this_org, this_repo, args.placeholder,
                            gh_content, cur_owners)

    for _ in skipped:
        print("OWNERS: complex (filters/aliases/wildcards) - skipping, not touching")
    for path, content in ops:
        target = Path(path)
        if target.exists() and target.read_text() == content:
            print(f"{path}: no change")
            continue
        existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        print(f"{path}: {'new' if not existed else 'changed'}")


if __name__ == "__main__":
    main()
