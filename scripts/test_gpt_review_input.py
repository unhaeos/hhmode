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

    def test_the_issue_comes_first_when_given(self):
        # the reviewer judges the change against the acceptance criteria it is meant to meet
        (self.repo / "keep.py").write_text("a = 2\n", encoding="utf-8")
        self.git("commit", "-qam", "change")
        issues = "# Issue #7: one header per project\n\n## Acceptance criteria\n- [ ] AC1: one header\n"
        out = gi.build(self.repo, self.base, issues)
        self.assertTrue(out.startswith("## Issue(s) this change closes\n\n# Issue #7: one header per project"))
        self.assertLess(out.index("AC1: one header"), out.index("## Diff"))
        self.assertNotIn("## Issue(s)", gi.build(self.repo, self.base))
        self.assertNotIn("## Issue(s)", gi.build(self.repo, self.base, "  \n"))

    def test_the_command_line_takes_the_issues_file_as_a_third_argument(self):
        (self.repo / "keep.py").write_text("a = 2\n", encoding="utf-8")
        self.git("commit", "-qam", "change")
        issues = self.repo.parent / f"issues-{self.repo.name}.md"
        issues.write_text("# Issue #7: x\n\n- [ ] AC1: y\n", encoding="utf-8")
        self.addCleanup(issues.unlink)
        script = pathlib.Path(gi.__file__)
        run = lambda *a: subprocess.run([sys.executable, str(script), str(self.repo), self.base, *a],
                                        check=True, capture_output=True, text=True).stdout
        self.assertIn("AC1: y", run(str(issues)))
        self.assertNotIn("Issue(s)", run())

    def test_a_symlink_to_an_outside_file_is_not_sent(self):
        # independent review of ac095e1: read_text followed a committed link and put an outside file into the input
        secret = pathlib.Path(self.tmp.name).parent / f"secret-{pathlib.Path(self.tmp.name).name}"
        secret.write_text("TOKEN=abc123\n", encoding="utf-8")
        self.addCleanup(secret.unlink)
        (self.repo / "link").symlink_to(secret)
        self.git("add", "link")
        self.git("commit", "-qm", "link")
        out = gi.build(self.repo, self.base)
        self.assertNotIn("abc123", out)
        self.assertIn("(symlink or outside the repo, not included)", out)

    def test_a_non_utf8_file_does_not_stop_the_input(self):
        (self.repo / "keep.py").write_bytes("# caf\xe9\n".encode("latin-1"))
        self.git("commit", "-qam", "latin1")
        self.assertIn("### keep.py", gi.build(self.repo, self.base))

    def test_a_non_ascii_name_is_read(self):
        (self.repo / "한글.md").write_text("내용\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "ko")
        self.assertIn("### 한글.md\n\n```\n내용", gi.build(self.repo, self.base))

    def test_long_files_are_cut_and_say_so(self):
        (self.repo / "keep.py").write_text("y" * (gi.FILE_CAP + 10), encoding="utf-8")
        self.git("commit", "-qam", "long")
        self.assertIn(f"(cut at {gi.FILE_CAP} of {gi.FILE_CAP + 10} characters)", gi.build(self.repo, self.base))


if __name__ == "__main__":
    unittest.main()
