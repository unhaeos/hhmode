"""Tests for automerge.py. Run: python3 -m unittest scripts/test_automerge.py (from the hhmode root)."""
from __future__ import annotations

import pathlib
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import automerge as am  # noqa: E402
import record_review as rr  # noqa: E402

SHA = "c" * 40
OLD = "d" * 40
GPT_LOW = "## Findings\nnone\n\n## Tier\nlow — docs/README.md: text only\n"
GPT_MED = "## Findings\nnone\n\n## Tier\nmedium — scripts/x.py: behaviour change\n"
STATUS = {"review": "passed", "verify": "passed", "ci": "ok", "mergeable": "MERGEABLE"}
# A PR body that fills the PR form (templates/pr.md) for ISSUE below.
BODY = """## Why
Weekly report named a project twice.
Closes #7

## What changed
One header line per project.

## Acceptance criteria
- AC1: python3 -m unittest scripts/test_weekly.py → OK

## Verification
**Review: PASS** · ccccccc · standard · verifier 11111111

## Risk
low — commands/weekly-report.md: report wording only
none found: grep shows no other caller

## How to revert
git revert ccccccc

## Out of scope
none
"""


def pr(**over):
    base = {"number": 12, "title": "docs: x", "url": "https://github.com/o/r/pull/12", "state": "OPEN",
            "baseRefName": "main", "headRefOid": SHA, "body": BODY,
            "mergeable": "MERGEABLE",
            "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS", "name": "ci"}]}
    base.update(over)
    return base


def rec(**over):
    base = {"review": "PASS", "verify": "PASS", "tier": "low", "gpt": "low", "since": None, "sha": SHA}
    base.update(over)
    return base


class Decide(unittest.TestCase):
    def test_all_clean_and_low_merges(self):
        merge, reasons, *_ = am.decide(pr(), [rec()])
        self.assertTrue(merge, reasons)

    # Verifier on c982ba2: the author's free-text tier kept reading lower than written; it no longer decides.
    def test_the_authors_tier_does_not_decide(self):
        for body in ("**Risk tier: low**", "**Risk tier: medium** - **high**", "no tier field at all"):
            merge, reasons, tiers, _ = am.decide(pr(body=body), [rec()])
            self.assertTrue(merge, (body, reasons))
            self.assertEqual(list(tiers), ["Claude verifier", "Codex review"])

    # k-defense-kg #35: the author called a dependency pin low.
    def test_highest_tier_wins_over_the_authors(self):
        merge, reasons, *_ = am.decide(pr(), [rec(tier="high")])
        self.assertFalse(merge)
        self.assertIn("risk tier high", reasons)
        self.assertFalse(am.decide(pr(), [rec(gpt="high")])[0])

    # User, 2026-10-30: up to medium merges without the user; high still goes to them.
    def test_medium_merges_high_does_not(self):
        merge, reasons, *_ = am.decide(pr(), [rec(tier="medium", gpt="medium")])
        self.assertTrue(merge, reasons)
        self.assertFalse(am.decide(pr(), [rec(tier="medium", gpt="high")])[0])

    def test_missing_codex_review_goes_to_the_user(self):
        merge, reasons, *_ = am.decide(pr(), [rec(gpt=None)])
        self.assertFalse(merge)
        self.assertTrue(any("Codex" in r for r in reasons))

    # hhmode #10 (2026-10-29): a record from before tiers existed must say so, not look like a broken PR.
    def test_old_record_without_a_tier_says_why(self):
        merge, reasons, *_ = am.decide(pr(), [rec(tier=None)])
        self.assertFalse(merge)
        self.assertTrue(any("written before the field existed" in r for r in reasons))

    def test_review_or_verify_not_pass_goes_to_the_user(self):
        self.assertFalse(am.decide(pr(), [rec(review="ISSUES")])[0])
        self.assertFalse(am.decide(pr(), [rec(review="BLOCKED")])[0])
        self.assertFalse(am.decide(pr(), [rec(verify="FAIL")])[0])
        self.assertFalse(am.decide(pr(), [rec(review=None)])[0])

    def test_ci_failing_or_pending_waits_and_no_ci_is_fine(self):
        self.assertFalse(am.decide(pr(statusCheckRollup=[{"status": "COMPLETED", "conclusion": "FAILURE"}]),
                                   [rec()])[0])
        self.assertFalse(am.decide(pr(statusCheckRollup=[{"status": "IN_PROGRESS", "conclusion": ""}]), [rec()])[0])
        self.assertFalse(am.decide(pr(statusCheckRollup=[{"state": "PENDING", "context": "x"}]), [rec()])[0])
        merge, _, _, status = am.decide(pr(statusCheckRollup=[]), [rec()])
        self.assertTrue(merge)
        self.assertEqual(status["ci"], "none")

    # GPT lane on e008f76 (P1): the review is against origin/main, so a PR into another base carries unreviewed code.
    def test_pr_into_another_base_goes_to_the_user(self):
        merge, reasons, *_ = am.decide(pr(baseRefName="release"), [rec()])
        self.assertFalse(merge)
        self.assertTrue(any("main" in r for r in reasons))

    def test_conflicting_or_closed_pr_goes_to_the_user(self):
        self.assertFalse(am.decide(pr(mergeable="CONFLICTING"), [rec()])[0])
        self.assertFalse(am.decide(pr(state="MERGED"), [rec()])[0])

    # A re-review scoped `since` an earlier commit saw only the new diff; the earlier commit's tiers still count.
    def test_tiers_from_the_since_ancestor_count(self):
        merge, reasons, tiers, _ = am.decide(pr(), [rec(since=OLD[:7]), rec(sha=OLD, gpt="high")])
        self.assertFalse(merge)
        self.assertIn("risk tier high", reasons)
        self.assertIn(f"Codex review ({OLD[:7]})", tiers)


class Chain(unittest.TestCase):
    """The Codex review is a fact of the standard review at the bottom of a chain of `since` records. A fix round ran
    without Codex and a carried record borrows the earlier review's result, so neither needs one of its own."""

    def test_a_fix_on_top_of_a_standard_review_merges(self):
        merge, reasons, tiers, _ = am.decide(pr(), [rec(mode="fix", gpt=None, since=OLD[:7]),
                                                    rec(mode="standard", sha=OLD, gpt="low")])
        self.assertTrue(merge, reasons)
        self.assertEqual(list(tiers), ["Claude verifier", f"Claude verifier ({OLD[:7]})", f"Codex review ({OLD[:7]})"])

    def test_a_carried_head_merges_with_or_without_its_own_copy_of_the_codex_review(self):
        for gpt in ("low", None):
            merge, reasons, *_ = am.decide(pr(), [rec(mode="carry", gpt=gpt, since=OLD[:7]),
                                                  rec(mode="standard", sha=OLD, gpt="low")])
            self.assertTrue(merge, (gpt, reasons))

    def test_a_chain_with_no_codex_review_anywhere_goes_to_the_author(self):
        for chain in ([rec(mode="fix", gpt=None, since=OLD[:7]), rec(mode="fix", sha=OLD, gpt=None)],
                      [rec(mode="carry", gpt=None)],
                      [rec(mode="fix", gpt=None, since=OLD[:7]), rec(mode="standard", sha=OLD, gpt=None)]):
            merge, reasons, *_ = am.decide(pr(), chain)
            self.assertFalse(merge)
            self.assertEqual(sum("Codex" in r for r in reasons), 1, reasons)      # said once, not once per record

    def test_a_standard_or_old_full_head_still_needs_its_own_codex_review(self):
        for mode in ("standard", "full", None):
            merge, reasons, *_ = am.decide(pr(), [rec(mode=mode, gpt=None)])
            self.assertFalse(merge, mode)
            self.assertTrue(any("Codex" in r for r in reasons), mode)
        # ... also when an earlier standard review in the chain has one
        merge, reasons, *_ = am.decide(pr(), [rec(mode="standard", gpt=None, since=OLD[:7]),
                                              rec(mode="standard", sha=OLD, gpt="low")])
        self.assertFalse(merge)

    def test_a_fix_head_does_not_hide_a_high_tier_from_the_chain(self):
        merge, reasons, *_ = am.decide(pr(), [rec(mode="fix", gpt=None, since=OLD[:7]),
                                              rec(mode="standard", sha=OLD, gpt="high")])
        self.assertFalse(merge)
        self.assertIn("risk tier high", reasons)

    def test_load_records_follows_a_carried_head_to_the_review_it_took(self):
        gate = pathlib.Path(tempfile.mkdtemp())
        s = "11111111-2222-3333-4444-555555555555"
        result = {"sha": OLD, "mode": "standard", "tier": "medium", "lanes": [], "findings": []}
        (gate / f"{OLD}.review.md").write_text(rr.render("PASS", OLD, result, "r", s, "PASS"))
        (gate / f"{OLD}.gpt.md").write_text(GPT_MED)
        (gate / f"{SHA}.review.md").write_text(rr.render_carry(SHA, OLD, ["README.md"], "medium"))
        recs = am.load_records(gate, SHA)
        self.assertEqual([(r["sha"], r["mode"], r["gpt"]) for r in recs],
                         [(SHA, "carry", None), (OLD, "standard", "medium")])
        merge, reasons, *_ = am.decide(pr(), recs)
        self.assertTrue(merge, reasons)


class Parse(unittest.TestCase):
    # The fields are read from what record_review.py actually writes, so a format change breaks this test.
    def test_record_fields_from_a_real_record(self):
        result = {"sha": SHA, "mode": "standard", "tier": "medium", "lanes": [], "findings": []}
        text = rr.render("PASS", SHA, result, "report", "11111111-2222-3333-4444-555555555555", "PASS",
                         since=OLD)
        self.assertEqual(am.record_fields(text),
                         {"review": "PASS", "since": OLD[:7], "mode": "standard", "verify": "PASS", "tier": "medium"})

    def test_record_fields_read_the_mode_of_every_kind_of_record(self):
        result = {"sha": SHA, "mode": "fix", "tier": "low", "lanes": [], "findings": []}
        fix = rr.render("PASS", SHA, result, "r", "s" * 36, "PASS", since=OLD)
        self.assertEqual(am.record_fields(fix)["mode"], "fix")
        carry = rr.render_carry(SHA, OLD, ["README.md"], "low")
        self.assertEqual(am.record_fields(carry), {"review": "PASS", "since": OLD[:7], "mode": "carry",
                                                   "verify": "PASS", "tier": "low"})
        full = "**Review: PASS** · ccccccc · full · verifier 1\n\n<!-- verifier-session: s; verify: PASS; lanes: -->\n"
        self.assertEqual(am.record_fields(full)["mode"], "full")
        self.assertIsNone(am.record_fields("")["mode"])

    # Verifier note on 08df90d (P3): an unfilled tier line read as low.
    def test_gpt_tier(self):
        self.assertEqual(am.gpt_tier(GPT_LOW), "low")
        self.assertEqual(am.gpt_tier(GPT_MED), "medium")
        self.assertIsNone(am.gpt_tier("## Findings\nnone\n"))
        self.assertIsNone(am.gpt_tier("## Tier\nlow | medium | high — <path: reason>\n"))
        self.assertIsNone(am.gpt_tier("## Tier\nlow-to-medium — x\n"))

    def test_load_records_follows_since(self):
        gate = pathlib.Path(tempfile.mkdtemp())
        result = {"sha": SHA, "mode": "standard", "tier": "low", "lanes": [], "findings": []}
        s = "11111111-2222-3333-4444-555555555555"
        (gate / f"{SHA}.review.md").write_text(rr.render("PASS", SHA, result, "r", s, "PASS", since=OLD))
        (gate / f"{SHA}.gpt.md").write_text(GPT_LOW)
        (gate / f"{OLD}.review.md").write_text(rr.render("PASS", OLD, {**result, "sha": OLD}, "r", s, "PASS"))
        (gate / f"{OLD}.gpt.md").write_text(GPT_MED)
        recs = am.load_records(gate, SHA)
        self.assertEqual([r["sha"] for r in recs], [SHA, OLD])
        self.assertEqual([r["gpt"] for r in recs], ["low", "medium"])

    # PR #13 and the verifier on a93fe87 / 8ddbe0d / c982ba2: only `<tier> — <reason>` counts.
    def test_codex_tier_only_in_its_exact_form(self):
        line = "## Tier\n{}\n"
        self.assertEqual(am.gpt_tier(line.format("high — scripts/automerge.py: from low to low or medium risk.")),
                         "high")
        for text in ("medium - high — x", "medium – high — x", "**medium** - **high** — x", "**high** — x",
                     "high", "high—a.py", "low | medium | high — <path: reason>", "low-to-medium — x"):
            self.assertIsNone(am.gpt_tier(line.format(text)), text)


class Message(unittest.TestCase):
    TIERS = {"Claude verifier": "low", "Codex review": None}

    # User, 2026-10-29: the report had no repo name and unexplained labels ("author low", "no GPT"), and nobody could
    # read it. User, 2026-10-30: every harness artifact is plain English.
    def test_report_names_the_repo_and_speaks_plainly(self):
        text = am.message(pr(), False, ["the Codex review did not run for this verification"], self.TIERS,
                          STATUS, "shadow", None)
        self.assertIn("[r #12] Needs you", text)
        self.assertIn("Review passed · Tests passed · CI passing · no conflicts", text)
        self.assertIn("Claude verifier low · Codex review none", text)
        self.assertIn('any "high" needs you', text)
        for jargon in ("GPT", "lane", "shadow"):
            self.assertNotIn(jargon, text)
        self.assertIsNone(re.search(r"[가-힣]", text))

    def test_ci_and_conflict_words(self):
        for ci, mergeable, said in (("none", "MERGEABLE", "CI none · no conflicts"),
                                    ("pending", "UNKNOWN", "CI running · still checking"),
                                    ("failing", "CONFLICTING", "CI failing · conflicts")):
            text = am.message(pr(), False, [], self.TIERS, {**STATUS, "ci": ci, "mergeable": mergeable}, "on", None)
            self.assertIn(said, text)

    def test_shadow_says_it_did_not_merge(self):
        text = am.message(pr(), True, [], self.TIERS, STATUS, "shadow", None)
        self.assertIn("[trial] would merge, not merged", text)

    def test_on_gives_the_revert(self):
        text = am.message(pr(), True, [], self.TIERS, STATUS, "on", "e" * 40)
        self.assertIn("*[r #12] Merged*", text)
        self.assertIn("git revert eeeeeee", text)

    # GPT lane on e008f76 (P3): --dry-run with mode on printed "Merged" and "git revert ?".
    def test_no_merge_commit_never_reads_as_merged(self):
        for mode in ("on", "dry-run"):
            text = am.message(pr(), True, [], self.TIERS, STATUS, mode, None)
            self.assertIn("would merge, not merged", text)
            self.assertNotIn("*Merged*", text)
            self.assertNotIn("git revert", text)

    # Verifier note on 08df90d (P2): a merge refused by GitHub ended the run with no report.
    def test_failed_merge_is_reported(self):
        text = am.message(pr(), True, [], self.TIERS, STATUS, "on", None, error="Pull request is in draft")
        self.assertIn("Merge failed", text)
        self.assertIn("Pull request is in draft", text)

    # Verifier note on f07e72f (P2): the merge went through, the lookup after it failed, and it read as a failure.
    def test_merge_then_failed_lookup_reads_as_merged(self):
        rc, text, calls, _ = run_main(lookup_fails=True)
        self.assertEqual(rc, 0)
        self.assertTrue(any(c[:2] == ("pr", "merge") for c in calls))
        self.assertIn("Merged*", text)
        self.assertIn("Merged, but the merge commit could not be read back", text)
        self.assertNotIn("Merge failed", text)
        self.assertIn("automerge: MERGED", text)

    def test_to_user_names_the_reasons(self):
        text = am.message(pr(), False, ["risk tier medium", "CI is failing"], self.TIERS, STATUS, "shadow", None)
        self.assertIn("Needs you", text)
        self.assertIn("Why it was not merged: risk tier medium, CI is failing", text)


ISSUE = {"number": 7, "url": "https://github.com/o/r/issues/7", "state": "OPEN", "title": "One header per project",
         "body": "## Background\nThe report names a project twice.\n\n## Acceptance criteria\n"
                 "- [ ] AC1: each project is named once\n\n## Out of scope\nnone\n\n## Risk\nlow — docs\n"}


def run_main(pr_over=None, records=None, check=None, issue_state="OPEN", lookup_fails=False, args=(),
             rules="", diff="diff --git a/x b/x\n+line\n", graphql_fails=False):
    """main() with gh and the merge check faked; returns (exit code, stdout, gh calls, merge-check inputs)."""
    import contextlib, io, json as js, subprocess
    here = pathlib.Path(tempfile.mkdtemp())
    repo = here / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (here / "local").mkdir()
    (here / "local" / "automerge").write_text("on\n")
    calls, inputs = [], []

    def fake_gh(*a, cwd):
        calls.append(a)
        if a[:2] == ("api", "graphql"):
            if graphql_fails:
                raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 502: Bad Gateway")
            return js.dumps({"data": {"repository": {"pullRequest": {"closingIssuesReferences": {"nodes": [ISSUE]}}}}})
        if a[:2] == ("pr", "diff"):
            return diff
        if a[0] == "api" and "contents/CLAUDE.md" in a[-1]:
            if rules is None:
                raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 500: Internal Server Error")
            if rules == "":
                raise subprocess.CalledProcessError(1, "gh", stderr="gh: Not Found (HTTP 404)")
            return rules
        if a[:2] == ("issue", "view"):
            return js.dumps({"state": issue_state})
        if a[:2] in {("pr", "merge"), ("issue", "close"), ("pr", "comment")}:
            return ""
        if "mergeCommit" in a:
            if lookup_fails:
                raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 502: Bad Gateway")
            return js.dumps({"mergeCommit": {"oid": "e" * 40}})
        return js.dumps(pr(**(pr_over or {})))

    def fake_check(text):
        inputs.append(text)
        return check or {"merge": True, "reason": "Names each project once in the weekly report.",
                         "session": "abcd1234-x"}
    saved = (am.gh, am.load_records, am.HERE, am.merge_check, am.CLOSE_WAIT)
    am.gh, am.load_records, am.HERE, am.merge_check, am.CLOSE_WAIT = (
        fake_gh, (lambda gate, sha: records or [rec()]), here, fake_check, 0)
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = am.main(["12", "--repo", str(repo), *args])
    finally:
        am.gh, am.load_records, am.HERE, am.merge_check, am.CLOSE_WAIT = saved
    return rc, out.getvalue(), calls, inputs


class Flow(unittest.TestCase):
    """User, 2026-10-30: when CI, the verifier and the review pass, a fresh Claude checks and merges; only what
    needs the user goes to Slack; the issue the PR closes is closed."""

    def test_clean_pr_is_checked_merged_and_its_issue_closed_without_slack(self):
        rc, text, calls, inputs = run_main()
        self.assertIn(("pr", "merge", "12", "--squash", "--match-head-commit", SHA), calls)
        self.assertTrue(any(c[:3] == ("issue", "close", ISSUE["url"]) and "completed" in c for c in calls))
        self.assertTrue(any(c[:2] == ("pr", "comment") and "Merge check (Claude, session abcd1234): merged." in c[-1]
                            for c in calls))
        self.assertIn("each project is named once", inputs[0])         # the check reads the issue it closes
        self.assertIn("+line", inputs[0])
        self.assertNotIn("[slack]", text)
        self.assertIn("automerge: MERGED", text)

    def test_an_issue_github_already_closed_is_left_alone(self):
        _, _, calls, _ = run_main(issue_state="CLOSED")
        self.assertFalse(any(c[:2] == ("issue", "close") for c in calls))

    def test_merge_check_no_goes_to_slack_unmerged(self):
        rc, text, calls, _ = run_main(check={"merge": False, "reason": "scripts/x.py:3 deletes data", "session": ""})
        self.assertFalse(any(c[:2] == ("pr", "merge") for c in calls))
        self.assertIn("Merge check (Claude): scripts/x.py:3 deletes data", text)
        self.assertIn("[slack]", text)

    # A fact that fails stops everything: no merge check, and no Slack — the author fixes it (/pr step 9).
    def test_a_failing_fact_skips_the_check_and_slack(self):
        failing = [{"status": "COMPLETED", "conclusion": "FAILURE", "name": "ci"}]
        rc, text, calls, inputs = run_main(pr_over={"statusCheckRollup": failing})
        self.assertEqual(inputs, [])
        self.assertFalse(any(c[:2] == ("pr", "merge") for c in calls))
        self.assertIn("CI is failing", text)
        self.assertNotIn("[slack]", text)
        _, text, _, _ = run_main(pr_over={"statusCheckRollup": failing}, args=("--report",))
        self.assertIn("[slack]", text)

    # Verifier and GPT lane on c470756: what the check cannot read must not pass, and must not crash silently.
    def test_unreadable_input_goes_to_the_user_without_the_check(self):
        for kw, said in ((dict(rules=None), "could not read the repo's CLAUDE.md"),
                         (dict(diff="+" * (am.DIFF_CAP + 1)), "for the merge check to read all of it"),
                         (dict(graphql_fails=True), "could not read the issues this PR closes")):
            rc, text, calls, inputs = run_main(**kw)
            self.assertEqual(inputs, [], said)
            self.assertFalse(any(c[:2] == ("pr", "merge") for c in calls), said)
            self.assertIn(said, text)
            self.assertIn("[slack]", text)

    def test_the_repo_rules_reach_the_check(self):
        _, _, _, inputs = run_main(rules="| Medium | user confirmation |")
        self.assertIn("| Medium | user confirmation |", inputs[0])

    def test_issue_comment_without_a_merge_commit_says_no_unknown(self):
        _, _, calls, _ = run_main(lookup_fails=True)
        close = [c for c in calls if c[:2] == ("issue", "close")][0]
        self.assertEqual(close[-1], "Done in the merge of #12")

    def test_a_high_tier_skips_the_check_and_goes_to_slack(self):
        rc, text, calls, inputs = run_main(records=[rec(tier="high")])
        self.assertEqual(inputs, [])
        self.assertIn("risk tier high", text)
        self.assertIn("[slack]", text)

    def test_the_issue_comment_names_the_merge_commit(self):
        _, _, calls, _ = run_main()
        close = [c for c in calls if c[:2] == ("issue", "close")][0]
        self.assertEqual(close[-1], "Done in the merge of #12 (eeeeeee)")

    # User, 2026-10-30: the issue's criteria must reach the PR. A body that skips the form is the author's to fix:
    # printed, not sent, and the merge check does not start.
    def test_a_pr_body_that_skips_the_forms_waits_for_the_author(self):
        for body, said in (("**Risk tier: low** (docs only)", "PR body: missing section: ## Why"),
                           (BODY.replace("- AC1: python3 -m unittest scripts/test_weekly.py → OK",
                                         "- AC9: something else"),
                            "PR body: Acceptance criteria does not name AC1 of issue #7")):
            rc, text, calls, inputs = run_main(pr_over={"body": body})
            self.assertEqual(inputs, [], said)
            self.assertFalse(any(c[:2] == ("pr", "merge") for c in calls), said)
            self.assertIn(said, text)
            self.assertIn("Needs you", text)
            self.assertIn("automerge: TO USER", text)
            self.assertNotIn("[slack]", text)
        _, text, _, _ = run_main(pr_over={"body": "**Risk tier: low**"}, args=("--report",))
        self.assertIn("[slack]", text)

    # The issues are read before deciding, also on a dry run: reading is all they cost.
    def test_dry_run_reads_the_issues_and_checks_the_form(self):
        rc, text, calls, inputs = run_main(args=("--dry-run",))
        self.assertTrue(any(c[:2] == ("api", "graphql") for c in calls))
        self.assertIn("[dry-run] would merge, not merged", text)
        self.assertEqual(inputs, [])
        _, text, _, _ = run_main(pr_over={"body": BODY.replace("Closes #7\n", "").replace("AC1", "AC9")},
                                 args=("--dry-run",))
        self.assertIn("Acceptance criteria does not name AC1 of issue #7", text)

    def test_form_problems_are_reasons_for_the_author(self):
        self.assertEqual(am.form_problems(pr(), [ISSUE]), [])
        got = am.form_problems(pr(body="## Why\nx\nCloses #8"), [ISSUE])
        self.assertIn("PR body: issue #8 was not read", got)
        self.assertIn("PR body: missing section: ## Acceptance criteria", got)


class CheckInput(unittest.TestCase):
    # Merge check on k-defense-kg #51: it held a medium PR back only because the record happened to quote the
    # repo's rule; the rule is now always in its input.
    def test_input_carries_the_pr_issue_rules_records_and_diff(self):
        text = am.check_input(pr(body="THE BODY"), [ISSUE], [rec(text="REC", gpt_text="GPT")], "+x\n",
                              "Medium | user confirmation")
        for part in ("THE BODY", "each project is named once", "Medium | user confirmation", "REC", "GPT", "+x"):
            self.assertIn(part, text)
        self.assertNotIn("CLAUDE.md", am.check_input(pr(), [], [rec(text="", gpt_text="")], "", ""))

    # GPT lane on c470756: a local ref could predate a new rule, and any failure read as "no rules".
    def test_repo_rules_come_from_github_and_fail_closed(self):
        import subprocess
        asked = []

        def fake_gh(*a, cwd, answer):
            asked.append(a[-1])
            if isinstance(answer, str):
                return answer
            raise subprocess.CalledProcessError(1, "gh", stderr=answer[0])
        saved = am.gh
        try:
            for answer, want in (("rules\n", "rules\n"), (("gh: Not Found (HTTP 404)",), ""),
                                 (("HTTP 502: Bad Gateway",), None)):
                am.gh = lambda *a, cwd, answer=answer: fake_gh(*a, cwd=cwd, answer=answer)
                self.assertEqual(am.repo_rules(pr(), "."), want)
        finally:
            am.gh = saved
        self.assertEqual(asked[0], "repos/o/r/contents/CLAUDE.md?ref=main")


class MergeCheck(unittest.TestCase):
    """merge_check() against a stand-in `claude` on PATH."""

    def run_with(self, body):
        import os
        bin_dir = pathlib.Path(tempfile.mkdtemp())
        self.seen = bin_dir / "seen"
        (bin_dir / "claude").write_text(f"#!/usr/bin/env bash\ncat > /dev/null\n{{ pwd; echo \"$@\"; }} > {self.seen}\n"
                                        + body)
        (bin_dir / "claude").chmod(0o755)
        old = os.environ["PATH"]
        os.environ["PATH"] = f"{bin_dir}:{old}"
        try:
            return am.merge_check("input")
        finally:
            os.environ["PATH"] = old

    # Verifier on c470756: run in the PR's worktree, the check also read that branch's own CLAUDE.md.
    def test_runs_in_an_empty_folder_with_customizations_off(self):
        self.run_with("""echo '{"structured_output": {"merge": true, "reason": "x"}}'\n""")
        cwd, args = self.seen.read_text().splitlines()[:2]
        self.assertIn("merge-check-", cwd)
        self.assertIn("--safe-mode", args)
        self.assertIn("--tools", args)

    # Verifier on 4c93a55 (P3): the empty folder was made with mkdtemp and never removed.
    def test_the_empty_folder_is_removed_afterwards(self):
        self.run_with("""echo '{"structured_output": {"merge": true, "reason": "x"}}'\n""")
        cwd = self.seen.read_text().splitlines()[0]
        self.assertFalse(pathlib.Path(cwd).exists())

    def test_empty_output_reports_stderr(self):
        got = self.run_with("echo 'credit balance too low' >&2\nexit 1\n")
        self.assertIn("credit balance too low", got["reason"])

    def test_structured_answer(self):
        got = self.run_with(
            """echo '{"structured_output": {"merge": true, "reason": "Docs only."}, "session_id": "s1"}'\n""")
        self.assertEqual(got, {"merge": True, "reason": "Docs only.", "session": "s1"})

    # No answer is a no: the PR goes to the user with what the check said.
    def test_no_answer_is_a_no(self):
        for body in ("echo 'not json'\n", """echo '{"result": "Claude Code can\\x27t use your subscription"}'\n""",
                     "exit 1\n"):
            got = self.run_with(body)
            self.assertFalse(got["merge"])
            self.assertIn("the merge check could not answer", got["reason"])


if __name__ == "__main__":
    unittest.main()
