"""Tests for gpt_review_input.py. Run: python3 -m unittest scripts/test_gpt_review_input.py (from the hhmode root)."""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import gpt_review_input as gi  # noqa: E402


class Build(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.tmp.name)
        self.git("init", "-q")
        (self.repo / "keep.py").write_text("a = 1\n", encoding="utf-8")
        (self.repo / "gone.py").write_text("b = 1\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "base")
        self.base = self.git("rev-parse", "HEAD").strip()

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                              check=True, capture_output=True, text=True).stdout

    def test_diff_and_whole_changed_files_but_not_deleted_ones(self):
        # a diff-only reviewer raised no P0/P1 in 88 review-log rows: the GPT lane gets the files too
        (self.repo / "keep.py").write_text("a = 1\n" + "x = 2\n" * 50, encoding="utf-8")
        (self.repo / "gone.py").unlink()
        self.git("commit", "-qam", "change")
        out = gi.build(self.repo, self.base)
        self.assertIn("```diff\n", out)
        self.assertIn("### keep.py", out)
        self.assertEqual(out.count("x = 2"), 100)        # 50 lines in the diff, 50 in the whole file
        self.assertNotIn("### gone.py", out)

    def test_long_files_are_cut_and_say_so(self):
        (self.repo / "keep.py").write_text("y" * (gi.FILE_CAP + 10), encoding="utf-8")
        self.git("commit", "-qam", "long")
        self.assertIn(f"(cut at {gi.FILE_CAP} of {gi.FILE_CAP + 10} characters)", gi.build(self.repo, self.base))


if __name__ == "__main__":
    unittest.main()
