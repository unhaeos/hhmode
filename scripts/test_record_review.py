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
import automerge as am  # noqa: E402
import record_review as rr  # noqa: E402

SHA = "a" * 40
OLD = "b" * 40
SESSION = "11111111-2222-3333-4444-555555555555"
ISSUES = ("# Issue #7: One header per project\n\n## Background\nx\n\n## Acceptance criteria\n"
          "- [ ] AC1: one header\n- [ ] AC2: no duplicates\n\n## Out of scope\nnone\n\n## Risk\nlow — docs\n\n"
          "# Issue #8: Second\n\n## Acceptance criteria\n- [ ] AC1: works\n")
WANT = [(7, "AC1"), (7, "AC2"), (8, "AC1")]


def result(**over):
    base = {
        "sha": SHA, "mode": "standard", "tier": "low",
        "lanes": [
            {"lane": "bug", "sha": SHA, "status": "ran"},
            {"lane": "bug-gpt", "sha": SHA, "status": "ran"},
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
        f = {"id": "F1", "raised_by": "bug", "severity": "P1", "validation": "none"}
        with self.assertRaises(rr.Refused):
            rr.check(result(findings=[f]), SHA, "PASS")

    def test_confirmed_p1_is_issues(self):
        f = {"id": "F1", "raised_by": "bug", "severity": "P1", "validation": "CONFIRMED"}
        self.assertEqual(rr.check(result(findings=[f]), SHA, "PASS"), "ISSUES")

    def test_rejected_p1_passes(self):
        f = {"id": "F1", "raised_by": "bug", "severity": "P1", "validation": "REJECTED"}
        self.assertEqual(rr.check(result(findings=[f]), SHA, "PASS"), "PASS")

    def test_unknown_severity_is_refused(self):
        # verifier note on hhmode #3: "p1" / "high" would skip the validator check
        for sev in ("p1", "P1 ", "high", None):
            with self.assertRaises(rr.Refused):
                rr.check(result(findings=[{"id": "F1", "raised_by": "bug", "severity": sev}]), SHA, "PASS")

    def test_p3_needs_no_validator(self):
        f = {"id": "F1", "raised_by": "bug", "severity": "P3"}
        self.assertEqual(rr.check(result(findings=[f]), SHA, "PASS"), "PASS")

    def test_rule_violation_is_issues(self):
        f = {"id": "R1", "raised_by": "rules", "severity": "rule"}
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

    def test_full_mode_no_longer_needs_a_diff_only_lane(self):
        # 2026-10-29: the diff-only lane raised no P0/P1 in 88 k-defense-kg review-log rows
        lanes = result()["lanes"] + [{"lane": "bug-fable", "sha": SHA, "status": "ran"}]
        self.assertEqual(rr.check(result(mode="full", lanes=lanes), SHA, "PASS"), "PASS")

    def test_both_modes_need_the_gpt_lane(self):
        # the only reviewer from another company; without it every lane is an Anthropic model
        lanes = [ln for ln in result()["lanes"] if ln["lane"] != "bug-gpt"]
        with self.assertRaises(rr.Refused):
            rr.check(result(lanes=lanes), SHA, "PASS")
        blocked = lanes_with("bug-gpt", status="blocked", reason="codex exec failed")
        self.assertEqual(rr.check(result(lanes=blocked), SHA, "PASS"), "BLOCKED")

    def test_raised_by_must_be_lane_names(self):
        # the log had 25 spellings of four reviewers ("opus", "Opusfull", "Fable)"), so no fix rate per reviewer
        for who in ("opus", "bug-reviewer(opus)", "Fable)", "bug, rules", "", None):
            with self.assertRaises(rr.Refused):
                rr.check(result(findings=[{"id": "F1", "severity": "P3", "raised_by": who}]), SHA, "PASS")
        ok = {"id": "F1", "severity": "P3", "raised_by": "bug+bug-fable"}
        self.assertEqual(rr.check(result(findings=[ok]), SHA, "PASS"), "PASS")

    # A missing or loose tier ("Low", "none") must not reach automerge.py as low by default.
    def test_tier_is_required_and_exact(self):
        for bad in (None, "Low", "none", "trivial"):
            r = result(tier=bad) if bad is not None else {k: v for k, v in result().items() if k != "tier"}
            with self.assertRaises(rr.Refused):
                rr.check(r, SHA, "PASS")

    def test_result_for_another_commit_is_refused(self):
        with self.assertRaises(rr.Refused):
            rr.check(result(sha=OLD), SHA, "PASS")


def entry(issue, ac, status="met", evidence="python3 -m unittest -> OK"):
    return {"issue": issue, "id": ac, "status": status, "evidence": evidence}


def judged(**change):
    """An entry for each expected criterion, `change` applied to the (7, AC2) one."""
    return [{**entry(n, ac), **(change if (n, ac) == (7, "AC2") else {})} for n, ac in WANT]


class Criteria(unittest.TestCase):
    """The issue's acceptance criteria (forms.py) reach the verdict: each one is judged with evidence."""

    def test_criteria_are_read_per_issue(self):
        self.assertEqual(rr.issue_criteria(ISSUES), WANT)
        self.assertEqual(rr.issue_criteria(""), [])
        self.assertEqual(rr.issue_criteria("# Issue #9: old issue\n\nno sections here\n"), [])

    def test_all_met_passes(self):
        self.assertEqual(rr.check(result(criteria=judged()), SHA, "PASS", WANT), "PASS")

    def test_a_criterion_without_an_entry_is_refused(self):
        with self.assertRaises(rr.Refused) as cm:
            rr.check(result(criteria=judged()[:2]), SHA, "PASS", WANT)
        self.assertIn("AC1 of issue #8", str(cm.exception))
        with self.assertRaises(rr.Refused):
            rr.check(result(), SHA, "PASS", WANT)
        # an entry that names the issue as text is not the entry for issue 7
        with self.assertRaises(rr.Refused):
            rr.check(result(criteria=judged(issue="7")), SHA, "PASS", WANT)

    def test_an_unknown_status_is_refused(self):
        for bad in ("Met", "pass", "", None):
            with self.assertRaises(rr.Refused):
                rr.check(result(criteria=judged(status=bad)), SHA, "PASS", WANT)

    def test_met_and_not_met_need_evidence_but_unclear_does_not(self):
        for status in ("met", "not-met"):
            for blank in ("", "  ", None):
                with self.assertRaises(rr.Refused):
                    rr.check(result(criteria=judged(status=status, evidence=blank)), SHA, "PASS", WANT)
        self.assertEqual(rr.check(result(criteria=judged(status="unclear", evidence="")), SHA, "PASS", WANT), "PASS")

    def test_not_met_is_issues_like_a_confirmed_p1(self):
        self.assertEqual(rr.check(result(criteria=judged(status="not-met")), SHA, "PASS", WANT), "ISSUES")

    def test_a_blocked_lane_still_wins_over_not_met(self):
        lanes = lanes_with("bug", status="blocked", reason="GPU busy")
        self.assertEqual(rr.check(result(lanes=lanes, criteria=judged(status="not-met")), SHA, "PASS", WANT),
                         "BLOCKED")

    def test_no_issue_means_no_criteria_are_asked_for(self):
        self.assertEqual(rr.check(result(), SHA, "PASS"), "PASS")
        self.assertEqual(rr.check(result(criteria=judged(status="Met")), SHA, "PASS"), "PASS")


def rendered(res=None, expected=WANT, verdict="PASS", report="### Must fix\n- none"):
    res = res if res is not None else result(criteria=judged(), findings=[
        {"id": "F1", "severity": "P2", "raised_by": "bug"}, {"id": "F2", "severity": "P3", "raised_by": "bug"},
        {"id": "F3", "severity": "P3", "raised_by": "rules"},
        {"id": "F4", "severity": "P1", "raised_by": "bug", "validation": "REJECTED"}])
    res = {**res, "tier": "medium"}
    return rr.render(verdict, SHA, res, report, SESSION, "PASS", expected=expected)


class Render(unittest.TestCase):
    def test_the_first_line_is_what_the_gates_read(self):
        text = rendered()
        self.assertEqual(text.splitlines()[0], f"**Review: PASS** · {SHA[:7]} · standard · verifier 11111111")
        m = am.HEAD_RE.match(text)
        self.assertEqual((m.group(1), m.group(2), m.group(3)), ("PASS", SHA[:7], "standard"))
        self.assertEqual(am.record_fields(text), {"review": "PASS", "since": None, "verify": "PASS", "tier": "medium"})
        self.assertEqual(rr.reviewed_as(text), "standard")
        since = rr.render("PASS", SHA, result(), "r", SESSION, "PASS", since=OLD)
        self.assertEqual(am.record_fields(since)["since"], OLD[:7])

    def test_summary_table_follows_the_first_line(self):
        lines = rendered().splitlines()
        self.assertEqual(lines[1], "")
        self.assertEqual(lines[2], "| Verdict | Risk | Tests | Live run | Findings | Acceptance criteria |")
        self.assertEqual(lines[3], "|---|---|---|---|---|---|")
        # the rejected P1 is not counted
        self.assertEqual(lines[4], "| PASS | medium | PASS | ran | P0 0 · P1 0 · P2 1 · P3 2 | 3/3 met |")

    def test_criteria_table_comes_before_the_report_and_the_provenance_comment_after(self):
        text = rendered(report="REPORT BODY")
        self.assertIn("### Acceptance criteria\n\n| Issue | Criterion | Status | Evidence |\n|---|---|---|---|\n", text)
        self.assertIn("| #7 | AC2 | met | python3 -m unittest -> OK |", text)
        self.assertIn("| #8 | AC1 | met |", text)
        self.assertLess(text.index("### Acceptance criteria"), text.index("REPORT BODY"))
        self.assertLess(text.index("REPORT BODY"), text.index("<!-- verifier-session:"))
        self.assertTrue(text.endswith(" -->\n"))

    def test_without_an_issue_the_cell_is_a_dash_and_there_is_no_criteria_table(self):
        text = rendered(res=result(), expected=[])
        self.assertIn("| PASS | medium | PASS | ran | P0 0 · P1 0 · P2 0 · P3 0 | — |", text)
        self.assertNotIn("### Acceptance criteria", text)

    def test_counts_show_what_is_not_met_and_rule_violations(self):
        res = result(criteria=judged(status="not-met"),
                     findings=[{"id": "R1", "severity": "rule", "raised_by": "rules"}])
        text = rendered(res=res, verdict="ISSUES")
        self.assertIn("| ISSUES | medium | PASS | ran | P0 0 · P1 0 · P2 0 · P3 0 · rule 1 | 2/3 met |", text)
        self.assertIn("| #7 | AC2 | not-met |", text)

    def test_evidence_with_a_pipe_or_a_line_break_keeps_its_row(self):
        text = rendered(res=result(criteria=judged(evidence="grep x | wc -l\n3")))
        self.assertIn("| #7 | AC2 | met | grep x \\| wc -l 3 |", text)

    def test_live_run_shows_not_applicable(self):
        res = result(lanes=lanes_with("live", status="not-applicable", reason="docs only"))
        self.assertIn("| PASS | medium | PASS | not-applicable |", rendered(res=res, expected=[]))


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

    def _main(self, mode="standard", since=None):
        return rr.main(["--repo", str(self.repo), "--result", str(self.res), "--report", str(self.rep),
                        "--session", "11111111-2222-3333-4444-555555555555", "--mode", mode,
                        "--log-dir", str(self.logs)] + (["--since", since] if since else []))

    # A re-review limited to the diff after an earlier commit (pstack: re-verify in proportion).
    def _second_commit(self, reviewed=True, head="ISSUES", mode="standard"):
        first = self.sha
        if reviewed:
            (self.gate / f"{first}.review.md").write_text(
                f"**Review: {head}** · {first[:7]} · {mode} · verifier 9\n\n"
                "<!-- verifier-session: 9; verify: PASS; lanes: -->\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                        "--allow-empty", "-m", "fix"], check=True, capture_output=True)
        self.sha = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"],
                                  check=True, capture_output=True, text=True).stdout.strip()
        return first

    def _issues_file(self):
        path = self.res.parent / "issues.md"
        path.write_text(ISSUES, encoding="utf-8")
        return path

    def _main_with_issues(self):
        return rr.main(["--repo", str(self.repo), "--result", str(self.res), "--report", str(self.rep),
                        "--session", SESSION, "--mode", "standard", "--log-dir", str(self.logs),
                        "--issues", str(self._issues_file())])

    def test_issues_given_the_record_carries_the_criteria(self):
        self._write(criteria=judged())
        self.assertEqual(self._main_with_issues(), 0)
        rec = (self.gate / f"{self.sha}.review.md").read_text(encoding="utf-8")
        self.assertIn("| PASS | low | PASS | ran | P0 0 · P1 0 · P2 0 · P3 0 | 3/3 met |", rec)
        self.assertIn("| #8 | AC1 | met |", rec)
        self.assertEqual(am.record_fields(rec)["review"], "PASS")

    def test_issues_given_a_result_without_criteria_is_refused(self):
        self._write()
        self.assertEqual(self._main_with_issues(), 2)
        self.assertFalse((self.gate / f"{self.sha}.review.md").exists())
        self.assertFalse((self.logs / "myrepo.tsv").exists())

    def test_a_criterion_not_met_makes_the_record_issues(self):
        self._write(criteria=judged(status="not-met"))
        self.assertEqual(self._main_with_issues(), 0)
        rec = (self.gate / f"{self.sha}.review.md").read_text(encoding="utf-8")
        self.assertTrue(rec.startswith("**Review: ISSUES**"))
        self.assertIn("2/3 met", rec)

    def test_since_a_reviewed_ancestor_is_named_in_the_record(self):
        first = self._second_commit()
        self._write()
        self.assertEqual(self._main(since=first), 0)
        head = (self.gate / f"{self.sha}.review.md").read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(head, f"**Review: PASS** · {self.sha[:7]} · standard · since {first[:7]} · verifier 11111111")

    def test_since_an_unreviewed_commit_is_refused(self):
        # otherwise the diff before it would never have been read by any verifier
        first = self._second_commit(reviewed=False)
        self._write()
        self.assertEqual(self._main(since=first), 2)
        self.assertFalse((self.gate / f"{self.sha}.review.md").exists())

    def test_since_a_blocked_review_is_refused(self):
        # independent review of e6968d0 (F1): a BLOCKED record also names its verifier session, and a PASS
        # scoped to it left the blocked commit's diff unread by any bug reviewer
        first = self._second_commit(head="BLOCKED")
        self._write()
        self.assertEqual(self._main(since=first), 2)
        self.assertFalse((self.gate / f"{self.sha}.review.md").exists())

    def test_since_a_weaker_mode_is_refused(self):
        # F2: a full review scoped to a standard one never has Fable read the diff before it
        first = self._second_commit(mode="standard")
        lanes = [{**ln, "sha": None} for ln in result()["lanes"]] + [{"lane": "bug-fable", "status": "ran"}]
        self._write(mode="full")
        r = json.loads(self.res.read_text(encoding="utf-8"))
        r["lanes"] = [{**ln, "sha": self.sha} for ln in lanes]
        self.res.write_text(json.dumps(r), encoding="utf-8")
        self.assertEqual(self._main(mode="full", since=first), 2)
        (self.gate / f"{first}.review.md").write_text(
            f"**Review: PASS** · {first[:7]} · full · verifier 9\n\n<!-- verifier-session: 9 -->\n", encoding="utf-8")
        self.assertEqual(self._main(mode="full", since=first), 0)

    def test_since_the_commit_itself_or_a_non_ancestor_is_refused(self):
        self._second_commit()
        self._write()
        self.assertEqual(self._main(since=self.sha), 2)
        other = subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c", "user.name=t",
                                "commit-tree", "-m", "o", "HEAD^{tree}"],
                               check=True, capture_output=True, text=True).stdout.strip()
        (self.gate / f"{other}.review.md").write_text(       # a valid record: only ancestry is wrong
            f"**Review: PASS** · {other[:7]} · standard · verifier 9\n\n<!-- verifier-session: 9 -->\n",
            encoding="utf-8")
        self.assertEqual(self._main(since=other), 2)

    # Found by the verifier on hhmode #3 (F2, F3, F1).
    def test_full_request_reported_as_standard_is_refused(self):
        self._write()
        self.assertEqual(self._main(mode="full"), 2)

    def test_verify_record_with_an_unknown_verdict_is_refused(self):
        self._write(verify="")
        self.assertEqual(self._main(), 2)
        self.assertFalse((self.gate / f"{self.sha}.review.md").exists())

    def test_record_carries_the_tier(self):
        self._write()
        self.assertEqual(self._main(), 0)
        rec = (self.gate / f"{self.sha}.review.md").read_text(encoding="utf-8")
        self.assertIn("tier: low;", rec)

    def test_record_carries_the_verify_verdict(self):
        self._write()
        self.assertEqual(self._main(), 0)
        rec = (self.gate / f"{self.sha}.review.md").read_text(encoding="utf-8")
        self.assertIn("verify: PASS;", rec)

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
        self._write(findings=[{"id": "F1", "raised_by": "bug", "severity": "P0", "validation": "none"}])
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
