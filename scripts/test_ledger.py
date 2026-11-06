"""Tests for ledger.py (hhmode #31). Run: python3 -m unittest scripts/test_ledger.py (from the hhmode root)."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ledger as lg  # noqa: E402

SCRIPT = pathlib.Path(__file__).resolve().parent / "ledger.py"


def run(cwd, *args, stdin=""):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, input=stdin, capture_output=True, text=True)


class Ledger(unittest.TestCase):
    def setUp(self):
        self.repo = pathlib.Path(tempfile.mkdtemp()) / "repo"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                        "--allow-empty", "-m", "init"], check=True)
        self.file = self.repo / ".git" / "gate" / "ledger.md"

    # AC1: add, show, done in a scratch repo.
    def test_add_show_done(self):
        self.assertEqual(run(self.repo, "add", "PR #27 waits on the AC1 decision").stdout.strip(), "ledger: added [1]")
        run(self.repo, "add", "do not touch k-defense-kg #97")
        shown = run(self.repo, "show").stdout
        self.assertIn("[1] ", shown)
        self.assertIn("PR #27 waits on the AC1 decision", shown)
        self.assertIn("[2] ", shown)
        self.assertTrue(self.file.exists())
        self.assertEqual(run(self.repo, "done", "1").stdout.strip(), "ledger: removed [1]")
        shown = run(self.repo, "show").stdout
        self.assertNotIn("PR #27", shown)
        self.assertIn("do not touch k-defense-kg #97", shown)
        self.assertEqual(run(self.repo, "done", "1").returncode, 1)

    def test_numbers_are_not_reused_after_done(self):
        run(self.repo, "add", "a")
        run(self.repo, "add", "b")
        run(self.repo, "done", "1")
        self.assertEqual(run(self.repo, "add", "c").stdout.strip(), "ledger: added [3]")

    def test_done_keeps_the_item_marked_closed(self):
        run(self.repo, "add", "do not touch #97")
        run(self.repo, "done", "1")
        text = self.file.read_text()
        self.assertIn("- closed ", text)
        self.assertIn("[1] ", text)
        self.assertIn("do not touch #97", text)
        self.assertEqual(run(self.repo, "show").stdout.strip(), "ledger: no open items")

    def test_compact_lists_files_the_branch_committed(self):
        g = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(g + ["update-ref", "refs/remotes/origin/main", "HEAD"], check=True)
        subprocess.run(g + ["checkout", "-q", "-b", "feat"], check=True)
        (self.repo / "a.py").write_text("x")
        subprocess.run(g + ["add", "a.py"], check=True)
        subprocess.run(g + ["commit", "-q", "-m", "a"], check=True)
        out = run(self.repo, "--hook", stdin=json.dumps({"source": "compact", "cwd": str(self.repo)})).stdout
        self.assertIn("Committed on this branch since origin/main: 1 files", out)
        self.assertIn("  a.py", out)

    def test_a_worktree_shares_the_repos_ledger(self):
        wt = self.repo.parent / "wt"
        subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "-q", "-b", "x", str(wt)], check=True)
        run(wt, "add", "from the worktree")
        self.assertIn("from the worktree", run(self.repo, "show").stdout)

    # AC2: after a compaction, the items, the branch and the short status.
    def test_compact_prints_items_branch_and_status(self):
        run(self.repo, "add", "PR #27 waits on the AC1 decision")
        (self.repo / "new.txt").write_text("x")
        out = run(self.repo, "--hook", stdin=json.dumps({"source": "compact", "cwd": str(self.repo)})).stdout
        self.assertIn("PR #27 waits on the AC1 decision", out)
        self.assertIn("Branch: main at ", out)
        self.assertIn("?? new.txt", out)

    # AC3: at startup, the items and how to add one; no git state.
    def test_startup_prints_items_and_how_to_add(self):
        run(self.repo, "add", "do not touch #97")
        out = run(self.repo, "--hook", stdin=json.dumps({"source": "startup", "cwd": str(self.repo)})).stdout
        self.assertIn("do not touch #97", out)
        self.assertIn("ledger.py add", out)
        self.assertNotIn("Branch:", out)

    def test_startup_with_no_items_prints_only_how_to_add(self):
        out = run(self.repo, "--hook", stdin=json.dumps({"source": "startup", "cwd": str(self.repo)})).stdout
        self.assertEqual(out.strip(), lg.HOW)

    # AC4: exits 0 and prints nothing outside a repo, on an unreadable ledger, on bad input.
    def test_outside_a_repo_is_silent(self):
        plain = tempfile.mkdtemp()
        r = run(plain, "--hook", stdin=json.dumps({"source": "compact", "cwd": plain}))
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_bad_input_is_silent(self):
        for stdin in ("not json", "[1, 2]"):
            r = run(self.repo, "--hook", stdin=stdin)
            self.assertEqual((r.returncode, r.stdout), (0, ""), stdin)

    def test_unreadable_ledger_is_silent(self):
        if os.geteuid() == 0:
            self.skipTest("root reads any file")
        run(self.repo, "add", "x")
        self.file.chmod(0)
        try:
            r = run(self.repo, "--hook", stdin=json.dumps({"source": "compact", "cwd": str(self.repo)}))
        finally:
            self.file.chmod(0o644)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_missing_ledger_on_compact_still_gives_git_state(self):
        out = run(self.repo, "--hook", stdin=json.dumps({"source": "compact", "cwd": str(self.repo)})).stdout
        self.assertIn("Branch: main", out)
        self.assertIn("Working tree: clean", out)


if __name__ == "__main__":
    unittest.main()
