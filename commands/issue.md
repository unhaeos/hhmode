---
description: Write an issue from the issue form, check it with forms.py, and open it with gh. One issue is one pull request's worth of work.
argument-hint: [what needs doing, in a sentence or two] (optional; asked for if omitted)
---

# /issue

Turn a task into an issue that someone else can build and check without asking you. The issue is the first of four linked forms (issue, PR body, verifier record, merge check), and its Acceptance criteria, Risk and Out of scope are read again at each of them.

## Steps

1. **Size it.** One issue = one PR's worth of work. If the task needs more than one PR, write the first PR's worth as this issue and name the rest under Out of scope (or open them as separate issues).
2. **Write the body** to a temp file from `~/projects/hhmode/templates/issue.md`: every section filled, nothing left in `<angle brackets>`.
   - Acceptance criteria: numbered `- [ ] AC1: <criterion>`, each one checkable by someone who did not write the change (a command and its expected result, or a file and what it must contain). No "works well" or "is cleaner".
   - Risk: `low`, `medium` or `high`, then ` — ` and a short reason. The tiers are in `~/projects/hhmode/skills/code-review/references/tiers.md`; the repo's CLAUDE.md wins if it defines its own. The change sets the tier. When unsure, take the higher one.
3. **Check the form.** `python3 ~/projects/hhmode/scripts/forms.py issue <tmp>`. Fix what it prints and run it again until it prints `ok`.
4. **Open it.** `gh issue create --title "<one sentence>" --body-file <tmp>`. The title is one sentence that states the task, for example "Show each project name once in the weekly report". Print the issue URL.

## Rules

- Never open an issue that did not pass step 3.
- The section headings stay in English, because `forms.py` reads them; the text under them follows the repo's existing language.
- If `gh` is not authenticated or the repo has no remote, stop and say so.
- Output in Korean.

## Args
$ARGUMENTS
