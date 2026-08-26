#!/usr/bin/env python3
"""Offline dry-run test of sync.py against the real kubernetes/kubernetes
OWNERS, LICENSE, and CONTRIBUTING.md (committed in fixtures/). Stubs the
remote fetch to serve those fixtures, so it needs no network or GH_TOKEN.

Run:  python3 test/test_sync.py
"""
import contextlib
import importlib.util
import io
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures" / "kubernetes-kubernetes"
SYNC = HERE.parent / "sync.py"


def load():
    spec = importlib.util.spec_from_file_location("sync", SYNC)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def fake_gh_content(org, repo, branch, path):
    p = FIX / path
    return p.read_text() if p.exists() else None


def run_dry(m):
    out = io.StringIO()
    old_fetch, old_cwd, old_argv = m.gh_content, os.getcwd(), sys.argv
    m.gh_content = fake_gh_content
    os.chdir(HERE)
    sys.argv = ["sync.py", "--org", "kubernetes",
                "--maintainers", str(HERE / "config" / "maintainers.yaml"),
                "--static-config", str(HERE / "config" / "repo-file-sync.yml"),
                "--template", str(HERE / "config" / "CONTRIBUTING.md"),
                "--placeholder", "kubernetes/.project"]
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

    k8s_owners = (FIX / "OWNERS").read_text()
    assert not m.is_simple_owners(k8s_owners), "k8s filter-based OWNERS must be flagged complex"
    assert m.is_simple_owners("approvers:\n  - alice\nreviewers:\n  - bob\n"), \
        "flat OWNERS must be flagged simple"

    out = run_dry(m)
    print(out)

    for op in ("OWNERS", "CONTRIBUTING.md", "LICENSE"):
        assert f"kubernetes/kubernetes {op}:" in out, f"missing op {op}"

    # Complex k8s OWNERS is detected and left untouched - our flat roster must
    # NOT be applied over it.
    assert "complex OWNERS" in out, "complex OWNERS not detected"
    assert "+alice-approver" not in out and "+bob-approver" not in out, \
        "must not try to overwrite complex OWNERS"
    # Our stubs differ from the committed k8s reference files, and the dry-run
    # shows the actual merge diff (what would land on the target repo).
    assert "would change:" in out, "no merge-diff header printed"
    assert "+Stub CONTRIBUTING template for the test" in out, "CONTRIBUTING merge diff not shown"
    assert "+Placeholder LICENSE for the offline test" in out, "LICENSE merge diff not shown"
    # Dry-run default: nothing pushed.
    assert "pushed" not in out, "dry-run should not push"

    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
