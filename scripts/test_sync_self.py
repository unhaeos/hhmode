"""Tests for sync_self.sh. Run: python3 -m unittest scripts/test_sync_self.py (from the hhmode root).

Each test builds a scratch origin, a clone standing in for ~/projects/hhmode, and a scratch ~/.claude."""
from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).with_name("sync_self.sh")


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


class SyncSelf(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.origin = self.tmp / "origin.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        seed = self.tmp / "seed"
        git(self.tmp, "clone", "-q", str(self.origin), str(seed))
        (seed / "skills" / "old").mkdir(parents=True)
        (seed / "skills" / "old" / "SKILL.md").write_text("old\n")
        (seed / ".gitignore").write_text("local/\n")
        git(seed, "add", ".")
        git(seed, "commit", "-qm", "seed")
        git(seed, "push", "-q", "origin", "main")
        self.seed = seed
        self.hh = self.tmp / "hhmode"
        git(self.tmp, "clone", "-q", str(self.origin), str(self.hh))
        self.cl = self.tmp / "claude"
        (self.cl / "skills").mkdir(parents=True)
        (self.cl / "agents").mkdir()
        os.symlink(self.hh / "skills" / "old", self.cl / "skills" / "old")

    def merge_on_github(self, path, text="x\n"):
        f = self.seed / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        git(self.seed, "add", ".")
        git(self.seed, "commit", "-qm", f"add {path}")
        git(self.seed, "push", "-q", "origin", "main")

    def run_sync(self):
        env = {**os.environ, "HHMODE_DIR": str(self.hh), "CLAUDE_DIR": str(self.cl), "TMPDIR": str(self.tmp)}
        p = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.strip()

    def head(self, repo):
        return git(repo, "rev-parse", "HEAD")

    # 2026-10-29: /correct (#5) and /bro (#6) merged, checkout stayed behind, new skill unlinked.
    def test_merged_skill_is_pulled_and_linked(self):
        self.merge_on_github("skills/correct/SKILL.md")
        self.merge_on_github("agents/plan-reviewer.md")
        out = self.run_sync()
        self.assertEqual(self.head(self.hh), self.head(self.seed))
        self.assertEqual(os.readlink(self.cl / "skills" / "correct"), str(self.hh / "skills" / "correct"))
        self.assertEqual(os.readlink(self.cl / "agents" / "plan-reviewer.md"),
                         str(self.hh / "agents" / "plan-reviewer.md"))
        self.assertIn("updated", out)
        self.assertIn("skill:correct", out)
        self.assertIn("agent:plan-reviewer", out)

    def test_nothing_to_do_prints_nothing(self):
        self.assertEqual(self.run_sync(), "")

    def test_tracked_change_blocks_the_update(self):
        before = self.head(self.hh)
        self.merge_on_github("skills/new/SKILL.md")
        (self.hh / "skills" / "old" / "SKILL.md").write_text("edited locally\n")
        self.run_sync()
        self.assertEqual(self.head(self.hh), before)
        self.assertEqual((self.hh / "skills" / "old" / "SKILL.md").read_text(), "edited locally\n")

    def test_other_branch_is_left_alone(self):
        git(self.hh, "checkout", "-qb", "feat/x")
        before = self.head(self.hh)
        self.merge_on_github("skills/new/SKILL.md")
        self.run_sync()
        self.assertEqual(self.head(self.hh), before)

    def test_existing_name_is_never_replaced(self):
        self.merge_on_github("skills/report/SKILL.md")
        (self.cl / "skills" / "report").mkdir()
        (self.cl / "skills" / "report" / "SKILL.md").write_text("someone else's\n")
        self.run_sync()
        self.assertFalse((self.cl / "skills" / "report").is_symlink())
        self.assertEqual((self.cl / "skills" / "report" / "SKILL.md").read_text(), "someone else's\n")

    def test_ignored_local_file_is_not_overwritten(self):
        before = self.head(self.hh)
        (self.hh / "local").mkdir()
        (self.hh / "local" / "identity.md").write_text("mine\n")
        git(self.seed, "rm", "-q", "--cached", ".gitignore")
        (self.seed / ".gitignore").unlink()
        self.merge_on_github("local/identity.md", "from a PR\n")
        out = self.run_sync()
        self.assertEqual(self.head(self.hh), before)
        self.assertEqual((self.hh / "local" / "identity.md").read_text(), "mine\n")
        self.assertIn("refused", out)

    def test_unreachable_origin_still_links_and_exits_0(self):
        (self.hh / "skills" / "fresh").mkdir()
        (self.hh / "skills" / "fresh" / "SKILL.md").write_text("x\n")
        git(self.hh, "remote", "set-url", "origin", str(self.tmp / "missing.git"))
        out = self.run_sync()
        self.assertIn("skill:fresh", out)


if __name__ == "__main__":
    unittest.main()
