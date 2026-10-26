---
name: investigate
description: Read-only investigation that ends in a cited explanation or a recommendation, not a code change. Use when the user asks "why does X happen", "이거 왜 이래", "어떻게 동작하는지 조사해", "are we sure that...", or wants a decision between alternatives. If a code change follows, hand back to the user first.
---

# Investigate

You own the answer. Read, do not edit.

Copy these steps into your todo list verbatim. A skipped step must be marked `skip: <reason>`.

1. **State the question in one line** and what observation would settle it.
2. **Read the real thing.** Source, logs, result files, git history. Do not answer from memory of how similar systems usually work. Every claim gets a citation: `file:line`, a command and its output, or a commit hash.
3. **Label every claim** `measured` (you observed it), `inferred` (follows from observations), or `guess` (no direct evidence). A guess is allowed only when labeled.
4. **If the premise of the question is wrong, say so first**, with the evidence, before answering the question as asked.
5. **Write the output** in this shape:
   - Answer (one paragraph, leads with the conclusion)
   - Evidence (bulleted citations)
   - What this does not establish (open gaps)
   - Recommendation + tradeoffs table, only if the request is a decision between alternatives
6. **Verdict line:** `VERIFIED` (evidence settles it), `NOT VERIFIED` (evidence contradicts the premise), `INCONCLUSIVE` (could not observe). Inconclusive is not a pass; say what observation is missing.

No code changes, no "while I was here" fixes. If the investigation shows a change is needed, stop and hand back.

Adapted from pstack playbook `investigation` and skill `figure-it-out` (Lauren Tan, MIT). Removed: how/why/unslop skill routing, throughput checkpoint.
