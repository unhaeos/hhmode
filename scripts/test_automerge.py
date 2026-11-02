"""Tests for automerge.py. Run: python3 -m unittest scripts/test_automerge.py (from the hhmode root)."""
from __future__ import annotations

import contextlib
import fcntl
import io
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
import time
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
        rc, text, calls, _ = run_main(claude_merges=False, lookup_fails=True)
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


COMMAND = f"gh pr merge 12 -R o/r --squash --match-head-commit {SHA}"
ISSUE = {"number": 7, "url": "https://github.com/o/r/issues/7", "state": "OPEN", "title": "One header per project",
         "body": "## Background\nThe report names a project twice.\n\n## Acceptance criteria\n"
                 "- [ ] AC1: each project is named once\n\n## Out of scope\nnone\n\n## Risk\nlow — docs\n"}


def fake_codex(a, codex):
    """The Codex part of the fake gh: the REST lists of comments, review bodies and line comments, and `pr list`. None
    when `a` is not one of those calls. `codex`: {"issue_comments", "reviews", "lines", "recent", "fails"}."""
    codex = codex or {}
    if "--slurp" in a or a[:2] == ("pr", "list"):
        if codex.get("fails"):
            raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 502: Bad Gateway")
        if a[:2] == ("pr", "list"):
            return json.dumps([{"number": q["number"]} for q in codex.get("recent", [])])
        if "/issues/" in a[1] and not a[1].endswith("/issues/12/comments"):        # another, recent PR
            n = int(a[1].split("/issues/")[1].split("/")[0])
            return json.dumps([next((q["comments"] for q in codex.get("recent", []) if q["number"] == n), [])])
        kind = "issue_comments" if "/issues/" in a[1] else "reviews" if a[1].endswith("/reviews") else "lines"
        return json.dumps([codex.get(kind, [])])      # --slurp: a list of pages
    return None


def lock_is_held(gate):
    """Whether another open file description holds the PR's merge lock right now."""
    with open(next(gate.glob("merge-*.lock")), "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def run_main(pr_over=None, records=None, check=None, issue_state="OPEN", lookup_fails=False, args=(),
             rules="", diff="diff --git a/x b/x\n+line\n", graphql_fails=False, mode="on", claude_merges=True,
             merge_fails=None, readback_fails=False, codex=None, slack=None, here=None, probe=None):
    """main() with gh and the merge check faked; returns (exit code, stdout, gh calls, merge-check inputs).
    The merge check shows up in the calls as ("merge-check", the command it was given or None). `claude_merges`: the
    fake Claude runs the merge command it was given, as the real one does when allowed; False is a denied tool. The
    fake PR starts open and is merged by that command or by `gh pr merge`. `slack`: a list that collects what would be
    posted. `here`: reuse an earlier run's folder (same repo, same gate). `probe`: a list that collects (event,
    whether the merge lock was held) when the PR is read and when the merge check runs."""
    import contextlib, io, json as js
    here = here or pathlib.Path(tempfile.mkdtemp())
    repo = here / "repo"
    if not repo.exists():
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (here / "local").mkdir()
    (here / "local" / "automerge").write_text(f"{mode}\n")
    gate = repo / ".git" / "gate"
    calls, inputs = [], []
    st = {"state": "OPEN", "by": None}

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
        if a[:2] == ("pr", "merge"):
            if merge_fails:
                raise subprocess.CalledProcessError(1, "gh", stderr=merge_fails)
            st.update(state="MERGED", by="script")
            return ""
        if a[:2] in {("issue", "close"), ("pr", "comment")}:
            return ""
        if a[-1] == "state,mergeCommit":
            if readback_fails or (lookup_fails and st["by"] == "script"):
                raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 502: Bad Gateway")
            merged = {"oid": "e" * 40} if st["state"] == "MERGED" else None
            return js.dumps({"state": st["state"], "mergeCommit": merged})
        if (got := fake_codex(a, codex)) is not None:
            return got
        if probe is not None and a[:2] == ("pr", "view") and a[-1].startswith("number,"):
            probe.append(("read", lock_is_held(gate)))
        return js.dumps(pr(**(pr_over or {})))

    def fake_check(text, command=None):
        inputs.append(text)
        calls.append(("merge-check", command))
        if probe is not None:
            probe.append(("check", lock_is_held(gate)))
        answer = check or {"merge": True, "reason": "Names each project once in the weekly report.",
                           "session": "abcd1234-x"}
        if command and claude_merges and (answer["merge"] or claude_merges == "always"):
            st.update(state="MERGED", by="claude")
        return answer
    saved = (am.gh, am.load_records, am.HERE, am.merge_check, am.CLOSE_WAIT, am.post_slack)
    am.gh, am.load_records, am.HERE, am.merge_check, am.CLOSE_WAIT = (
        fake_gh, (lambda gate, sha: records or [rec()]), here, fake_check, 0)
    if slack is not None:
        am.post_slack = lambda text: (slack.append(text), "sent")[1]
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = am.main(["12", "--repo", str(repo), *args])
    finally:
        am.gh, am.load_records, am.HERE, am.merge_check, am.CLOSE_WAIT, am.post_slack = saved
    return rc, out.getvalue(), calls, inputs


class Flow(unittest.TestCase):
    """User, 2026-10-30: when CI, the verifier and the review pass, a fresh Claude checks and merges; only what
    needs the user goes to Slack; the issue the PR closes is closed."""

    def test_clean_pr_is_checked_merged_and_its_issue_closed_and_reported(self):
        slack = []
        rc, text, calls, inputs = run_main(slack=slack)
        self.assertIn(("merge-check", COMMAND), calls)          # Claude was given the merge command and ran it
        self.assertFalse(any(c[:2] == ("pr", "merge") for c in calls))      # so the script did not
        self.assertIn("Merged by the merge check (Claude)", text)
        self.assertTrue(any(c[:3] == ("issue", "close", ISSUE["url"]) and "completed" in c for c in calls))
        self.assertTrue(any(c[:2] == ("pr", "comment") and "Merge check (Claude, session abcd1234): merged." in c[-1]
                            for c in calls))
        self.assertIn("each project is named once", inputs[0])         # the check reads the issue it closes
        self.assertIn("+line", inputs[0])
        # hhmode #18 AC1: a merge is reported too, once, with what closed and how to undo it.
        self.assertEqual(len(slack), 1)
        self.assertTrue(slack[0].startswith("✅ *[r #12] Merged*"))
        self.assertIn("• Closed: #7", slack[0])
        self.assertIn("To undo: `git revert", slack[0])
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
        _, _, calls, _ = run_main(claude_merges=False, lookup_fails=True)
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


class ClaudeMerges(unittest.TestCase):
    """User decision 2026-11-02: Claude runs the merge itself, with exactly one allowed command; the script reads the
    PR back and never leaves an approved PR unmerged."""

    def test_the_command_is_built_from_the_pr(self):
        self.assertEqual(am.merge_command(pr()), COMMAND)
        other = pr(number=17, url="https://github.com/unhaeos/hhmode/pull/17", headRefOid="a" * 40)
        self.assertEqual(am.merge_command(other),
                         "gh pr merge 17 -R unhaeos/hhmode --squash --match-head-commit " + "a" * 40)
        self.assertEqual(am.merge_args(pr()),
                         ["pr", "merge", "12", "-R", "o/r", "--squash", "--match-head-commit", SHA])

    def test_when_claude_merged_the_script_does_not_merge_again(self):
        _, text, calls, _ = run_main()
        self.assertFalse(any(c[:2] == ("pr", "merge") for c in calls))
        self.assertIn("*[r #12] Merged*", text)
        self.assertIn("Merged by the merge check (Claude)", text)
        self.assertIn("git revert eeeeeee", text)
        comment = [c for c in calls if c[:2] == ("pr", "comment")][0][-1]
        self.assertIn("Merge check (Claude, session abcd1234): merged.", comment)
        self.assertNotIn("did not run", comment)

    # Claude said yes, but its command was denied or skipped: the PR is still open, so the script runs the same one.
    def test_a_yes_with_the_pr_still_open_is_merged_by_the_script(self):
        rc, text, calls, _ = run_main(claude_merges=False)
        self.assertEqual(sum(c[:2] == ("pr", "merge") for c in calls), 1)
        self.assertIn(("pr", "merge", "12", "-R", "o/r", "--squash", "--match-head-commit", SHA), calls)
        self.assertIn(("merge-check", COMMAND), calls)       # the same command Claude was given
        comment = [c for c in calls if c[:2] == ("pr", "comment")][0][-1]
        self.assertIn("its merge command did not run", comment)
        self.assertIn("the script ran the same command and merged the PR", comment)
        self.assertIn("Merged by this script, because the merge check's own command did not run", text)
        self.assertTrue(any(c[:2] == ("issue", "close") for c in calls))
        self.assertIn("automerge: MERGED", text)
        self.assertIn("[slack]", text)                          # hhmode #18: every merge is reported

    # Verifier note on 502f5a8: an issue whose close failed is not listed as closed.
    def test_a_failed_issue_close_is_not_listed_as_closed(self):
        saved = am.close_issues
        am.close_issues = lambda issues, pr, merged, cwd: [f"could not close issue #7: HTTP 403"]
        slack = []
        try:
            run_main(slack=slack)
        finally:
            am.close_issues = saved
        self.assertNotIn("Closed: #7", slack[0])
        self.assertIn("could not close issue #7", slack[0])

    # hhmode #18 AC3: Slack failing after a merge is printed and does not turn the merge into a failure.
    def test_slack_failing_after_a_merge_leaves_it_merged(self):
        saved = am.post_once
        am.post_once = lambda *a, **k: (_ for _ in ()).throw(OSError("network down"))
        try:
            rc, text, calls, _ = run_main()
        finally:
            am.post_once = saved
        self.assertEqual(rc, 0)
        self.assertIn("[slack] not sent: network down", text)
        self.assertIn("automerge: MERGED", text)

    def test_the_fallback_merge_failing_is_reported(self):
        rc, text, calls, _ = run_main(claude_merges=False, merge_fails="X Head branch was modified")
        self.assertIn("Merge failed", text)
        self.assertIn("Head branch was modified", text)
        self.assertIn("[slack]", text)
        self.assertIn("automerge: MERGE FAILED", text)
        self.assertFalse(any(c[:2] == ("pr", "comment") for c in calls))

    # If the PR cannot be read back, the script does not guess: merging again could be a second merge of a merged PR.
    def test_an_unreadable_pr_after_the_check_is_reported_and_not_merged_again(self):
        rc, text, calls, _ = run_main(readback_fails=True)
        self.assertFalse(any(c[:2] == ("pr", "merge") for c in calls))
        self.assertIn("could not read the PR after the merge check", text)
        self.assertIn("[slack]", text)

    # Dry run runs no check. Any other mode runs the check with no tools: Claude never holds the merge command.
    def test_no_merge_command_in_dry_run_or_a_mode_other_than_on(self):
        _, text, calls, inputs = run_main(args=("--dry-run",))
        self.assertEqual(inputs, [])
        self.assertFalse(any(c[0] == "merge-check" or c[:2] == ("pr", "merge") for c in calls))
        for mode in ("shadow", "off", "trial"):
            _, text, calls, inputs = run_main(mode=mode)
            self.assertEqual(len(inputs), 1, mode)
            self.assertIn(("merge-check", None), calls, mode)
            self.assertFalse(any(c[:2] == ("pr", "merge") for c in calls), mode)
            self.assertFalse(any(c[:2] == ("pr", "comment") for c in calls), mode)
            self.assertIn("would merge, not merged", text)
        # `--dry-run` wins over mode `on`
        _, _, calls, inputs = run_main(mode="on", args=("--dry-run",))
        self.assertEqual(inputs, [])

    def test_a_no_leaves_the_pr_alone(self):
        no = {"merge": False, "reason": "scripts/x.py:3 deletes data", "session": ""}
        _, text, calls, _ = run_main(check=no, claude_merges=True)
        self.assertFalse(any(c[:2] == ("pr", "merge") for c in calls))
        # Claude held the merge command, so the PR is read back even after a no (verifier on f97c493); still open.
        self.assertTrue(any(c[-1] == "state,mergeCommit" for c in calls))
        self.assertIn("automerge: TO USER", text)
        self.assertIn("[slack]", text)


class Lock(unittest.TestCase):
    """verifier on k-defense-kg caf3607 (P1): the runner workflow and /pr step 8 could run two merge checks on one PR
    at once, each with its own Claude."""

    def test_a_second_run_waits_for_the_first(self):
        gate = pathlib.Path(tempfile.mkdtemp()) / "gate"
        entered = threading.Event()

        def second():
            with am.merge_lock(gate, "o", "r", 12):
                entered.set()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), am.merge_lock(gate, "o", "r", 12):
            t = threading.Thread(target=second)
            t.start()
            self.assertFalse(entered.wait(0.3))             # blocked while the first holds it
        self.assertTrue(entered.wait(5))                    # and goes on once the first is done
        t.join()
        self.assertIn("another merge check is running on #12", out.getvalue())
        self.assertTrue((gate / "merge-o-r-12.lock").exists())

    def test_another_pr_does_not_wait(self):
        gate = pathlib.Path(tempfile.mkdtemp()) / "gate"
        with am.merge_lock(gate, "o", "r", 12):
            with am.merge_lock(gate, "o", "r", 13):
                with am.merge_lock(gate, "o", "other", 12):
                    pass

    def test_a_run_holds_the_lock_while_it_reads_the_pr_and_while_the_check_runs(self):
        probe = []
        run_main(probe=probe)
        self.assertEqual(probe, [("read", True), ("check", True)])      # read fresh only after taking it

    def test_a_run_waits_for_a_held_lock(self):
        here = pathlib.Path(tempfile.mkdtemp())
        run_main(here=here)                                 # makes the repo and its gate
        gate = here / "repo" / ".git" / "gate"
        done, out = threading.Event(), []

        def second():
            out.append(run_main(here=here, pr_over={"state": "MERGED"}))
            done.set()
        with am.merge_lock(gate, "o", "r", 12):
            t = threading.Thread(target=second)
            t.start()
            self.assertFalse(done.wait(0.3))
        self.assertTrue(done.wait(5))
        t.join()
        self.assertIn("nothing to do", out[0][1])

    # A run that waited finds the PR merged by the one before it: it ends there, printed, without Slack.
    def test_a_pr_that_is_no_longer_open_ends_quietly(self):
        for state in ("MERGED", "CLOSED"):
            slack = []
            rc, text, calls, inputs = run_main(pr_over={"state": state}, mode="shadow", slack=slack,
                                               args=("--report",))
            self.assertEqual(rc, 0)
            self.assertIn(f"#12 is {state}, nothing to do", text)
            self.assertNotIn("[slack]", text)
            self.assertEqual((slack, inputs), ([], []))
            self.assertFalse(any(c[:2] in {("pr", "merge"), ("pr", "diff"), ("api", "graphql")} for c in calls))


class Marks(unittest.TestCase):
    """hhmode #23 AC1: what the user acts on, what failed and what merged are told apart at a glance in Slack."""

    def test_each_outcome_starts_with_its_mark(self):
        tiers = {"Claude verifier": "low", "Codex review": "low"}
        needs = am.message(pr(), False, ["risk tier high"], tiers, STATUS, "on", None)
        failed = am.message(pr(), True, [], tiers, STATUS, "on", None, error="Pull request is in draft")
        merged = am.message(pr(), True, [], tiers, STATUS, "on", "e" * 40)
        trial = am.message(pr(), True, [], tiers, STATUS, "shadow", None)
        self.assertTrue(needs.startswith("🔔 *[r #12] Needs you*"))
        self.assertTrue(failed.startswith("⚠️ *[r #12] Merge failed*"))
        self.assertTrue(merged.startswith("✅ *[r #12] Merged*"))
        self.assertTrue(trial.startswith("*[r #12] [trial] would merge"))         # no mark: nothing to act on
        self.assertEqual(am.slack_key(needs), needs.split("\n")[0].removeprefix("🔔 "))


class SlackOnce(unittest.TestCase):
    """CI and Gate both finishing starts the runner twice per push (verifier note on k-defense-kg caf3607: a high-tier
    PR got "Needs you" twice)."""

    def setUp(self):
        self.gate = pathlib.Path(tempfile.mkdtemp()) / "gate"
        self.sent, self.saved = [], am.post_slack
        am.post_slack = lambda text: (self.sent.append(text), "sent")[1]

    def tearDown(self):
        am.post_slack = self.saved

    def test_the_same_message_for_the_same_head_goes_out_once(self):
        self.assertEqual(am.post_once("Needs you", self.gate, 12, SHA), "sent")
        self.assertIn("already sent", am.post_once("Needs you", self.gate, 12, SHA))
        self.assertEqual(self.sent, ["Needs you"])
        marker = (self.gate / f"slack-12-{SHA}.sent").read_text()
        self.assertNotIn("Needs you", marker)               # a hash, not the text

    def test_another_message_another_head_or_another_pr_goes_out(self):
        am.post_once("Needs you", self.gate, 12, SHA)
        am.post_once("Needs you, differently", self.gate, 12, SHA)
        am.post_once("Needs you", self.gate, 12, OLD)
        am.post_once("Needs you", self.gate, 13, SHA)
        am.post_once("Needs you", self.gate, 12, SHA)       # still remembered after the other message
        self.assertEqual(len(self.sent), 4)

    # Two runs on one head whose merge check said no in different words: one message, not two.
    def test_a_different_reason_for_the_same_outcome_goes_out_once(self):
        first = "*[r #12] Needs you* — docs: x\n• Why it was not merged: the check said A\nurl"
        second = "*[r #12] Needs you* — docs: x\n• Why it was not merged: the check said B\nurl"
        sent = []
        saved = am.post_slack
        am.post_slack = lambda text: sent.append(text) or "sent"
        try:
            gate = pathlib.Path(tempfile.mkdtemp())
            am.post_once(first, gate, 12, SHA)
            self.assertIn("already sent", am.post_once(second, gate, 12, SHA))
        finally:
            am.post_slack = saved
        self.assertEqual(sent, [first])

    # hhmode #23 AC2: a message sent before the marks existed is not taken for a new one.
    def test_a_message_sent_before_the_marks_is_not_sent_again(self):
        old = "*[r #12] Needs you* — docs: x\n• Why it was not merged: risk tier high\nurl"
        new = "🔔 *[r #12] Needs you* — docs: x\n• Why it was not merged: risk tier high\nurl"
        marker = self.gate / f"slack-12-{SHA}.sent"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(am.hashlib.sha256(old.split("\n", 1)[0].encode()).hexdigest() + "\n")
        self.assertIn("already sent", am.post_once(new, self.gate, 12, SHA))
        self.assertEqual(self.sent, [])

    def test_a_message_that_did_not_go_out_is_tried_again(self):
        am.post_slack = lambda text: "not sent: ratelimited"
        self.assertEqual(am.post_once("Needs you", self.gate, 12, SHA), "not sent: ratelimited")
        am.post_slack = lambda text: (self.sent.append(text), "sent")[1]
        self.assertEqual(am.post_once("Needs you", self.gate, 12, SHA), "sent")

    def test_two_runs_on_one_head_send_one_message(self):
        here, sent = pathlib.Path(tempfile.mkdtemp()), []
        _, first, _, _ = run_main(records=[rec(tier="high")], here=here, slack=sent)
        _, second, _, _ = run_main(records=[rec(tier="high")], here=here, slack=sent)
        self.assertEqual(len(sent), 1)
        self.assertIn("[slack] sent", first)
        self.assertIn("[slack] not sent: the same message was already sent", second)
        # a new head is a new message
        _, third, _, _ = run_main(records=[rec(tier="high")], here=here, slack=sent, pr_over={"headRefOid": OLD})
        self.assertEqual(len(sent), 2)


def codex_comment(security=None, code=None, login=am.CODEX_BOT, prose="## Codex Review Summary\n"):
    """A PR comment as the Codex app writes it (measured on k-defense-kg #67): the state as JSON in an HTML comment,
    then prose."""
    state = {"code_review": code or {"commit_sha": None, "has_any_findings": None, "has_unresolved_findings": None,
                                     "status": None},
             "security_review": security or {"commit_sha": SHA, "has_any_findings": None,
                                             "has_unresolved_findings": None, "status": "completed"}}
    return {"user": {"login": login}, "body": "<!-- codex-pull-request-review-summary -->\n"
            f"<!-- codex-review-state:v1 {json.dumps(state, sort_keys=True)} -->\n{prose}"}


class ClaudeAnswerLost(unittest.TestCase):
    """Verifier and Codex on f97c493 (P1): Claude held the merge command, ran it, and then its answer was lost or said
    no. The PR is read back whatever the answer."""

    def test_a_merge_claude_ran_is_reported_as_merged_and_its_issue_closed(self):
        lost = {"merge": False, "reason": "the merge check did not answer: timed out", "session": ""}
        slack = []
        rc, text, calls, _ = run_main(check=lost, claude_merges="always", slack=slack)
        self.assertIn("automerge: MERGED", text)
        self.assertTrue(any(c[:2] == ("issue", "close") for c in calls))
        self.assertFalse(any(c[:2] == ("pr", "merge") for c in calls))        # the script did not merge again
        self.assertTrue(slack and "answer was lost or said no" in slack[0])

    def test_a_no_with_the_pr_still_open_stays_a_no(self):
        no = {"merge": False, "reason": "scripts/x.py:3 deletes data", "session": "s"}
        rc, text, calls, _ = run_main(check=no, claude_merges=True)
        self.assertIn("automerge: TO USER", text)
        self.assertFalse(any(c[:2] == ("issue", "close") for c in calls))


class AskedOnce(unittest.TestCase):
    """Verifier on 91848ab (two P1): the merge check's answer for a head is kept whether or not its DM went out, and a
    second starter (/pr step 8 or the poller) does not ask Claude again for that head."""

    def test_a_no_is_not_asked_again(self):
        here = pathlib.Path(tempfile.mkdtemp())
        no = {"merge": False, "reason": "scripts/x.py:3 deletes data", "session": "s1"}
        _, _, _, first = run_main(check=no, here=here)
        rc, text, calls, second = run_main(check={"merge": True, "reason": "would merge", "session": "s2"}, here=here)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])                                    # Claude was not asked again
        self.assertIn("already said no", text)
        self.assertIn("automerge: TO USER", text)
        self.assertFalse(any(c[:2] == ("pr", "merge") for c in calls))

    def test_a_yes_the_merge_did_not_follow_is_retried_without_asking(self):
        here = pathlib.Path(tempfile.mkdtemp())
        _, _, _, first = run_main(claude_merges=False, merge_fails="X Head branch was modified", here=here)
        rc, text, calls, second = run_main(claude_merges=False, here=here)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertIn(("pr", "merge", "12", "-R", "o/r", "--squash", "--match-head-commit", SHA), calls)
        self.assertIn("automerge: MERGED", text)


class Codex(unittest.TestCase):
    """The Codex app on GitHub (login chatgpt-codex-connector[bot]) edits one PR comment that carries its state as
    JSON. Only that JSON is read."""

    def test_state_is_the_json_in_the_apps_comment(self):
        state = am.codex_state([{"user": {"login": "a-person"}, "body": "nice"}, codex_comment()])
        self.assertEqual(state["security_review"]["status"], "completed")
        self.assertEqual(state["security_review"]["commit_sha"], SHA)
        self.assertIsNone(state["code_review"]["status"])

    def test_no_comment_from_the_app_is_no_state(self):
        self.assertIsNone(am.codex_state([]))
        self.assertIsNone(am.codex_state([{"user": {"login": "a-person"}, "body": "hi"}]))

    # Anyone can paste the marker; only the app's own login counts.
    def test_a_marker_pasted_by_someone_else_is_ignored(self):
        for login in ("a-person", "chatgpt-codex-connector", "someone[bot]"):
            self.assertIsNone(am.codex_state([codex_comment(login=login)]), login)

    # The prose says what the JSON says to a person; a gate must not read it.
    def test_the_prose_is_never_read(self):
        running = codex_comment({"commit_sha": SHA, "has_any_findings": None, "has_unresolved_findings": None,
                                 "status": "running"}, prose="| Security Review | Completed | No findings |\n")
        self.assertEqual(am.codex_state([running])["security_review"]["status"], "running")
        broken = codex_comment(prose="")
        broken["body"] = broken["body"].replace('"status": "completed"', '"status": completed')      # not JSON
        self.assertEqual(am.codex_state([broken]), {})
        self.assertEqual(am.codex_reasons({}, SHA)[0], ["the Codex security review has not finished"])

    def test_the_newest_comment_wins(self):
        old = codex_comment({"commit_sha": OLD, "has_any_findings": None, "has_unresolved_findings": None,
                             "status": "in_progress"})
        self.assertEqual(am.codex_state([old, codex_comment()])["security_review"]["status"], "completed")

    def test_completed_with_no_findings_on_the_head_passes(self):
        sec = {"commit_sha": SHA, "has_any_findings": False, "has_unresolved_findings": False, "status": "completed"}
        self.assertEqual(am.codex_reasons({"security_review": sec}, SHA), ([], False, None))
        sec["has_unresolved_findings"] = None               # the app's own comment leaves it null when clean
        self.assertEqual(am.codex_reasons({"security_review": sec}, SHA), ([], False, None))

    def test_not_completed_waits_for_the_app_and_is_not_for_the_user(self):
        for sec in (None, {}, {"commit_sha": None, "status": None}, {"commit_sha": SHA, "status": "in_progress"},
                    {"commit_sha": SHA, "status": "failed"}, "completed"):
            got = am.codex_reasons({"security_review": sec}, SHA)
            self.assertEqual(got, (["the Codex security review has not finished"], False, None), sec)
        self.assertEqual(am.codex_reasons(None, SHA)[0], ["the Codex security review has not finished"])

    def test_unresolved_findings_go_to_the_user(self):
        sec = {"commit_sha": SHA, "has_any_findings": True, "has_unresolved_findings": True, "status": "completed"}
        self.assertEqual(am.codex_reasons({"security_review": sec}, SHA),
                         (["the Codex security review has unresolved findings"], True, None))
        sec["has_unresolved_findings"] = False               # findings that are all resolved do not stop the merge
        self.assertEqual(am.codex_reasons({"security_review": sec}, SHA)[:2], ([], False))

    def test_a_review_of_another_commit_is_accepted_with_a_note(self):
        sec = {"commit_sha": OLD, "has_any_findings": None, "has_unresolved_findings": None, "status": "completed"}
        reasons, for_user, note = am.codex_reasons({"security_review": sec}, SHA)
        self.assertEqual((reasons, for_user), ([], False))
        self.assertEqual(note, f"The Codex security review covered commit {OLD[:7]}, not this PR's head {SHA[:7]}.")
        sec["commit_sha"] = None
        self.assertIn("covered commit unknown", am.codex_reasons({"security_review": sec}, SHA)[2])

    def review(self, codex):
        """codex_review() against stand-in gh output; returns (result, the gh calls)."""
        calls, saved = [], am.gh

        def fake(*a, cwd):
            calls.append(a)
            return fake_codex(a, codex)
        am.gh = fake
        try:
            return am.codex_review(pr(), "."), calls
        finally:
            am.gh = saved

    def test_a_repo_with_no_codex_app_has_no_fact(self):
        quiet = [{"number": n, "comments": [{"user": {"login": "a"}, "body": "ok"}]} for n in range(11, 1, -1)]
        got, calls = self.review({"issue_comments": [{"user": {"login": "a"}, "body": "hi"}], "recent": quiet})
        self.assertEqual(got, ([], False, ""))
        listed = [c for c in calls if c[:2] == ("pr", "list")][0]
        self.assertEqual(listed[listed.index("--limit") + 1], "10")      # the repo's 10 most recent PRs
        self.assertIn("o/r", listed)
        self.assertFalse(any("reviews" in c[1] or "/pulls/" in c[1] for c in calls if c[0] == "api"))

    def test_a_repo_that_used_the_app_on_a_recent_pr_waits_for_it_on_this_one(self):
        recent = [{"number": 11, "comments": [codex_comment()]}]
        got, _ = self.review({"recent": recent})
        self.assertEqual(got[:2], (["the Codex security review has not finished"], False))

    # Verifier and Codex on f97c493 (P1): a marker anyone pasted made every PR wait for a review no app writes.
    def test_a_marker_pasted_by_a_person_does_not_turn_the_check_on(self):
        pasted = codex_comment(login="alice")
        got, _ = self.review({"issue_comments": [pasted], "recent": [{"number": 11, "comments": [pasted]}]})
        self.assertEqual(got, ([], False, ""))

    def test_the_apps_own_state_on_this_pr_needs_no_other_pr(self):
        (reasons, for_user, text), calls = self.review({"issue_comments": [codex_comment()]})
        self.assertEqual((reasons, for_user), ([], False))
        self.assertFalse(any(c[:2] == ("pr", "list") for c in calls))
        self.assertNotIn("covered commit", text)

    def test_the_apps_comments_reach_the_merge_check_and_other_peoples_do_not(self):
        sec = {"commit_sha": OLD, "has_any_findings": True, "has_unresolved_findings": None, "status": "completed"}
        (reasons, _, text), _ = self.review({
            "issue_comments": [codex_comment(sec, prose="Summary: one finding on login.\n"),
                               {"user": {"login": "a-person"}, "body": "HUMAN CHATTER"}],
            "reviews": [{"user": {"login": am.CODEX_BOT}, "body": "Review body: see line comment."},
                        {"user": {"login": "a-person"}, "body": "HUMAN REVIEW"},
                        {"user": {"login": am.CODEX_BOT}, "body": ""}],
            "lines": [{"user": {"login": am.CODEX_BOT}, "path": "api/auth.py", "line": 42, "body": "P1: token logged"},
                      {"user": {"login": "a-person"}, "path": "x.py", "line": 1, "body": "HUMAN LINE"}]})
        self.assertEqual(reasons, [])
        for want in ("Codex security review on GitHub", f"covered commit {OLD[:7]}", "Summary: one finding on login.",
                     "Review body: see line comment.", "api/auth.py:42: P1: token logged"):
            self.assertIn(want, text)
        for not_wanted in ("HUMAN CHATTER", "HUMAN REVIEW", "HUMAN LINE"):
            self.assertNotIn(not_wanted, text)

    # Through main(): what the Codex state does to the run.
    def test_not_finished_is_printed_not_sent_and_the_check_does_not_start(self):
        running = codex_comment({"commit_sha": SHA, "has_any_findings": None, "has_unresolved_findings": None,
                                 "status": "in_progress"})
        rc, text, calls, inputs = run_main(codex={"issue_comments": [running]})
        self.assertEqual(inputs, [])
        self.assertIn("the Codex security review has not finished", text)
        self.assertIn("automerge: TO USER", text)
        self.assertNotIn("[slack]", text)
        self.assertFalse(any(c[:2] == ("pr", "merge") for c in calls))

    def test_unresolved_findings_go_to_slack_and_the_check_does_not_start(self):
        sec = {"commit_sha": SHA, "has_any_findings": True, "has_unresolved_findings": True, "status": "completed"}
        rc, text, calls, inputs = run_main(codex={"issue_comments": [codex_comment(sec)]})
        self.assertEqual(inputs, [])
        self.assertIn("Why it was not merged: the Codex security review has unresolved findings", text)
        self.assertIn("[slack]", text)
        self.assertFalse(any(c[:2] == ("pr", "merge") for c in calls))

    def test_a_finished_clean_review_lets_the_pr_through_with_its_comments_in_the_check(self):
        rc, text, calls, inputs = run_main(codex={"issue_comments": [codex_comment()]})
        self.assertIn("automerge: MERGED", text)
        self.assertIn("Codex security review on GitHub", inputs[0])
        self.assertNotIn("covered commit", inputs[0])

    def test_a_review_of_an_earlier_commit_still_merges_and_the_check_is_told(self):
        sec = {"commit_sha": OLD, "has_any_findings": None, "has_unresolved_findings": None, "status": "completed"}
        rc, text, calls, inputs = run_main(codex={"issue_comments": [codex_comment(sec)]})
        self.assertIn("automerge: MERGED", text)
        self.assertIn(f"covered commit {OLD[:7]}, not this PR's head {SHA[:7]}", inputs[0])

    def test_a_repo_without_the_app_gets_no_codex_section(self):
        _, text, _, inputs = run_main()
        self.assertIn("automerge: MERGED", text)
        self.assertNotIn("Codex security review on GitHub", inputs[0])

    def test_an_unreadable_codex_state_goes_to_the_user(self):
        rc, text, calls, inputs = run_main(codex={"fails": True})
        self.assertEqual(inputs, [])
        self.assertIn("could not read the Codex review from GitHub", text)
        self.assertIn("[slack]", text)

    def test_dry_run_reads_the_codex_state(self):
        rc, text, calls, inputs = run_main(args=("--dry-run",), codex={"issue_comments": [codex_comment()]})
        self.assertIn("[dry-run] would merge, not merged", text)
        self.assertTrue(any(c[0] == "api" and "/issues/12/comments" in c[1] for c in calls))
        _, text, _, _ = run_main(args=("--dry-run",), codex={"recent": [{"number": 11, "comments": [
            codex_comment()]}]})
        self.assertIn("the Codex security review has not finished", text)


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

    def run_with(self, body, command=None):
        import os
        bin_dir = pathlib.Path(tempfile.mkdtemp())
        self.seen = bin_dir / "seen"
        self.argv = bin_dir / "argv"
        (bin_dir / "claude").write_text(f"#!/usr/bin/env bash\ncat > /dev/null\n{{ pwd; echo \"$@\"; }} > {self.seen}\n"
                                        f"printf '%s\\n' \"$@\" > {self.argv}\n" + body)
        (bin_dir / "claude").chmod(0o755)
        old = os.environ["PATH"]
        os.environ["PATH"] = f"{bin_dir}:{old}"
        try:
            return am.merge_check("input", command)
        finally:
            os.environ["PATH"] = old

    # Verifier on c470756: run in the PR's worktree, the check also read that branch's own CLAUDE.md.
    def test_runs_in_an_empty_folder_with_customizations_off(self):
        self.run_with("""echo '{"structured_output": {"merge": true, "reason": "x"}}'\n""")
        cwd, args = self.seen.read_text().splitlines()[:2]
        self.assertIn("merge-check-", cwd)
        self.assertIn("--safe-mode", args)
        self.assertIn("--tools", args)

    # User decision 2026-11-02: Claude runs the merge, allowed exactly one command. Measured with `claude -p --safe-mode
    # --tools Bash --allowedTools "Bash(gh pr view 17 -R unhaeos/hhmode --json state)"`: that command ran, the same
    # with 16 was denied, so an exact entry pins the PR and the commit.
    def test_claude_is_allowed_the_one_merge_command_and_nothing_else(self):
        ok = """echo '{"structured_output": {"merge": true, "reason": "x"}}'\n"""
        self.run_with(ok, COMMAND)
        args = self.argv.read_text().splitlines()
        self.assertEqual(args[args.index("--tools") + 1], "Bash")
        self.assertEqual(args[args.index("--allowedTools") + 1], f"Bash({COMMAND})")
        self.assertEqual(args.count("--allowedTools"), 1)
        self.assertIn("--safe-mode", args)
        self.assertIn(COMMAND, args[args.index("-p") + 1])          # the prompt gives the command verbatim
        self.assertIn("merge-check-", self.seen.read_text().splitlines()[0])      # still the empty folder

    def test_with_no_command_claude_has_no_tools(self):
        self.run_with("""echo '{"structured_output": {"merge": true, "reason": "x"}}'\n""")
        args = self.argv.read_text().splitlines()
        self.assertEqual(args[args.index("--tools") + 1], "")
        self.assertNotIn("--allowedTools", args)
        self.assertNotIn("gh pr merge", " ".join(args))

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
