#!/usr/bin/env python3
"""Run the merge check from this PC on a timer, for the repos in local/merge_poll.json.

Every few minutes (a systemd user timer, `--install`), for each configured repo: list the open PRs and run
scripts/automerge.py for each one that is ready, that is:
  - not a draft, and its CI has finished and passed (a failing CI is the author's to fix, /pr step 9);
  - its head commit has a review record on this machine (no record: nothing to check yet);
  - the Codex app's review has finished, where the repo uses the app;
  - the merge check has not said no for that head (automerge keeps its answer in gate/merge-check-<n>-<sha>.json,
    whether or not the DM went out), and nothing was sent to the user for it (gate/slack-<n>-<sha>.sent). A yes the
    merge did not follow is retried by automerge with the same pinned command, without asking Claude again.
Only data comes from GitHub (PR numbers, head SHAs, check and Codex states). Nothing GitHub serves runs here: the
script that runs is this checkout's automerge.py, which holds its own per-PR lock, so /pr step 8 running it at the
same time is safe. Does nothing while local/automerge is not `on`.

Why (hhmode #26, 2026-11-02): k-defense-kg #73 ran the merge check from a repository-level self-hosted runner on
this PC. The Codex security review of #73 (P1) and GitHub's hardening guide ("any user capable of invoking workflows
has access to this environment") both apply: four accounts can push there, and a workflow on any branch naming the
runner would run as this user, next to the GitHub admin token, the Claude and Codex logins, the Slack token and the DB
credentials, with the user in the docker group. The merge check needs those credentials, so the runner was stopped
and the check moved here, where GitHub sends no code.

  python3 scripts/merge_poll.py              one pass over the configured repos
  python3 scripts/merge_poll.py --dry-run    say what would run, run nothing
  python3 scripts/merge_poll.py --install    write and start the systemd user timer
  python3 scripts/merge_poll.py --uninstall  stop and remove it

local/merge_poll.json: {"repos": [{"repo": "<owner>/<name>", "path": "~/projects/<name>"}], "interval_minutes": 3}
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import automerge as am  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent          # hhmode root
CONFIG = HERE / "local" / "merge_poll.json"
UNIT = "hhmode-merge-poll"
DEFAULT_INTERVAL = 3                                            # minutes


def load_config(path: pathlib.Path = CONFIG) -> dict:
    if not path.exists():
        return {"repos": [], "interval_minutes": DEFAULT_INTERVAL}
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.setdefault("repos", [])
    cfg.setdefault("interval_minutes", DEFAULT_INTERVAL)
    return cfg


def mode_on() -> bool:
    f = am.HERE / "local" / "automerge"
    return f.exists() and f.read_text().strip() == "on"


def gate_dir(path: pathlib.Path) -> pathlib.Path:
    common = subprocess.run(["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            check=True, capture_output=True, text=True).stdout.strip()
    return pathlib.Path(common) / "gate"


def why_not(pr: dict, path: pathlib.Path, gate: pathlib.Path) -> str | None:
    """Why this PR is not ready for a merge check now, or None when it is."""
    n, head = pr["number"], pr["headRefOid"]
    if pr.get("isDraft"):
        return "a draft"
    ci = am.checks_state(pr.get("statusCheckRollup") or [])
    if ci == "pending":
        return "CI is still running"
    if ci == "failing":
        return "CI is failing (the author's to fix)"
    earlier = am.decided(gate, n, head)
    if earlier is not None and not earlier["merge"]:
        return "the merge check already said no for this head"
    if earlier is None and (gate / f"slack-{n}-{head}.sent").exists():
        return "already sent to the user for this head"
    if not (gate / f"{head}.review.md").exists():
        return "no review record for this head yet"
    reasons, _, _ = am.codex_review(pr, path)
    if "the Codex security review has not finished" in reasons:
        return "the Codex review is still running"
    return None


def run_automerge(n: int, path: pathlib.Path) -> str:
    out = subprocess.run([sys.executable, str(HERE / "scripts" / "automerge.py"), str(n), "--repo", str(path)],
                         capture_output=True, text=True)
    lines = (out.stdout or out.stderr or "").strip().splitlines()
    return lines[-1] if lines else f"exit {out.returncode}"


def poll(cfg: dict, dry_run: bool = False, run=run_automerge) -> list[str]:
    """One pass; returns one line per PR looked at."""
    log = []
    for entry in cfg["repos"]:
        slug, path = entry["repo"], pathlib.Path(os.path.expanduser(entry["path"]))
        # One repo or one PR that GitHub or git fails on does not end the pass for the rest (verifier on 91848ab).
        try:
            gate = gate_dir(path)
            prs = json.loads(am.gh("pr", "list", "-R", slug, "--state", "open", "--json",
                                   "number,url,headRefOid,isDraft,statusCheckRollup", cwd=path))
        except (subprocess.CalledProcessError, OSError, ValueError) as e:
            log.append(f"{slug}: could not list its PRs: {(getattr(e, 'stderr', None) or str(e)).strip()[:200]}")
            continue
        for pr in prs:
            try:
                why = why_not(pr, path, gate)
            except (subprocess.CalledProcessError, ValueError) as e:
                log.append(f"{slug}#{pr['number']}: could not read its state: "
                           f"{(getattr(e, 'stderr', None) or str(e)).strip()[:200]}")
                continue
            if why:
                log.append(f"{slug}#{pr['number']} {pr['headRefOid'][:7]}: skipped, {why}")
            elif dry_run:
                log.append(f"{slug}#{pr['number']} {pr['headRefOid'][:7]}: would run the merge check")
            else:
                log.append(f"{slug}#{pr['number']} {pr['headRefOid'][:7]}: {run(pr['number'], path)}")
    return log


def unit_files(interval: int, path_env: str) -> dict[str, str]:
    """The systemd user units: a one-shot service, and a timer that starts it every `interval` minutes."""
    script = HERE / "scripts" / "merge_poll.py"
    return {
        f"{UNIT}.service": (f"[Unit]\nDescription=hhmode merge check poller (hhmode #26)\n\n[Service]\nType=oneshot\n"
                            f"ExecStart={sys.executable} {script}\nEnvironment=PATH={path_env}\n"),
        f"{UNIT}.timer": (f"[Unit]\nDescription=Run the hhmode merge check poller every {interval} minutes\n\n"
                          f"[Timer]\nOnBootSec=2min\nOnUnitActiveSec={interval}min\nUnit={UNIT}.service\n\n"
                          f"[Install]\nWantedBy=timers.target\n"),
    }


def tool_path() -> str:
    """PATH for the timer: wherever gh, claude and git are now, then the system dirs."""
    dirs = [str(pathlib.Path(p).parent) for p in (shutil.which(t) for t in ("gh", "claude", "git")) if p]
    return ":".join(dict.fromkeys(dirs + ["/usr/local/bin", "/usr/bin", "/bin"]))


def install(cfg: dict, unit_dir: pathlib.Path) -> None:
    unit_dir.mkdir(parents=True, exist_ok=True)
    for name, text in unit_files(int(cfg["interval_minutes"]), tool_path()).items():
        (unit_dir / name).write_text(text, encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", f"{UNIT}.timer"], check=True)


def uninstall(unit_dir: pathlib.Path) -> None:
    subprocess.run(["systemctl", "--user", "disable", "--now", f"{UNIT}.timer"], check=False)
    for name in (f"{UNIT}.service", f"{UNIT}.timer"):
        (unit_dir / name).unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args(argv)
    unit_dir = pathlib.Path.home() / ".config" / "systemd" / "user"
    cfg = load_config()
    if a.install:
        install(cfg, unit_dir)
        print(f"merge_poll: timer on, every {cfg['interval_minutes']} min ({unit_dir}/{UNIT}.timer)")
        return 0
    if a.uninstall:
        uninstall(unit_dir)
        print("merge_poll: timer removed")
        return 0
    if not mode_on():
        print("merge_poll: local/automerge is not `on`; nothing to do")
        return 0
    if not cfg["repos"]:
        print(f"merge_poll: no repos in {CONFIG}; nothing to do")
        return 0
    for line in poll(cfg, dry_run=a.dry_run):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
