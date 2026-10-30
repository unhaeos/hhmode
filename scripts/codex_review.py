#!/usr/bin/env python3
"""Render Codex's answer (JSON, shaped by skills/code-review/gpt-review.schema.json) as the markdown the verifier
and automerge.py already read:

  ## Findings
  ### F1 [P1] <title>
  - location: ...
  - trigger: ...
  - evidence: ...
  - fix: ...

  ## Tier
  <tier> — <tier_reason>

Why JSON: Codex used to write this markdown itself, and its tier line kept coming back in forms the merge had to
guess at ("medium - high", bold words: verifier on a93fe87, 8ddbe0d, c982ba2). The schema fixes the tier to one of
three words and this script writes the line, so forms.tier_line (which automerge uses) always parses it. A finding's
extra lines are indented, so none of its text starts a line of its own: a quoted `## Tier` in a finding must not be
read as the tier.

Usage: codex_review.py <gpt-review.json>      (prints markdown to stdout)
"""
from __future__ import annotations

import json
import pathlib
import sys


def one_line(text: str) -> str:
    return " ".join(str(text).split())


def block(text: str) -> str:
    """Several lines allowed, each continuation indented under its `- key:` so that it stays inside that item."""
    return str(text).strip().replace("\n", "\n  ")


def render(data: dict) -> str:
    findings = [
        f"### {one_line(f['id'])} [{f['priority']}] {one_line(f['title'])}\n"
        f"- location: {one_line(f['location'])}\n- trigger: {block(f['trigger'])}\n"
        f"- evidence: {block(f['evidence'])}\n- fix: {block(f['fix'])}"
        for f in data["findings"]]
    # A tier without a reason would not parse as `<tier> — <reason>`, and an unparsed tier stops the merge.
    reason = one_line(data["tier_reason"]) or "no reason given"
    body = "\n\n".join(findings) if findings else "none"
    return f"## Findings\n{body}\n\n## Tier\n{data['tier']} — {reason}\n"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.stdout.write(render(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))))
