"""The merge reads exactly the tier Codex gave, whatever Codex wrote as the reason."""
import automerge as am
import codex_review as cr

PATHS = ["scripts/codex_review.py", "scripts/automerge.py", "scripts/forms.py"]
INVARIANT = ("For any schema-valid Codex result, automerge.gpt_tier reads back from codex_review.render exactly the "
             "tier in the result, never a tier word from the reason or the findings.")
ORIGIN = ("review findings on hhmode a93fe87, 8ddbe0d, c982ba2: 'medium - high' read as medium and merged without "
          "the user; fixed by the JSON schema. This check keeps the schema path honest.")

TIERS = ["low", "medium", "high"]
WORDS = ["low", "medium", "high", "-", "–", "—", ":", "**", "## Tier", "\n", "scripts/automerge.py", "reason", "risk"]


def _free(rng):
    return " ".join(rng.choice(WORDS) for _ in range(rng.randint(0, 6)))


def check(rng):
    tier = rng.choice(TIERS)
    data = {"tier": tier, "tier_reason": _free(rng),
            "findings": [{"id": f"G{i}", "priority": rng.choice(["P1", "P2", "P3"]), "title": _free(rng) or "t",
                          "location": "a.py:1", "trigger": _free(rng), "evidence": _free(rng), "fix": _free(rng)}
                         for i in range(rng.randint(0, 2))]}
    got = am.gpt_tier(cr.render(data))
    assert got == tier, f"Codex said {tier!r}, the merge read {got!r} (reason {data['tier_reason']!r})"
