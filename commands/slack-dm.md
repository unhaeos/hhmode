---
description: Draft a Slack DM in my own voice, calibrated against my real recent messages. Sends only after explicit OK.
argument-hint: <recipient> <topic or key points>
---

# /slack-dm

Take `$ARGUMENTS` and draft a Slack DM in my voice. Draft only. Never send without an explicit OK.

Read my Slack user_id from `~/projects/hhmode/local/identity.md` (gitignored). `<ME>` below means that user_id. Voice samples are in `~/projects/hhmode/local/slack-voice.md`.

## Steps

1. **Calibrate tone, every time.** Measure, do not assume.
   - Resolve the recipient's user_id with `slack_search_users`.
   - Read 10 to 20 of my recent messages with `from:<@<ME>>`, narrowed to that DM with `in:<@recipient>` when possible. Observe current phrasing and emoji habits and follow them.
   - The rules below are a guard layered on top. When real messages differ from the rules, follow the messages.

2. **Draft** per the voice rules. Present in a code block.

3. **Confirm.** Ask whether to send. Apply any tone or content changes requested.

4. **Send** with `slack_send_message` to that DM channel only after an explicit OK. Without it, the draft is the deliverable.

## Voice rules (distilled from real messages)

- Plain mix of 합니다체 and 해요체. Short and direct. Point and conclusion first. One topic is 2 to 4 sentences.
- Minimal emoji. No strings of `:pray:`, `:raised_hands:`, colored circles. Numbered `1. 2.` only when listing technical items. A light `!` is fine.
- Typical endings: "~더라고요 / ~까요? / ~습니다 / ~할게요 / ~같습니다". Occasional "넵 / 앗".
- No excess politeness or formality. No repeated thanks, no deferential tone. Peer to peer.
- Technical content stays concrete: endpoints, fields, measured numbers as they are.
- Never "저희". I am one person: "제가 / 저는 / 제 쪽에서".
- A question DM is "this is the situation, is this right?" in one breath, not an open-ended list.

See `local/slack-voice.md` for real examples.
