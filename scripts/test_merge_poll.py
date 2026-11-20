"""Tests for merge_poll.py (hhmode #26). Run: python3 -m unittest scripts/test_merge_poll.py (from the hhmode root).

GitHub is a stand-in `gh`; automerge.py never really runs (a recorder takes its place)."""
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
import merge_poll as mp  # noqa: E402

READY, RUNNING = "a" * 40, "b" * 40
OK = [{"status": "COMPLETED", "conclusion": "SUCCESS", "name": "ci"}]
PENDING = [{"status": "IN_PROGRESS", "conclusion": "", "name": "ci"}]


def pr(n, head, rollup=OK, draft=False):
    return {"number": n, "url": f"https://github.com/o/r/pull/{n}", "headRefOid": head, "isDraft": draft,
            "statusCheckRollup": rollup}


class Poll(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.repo = self.tmp / "repo"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.gate = self.repo / ".git" / "gate"
        self.gate.mkdir()
        for head in (READY, RUNNING):
            (self.gate / f"{head}.review.md").write_text("**Review: PASS** · x\n")
        (self.tmp / "local").mkdir()
        (self.tmp / "local" / "automerge").write_text("on\n")
        self.prs = [pr(1, READY), pr(2, RUNNING, PENDING)]
        self.codex = []                      # reasons codex_review returns
        self.gh_calls, self.ran = [], []
        self.saved = (am.gh, am.codex_review, am.HERE)
        am.gh = lambda *a, cwd: (self.gh_calls.append(a), json.dumps(self.prs))[1]
        am.codex_review = lambda p, cwd: (list(self.codex), False, "")
        am.HERE = self.tmp
        self.cfg = {"repos": [{"repo": "o/r", "path": str(self.repo)}], "interval_minutes": 3}

    def tearDown(self):
        am.gh, am.codex_review, am.HERE = self.saved

    def run_poll(self, **kw):
        return mp.poll(self.cfg, run=lambda n, path: (self.ran.append(n), "automerge: MERGED")[1], **kw)

    # AC4: two PRs, one ready and one with CI still running; only the ready one is checked.
    def test_only_the_ready_pr_is_checked(self):
        log = self.run_poll()
        self.assertEqual(self.ran, [1])
        self.assertIn("o/r#2 bbbbbbb: skipped, CI is still running", log)

    # AC1: only data comes from GitHub: one `pr list` for numbers, heads and check states.
    def test_github_gives_only_numbers_heads_and_states(self):
        self.run_poll()
        (call,) = self.gh_calls
        self.assertEqual(call[:2], ("pr", "list"))
        self.assertEqual(call[call.index("--json") + 1], "number,url,headRefOid,isDraft,statusCheckRollup")

    # AC2: a second pass does nothing for a head already checked (automerge's once-per-head marker).
    def test_a_second_pass_does_nothing_for_the_same_head(self):
        self.run_poll()
        (self.gate / f"slack-1-{READY}.sent").write_text("hash\n")          # what automerge leaves after its DM
        log = self.run_poll()
        self.assertEqual(self.ran, [1])
        self.assertIn("o/r#1 aaaaaaa: skipped, already sent to the user for this head", log)

    # Verifier on 91848ab (P1): a no whose DM never went out was judged again every pass.
    def test_a_no_is_not_asked_again_even_when_its_dm_failed(self):
        am.record_decision(self.gate, 1, READY, {"merge": False, "reason": "x", "session": "s"})
        log = self.run_poll()
        self.assertEqual(self.ran, [])
        self.assertIn("o/r#1 aaaaaaa: skipped, the merge check already said no for this head", log)

    def test_a_yes_the_merge_did_not_follow_is_retried(self):
        am.record_decision(self.gate, 1, READY, {"merge": True, "reason": "x", "session": "s"})
        self.run_poll()
        self.assertEqual(self.ran, [1])

    # Verifier on 91848ab (P2): one failing repo or PR ended the whole pass.
    def test_a_failing_repo_does_not_stop_the_others(self):
        self.cfg["repos"].insert(0, {"repo": "o/broken", "path": str(self.tmp / "not-a-repo")})
        log = self.run_poll()
        self.assertTrue(log[0].startswith("o/broken: could not list its PRs"))
        self.assertEqual(self.ran, [1])

    def test_a_new_head_is_checked_again(self):
        (self.gate / f"slack-1-{READY}.sent").write_text("hash\n")
        new = "c" * 40
        (self.gate / f"{new}.review.md").write_text("**Review: PASS** · x\n")
        self.prs = [pr(1, new)]
        self.run_poll()
        self.assertEqual(self.ran, [1])

    # AC1: the Codex review, where the repo uses it, must have finished.
    def test_a_running_codex_review_waits(self):
        self.codex = ["the Codex security review has not finished"]
        log = self.run_poll()
        self.assertEqual(self.ran, [])
        self.assertIn("o/r#1 aaaaaaa: skipped, the Codex review is still running", log)

    def test_drafts_failing_ci_and_unreviewed_heads_wait(self):
        unreviewed = "d" * 40
        self.prs = [pr(3, READY, draft=True), pr(4, READY, [{"status": "COMPLETED", "conclusion": "FAILURE"}]),
                    pr(5, unreviewed)]
        log = self.run_poll()
        self.assertEqual(self.ran, [])
        self.assertIn("o/r#3 aaaaaaa: skipped, a draft", log)
        self.assertIn("o/r#4 aaaaaaa: skipped, CI is failing (the author's to fix)", log)
        self.assertIn("o/r#5 ddddddd: skipped, no review record for this head yet", log)

    def test_dry_run_runs_nothing(self):
        log = self.run_poll(dry_run=True)
        self.assertEqual(self.ran, [])
        self.assertIn("o/r#1 aaaaaaa: would run the merge check", log)

    def test_a_repo_tick_runs_in_its_checkout_before_its_prs_are_read(self):
        self.cfg["repos"][0]["tick"] = ["python3", "scripts/ci_budget.py", "tick"]
        order = []
        am.gh = lambda *a, cwd: (order.append("gh"), json.dumps(self.prs))[1]
        log = mp.poll(self.cfg, run=lambda n, path: "automerge: MERGED",
                      tick=lambda cmd, path: (order.append((tuple(cmd), str(path))), "exit 0")[1])
        self.assertEqual(order[0], (("python3", "scripts/ci_budget.py", "tick"), str(self.repo)))
        self.assertEqual(order[1:], ["gh"])
        self.assertIn("o/r: tick exit 0", log)

    def test_no_tick_without_one_in_the_config_and_none_on_a_dry_run(self):
        ticks = []
        mp.poll(self.cfg, run=lambda n, path: "x", tick=lambda cmd, path: ticks.append(cmd))
        self.cfg["repos"][0]["tick"] = ["true"]
        log = mp.poll(self.cfg, dry_run=True, run=lambda n, path: "x", tick=lambda cmd, path: ticks.append(cmd))
        self.assertEqual(ticks, [])
        self.assertIn("o/r: tick would run", log)

    def main_checkout(self):
        g = lambda *a: subprocess.run(["git", "-C", str(self.repo), *a], check=True, capture_output=True)
        g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
        g("branch", "-M", "main")
        g("update-ref", "refs/remotes/origin/main", "HEAD")
        return g

    def test_run_tick_reports_exit_and_last_line_and_survives_a_missing_program(self):
        self.main_checkout()
        self.assertEqual(mp.run_tick(["sh", "-c", "echo one; echo two; exit 3"], self.repo), "exit 3, two")
        self.assertTrue(mp.run_tick(["/nonexistent/tick"], self.repo).startswith("failed:"))
        self.assertTrue(mp.run_tick(["sh", "-c", r"printf '\377\376 bad\n'"], self.repo).startswith("exit 0"))

    def test_a_tick_runs_only_from_clean_main_at_origin_main(self):
        g = self.main_checkout()
        ran = ["sh", "-c", "echo ran"]
        self.assertEqual(mp.run_tick(ran, self.repo), "exit 0, ran")
        (self.repo / "shadow.py").write_text("x = 1\n")
        self.assertEqual(mp.run_tick(ran, self.repo), "refused: the checkout has untracked Python files")
        (self.repo / "shadow.py").unlink()
        (self.repo / "notes.txt").write_text("not code\n")
        self.assertEqual(mp.run_tick(ran, self.repo), "exit 0, ran")
        g("add", "notes.txt")
        self.assertEqual(mp.run_tick(ran, self.repo), "refused: the checkout has uncommitted changes")
        g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "y")
        self.assertEqual(mp.run_tick(ran, self.repo), "refused: the checkout is not at origin/main")
        g("update-ref", "refs/remotes/origin/main", "HEAD")
        g("switch", "-q", "-c", "pr-branch")
        self.assertEqual(mp.run_tick(ran, self.repo), "refused: the checkout is not on main")

    def test_a_tick_that_raises_does_not_end_the_pass(self):
        self.cfg["repos"][0]["tick"] = ["x"]
        def boom(cmd, path):
            raise ValueError("odd")
        log = mp.poll(self.cfg, run=lambda n, path: "automerge: MERGED", tick=boom)
        self.assertIn("o/r: tick failed: odd", log)
        self.assertIn("o/r#1 aaaaaaa: automerge: MERGED", log)

    # AC3: nothing at all while local/automerge is not `on`.
    def test_nothing_while_automerge_is_not_on(self):
        (self.tmp / "local" / "automerge").write_text("shadow\n")
        saved = mp.load_config
        mp.load_config = lambda path=None: self.cfg
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                mp.main([])
        finally:
            mp.load_config = saved
        self.assertEqual(self.gh_calls, [])
        self.assertIn("not `on`", out.getvalue())


class Units(unittest.TestCase):
    # AC3: a systemd user timer, its interval from the config (default 3 minutes).
    def test_the_timer_runs_the_poller_every_interval(self):
        units = mp.unit_files(5, "/usr/bin:/bin")
        self.assertIn("OnUnitActiveSec=5min", units["hhmode-merge-poll.timer"])
        self.assertIn("WantedBy=timers.target", units["hhmode-merge-poll.timer"])
        self.assertIn("Type=oneshot", units["hhmode-merge-poll.service"])
        self.assertIn("scripts/merge_poll.py", units["hhmode-merge-poll.service"])
        self.assertIn("Environment=PATH=/usr/bin:/bin", units["hhmode-merge-poll.service"])

    def test_the_default_interval_is_three_minutes(self):
        cfg = mp.load_config(pathlib.Path(tempfile.mkdtemp()) / "missing.json")
        self.assertEqual(cfg["interval_minutes"], 3)
        self.assertEqual(cfg["repos"], [])


if __name__ == "__main__":
    unittest.main()
