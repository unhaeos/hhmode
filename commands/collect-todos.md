---
description: Scan Slack and Gmail (received, and promises I made) and append only real to-dos to memo.md
argument-hint: (empty = since last run) | days=N | emoji:<name> (Slack reaction mode)
---

# /collect-todos

Filter Slack and Gmail down to two things: requests I must act on, and commitments I made. Write each as a short to-do, phrased the way I would write it, into `~/.claude/memo.md`. Discard everything else. The viewer is `~/projects/todo-widget/server.py`.

Read my Slack user_id and email from `~/projects/hhmode/local/identity.md` (gitignored). `<ME>` below means that user_id. Read address-form overrides from `~/projects/hhmode/local/slack-voice.md` if present.

## Modes

- Default (no args): filter all four sources below.
- `days=N`: collection window of the last N days (default 7).
- `emoji:<name>`: Slack reaction mode (`hasmy::<name>:`).

## Steps

1. **Window.** If `~/projects/todo-widget/.lastrun` exists, start there; otherwise last 7 days (`days=N` wins). Today via `date +%Y-%m-%d`. Slack uses `after:YYYY-MM-DD`; Gmail uses `after:YYYY/MM/DD` (slashes).

2. **Dedup set.** Collect every URL after `↗` in memo.md, including completed `[x]` items. Skip anything that is a re-mention of an existing item even when the URL differs.

3. **Four searches.**
   - (a) Slack received: `slack_search_public_and_private`, query `to:me after:<d>`, sort=timestamp desc, limit 20, include_context false. If mentions are missing, add `<@<ME>> after:<d>`.
   - (b) Slack sent: query `from:me after:<d>`. This is where my commitments are.
   - (c) Gmail received: `search_threads`, query `in:inbox after:<d> -category:promotions -category:social -category:forums`. Judge from subject and snippet; use `get_thread` when unclear.
   - (d) Gmail sent: `search_threads`, query `in:sent after:<d>`.
   If a response spills to a file, extract only sender, time, content, permalink (or threadId).

4. **Judgment differs by source.**
   - Received (a, c). Keep: requests, questions, assignments, confirmation requests, deadlines addressed to me, where my action unblocks it. Drop: FYI, newsletters, notifications, automated mail, receipts, small talk, greetings, finished threads.
   - Sent (b, d). Keep: commitments I made ("I'll do / fix / send / write up ..."), deadlines and follow-ups I set myself. A numbered list of several promises in one message becomes several items. Do not drop a commitment because the deliverable looks small; a promise I made is my to-do by default. Drop: plain answers, agreement, greetings, things already done, and questions that hand the ball back to the other person ("shall I ...?", "do you want ...?").
   - When unclear: drop received items (noise first), keep sent commitments.
   - No hardcoded people or phrases; apply general criteria.

5. **Priority.** Imminent deadline or urgent `[P1]`, ordinary request or commitment `[P2]`, light or less urgent `[P3]`.

6. **Append kept items** after `<!-- ITEMS BELOW -->` in memo.md:
   ```
   - [ ] <message date YYYY-MM-DD> [Pn] [slack|gmail] <short title> — <detail (optional)> ↗<permalink>
   ```
   - Title: `[object] + [verb]`, about 25 characters, imperative, never a paste of the original. Add `(M/D 마감)` when there is a deadline. For my own commitments, keep the promise as stated.
   - Detail (optional): after ` — `, full sentences in this order: context (who, what thread), what to do, conditions and deadline. No telegraphic word lists or abbreviation clusters; a reader without context must understand it. Several sub-items go one per ` ⏎ ` separator (the widget renders it as line breaks; the memo.md line itself stays one physical line).
   - No ` — ` inside the title (it is the separator). Address people as `'OO님'` rather than by bare name, applying overrides from `local/slack-voice.md`.
   - Source tag `[slack]` or `[gmail]`.
   - `↗<permalink>` is required. Slack: message permalink. Gmail: `https://mail.google.com/mail/u/0/#all/<threadId>`.
   - Skip URLs already in the dedup set.

7. **Update `.lastrun`** with today's date.

8. **Output (Korean).**
   - `+ 살린 N건`: one line per added item, with source (슬랙받음 / 슬랙약속 / 메일받음 / 메일약속).
   - `– 버린 M건`: top few as "source, sender: one-line gist (reason dropped)", so misjudgments can be caught.
   - Last line: `보기: <memo_viewer from identity.md>`.

## Rules

- Korean output, no filler. Append only; never modify existing memo items.
- Always show the dropped list. It is how filter quality gets checked.

## Args
$ARGUMENTS
