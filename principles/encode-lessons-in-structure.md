# Encode Lessons in Structure

When you write the same instruction a second time, or see the same correction twice, encode it as structure (a script, a lint, a check in the harness, a required field) instead of more text.

- Text rules get skipped under load. Structure does not.
- If the lesson needs judgment and cannot be encoded, make the instruction more prominent and add a concrete example of the failure.
- **Corollary:** if the fix is structural, use only the structural fix. The instruction was the symptom.

In this repo: a line in `log.md` is the first occurrence. The second occurrence of the same line is the trigger to add a file or script.

Adapted from pstack `principle-encode-lessons-in-structure` (Lauren Tan, MIT).
