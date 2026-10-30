"""Tests for review_weight.py. Run: python3 -m unittest scripts/test_review_weight.py (from the hhmode root).

Each test builds a scratch repo with a first commit that has a review record, then changes it."""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import record_review as rr  # noqa: E402
import review_weight as rw  # noqa: E402

SESSION = "11111111-2222-3333-4444-555555555555"


class Weight(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.tmp.name) / "r"
        self.repo.mkdir()
        self.git("init", "-q")
        (self.repo / "app.py").write_text("x = 1\n" * 100, encoding="utf-8")
        (self.repo / "README.md").write_text("hello\n", encoding="utf-8")
        (self.repo / "blob.bin").write_bytes(b"\x00\x01\x02")
        self.write("sub/README.md", "nested\n")
        self.first = self.commit("first")
        self.gate = self.repo / ".git" / "gate"
        self.gate.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, msg="change"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def review(self, sha, verdict="PASS", verify="PASS", mode="standard"):
        res = {"mode": mode, "tier": "low", "lanes": [], "findings": []}
        (self.gate / f"{sha}.review.md").write_text(rr.render(verdict, sha, res, "r", SESSION, verify),
                                                    encoding="utf-8")

    def kind(self, since=None, head=None):
        return rw.weight(self.repo, since or self.first, head or "HEAD")[0]

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")

    # Verifier and Codex on 9aadb3c: with rename detection, `git mv app.py docs/app.py` listed only docs/app.py.
    def test_code_moved_into_docs_is_not_wording(self):
        self.review(self.first)
        (self.repo / "docs").mkdir()
        self.git("mv", "app.py", "docs/app.py")
        self.commit("move")
        self.assertNotEqual(self.kind(), "carry")

    # Verifier on 9aadb3c: a wording-only commit that closes an issue was carried with no criteria judged.
    def test_a_wording_commit_that_closes_an_issue_gets_a_verifier(self):
        self.review(self.first)
        self.write("README.md", "hello again\n")
        self.commit("docs: say hello\n\nCloses #7")
        kind, why = rw.weight(self.repo, self.first, "HEAD")
        self.assertEqual(kind, "fix")
        self.assertIn("#7", why)

    # Verifier on 79691db: the Closes rule returned fix before the new-file and size checks.
    def test_closes_rules_out_carry_but_not_the_size_checks(self):
        self.review(self.first)
        self.write("docs/new.md", "a new page\n")
        self.commit("docs: add a page\n\nCloses #7")
        self.assertEqual(self.kind(), "standard")       # a new file, even under docs/

    def test_the_first_review_on_a_branch_is_standard(self):
        for since in (None, ""):
            kind, reason = rw.weight(self.repo, since, "HEAD")
            self.assertEqual(kind, "standard")
            self.assertIn("no earlier review", reason)

    def test_wording_only_after_a_pass_is_carried(self):
        self.review(self.first)
        self.write("README.md", "hello again\n")
        self.write("docs/guide.md", "a new page\n")          # a new file under docs/ is still wording
        self.write("log.md", "one line\n")
        self.commit()
        kind, reason = rw.weight(self.repo, self.first, "HEAD")
        self.assertEqual(kind, "carry")
        self.assertIn("Only wording changed", reason)
        self.assertIn("README.md", reason)
        self.assertTrue(reason.endswith("."))

    def test_carry_only_from_a_pass_that_counts(self):
        self.write("README.md", "hello again\n")
        self.commit()
        self.assertEqual(self.kind(), "fix")                  # no record at all
        for verdict, verify in (("ISSUES", "PASS"), ("BLOCKED", "BLOCKED"), ("PASS", "FAIL")):
            self.review(self.first, verdict=verdict, verify=verify)
            self.assertEqual(self.kind(), "fix", (verdict, verify))
        self.review(self.first)
        self.assertEqual(self.kind(), "carry")
        self.review(self.first, mode="fix")                    # a fix review that passed can be carried too
        self.assertEqual(self.kind(), "carry")

    def test_a_carried_record_is_not_something_to_carry_from(self):
        self.review(self.first)
        self.write("README.md", "one\n")
        second = self.commit()
        (self.gate / f"{second}.review.md").write_text(rr.render_carry(second, self.first, ["README.md"], "low"),
                                                       encoding="utf-8")
        self.write("README.md", "two\n")
        self.commit()
        self.assertEqual(self.kind(since=second), "fix")

    def test_a_code_file_among_the_wording_makes_it_a_fix(self):
        self.review(self.first)
        self.write("README.md", "hello again\n")
        self.write("app.py", "x = 1\n" * 99 + "x = 2\n")
        self.commit()
        self.assertEqual(self.kind(), "fix")

    def test_only_the_named_wording_is_wording(self):
        self.review(self.first)
        self.write("sub/README.md", "changed\n")             # only the README.md at the repo root is named
        self.commit()
        self.assertEqual(self.kind(), "fix")

    def test_the_line_limit(self):
        self.assertEqual(rw.FIX_LINES, 150)
        for added, want in ((rw.FIX_LINES, "fix"), (rw.FIX_LINES + 1, "standard")):
            self.git("checkout", "-q", self.first)
            self.write("app.py", "x = 1\n" * 100 + "y = 2\n" * added)
            self.commit()
            self.assertEqual(self.kind(), want, added)

    def test_deleted_lines_count_too(self):
        self.write("app.py", "y = 2\n" * 100)                  # 100 added + 100 deleted
        self.commit()
        kind, reason = rw.weight(self.repo, self.first, "HEAD")
        self.assertEqual(kind, "standard")
        self.assertIn("200 lines", reason)

    def test_a_new_file_is_standard_however_small(self):
        self.write("tiny.py", "x = 1\n")
        self.commit()
        kind, reason = rw.weight(self.repo, self.first, "HEAD")
        self.assertEqual(kind, "standard")
        self.assertIn("tiny.py", reason)

    def test_a_binary_file_is_large(self):
        (self.repo / "blob.bin").write_bytes(b"\x00\x01\x02\x03")
        self.commit()
        kind, reason = rw.weight(self.repo, self.first, "HEAD")
        self.assertEqual(kind, "standard")
        self.assertIn("binary", reason)

    def test_a_small_change_to_an_existing_file_is_a_fix(self):
        self.write("app.py", "x = 1\n" * 99 + "x = 2\n")
        self.commit()
        kind, reason = rw.weight(self.repo, self.first, "HEAD")
        self.assertEqual(kind, "fix")
        self.assertIn("2 lines", reason)

    def test_a_moved_file_is_not_trusted_as_a_no_op(self):
        self.git("mv", "app.py", "app2.py")
        self.commit()
        self.assertEqual(self.kind(), "standard")

    def test_no_change_at_all_after_a_pass_is_carried(self):
        self.review(self.first)
        self.git("commit", "-q", "--allow-empty", "-m", "empty")
        kind, reason = rw.weight(self.repo, self.first, "HEAD")
        self.assertEqual(kind, "carry")
        self.assertIn("Nothing changed", reason)

    def test_the_command_line_prints_kind_tab_reason(self):
        self.write("app.py", "x = 1\n" * 99 + "x = 2\n")
        self.commit()
        run = lambda *a: subprocess.run([sys.executable, str(HERE / "review_weight.py"), str(self.repo), *a],
                                        check=True, capture_output=True, text=True).stdout
        kind, reason = run(self.first, "HEAD").rstrip("\n").split("\t")
        self.assertEqual(kind, "fix")
        self.assertTrue(reason)
        self.assertTrue(run("", "HEAD").startswith("standard\t"))


if __name__ == "__main__":
    unittest.main()
