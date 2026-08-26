#!/usr/bin/env python3
"""Offline dry-run tests of sync.py against committed reference fixtures.

Each scenario has two distinct inputs, so the comparison is old-remote vs
processed-local (not a file compared to itself):
  - the LOCAL source files (maintainers.yaml, CONTRIBUTING template, static
    sources) that sync.py processes,
  - the OLD REMOTE snapshot (what the target repo currently has on GitHub).

The remote fetch is stubbed to serve the remote snapshot, so no network or
GH_TOKEN is needed. run_dry() is shared; adding a scenario is one dict.

Run:  python3 test/test_sync.py
"""
import contextlib
import importlib.util
import io
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYNC = HERE.parent / "sync.py"

SCENARIOS = [
    dict(
        name="kubernetes",
        remote="kubernetes-kubernetes",
        org="kubernetes",
        maintainers="config/maintainers.yaml",
        static="config/repo-file-sync.yml",
        template="config/CONTRIBUTING.md",
        placeholder="kubernetes/.project",
        present=[
            "kubernetes/kubernetes OWNERS:",
            "complex OWNERS",  # filter-based OWNERS detected and skipped
            "CONTRIBUTING.md:",
            "would change:",
            "+Stub CONTRIBUTING template for the test",
            "LICENSE:",
            "+Placeholder LICENSE for the offline test",
        ],
        absent=["+alice-approver", "+bob-approver", "pushed"],
    ),
    dict(
        name="project-hami",
        remote="remote-hami",  # Project-HAMi/HAMi's real current files
        org="Project-HAMi",
        maintainers="config/hami/maintainers.yaml",  # single repo: Project-HAMi/HAMi
        static="config/hami/repo-file-sync.yml",
        template="fixtures/Project-HAMi-HAMi/CONTRIBUTING.md",
        placeholder="Project-HAMi/.project",
        present=[
            "Project-HAMi/HAMi OWNERS:",
            "OWNERS: no change",
            "Project-HAMi/HAMi CONTRIBUTING.md:",
            "would change:",
            "CODE_OF_CONDUCT.md:",
            "SECURITY.md:",
        ],
        absent=["pushed"],
    ),
]


def load():
    spec = importlib.util.spec_from_file_location("sync", SYNC)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_dry(m, s):
    remote_dir = HERE / "fixtures" / s["remote"]
    out = io.StringIO()
    old_fetch, old_cwd, old_argv = m.gh_content, os.getcwd(), sys.argv
    m.gh_content = lambda org, repo, branch, path: (
        (remote_dir / path).read_text() if (remote_dir / path).exists() else None)
    os.chdir(HERE)
    sys.argv = ["sync.py", "--org", s["org"],
                "--maintainers", str(HERE / s["maintainers"]),
                "--static-config", str(HERE / s["static"]),
                "--template", str(HERE / s["template"]),
                "--placeholder", s["placeholder"]]
    try:
        with contextlib.redirect_stdout(out):
            m.main()
    finally:
        m.gh_content = old_fetch
        os.chdir(old_cwd)
        sys.argv = old_argv
    return out.getvalue()


def main():
    m = load()

    k8s = (HERE / "fixtures" / "kubernetes-kubernetes" / "OWNERS").read_text()
    assert not m.is_simple_owners(k8s), "k8s filter-based OWNERS must be flagged complex"
    assert m.is_simple_owners("approvers:\n  - alice\nreviewers:\n  - bob\n"), \
        "flat OWNERS must be flagged simple"

    # @ORG@/@REPO@ variables and legacy placeholder fallback.
    assert m.render("https://@ORG@/@REPO@/issues", "my-org", "repo-a", "") == \
        "https://my-org/repo-a/issues"
    assert m.render("see Project-HAMi/.project", "Project-HAMi", "HAMi", "Project-HAMi/.project") == \
        "see Project-HAMi/HAMi"
    # The project-hami scenario exercises the legacy placeholder: the HAMi
    # CONTRIBUTING template's literal Project-HAMi/.project is replaced.
    hami_tmpl = (HERE / "fixtures" / "Project-HAMi-HAMi" / "CONTRIBUTING.md").read_text()
    rendered = m.render(hami_tmpl, "Project-HAMi", "HAMi", "Project-HAMi/.project")
    assert "Project-HAMi/.project" not in rendered
    assert "Project-HAMi/HAMi" in rendered

    for s in SCENARIOS:
        out = run_dry(m, s)
        print(f"\n=== {s['name']} ===")
        print(out)
        for expected in s["present"]:
            assert expected in out, f"[{s['name']}] missing: {expected}"
        for unexpected in s["absent"]:
            assert unexpected not in out, f"[{s['name']}] unexpectedly present: {unexpected}"

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
