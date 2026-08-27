#!/usr/bin/env python3
"""Offline dry-run tests of sync.py for the pull model.

The action pulls dot-project files FROM a source repo and proposes them as a
PR. These tests stub the source fetch (gh_content) to serve committed fixtures,
so no network or GH_TOKEN is needed, then run sync.py inside a throwaway target
dir seeded with the target's current files. run() is shared; a scenario is one
dict.

Run:  python3 test/test_sync.py
"""
import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import yaml
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYNC = HERE.parent / "sync.py"
FIX = HERE / "fixtures"

SCENARIOS = [
    dict(
        name="project-hami",
        source="Project-HAMi-HAMi",     # the dot-project source repo
        target="remote-hami",           # current state of Project-HAMi/HAMi
        repo="Project-HAMi/HAMi",
        placeholder="Project-HAMi/.project",
        files=["OWNERS", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md"],
        present=["OWNERS: changed", "CONTRIBUTING.md: changed",
                 "CODE_OF_CONDUCT.md:", "SECURITY.md:"],
        absent=["complex", "project-maintainers"],
    ),
    dict(
        name="kubernetes-complex",
        source="Project-HAMi-HAMi",     # roster only used if OWNERS regenerated
        target="kubernetes-kubernetes",  # has a complex (filter) OWNERS on disk
        repo="kubernetes/kubernetes",
        placeholder="Project-HAMi/.project",
        files=["OWNERS", "CONTRIBUTING.md"],
        present=["OWNERS: complex (filters/aliases/wildcards) - skipping",
                 "CONTRIBUTING.md: changed"],
        absent=["OWNERS: changed", "OWNERS: new"],
    ),
]


def load():
    spec = importlib.util.spec_from_file_location("sync", SYNC)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run(m, s):
    src_dir = FIX / s["source"]
    tgt_dir = FIX / s["target"]
    out = io.StringIO()
    work = Path(tempfile.mkdtemp(prefix="sync-test-"))
    for f in tgt_dir.iterdir():
        shutil.copy2(f, work / f.name)
    (work / "sync-dot-project.yml").write_text(
        "source: fixture/project@fixtures\n"
        + "files:\n" + "".join(f"  - {f}\n" for f in s["files"]))

    old_fetch, old_cwd, old_argv = m.gh_content, os.getcwd(), sys.argv
    m.gh_content = lambda org, repo, branch, path: (
        (src_dir / path).read_text() if (src_dir / path).exists() else None)
    os.chdir(work)
    sys.argv = ["sync.py", "--config", "sync-dot-project.yml",
                "--repo", s["repo"], "--placeholder", s["placeholder"]]
    try:
        with contextlib.redirect_stdout(out):
            m.main()
    finally:
        m.gh_content = old_fetch
        os.chdir(old_cwd)
        sys.argv = old_argv
    return out.getvalue(), work


def expected_hami_owners(m):
    roster = yaml.safe_load((FIX / "Project-HAMi-HAMi" / "maintainers.yaml").read_text())
    entry = next(e for e in roster["maintainers"] if e["project_id"] == "HAMi")
    teams = {t["name"]: t.get("members", []) for t in entry["teams"]}
    local = {k: v for k, v in teams.items() if k != "project-maintainers"}
    return m.gen_owners(local)


def main():
    m = load()

    assert m.parse_source("org/repo@branch") == ("org", "repo", "branch")
    assert m.parse_source("org/repo") == ("org", "repo", "main")

    assert m.render("https://@ORG@/@REPO@/issues", "my-org", "repo-a", "") == \
        "https://my-org/repo-a/issues"
    assert m.render("see Project-HAMi/.project", "Project-HAMi", "HAMi",
                    "Project-HAMi/.project") == "see Project-HAMi/HAMi"

    k8s = (FIX / "kubernetes-kubernetes" / "OWNERS").read_text()
    assert not m.is_simple_owners(k8s), "k8s filter-based OWNERS must be complex"
    assert m.is_simple_owners("approvers:\n  - alice\nreviewers:\n  - bob\n"), \
        "flat OWNERS must be simple"

    hami_owners = expected_hami_owners(m)
    assert "project-maintainers" not in hami_owners

    for s in SCENARIOS:
        out, work = run(m, s)
        print(f"\n=== {s['name']} ===")
        print(out)
        for expected in s["present"]:
            assert expected in out, f"[{s['name']}] missing: {expected}"
        for unexpected in s["absent"]:
            assert unexpected not in out, f"[{s['name']}] unexpected: {unexpected}"

        if s["name"] == "project-hami":
            assert (work / "OWNERS").read_text() == hami_owners
            contrib = (work / "CONTRIBUTING.md").read_text()
            assert "Project-HAMi/.project" not in contrib
            assert "Project-HAMi/HAMi" in contrib
            for f in ["CODE_OF_CONDUCT.md", "SECURITY.md"]:
                assert (work / f).read_text() == (FIX / s["source"] / f).read_text()
        if s["name"] == "kubernetes-complex":
            assert (work / "OWNERS").read_text() == (FIX / s["target"] / "OWNERS").read_text()
        shutil.rmtree(work, ignore_errors=True)

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
