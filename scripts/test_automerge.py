"""Tests for automerge.py. Run: python3 -m unittest scripts/test_automerge.py (from the hhmode root)."""
from __future__ import annotations

import pathlib
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
STATUS = {"review": "통과", "verify": "통과", "ci": "ok", "mergeable": "MERGEABLE"}


def pr(**over):
    base = {"number": 12, "title": "docs: x", "url": "https://github.com/o/r/pull/12", "state": "OPEN",
            "baseRefName": "main", "headRefOid": SHA, "body": "**Risk tier: low** (docs only)",
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

    # The /pr template line is "**Risk tier: low | medium | high**"; left unfilled it must not read as low.
    def test_template_placeholder_is_no_author_tier(self):
        merge, reasons, *_ = am.decide(pr(body="**Risk tier: low | medium | high**"), [rec()])
        self.assertFalse(merge)
        self.assertTrue(any("PR 본문" in r for r in reasons))

    # GPT lane on 08df90d: prose mentioning a tier must not shadow the field; two fields that disagree count as none.
    def test_only_the_risk_tier_field_counts(self):
        self.assertEqual(am.author_tier("Explain the low risk tier.\n**Risk tier: high** (gate)"), "high")
        self.assertIsNone(am.author_tier("**Risk tier: low**\n...\nRisk tier: medium"))
        self.assertIsNone(am.author_tier("We kept the risk tier low."))
        self.assertEqual(am.author_tier("**Risk tier: low** (docs only)"), "low")

    # k-defense-kg #35: the author called a dependency pin low.
    def test_highest_tier_wins_over_the_authors(self):
        merge, reasons, *_ = am.decide(pr(), [rec(tier="high")])
        self.assertFalse(merge)
        self.assertIn("위험도 높음", reasons)
        self.assertFalse(am.decide(pr(), [rec(gpt="high")])[0])

    # User, 2026-10-30: up to medium merges without the user; high still goes to them.
    def test_medium_merges_high_does_not(self):
        merge, reasons, *_ = am.decide(pr(body="**Risk tier: medium**"), [rec(tier="medium", gpt="medium")])
        self.assertTrue(merge, reasons)
        self.assertFalse(am.decide(pr(body="**Risk tier: high**"), [rec(tier="medium", gpt="medium")])[0])

    def test_missing_codex_review_goes_to_the_user(self):
        merge, reasons, *_ = am.decide(pr(), [rec(gpt=None)])
        self.assertFalse(merge)
        self.assertTrue(any("Codex" in r for r in reasons))

    # hhmode #10 (2026-10-29): a record from before tiers existed must say so, not look like a broken PR.
    def test_old_record_without_a_tier_says_why(self):
        merge, reasons, *_ = am.decide(pr(), [rec(tier=None)])
        self.assertFalse(merge)
        self.assertTrue(any("위험도 칸이 생기기 전" in r for r in reasons))

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
        self.assertIn("위험도 높음", reasons)
        self.assertIn(f"Codex 리뷰({OLD[:7]})", tiers)


class Parse(unittest.TestCase):
    # The fields are read from what record_review.py actually writes, so a format change breaks this test.
    def test_record_fields_from_a_real_record(self):
        result = {"sha": SHA, "mode": "standard", "tier": "medium", "lanes": [], "findings": []}
        text = rr.render("PASS", SHA, result, "report", "11111111-2222-3333-4444-555555555555", "PASS",
                         since=OLD)
        self.assertEqual(am.record_fields(text),
                         {"review": "PASS", "since": OLD[:7], "verify": "PASS", "tier": "medium"})

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


class Message(unittest.TestCase):
    TIERS = {"PR 쓴 에이전트": "low", "Claude 검증": "low", "Codex 리뷰": None}

    # User, 2026-10-29: the report had no repo name, said "작성자 low" and "GPT 없음", and nobody could read it.
    def test_report_names_the_repo_and_speaks_plainly(self):
        text = am.message(pr(), False, ["이 검증에서 Codex 리뷰가 돌지 않았거나 위험도를 못 읽음"], self.TIERS,
                          STATUS, "shadow", None)
        self.assertIn("[r #12] 확인 필요", text)
        self.assertIn("리뷰 통과 · 테스트 통과 · CI 통과 · 충돌 없음", text)
        self.assertIn("PR 쓴 에이전트 낮음 · Claude 검증 낮음 · Codex 리뷰 없음", text)
        self.assertIn("하나라도 '높음'이면 사용자 확인", text)
        for jargon in (" low", "GPT", "작성자"):
            self.assertNotIn(jargon, text)

    def test_shadow_says_it_did_not_merge(self):
        text = am.message(pr(), True, [], self.TIERS, STATUS, "shadow", None)
        self.assertIn("[시험 운영]", text)
        self.assertIn("실제 병합은 안 함", text)

    def test_on_gives_the_revert(self):
        text = am.message(pr(), True, [], self.TIERS, STATUS, "on", "e" * 40)
        self.assertIn("자동 병합", text)
        self.assertIn("git revert eeeeeee", text)

    # GPT lane on e008f76 (P3): --dry-run with mode on printed "자동 병합" and "git revert ?".
    def test_no_merge_commit_never_reads_as_merged(self):
        for mode in ("on", "dry-run"):
            text = am.message(pr(), True, [], self.TIERS, STATUS, mode, None)
            self.assertIn("실제 병합은 안 함", text)
            self.assertNotIn("git revert", text)

    # Verifier note on 08df90d (P2): a merge refused by GitHub ended the run with no report.
    def test_failed_merge_is_reported(self):
        text = am.message(pr(), True, [], self.TIERS, STATUS, "on", None, error="Pull request is in draft")
        self.assertIn("자동 병합 실패", text)
        self.assertIn("Pull request is in draft", text)

    # Verifier note on f07e72f (P2): the merge went through, the lookup after it failed, and it read as a failure.
    def test_merge_then_failed_lookup_reads_as_merged(self):
        rc, text, calls, _ = run_main(lookup_fails=True)
        self.assertEqual(rc, 0)
        self.assertTrue(any(c[:2] == ("pr", "merge") for c in calls))
        self.assertIn("자동 병합*", text)
        self.assertIn("병합은 됐지만 병합 커밋 번호를 못 읽음", text)
        self.assertNotIn("실패", text)
        self.assertIn("automerge: MERGED", text)

    def test_to_user_names_the_reasons(self):
        text = am.message(pr(), False, ["위험도 중간", "CI 실패"], self.TIERS, STATUS, "shadow", None)
        self.assertIn("확인 필요", text)
        self.assertIn("자동 병합 안 한 이유: 위험도 중간, CI 실패", text)


ISSUE = {"number": 7, "url": "https://github.com/o/r/issues/7", "state": "OPEN", "title": "주간 보고 머리글",
         "body": "프로젝트 이름을 한 번만 쓰기"}


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
        return check or {"merge": True, "reason": "주간 보고 머리글을 한 번만 쓰게 고침.", "session": "abcd1234-x"}
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
        self.assertTrue(any(c[:2] == ("pr", "comment") and "머지 확인(Claude, 세션 abcd1234)" in c[-1]
                            for c in calls))
        self.assertIn("프로젝트 이름을 한 번만 쓰기", inputs[0])         # the check reads the issue it closes
        self.assertIn("+line", inputs[0])
        self.assertNotIn("[slack]", text)
        self.assertIn("automerge: MERGED", text)

    def test_an_issue_github_already_closed_is_left_alone(self):
        _, _, calls, _ = run_main(issue_state="CLOSED")
        self.assertFalse(any(c[:2] == ("issue", "close") for c in calls))

    def test_merge_check_no_goes_to_slack_unmerged(self):
        rc, text, calls, _ = run_main(check={"merge": False, "reason": "scripts/x.py:3 가 데이터를 지움", "session": ""})
        self.assertFalse(any(c[:2] == ("pr", "merge") for c in calls))
        self.assertIn("머지 확인(Claude): scripts/x.py:3 가 데이터를 지움", text)
        self.assertIn("[slack]", text)

    # A fact that fails stops everything: no merge check, and no Slack — the author fixes it (/pr step 9).
    def test_a_failing_fact_skips_the_check_and_slack(self):
        failing = [{"status": "COMPLETED", "conclusion": "FAILURE", "name": "ci"}]
        rc, text, calls, inputs = run_main(pr_over={"statusCheckRollup": failing})
        self.assertEqual(inputs, [])
        self.assertFalse(any(c[:2] == ("pr", "merge") for c in calls))
        self.assertIn("CI 실패", text)
        self.assertNotIn("[slack]", text)
        _, text, _, _ = run_main(pr_over={"statusCheckRollup": failing}, args=("--report",))
        self.assertIn("[slack]", text)

    # Verifier and GPT lane on c470756: what the check cannot read must not pass, and must not crash silently.
    def test_unreadable_input_goes_to_the_user_without_the_check(self):
        for kw, said in ((dict(rules=None), "저장소 규칙(CLAUDE.md)을 못 읽음"),
                         (dict(diff="+" * (am.DIFF_CAP + 1)), "머지 확인이 다 읽을 수 없음"),
                         (dict(graphql_fails=True), "PR 정보를 못 읽음")):
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
        self.assertEqual(close[-1], "#12 머지로 완료")

    def test_a_high_tier_skips_the_check_and_goes_to_slack(self):
        rc, text, calls, inputs = run_main(records=[rec(tier="high")])
        self.assertEqual(inputs, [])
        self.assertIn("위험도 높음", text)
        self.assertIn("[slack]", text)


class CheckInput(unittest.TestCase):
    # Merge check on k-defense-kg #51: it held a medium PR back only because the record happened to quote the
    # repo's rule; the rule is now always in its input.
    def test_input_carries_the_pr_issue_rules_records_and_diff(self):
        text = am.check_input(pr(body="본문"), [ISSUE], [rec(text="REC", gpt_text="GPT")], "+x\n",
                              "Medium | user confirmation")
        for part in ("본문", "프로젝트 이름을 한 번만 쓰기", "Medium | user confirmation", "REC", "GPT", "+x"):
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

    def test_empty_output_reports_stderr(self):
        got = self.run_with("echo 'credit balance too low' >&2\nexit 1\n")
        self.assertIn("credit balance too low", got["reason"])

    def test_structured_answer(self):
        got = self.run_with("""echo '{"structured_output": {"merge": true, "reason": "문서만 바꿈"}, "session_id": "s1"}'\n""")
        self.assertEqual(got, {"merge": True, "reason": "문서만 바꿈", "session": "s1"})

    # No answer is a no: the PR goes to the user with what the check said.
    def test_no_answer_is_a_no(self):
        for body in ("echo 'not json'\n", """echo '{"result": "Claude Code can\\x27t use your subscription"}'\n""",
                     "exit 1\n"):
            got = self.run_with(body)
            self.assertFalse(got["merge"])
            self.assertIn("머지 확인 에이전트가 답하지 못함", got["reason"])


if __name__ == "__main__":
    unittest.main()
