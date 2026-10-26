# Explain the Number

Before you trust, report, or act on a measured number (speedup, accuracy, attack success rate, latency, eval score), explain what bounds it.

- **Ask "why not double?"** Name the resource or code path that limits the result. If you cannot say why the number is not twice as good, you do not know what you measured.
- **List what else the number could be measuring, and rule out each with evidence.** Usual suspects: errors counted as results, skipped or cached work, code that never ran, an untuned baseline, noise, judge/grader bias, a sample too small to matter.
- **Keep the evidence with the number.** Run count, seed(s), spread (std or min/max), and the named limiter go next to the number, not in your head.
- An eval result gets the same questions per trial: did every run actually do the task, does the gap hold across seeds and models, does the scenario matter.

You skipped this when a reported number has no run count, no spread, or no named limiter.

Adapted from pstack `principle-explain-the-number` (Lauren Tan, MIT).
