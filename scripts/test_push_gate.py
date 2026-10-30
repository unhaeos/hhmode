"""Tests for push_gate.py through a real `git push`. Run: python3 -m unittest scripts/test_push_gate.py (from the
hhmode root).

Each test builds a scratch origin and a clone whose core.hooksPath is this checkout's githooks/."""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import record_review as rr  # noqa: E402

HOOKS = HERE.parent / "githooks"


def git(cwd, *args, check=True):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          check=check, capture_output=True, text=True)


class PushGate(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        origin = self.tmp / "origin.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(origin))
        self.repo = self.tmp / "repo"
        git(self.tmp, "clone", "-q", str(origin), str(self.repo))
        self.commit("seed")
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "config", "core.hooksPath", str(HOOKS))
        self.gate = self.repo / ".git" / "gate"

    def commit(self, name):
        (self.repo / name).write_text(name + "\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", name)
        return git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def record(self, sha, verdict="PASS", verify="PASS", named=None):
        result = {"mode": "standard", "tier": "low", "lanes": []}
        self.gate.mkdir(exist_ok=True)
        (self.gate / f"{sha}.review.md").write_text(
            rr.render(verdict, named or sha, result, "report", "s" * 36, verify), encoding="utf-8")

    def push(self, *refs):
        return git(self.repo, "push", "-q", "origin", *refs, check=False)

    def branch(self, name="task"):
        git(self.repo, "checkout", "-qb", name)
        return self.commit(name)

    # hhmode #12: opened and merged with no verifier run.
    def test_no_record_blocks_the_push(self):
        sha = self.branch()
        r = self.push("task")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(f"task ({sha[:7]}): 독립 검증 기록이 없다", r.stderr)
        self.assertIn("verify_fresh.sh", r.stderr)

    def test_a_verifier_record_lets_it_through(self):
        self.record(self.branch())
        self.assertEqual(self.push("task").returncode, 0)

    # /pr step 4: a PR may open with ISSUES as long as it says why.
    def test_any_review_verdict_passes(self):
        self.record(self.branch(), verdict="ISSUES")
        self.assertEqual(self.push("task").returncode, 0)

    def test_failed_tests_block(self):
        self.record(self.branch(), verdict="ISSUES", verify="FAIL")
        r = self.push("task")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("테스트(verify)가 실패한 기록", r.stderr)

    # A record copied to another commit's name is not that commit's record.
    def test_a_record_naming_another_commit_does_not_count(self):
        sha = self.branch()
        self.record(sha, named="f" * 40)
        self.assertNotEqual(self.push("task").returncode, 0)

    # Only the tip counts; a new commit on top needs its own record (/pr: after a push, every fix is a new commit).
    def test_a_new_commit_needs_its_own_record(self):
        self.record(self.branch())
        self.assertEqual(self.push("task").returncode, 0)
        self.commit("fix")
        self.assertNotEqual(self.push("task").returncode, 0)

    # GPT lane on 8c86c3c: a tag as the source of a branch push skipped the gate.
    def test_a_tag_pushed_as_a_branch_is_checked(self):
        self.branch()
        git(self.repo, "tag", "sneaky")
        r = self.push("refs/tags/sneaky:refs/heads/other")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("other (", r.stderr)

    def test_deletes_tags_and_commits_already_on_main_pass(self):
        self.record(self.branch())
        self.assertEqual(self.push("task").returncode, 0)
        self.assertEqual(self.push("--delete", "task").returncode, 0)
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "tag", "v1")
        self.assertEqual(self.push("v1").returncode, 0)
        git(self.repo, "branch", "fresh", "origin/main")
        self.assertEqual(self.push("fresh").returncode, 0)


if __name__ == "__main__":
    unittest.main()
