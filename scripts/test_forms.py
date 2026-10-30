"""Tests for forms.py. Run: python3 -m unittest scripts/test_forms.py (from the hhmode root)."""
from __future__ import annotations

import contextlib
import io
import pathlib
import re
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import automerge as am  # noqa: E402
import forms  # noqa: E402

ISSUE = """## Background
Reports name a project twice.

## Acceptance criteria
- [ ] AC1: one header line per project
- [ ] AC2: the weekly report test passes

## Out of scope
The monthly report.

## Risk
medium — scripts/weekly.py: behaviour change
"""

AC_LIST = "- AC1: `grep -c '^## ' report.md` → 1\n- AC2: `python3 -m unittest scripts/test_weekly.py` → OK"
PR = """## Why
Reports name a project twice.
Closes #7

## What changed
One header line per project.

## Acceptance criteria
{ac}

## Verification
**Review: PASS** · abc1234 · standard · verifier 11111111

## Risk
medium — scripts/x.py: one function
none found: grep shows no other caller

## How to revert
git revert abc1234

## Out of scope
The monthly report.
""".replace("{ac}", AC_LIST)


def without(md: str, heading: str) -> str:
    """`md` with the `## heading` section removed."""
    return re.sub(rf"^## {heading}\n.*?(?=^## |\Z)", "", md, flags=re.S | re.M)


def fill(template: str, tier: str = "low") -> str:
    """A template with its comments dropped and every <placeholder> answered, as an author would."""
    text = re.sub(r"<!--.*?-->", "", template, flags=re.S).replace("<low | medium | high>", tier)
    return re.sub(r"<[^<>\n]*>", "filled", text.replace("Closes #<n>", "Closes #7"))


def after_front_matter(text: str) -> str:
    return text.split("\n---\n", 1)[1] if text.startswith("---\n") else text


class Parse(unittest.TestCase):
    def test_sections_by_heading(self):
        secs = forms.sections(ISSUE)
        self.assertEqual(list(secs), ["Background", "Acceptance criteria", "Out of scope", "Risk"])
        self.assertEqual(secs["Out of scope"], "The monthly report.")
        self.assertIn("AC2", secs["Acceptance criteria"])

    def test_a_deeper_heading_stays_inside_its_section(self):
        secs = forms.sections("## Verification\n### Acceptance criteria\ntable\n\n## Risks\nnone\n")
        self.assertEqual(list(secs), ["Verification", "Risks"])
        self.assertIn("### Acceptance criteria", secs["Verification"])

    def test_html_comments_do_not_count(self):
        md = "## Acceptance criteria\n<!-- write AC1 here -->\n- AC2: x\n"
        self.assertEqual(forms.criteria(md), ["AC2"])
        self.assertEqual(forms.sections("<!-- ## Why -->\n## Risk\nlow\n"), {"Risk": "low"})

    def test_criteria_ids_in_order_once(self):
        self.assertEqual(forms.criteria(ISSUE), ["AC1", "AC2"])
        md = "## Acceptance criteria\n- [ ] AC2: b\n- [ ] AC1: a, as AC2 says\n"
        self.assertEqual(forms.criteria(md), ["AC2", "AC1"])
        self.assertEqual(forms.criteria("## Background\nAC9 is mentioned here\n"), [])
        self.assertEqual(forms.criteria("## Acceptance criteria\n- BAC1 and AC10x\n"), [])

    def test_closes_reads_github_keywords(self):
        self.assertEqual(forms.closes("Closes #7\nfixes #8, Resolved: #9 and close #7"), [7, 8, 9])
        self.assertEqual(forms.closes("CLOSED #12"), [12])
        for text in ("see #7", "prefix #7", "closes o/r#7", "Closes #<n>", "fix(review): x", ""):
            self.assertEqual(forms.closes(text), [], text)

    # Verifier on a93fe87, 8ddbe0d, c982ba2: only `<tier> — <reason>` counts, for every rating.
    def test_tier_line_only_in_its_exact_form(self):
        self.assertEqual(forms.tier_line("high — a.py: from low to low or medium risk."), "high")
        for text in ("medium - high — x", "medium – high — x", "**medium** - **high** — x", "**high** — x", "high",
                     "low | medium | high", "<low | medium | high> — x", "low-to-medium — x", "", None):
            self.assertIsNone(forms.tier_line(text), text)
        self.assertIs(am.tier_line, forms.tier_line)       # one tier reader


class CheckIssue(unittest.TestCase):
    def test_a_filled_issue_is_ok(self):
        self.assertEqual(forms.check_issue(ISSUE), [])

    def test_each_missing_section_is_named(self):
        for name in forms.ISSUE_SECTIONS:
            problems = forms.check_issue(without(ISSUE, name))
            self.assertIn(f"missing section: ## {name}", problems)
        self.assertEqual(len(forms.check_issue("")), 4)

    def test_acceptance_criteria_without_items(self):
        md = ISSUE.replace("- [ ] AC1: one header line per project\n- [ ] AC2: the weekly report test passes\n",
                           "make it work\n")
        problems = forms.check_issue(md)
        self.assertEqual(len(problems), 1)
        self.assertIn("Acceptance criteria has no items", problems[0])

    def test_risk_must_start_with_a_tier(self):
        # One exact form, the same as Codex's Tier line: anything else is a problem the author fixes.
        for risk in ("unknown", "<low | medium | high> — why", "low | medium | high", "Medium, because", "",
                     "**high** — schema", "medium (a tool change)", "low", "medium - high — x"):
            problems = forms.check_issue(ISSUE.replace("medium — scripts/weekly.py: behaviour change", risk))
            self.assertTrue(any(p.startswith("Risk must start with") for p in problems), risk)
        for risk in ("low — docs", "high — schema change", "medium — a tool change\n  more"):
            self.assertEqual(forms.check_issue(ISSUE.replace("medium — scripts/weekly.py: behaviour change", risk)),
                             [], risk)


class CheckPr(unittest.TestCase):
    # Verifier and Codex on 5342eef: headings alone, or the template with only Risk filled, came back clean.
    def test_empty_sections_and_template_text_are_problems(self):
        empty = "\n\n".join(f"## {n}\n" for n in forms.PR_SECTIONS).replace("## Risk\n", "## Risk\nlow — docs\n")
        problems = forms.check_pr(empty, {})
        for n in forms.PR_SECTIONS:
            if n != "Risk":
                self.assertIn(f"section is empty: ## {n}", problems)
        tpl = (forms.TEMPLATES / "pr.md").read_text().replace("<low | medium | high> — <one line: the path or "
                                                              "behaviour that decides the tier>", "low — docs")
        problems = forms.check_pr(tpl, {7: ISSUE})
        self.assertTrue(any(p.startswith("template text left unfilled: - AC1: <how you checked it") for p in problems),
                        problems)
        self.assertTrue(forms.check_issue((forms.TEMPLATES / "issue.md").read_text()))

    def test_a_filled_pr_is_ok(self):
        self.assertEqual(forms.check_pr(PR, {7: ISSUE}), [])

    def test_each_missing_section_is_named(self):
        for name in forms.PR_SECTIONS:
            self.assertIn(f"missing section: ## {name}", forms.check_pr(without(PR, name), {7: ISSUE}))

    def test_a_criterion_the_pr_does_not_name(self):
        md = PR.replace("- AC2: `python3 -m unittest scripts/test_weekly.py` → OK\n", "")
        self.assertEqual(forms.check_pr(md, {7: ISSUE}), ["Acceptance criteria does not name AC2 of issue #7"])

    def test_a_criterion_named_only_outside_the_section_does_not_count(self):
        md = PR.replace("- AC2: `python3 -m unittest scripts/test_weekly.py` → OK\n", "").replace(
            "none found:", "AC2 is fine;")
        self.assertEqual(len(forms.check_pr(md, {7: ISSUE})), 1)

    def test_a_pr_that_closes_an_issue_it_did_not_read(self):
        problems = forms.check_pr(PR.replace("Closes #7", "Closes #7\nCloses #8"), {7: ISSUE})
        self.assertIn("issue #8 was not read", problems)
        self.assertNotIn("issue #7 was not read", problems)
        self.assertEqual(forms.check_pr(PR, {}), ["issue #7 was not read"])

    def test_no_linked_issue(self):
        md = PR.replace("Closes #7\n", "").replace(AC_LIST, "none — no linked issue")
        self.assertEqual(forms.check_pr(md, {}), [])

    def test_an_issue_with_no_criteria_asks_for_none(self):
        self.assertEqual(forms.check_pr(PR, {7: "## Background\nold issue, no form\n"}), [])

    def test_several_issues_need_the_issue_number_beside_the_id(self):
        issue8 = ISSUE.replace("AC2", "AC3")           # criteria AC1 and AC3
        body = PR.replace("Closes #7", "Closes #7\nCloses #8")
        problems = forms.check_pr(body, {7: ISSUE, 8: issue8})
        self.assertIn('Acceptance criteria does not name AC1 of issue #7 (write "- #7 AC1: ...")', problems)
        self.assertIn('Acceptance criteria does not name AC3 of issue #8 (write "- #8 AC3: ...")', problems)
        ok = body.replace(AC_LIST, "- #7 AC1: grep → 1\n- #7 AC2: unittest → OK\n- #8 AC1: x → y\n- AC3 of #8: z → w")
        self.assertEqual(forms.check_pr(ok, {7: ISSUE, 8: issue8}), [])

    def test_issue_number_must_match_exactly(self):
        issue70 = "## Acceptance criteria\n- [ ] AC1: a\n"
        body = PR.replace("Closes #7", "Closes #7\nCloses #70").replace(AC_LIST, "- #70 AC1: x → y\n- #7 AC2: z → w")
        problems = forms.check_pr(body, {7: ISSUE, 70: issue70})
        self.assertEqual(problems, ['Acceptance criteria does not name AC1 of issue #7 (write "- #7 AC1: ...")'])

    def test_an_issue_given_but_not_closed_in_the_body_is_still_checked(self):
        # automerge passes the issues GitHub says the PR closes, linked by hand or by keyword
        self.assertEqual(forms.check_pr(PR.replace("Closes #7\n", ""), {7: ISSUE}), [])
        md = PR.replace("Closes #7\n", "").replace("- AC2: `python3 -m unittest scripts/test_weekly.py` → OK\n", "")
        self.assertEqual(forms.check_pr(md, {7: ISSUE}), ["Acceptance criteria does not name AC2 of issue #7"])


class Templates(unittest.TestCase):
    """The templates are the forms: bodies built from them, with placeholders filled, must pass the checker."""
    issue_tpl = (ROOT / "templates" / "issue.md").read_text(encoding="utf-8")
    pr_tpl = (ROOT / "templates" / "pr.md").read_text(encoding="utf-8")

    def test_the_issue_template_has_the_four_sections_in_order(self):
        self.assertEqual(list(forms.sections(self.issue_tpl)), list(forms.ISSUE_SECTIONS))
        self.assertTrue(self.issue_tpl.startswith("<!-- Title: one sentence"))

    def test_the_pr_template_has_the_seven_sections_in_order(self):
        self.assertEqual(list(forms.sections(self.pr_tpl)), list(forms.PR_SECTIONS))

    def test_templates_filled_in_pass_and_unfilled_do_not(self):
        issue, pr = fill(self.issue_tpl, "medium"), fill(self.pr_tpl, "medium")
        self.assertEqual(forms.check_issue(issue), [])
        self.assertEqual(forms.criteria(issue), ["AC1", "AC2"])
        self.assertEqual(forms.check_pr(pr, {7: issue}), [])
        self.assertTrue(forms.check_issue(self.issue_tpl))      # the Risk placeholder is not a tier

    def test_the_risk_line_reads_once_filled(self):
        for tpl in (self.issue_tpl, self.pr_tpl):
            self.assertEqual(forms.tier_line(forms.sections(fill(tpl, "high"))["Risk"].splitlines()[0]), "high")
            self.assertTrue(forms.risk_problems(forms.sections(tpl)))       # unfilled placeholder

    def test_the_github_templates_match_ours(self):
        for ours, theirs in (("issue.md", ".github/ISSUE_TEMPLATE/task.md"),
                             ("pr.md", ".github/pull_request_template.md")):
            text = (ROOT / theirs).read_text(encoding="utf-8")
            self.assertEqual(after_front_matter(text), (ROOT / "templates" / ours).read_text(encoding="utf-8"),
                             f"{theirs} drifted from templates/{ours}")

    def test_the_github_issue_template_has_the_front_matter_github_needs(self):
        head = (ROOT / ".github" / "ISSUE_TEMPLATE" / "task.md").read_text(encoding="utf-8").split("\n---\n")[0]
        for key in ("name:", "about:", "title:", "labels: []"):
            self.assertIn(key, head)


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = forms.main(list(argv))
        return rc, out.getvalue()

    def test_issue_ok(self):
        self.assertEqual(self.run_cli("issue", self.write("i.md", ISSUE)), (0, "ok\n"))

    def test_issue_problems_one_per_line(self):
        rc, out = self.run_cli("issue", self.write("i.md", without(without(ISSUE, "Risk"), "Background")))
        self.assertEqual(rc, 1)
        self.assertEqual(out.splitlines(), ["missing section: ## Background", "missing section: ## Risk"])

    def test_pr_with_its_issue(self):
        pr, issue = self.write("pr.md", PR), self.write("issue.md", ISSUE)
        self.assertEqual(self.run_cli("pr", pr, "--issue", f"7={issue}"), (0, "ok\n"))
        rc, out = self.run_cli("pr", pr)
        self.assertEqual((rc, out), (1, "issue #7 was not read\n"))

    def test_pr_with_two_issues(self):
        body = PR.replace("Closes #7", "Closes #7\nCloses #8")
        pr, a, b = self.write("pr.md", body), self.write("a.md", ISSUE), self.write("b.md", ISSUE)
        rc, out = self.run_cli("pr", pr, "--issue", f"7={a}", "--issue", f"8={b}")
        self.assertEqual(rc, 1)
        self.assertIn('(write "- #8 AC1: ...")', out)

    def test_a_malformed_issue_argument_is_a_usage_error(self):
        pr = self.write("pr.md", PR)
        for bad in ("7", "x=file", "7="):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                forms.main(["pr", pr, "--issue", bad])
            self.assertEqual(cm.exception.code, 2)

    def test_run_as_a_script(self):
        import subprocess
        run = subprocess.run([sys.executable, str(HERE / "forms.py"), "issue", self.write("i.md", ISSUE)],
                             capture_output=True, text=True)
        self.assertEqual((run.returncode, run.stdout), (0, "ok\n"))


if __name__ == "__main__":
    unittest.main()
