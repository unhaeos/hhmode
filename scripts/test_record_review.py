"""Tests for record_review.py. Cases named after the 2026-10-29 failures they prevent. Run: python3 -m unittest
scripts/test_record_review.py (from the hhmode root)."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import record_review as rr  # noqa: E402

SHA = "a" * 40
OLD = "b" * 40


def result(**over):
    base = {
        "sha": SHA, "mode": "standard",
        "lanes": [
            {"lane": "bug", "sha": SHA, "status": "ran"},
            {"lane": "rules", "sha": SHA, "status": "ran"},
            {"lane": "live", "sha": SHA, "status": "ran", "evidence": "curl /x -> 200"},
        ],
        "findings": [],
    }
    base.update(over)
    return base


def lanes_with(name, **change):
    out = []
    for ln in result()["lanes"]:
        out.append({**ln, **change} if ln["lane"] == name else ln)
    return out


class Check(unittest.TestCase):
    def test_clean_pass(self):
        self.assertEqual(rr.check(result(), SHA, "PASS"), "PASS")

    def test_lane_from_an_older_round_is_refused(self):
        # PR #25/#30: the final commit had only one lane re-run, the record claimed both
        with self.assertRaises(rr.Refused):
            rr.check(result(lanes=lanes_with("rules", sha=OLD)), SHA, "PASS")

    def test_missing_lane_is_refused(self):
        lanes = [ln for ln in result()["lanes"] if ln["lane"] != "rules"]
        with self.assertRaises(rr.Refused):
            rr.check(result(lanes=lanes), SHA, "PASS")

    def test_p1_without_validator_is_refused(self):
        # PR #22: a P1 (ReDoS) was never sent to finding-validator
        f = {"id": "F1", "severity": "P1", "validation": "none"}
        with self.assertRaises(rr.Refused):
            rr.check(result(findings=[f]), SHA, "PASS")

    def test_confirmed_p1_is_issues(self):
        f = {"id": "F1", "severity": "P1", "validation": "CONFIRMED"}
        self.assertEqual(rr.check(result(findings=[f]), SHA, "PASS"), "ISSUES")

    def test_rejected_p1_passes(self):
        f = {"id": "F1", "severity": "P1", "validation": "REJECTED"}
        self.assertEqual(rr.check(result(findings=[f]), SHA, "PASS"), "PASS")

    def test_p3_needs_no_validator(self):
        f = {"id": "F1", "severity": "P3"}
        self.assertEqual(rr.check(result(findings=[f]), SHA, "PASS"), "PASS")

    def test_rule_violation_is_issues(self):
        f = {"id": "R1", "severity": "rule"}
        self.assertEqual(rr.check(result(findings=[f]), SHA, "PASS"), "ISSUES")

    def test_live_without_evidence_is_refused(self):
        # PR #30: failure paths shipped as "hard to simulate"
        with self.assertRaises(rr.Refused):
            rr.check(result(lanes=lanes_with("live", evidence="")), SHA, "PASS")

    def test_live_not_applicable_needs_a_reason(self):
        with self.assertRaises(rr.Refused):
            rr.check(result(lanes=lanes_with("live", status="not-applicable", reason="")), SHA, "PASS")
        ok = lanes_with("live", status="not-applicable", reason="docs only")
        self.assertEqual(rr.check(result(lanes=ok), SHA, "PASS"), "PASS")

    def test_blocked_lane_is_blocked(self):
        self.assertEqual(rr.check(result(lanes=lanes_with("bug", status="blocked", reason="GPU busy")),
                                  SHA, "PASS"), "BLOCKED")

    def test_verify_fail_is_issues_and_blocked_is_blocked(self):
        self.assertEqual(rr.check(result(), SHA, "FAIL"), "ISSUES")
        self.assertEqual(rr.check(result(), SHA, "BLOCKED"), "BLOCKED")

    def test_full_mode_needs_its_extra_lanes(self):
        with self.assertRaises(rr.Refused):
            rr.check(result(mode="full"), SHA, "PASS")

    def test_result_for_another_commit_is_refused(self):
        with self.assertRaises(rr.Refused):
            rr.check(result(sha=OLD), SHA, "PASS")


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.repo = root / "myrepo"
        self.repo.mkdir()
        run = lambda *a: subprocess.run(["git", "-C", str(self.repo), *a], check=True, capture_output=True)
        run("init", "-q")
        run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x")
        self.sha = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"],
                                  check=True, capture_output=True, text=True).stdout.strip()
        self.gate = self.repo / ".git" / "gate"
        self.gate.mkdir()
        (self.repo / "scripts").mkdir()
        self.verify_py = self.repo / "scripts" / "verify.py"     # a gated repo, like k-defense-kg
        self.verify_py.write_text("", encoding="utf-8")
        self.logs = root / "logs"
        self.res = root / "result.json"
        self.rep = root / "report.md"
        self.rep.write_text("### Must fix\n- none\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, verify="PASS", **over):
        (self.gate / f"{self.sha}.verify.json").write_text(json.dumps({"sha": self.sha, "verdict": verify}))
        r = result(sha=self.sha, lanes=[{**ln, "sha": self.sha} for ln in result()["lanes"]], **over)
        self.res.write_text(json.dumps(r), encoding="utf-8")

    def _main(self):
        return rr.main(["--repo", str(self.repo), "--result", str(self.res), "--report", str(self.rep),
                        "--session", "11111111-2222-3333-4444-555555555555", "--log-dir", str(self.logs)])

    def test_writes_record_and_log(self):
        self._write()
        self.assertEqual(self._main(), 0)
        rec = (self.gate / f"{self.sha}.review.md").read_text(encoding="utf-8")
        self.assertTrue(rec.startswith(f"**Review: PASS** · {self.sha[:7]} · standard · verifier 11111111"))
        self.assertIn("verifier-session: 11111111-2222-3333-4444-555555555555", rec)
        rows = (self.logs / "myrepo.tsv").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(rows), 1)
        self.assertIn("no findings (PASS)", rows[0])

    def test_no_verify_record_is_refused(self):
        self._write()
        (self.gate / f"{self.sha}.verify.json").unlink()
        self.assertEqual(self._main(), 2)
        self.assertFalse((self.gate / f"{self.sha}.review.md").exists())

    def test_refused_result_writes_nothing(self):
        self._write(findings=[{"id": "F1", "severity": "P0", "validation": "none"}])
        self.assertEqual(self._main(), 2)
        self.assertFalse((self.gate / f"{self.sha}.review.md").exists())
        self.assertFalse((self.logs / "myrepo.tsv").exists())

    # A repo with no verify step (hhmode itself): the verifier's own test run is the verify lane.
    def _write_no_verify_step(self, verify_lane):
        self.verify_py.unlink()
        lanes = [{**ln, "sha": self.sha} for ln in result()["lanes"]]
        if verify_lane is not None:
            lanes.append({"sha": self.sha, **verify_lane, "lane": "verify"})
        self.res.write_text(json.dumps(result(sha=self.sha, lanes=lanes)), encoding="utf-8")

    def test_no_verify_step_uses_the_verifiers_test_lane(self):
        self._write_no_verify_step({"status": "ran", "verdict": "PASS",
                                    "evidence": "python3 -m unittest -> Ran 17 tests OK"})
        self.assertEqual(self._main(), 0)
        rec = (self.gate / f"{self.sha}.review.md").read_text(encoding="utf-8")
        self.assertTrue(rec.startswith("**Review: PASS**"))

    def test_no_verify_step_without_a_test_lane_is_refused(self):
        self._write_no_verify_step(None)
        self.assertEqual(self._main(), 2)

    def test_no_verify_step_lane_without_evidence_is_refused(self):
        self._write_no_verify_step({"status": "ran", "verdict": "PASS", "evidence": ""})
        self.assertEqual(self._main(), 2)

    def test_no_verify_step_failing_tests_is_issues(self):
        self._write_no_verify_step({"status": "ran", "verdict": "FAIL", "evidence": "1 failed"})
        self.assertEqual(self._main(), 0)
        rec = (self.gate / f"{self.sha}.review.md").read_text(encoding="utf-8")
        self.assertTrue(rec.startswith("**Review: ISSUES**"))


if __name__ == "__main__":
    unittest.main()
