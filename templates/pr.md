<!-- Fill every section. Acceptance criteria, Risk and Out of scope are the same fields as in the issue form (templates/issue.md); scripts/forms.py checks this body against the issues it closes. -->
## Why
<1 to 3 lines: the reason for the change>
Closes #<n>
<!-- Keep one "Closes #<n>" line for each issue this work came from, and delete the line when there is none. GitHub closes the issue on merge. -->

## What changed
<2 to 5 lines: what changed, from the user's point of view>

## Acceptance criteria
- AC1: <how you checked it: command or file:line> → <result>
- AC2: <how you checked it: command or file:line> → <result>
<!-- One line for each criterion of each issue this PR closes. With more than one issue, write "- #<n> AC1: ...". With no linked issue, replace the list with: none — no linked issue -->

## Verification
<the Review and Verify lines exactly as verify_fresh.sh printed them, never typed by hand>
| Check | Command | Result |
|---|---|---|
| <your own check: tests, typecheck> | `<exact command>` | <exit code, key output line> |
| Independent verifier | `verify_fresh.sh` (standard, fix or carry) | <verdict · sha7 · verifier session id · record path> |

Label each result `measured` (you ran it) or `inferred`. If something could not be run, say so here.

## Risk
<low | medium | high> — <one line: the path or behaviour that decides the tier>
<what could break elsewhere, and what you checked to rule it out; "none found" is allowed only with the check that found none>

## How to revert
<one line: `git revert <sha>`, the flag to flip, or the data restore step if the change wrote to a database>

## Out of scope
<follow-ups deliberately left out; copy the issue's Out of scope, or "none">
