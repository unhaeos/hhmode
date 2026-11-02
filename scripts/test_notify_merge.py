"""Tests for notify_merge.py (hhmode #18). Run: python3 -m unittest scripts/test_notify_merge.py (from the hhmode
root)."""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import automerge as am  # noqa: E402
import notify_merge as nm  # noqa: E402

PR = {"number": 21, "title": "fix(x): y", "url": "https://github.com/o/r/pull/21", "state": "MERGED",
      "mergeCommit": {"oid": "e" * 40}, "headRefOid": "c" * 40}


class Message(unittest.TestCase):
    # AC2: the PR number and title, the merge commit, the tier, the issues it closed, and how to revert.
    def test_the_dm_names_everything_ac2_asks_for(self):
        text = nm.merged_message(PR, {"Claude verifier": "medium", "Codex review": "low"}, [18, 19])
        self.assertTrue(text.startswith("✅ *[r #21] Merged* — fix(x): y"))
        self.assertIn("Merge commit `eeeeeee`", text)
        self.assertIn("Risk: Claude verifier medium · Codex review low", text)
        self.assertIn("• Closed: #18, #19", text)
        self.assertIn("To undo: `git revert eeeeeee`", text)

    # Verifier note on 502f5a8: with no review record here, the tier comes from the PR body's Risk line.
    def test_the_body_risk_line_stands_in_for_a_missing_record(self):
        self.assertEqual(nm.body_tier("## Why\nx\n\n## Risk\nmedium — a.py: behaviour\nnone found\n"),
                         {"author (PR body)": "medium"})
        self.assertEqual(nm.body_tier("no risk section"), {})

    # Merge check on #20: a fix round has no Codex review of its own; the DM showed "Codex review none".
    def test_a_fix_rounds_missing_codex_review_is_not_shown(self):
        import record_review as rr
        gate = pathlib.Path(tempfile.mkdtemp())
        head, base = "c" * 40, "d" * 40
        s = "11111111-2222-3333-4444-555555555555"
        (gate / f"{head}.review.md").write_text(rr.render("PASS", head, {"mode": "fix", "tier": "medium", "lanes": []},
                                                          "r", s, "PASS", since=base))
        (gate / f"{base}.review.md").write_text(rr.render("PASS", base, {"mode": "standard", "tier": "medium",
                                                                         "lanes": []}, "r", s, "PASS"))
        (gate / f"{base}.gpt.md").write_text("## Findings\nnone\n\n## Tier\nmedium — a.py: x\n")
        tiers = nm.tiers_of(gate, head)
        self.assertNotIn("Codex review", tiers)
        self.assertEqual(tiers[f"Codex review ({base[:7]})"], "medium")

    def test_no_record_and_no_commit_still_reads(self):
        text = nm.merged_message({**PR, "mergeCommit": None}, {}, [])
        self.assertIn("Risk: no review record found", text)
        self.assertIn("To undo: Revert on the PR page", text)
        self.assertNotIn("Closed", text)


def run(state="MERGED", slack=None, slack_fails=False):
    repo = pathlib.Path(tempfile.mkdtemp()) / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    sent = [] if slack is None else slack

    def fake_gh(*a, cwd):
        if a[:2] == ("pr", "view"):
            return json.dumps({**PR, "state": state})
        if a[:2] == ("api", "graphql"):
            return json.dumps({"data": {"repository": {"pullRequest": {"closingIssuesReferences": {"nodes": [
                {"number": 18, "url": "https://github.com/o/r/issues/18", "state": "CLOSED", "title": "t",
                 "body": ""}]}}}}})
        raise AssertionError(a)

    def fake_slack(text):
        if slack_fails:
            raise OSError("network down")
        sent.append(text)
        return "sent"
    saved = (am.gh, am.post_slack)
    am.gh, am.post_slack = fake_gh, fake_slack
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = nm.main([str(PR["number"]), "--repo", str(repo)])
    finally:
        am.gh, am.post_slack = saved
    return rc, out.getvalue(), sent


class Main(unittest.TestCase):
    def test_a_merged_pr_is_sent_once(self):
        rc, text, sent = run()
        self.assertEqual(rc, 0)
        self.assertEqual(len(sent), 1)
        self.assertIn("• Closed: #18", sent[0])

    def test_a_pr_that_is_not_merged_sends_nothing(self):
        rc, text, sent = run(state="OPEN")
        self.assertEqual(rc, 1)
        self.assertEqual(sent, [])
        self.assertIn("not merged; nothing sent", text)

    # AC3: a Slack failure is printed and the merge stands.
    def test_slack_failing_is_printed_not_a_failure(self):
        rc, text, sent = run(slack_fails=True)
        self.assertEqual(rc, 0)
        self.assertIn("[slack] not sent: network down", text)


if __name__ == "__main__":
    unittest.main()
