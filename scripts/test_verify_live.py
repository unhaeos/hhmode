"""Tests for verify/live/run.py: which checks a change picks. Run: python3 -m unittest scripts/test_verify_live.py
(from the hhmode root). The live checks themselves run through verify/live/run.py, not here."""
from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "verify" / "live"))
import run  # noqa: E402


class Selection(unittest.TestCase):
    def setUp(self):
        self.checks = run.load_checks()

    def picked(self, paths):
        e = run.expand(paths)
        return "ALL" if e is None else sorted(m.__name__ for m in self.checks if run.picks(m, e))

    def test_every_check_declares_what_it_guards(self):
        self.assertTrue(self.checks)
        for m in self.checks:
            self.assertTrue(m.PATHS and m.INVARIANT and m.ORIGIN, m.__name__)

    def test_a_guarded_file_picks_its_checks(self):
        self.assertIn("check_review_input_egress", self.picked(["scripts/gpt_review_input.py"]))

    def test_a_change_to_an_imported_script_picks_the_importers_checks(self):
        # automerge imports forms, record_review imports review_weight
        self.assertIn("check_record_roundtrip", self.picked(["scripts/forms.py"]))
        self.assertIn("check_record_roundtrip", self.picked(["scripts/review_weight.py"]))

    def test_dependency_and_check_changes_run_everything(self):
        for path in ("uv.lock", "pyproject.toml", "requirements-dev.txt", ".python-version", "verify/live/check_x.py"):
            self.assertEqual(self.picked([path]), "ALL", path)

    def test_docs_pick_nothing(self):
        self.assertEqual(self.picked(["README.md"]), [])


if __name__ == "__main__":
    unittest.main()
