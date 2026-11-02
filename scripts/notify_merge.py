#!/usr/bin/env python3
"""DM the user that a PR merged, for a merge automerge.py did not make (`/land`, or a merge by hand that someone
reports). Usage: python3 ~/projects/hhmode/scripts/notify_merge.py <PR number> [--repo <checkout>]

The message names the PR and its title, the merge commit, the risk the verifier and Codex gave the reviewed commit,
the issues it closed and how to undo it. It goes to the Slack target in local/notify.json, once per PR head (the same
marker automerge.py uses, so a merge both report is sent once). A PR that is not merged sends nothing and exits 1. A
Slack failure is printed and exits 0: the merge stands whatever Slack says.

Why (hhmode #18, 2026-11-02): automerge.py reported only what needed the user, and /land had no Slack step, so the
user heard of no merge at all.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import automerge as am  # noqa: E402
import forms  # noqa: E402


def merged_message(pr: dict, tiers: dict, closed: list[int]) -> str:
    """The DM for a merged PR. `pr` carries number, title, url and mergeCommit."""
    repo = am.owner_repo(pr)[1]
    oid = ((pr.get("mergeCommit") or {}).get("oid")) or ""
    lines = [f"{am.MARKS['Merged']}*[{repo} #{pr['number']}] Merged* — {pr['title']}",
             f"• Merge commit `{oid[:7] or 'unknown'}`",
             "• Risk: " + (" · ".join(f"{k} {v or 'none'}" for k, v in tiers.items()) or "no review record found")]
    if closed:
        lines.append("• Closed: " + ", ".join(f"#{n}" for n in closed))
    lines.append(f"• To undo: `git revert {oid[:7]}` or Revert on the PR page" if oid
                 else "• To undo: Revert on the PR page")
    return "\n".join(lines + [pr["url"]])


def tiers_of(gate: pathlib.Path, head: str) -> dict:
    """The verifier's and Codex's tier on the reviewed head, from its record chain; empty with no record."""
    out = {}
    for i, r in enumerate(am.load_records(gate, head)):
        tag = "" if i == 0 else f" ({r.get('sha', '')[:7]})"
        if r.get("review") is None and i == 0:
            return {}
        out[f"Claude verifier{tag}"] = r.get("tier")
        # A fix or carry round has no Codex review of its own; its tier is on the earlier record in the chain, so
        # "Codex review none" there only misled (merge check on #20).
        if r.get("gpt") is not None or r.get("mode") not in am.LIGHT:
            out[f"Codex review{tag}"] = r.get("gpt")
    return out


def body_tier(body: str) -> dict:
    """The author's tier from the PR body's Risk section, for a merge with no review record on this machine (a /land
    from another checkout): the DM still names a tier (verifier note on 502f5a8)."""
    first = next((ln for ln in forms.sections(body).get("Risk", "").splitlines() if ln.strip()), "")
    tier = forms.tier_line(first)
    return {"author (PR body)": tier} if tier else {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pr", type=int)
    ap.add_argument("--repo", type=pathlib.Path, default=pathlib.Path.cwd())
    a = ap.parse_args(argv)
    repo = a.repo.resolve()
    pr = json.loads(am.gh("pr", "view", str(a.pr), "--json", "number,title,url,state,mergeCommit,headRefOid,body",
                          cwd=repo))
    if pr.get("state") != "MERGED":
        print(f"notify_merge: #{a.pr} is {pr.get('state')}, not merged; nothing sent")
        return 1
    common = subprocess.run(["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            check=True, capture_output=True, text=True).stdout.strip()
    gate = pathlib.Path(common) / "gate"
    closed = [i["number"] for i in am.closing_issues(pr, repo)]
    text = merged_message(pr, tiers_of(gate, pr["headRefOid"]) or body_tier(pr.get("body") or ""), closed)
    print(text)
    try:
        print(f"[slack] {am.post_once(text, gate, a.pr, pr['headRefOid'])}")
    except Exception as e:                              # the merge stands whatever Slack says (#18 AC3)
        print(f"[slack] not sent: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
