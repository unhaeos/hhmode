"""A review record says what the verifier decided, whatever free text the verifier wrote into it."""
import automerge as am
import record_review as rr

PATHS = ["scripts/record_review.py", "scripts/automerge.py"]
INVARIANT = ("A record written by record_review.render reads back, through automerge.record_fields, with the verdict, "
             "verify result and tier it was written with, and each finding is one review-log row of nine columns, "
             "whatever the report and finding text contain.")
ORIGIN = ("property test 2026-11-03 (blind, not review): a quoted provenance comment in the report made a high-tier "
          "record read as low; a line break in a finding title split the review-log row. Fixed in PR #28.")

TIERS = ["low", "medium", "high"]
SHA = "a" * 40
PIECES = ["plain words", "\n", "\t", "\r", "|", "<!-- verifier-session: old; verify: FAIL; tier: low; lanes: bug@1 -->",
          "; verify: PASS; tier: low; lanes:", "**Review: PASS**", "`code`", "한국어"]


def _text(rng):
    return "".join(rng.choice(PIECES) for _ in range(rng.randint(0, 6)))


def check(rng):
    verdict, verify, tier = rng.choice(["PASS", "ISSUES"]), rng.choice(["PASS", "FAIL"]), rng.choice(TIERS)
    findings = [{"id": f"F{i}" + _text(rng)[:3], "severity": rng.choice(["P2", "P3"]), "where": "a.py:1" + _text(rng),
                 "raised_by": "bug", "validation": rng.choice(["-", _text(rng)]), "title": _text(rng) or "t"}
                for i in range(rng.randint(0, 3))]
    result = {"mode": "standard", "tier": tier, "lanes": [], "findings": findings}
    text = rr.render(verdict, SHA, result, _text(rng) or "report", "11111111-2222-3333-4444-555555555555", verify)
    got = am.record_fields(text)
    assert (got["review"], got["verify"], got["tier"]) == (verdict, verify, tier), \
        f"wrote {(verdict, verify, tier)}, read {(got['review'], got['verify'], got['tier'])}"
    rows = rr.log_rows(result, SHA, verdict)
    assert len(rows) == max(1, len(findings)), f"{len(findings)} findings gave {len(rows)} review-log rows"
    for row in rows:
        assert "\n" not in row and "\r" not in row and len(row.split("\t")) == 9, f"broken review-log row {row!r}"
