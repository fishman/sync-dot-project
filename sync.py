#!/usr/bin/env python3
"""Sync dot-project files to every repo in an org.

Two jobs in one pass:
  1. Static community files from repo-file-sync.yml (group/files/repos).
  2. Per-repo OWNERS + CONTRIBUTING.md generated from maintainers.yaml.

Dry-run by default: logs member additions/removals and file diffs against the
live repos, pushes nothing. Pass --push to write. Pushing requires GH_TOKEN.
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


def put_file(org, repo, branch, path, content):
    url = f"repos/{org}/{repo}/contents/{path}"
    subprocess.run(
        ["gh", "api", url, "-X", "PUT", "-f", "message=sync: update {path}",
         "-f", f"content={base64.b64encode(content.encode()).decode()}",
         "-f", f"branch={branch}"],
        capture_output=True, text=True, check=True,
    )


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


def owners_diff(local, remote):
    if remote is None:
        return f"OWNERS: new file ({sum(map(len, local.values()))} members)"
    remote_roles = parse_owners(remote)
    out = []
    for role, members in local.items():
        cur = remote_roles.get(role, [])
        add = [m for m in members if m not in cur]
        rem = [m for m in cur if m not in members]
        if add:
            out.append(f"  {role} +{', +'.join(add)}")
        if rem:
            out.append(f"  {role} -{', -'.join(rem)}")
    for role, cur in remote_roles.items():
        if role not in local and cur:
            out.append(f"  {role} -{', -'.join(cur)} (whole role removed)")
    return "\n".join(out) if out else "OWNERS: no change"


class Op:
    __slots__ = ("org", "repo", "path", "content", "members")

    def __init__(self, org, repo, path, content, members=None):
        self.org = org
        self.repo = repo
        self.path = path
        self.content = content
        self.members = members  # filtered role dict for OWNERS ops, else None


def plan(maintainers, static, tmpl, org_default, placeholder):
    ops = []
    for entry in maintainers.get("maintainers", []):
        repo = entry["project_id"]
        org = entry.get("org", org_default)
        teams = {t["name"]: t.get("members", []) for t in entry.get("teams", [])}
        local = {k: v for k, v in teams.items() if k not in SKIP_TEAMS}
        owners = gen_owners(local)
        if owners.strip():
            ops.append(Op(org, repo, "OWNERS", owners, members=local))
        ops.append(Op(org, repo, "CONTRIBUTING.md",
                      tmpl.replace(placeholder, f"{org}/{repo}")))
    for group in static.get("group", []):
        for repo_str in group["repos"]:
            org, _, repo = repo_str.partition("/")
            for f in group["files"]:
                src = Path(f["source"])
                if src.exists():
                    ops.append(Op(org, repo, f["dest"], src.read_text()))
    return ops


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True, help="default GitHub org")
    parser.add_argument("--static-config", default="repo-file-sync.yml")
    parser.add_argument("--maintainers", default="maintainers.yaml")
    parser.add_argument("--template", default="CONTRIBUTING.md")
    parser.add_argument("--placeholder", default="Project-HAMi/.project",
                        help="string in the template replaced with {org}/{repo}")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--push", action="store_true",
                        help="actually push (dry-run is the default)")
    args = parser.parse_args()

    maintainers = yaml.safe_load(Path(args.maintainers).read_text()) or {}
    static = {}
    if Path(args.static_config).exists():
        static = yaml.safe_load(Path(args.static_config).read_text()) or {}
    tmpl = Path(args.template).read_text()

    if args.push and not os.environ.get("GH_TOKEN"):
        print("GH_TOKEN required to push", file=sys.stderr)
        sys.exit(1)

    for op in plan(maintainers, static, tmpl, args.org, args.placeholder):
        print(f"{op.org}/{op.repo} {op.path}:")
        cur = gh_content(op.org, op.repo, args.branch, op.path)
        if cur == op.content:
            print("  no change")
            continue
        if not args.push:
            if op.members is not None:
                print("  " + owners_diff(op.members, cur))
            else:
                print("  would change")
        else:
            put_file(op.org, op.repo, args.branch, op.path, op.content)
            print("  pushed")


if __name__ == "__main__":
    main()
