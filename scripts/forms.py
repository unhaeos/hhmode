#!/usr/bin/env python3
"""The one parser and checker for the two forms a task passes through: the issue (templates/issue.md) and the PR body
(templates/pr.md). They share three fields under the same names, so a criterion written in the issue can be found
again in the PR, in the verifier's record and in the merge check:

  Acceptance criteria   numbered AC1, AC2, ...
  Risk                  `<low | medium | high> — <reason>` (references/tiers.md), the same line in both
  Out of scope

  python3 scripts/forms.py issue FILE
  python3 scripts/forms.py pr FILE [--issue N=FILE ...]

Prints one problem per line and exits 1, or prints `ok` and exits 0. `pr` needs each closed issue's body (`--issue`):
a criterion the PR does not name is a problem.

Why (hhmode log.md, 2026-10-30): hhmode #12 merged with a second change its body never mentioned. A PR body is only as
checkable as the issue it answers, so the issue says what "done" is and every later step reads that same text.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ISSUE_SECTIONS = ("Background", "Acceptance criteria", "Out of scope", "Risk")
PR_SECTIONS = ("Why", "What changed", "Acceptance criteria", "Verification", "Risk", "How to revert", "Out of scope")

COMMENT = re.compile(r"<!--.*?-->", re.S)
HEADING = re.compile(r"^## (.+?)[ \t]*$", re.M)
AC_ID = re.compile(r"\bAC\d+\b")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?[ \t]+#(\d+)", re.I)
TIER_LINE = re.compile(r"(low|medium|high) — \S")


def tier_line(text: str | None) -> str | None:
    """The tier of a line in the one form every rating takes, `<tier> — <reason>`: the issue's and the PR's Risk and
    Codex's Tier. Anything else is none. Reading tier words out of free text kept finding a lower tier than written
    (verifier on a93fe87, 8ddbe0d, c982ba2: "medium - high", "medium – high", "**medium** - **high**")."""
    m = TIER_LINE.match((text or "").strip())
    return m.group(1) if m else None


def sections(md: str) -> dict[str, str]:
    """The text under each `## ` heading, keyed by the heading. HTML comments are dropped first: the templates carry
    their instructions in comments, and one left in the body must not count as an answer."""
    parts = HEADING.split(COMMENT.sub("", md or ""))        # [before the first heading, heading, text, heading, ...]
    out: dict[str, str] = {}
    for name, text in zip(parts[1::2], parts[2::2]):
        out.setdefault(name.strip(), text.strip())
    return out


def criteria(issue_md: str) -> list[str]:
    """The acceptance-criteria ids (AC1, AC2, ...) in an issue, in order, each once."""
    return list(dict.fromkeys(AC_ID.findall(sections(issue_md).get("Acceptance criteria", ""))))


def closes(text: str) -> list[int]:
    """The issue numbers after GitHub's closing keywords (`Closes #7`, `fixes #8`), in order, each once."""
    return list(dict.fromkeys(int(n) for n in CLOSING.findall(text or "")))


def check_issue(md: str) -> list[str]:
    """What is wrong with an issue body, one line each; empty when it fills the form."""
    secs = sections(md)
    out = [f"missing section: ## {name}" for name in ISSUE_SECTIONS if name not in secs]
    if "Acceptance criteria" in secs and not criteria(md):
        out.append('Acceptance criteria has no items; write each as "- [ ] AC1: <criterion>"')
    out += risk_problems(secs)
    return out


def risk_problems(secs: dict) -> list[str]:
    if "Risk" not in secs:
        return []
    first_line = next((ln for ln in secs["Risk"].splitlines() if ln.strip()), "")
    return [] if tier_line(first_line) else ['Risk must start with "<low | medium | high> — <reason>"']


def named(ac_text: str, issue: int, ac: str, several: bool) -> bool:
    """Whether the PR's Acceptance criteria section names criterion `ac` of `issue`: the id alone when the PR closes
    one issue, the issue number and the id on the same line when it closes several."""
    if not several:
        return re.search(rf"\b{ac}\b", ac_text) is not None
    return any(re.search(rf"#{issue}(?!\d)", ln) and re.search(rf"\b{ac}\b", ln) for ln in ac_text.splitlines())


def check_pr(md: str, issues: dict[int, str]) -> list[str]:
    """What is wrong with a PR body, one line each. `issues` maps the number of each issue the PR closes to its body.
    Every `Closes #n` in the PR must be among them, and every criterion of every issue must be named in the PR's
    Acceptance criteria section, so a criterion cannot be dropped on the way from the issue to the merge."""
    secs = sections(md)
    out = [f"missing section: ## {name}" for name in PR_SECTIONS if name not in secs]
    wanted = list(dict.fromkeys([*closes(md), *issues]))
    ac_text = secs.get("Acceptance criteria", "")
    for n in wanted:
        if n not in issues:
            out.append(f"issue #{n} was not read")
            continue
        for ac in criteria(issues[n]):
            if not named(ac_text, n, ac, several=len(wanted) > 1):
                out.append(f"Acceptance criteria does not name {ac} of issue #{n}"
                           + (f' (write "- #{n} {ac}: ...")' if len(wanted) > 1 else ""))
    out += risk_problems(secs)
    return out


def issue_arg(text: str) -> tuple[int, pathlib.Path]:
    n, eq, path = text.partition("=")
    if not (eq and n.isdigit() and path):
        raise argparse.ArgumentTypeError(f"{text!r}: expected N=FILE")
    return int(n), pathlib.Path(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="form", required=True)
    sub.add_parser("issue", help="check an issue body").add_argument("file", type=pathlib.Path)
    pr = sub.add_parser("pr", help="check a PR body against the issues it closes")
    pr.add_argument("file", type=pathlib.Path)
    pr.add_argument("--issue", action="append", default=[], type=issue_arg, metavar="N=FILE",
                    help="a closed issue's number and the file holding its body (repeat per issue)")
    a = ap.parse_args(argv)

    text = a.file.read_text(encoding="utf-8")
    if a.form == "issue":
        problems = check_issue(text)
    else:
        problems = check_pr(text, {n: path.read_text(encoding="utf-8") for n, path in a.issue})
    print("\n".join(problems) if problems else "ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
