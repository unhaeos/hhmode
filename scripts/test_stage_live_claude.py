"""Tests for stage_live_claude.sh. Run: python3 -m unittest scripts/test_stage_live_claude.py (from the hhmode root)."""
from __future__ import annotations

import pathlib
import subprocess
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).with_name("stage_live_claude.sh")


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


class Stage(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        origin = self.tmp / "origin.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(origin))
        self.wt = self.tmp / "wt"
        git(self.tmp, "clone", "-q", str(origin), str(self.wt))
        write(self.wt, "commands/old.md", "---\ndescription: old\n---\nold\n")
        write(self.wt, "README.md", "x\n")
        git(self.wt, "add", ".")
        git(self.wt, "commit", "-qm", "base")
        git(self.wt, "push", "-q", "origin", "main")
        git(self.wt, "checkout", "-qb", "feat")
        self.live = self.tmp / "live"
        self.ask = self.wt / ".verify" / "ask.sh"
        self.ask.parent.mkdir()

    def stage(self):
        p = subprocess.run(["bash", str(SCRIPT), str(self.wt), str(self.live), str(self.ask)],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.split("\n")[:-1]

    # 2026-10-29: #6 (/bro), #7 and #8 had their live lane BLOCKED; a same-named project copy loses to ~/.claude.
    def test_changed_command_skill_agent_are_staged_under_new_names(self):
        write(self.wt, "commands/bro.md", "---\ndescription: d\n---\nbody\n")
        write(self.wt, "skills/correct/SKILL.md", "---\nname: correct\ndescription: d\n---\nname: keep this line\n")
        write(self.wt, "skills/correct/ref.md", "ref\n")
        write(self.wt, "agents/plan-reviewer.md", "---\nname: plan-reviewer\n---\nx\n")
        write(self.wt, "README.md", "changed\n")
        git(self.wt, "add", ".")
        git(self.wt, "commit", "-qm", "change")
        out = self.stage()
        self.assertEqual(sorted(out), ["/bro-new", "agent plan-reviewer-new", "skill correct-new"])
        c = self.live / ".claude"
        self.assertEqual((c / "commands" / "bro-new.md").read_text(), "---\ndescription: d\n---\nbody\n")
        skill = (c / "skills" / "correct-new" / "SKILL.md").read_text()
        self.assertIn("name: correct-new\n", skill)
        self.assertIn("name: keep this line", skill)          # only the frontmatter name is renamed
        self.assertTrue((c / "skills" / "correct-new" / "ref.md").exists())
        self.assertIn("name: plan-reviewer-new", (c / "agents" / "plan-reviewer-new.md").read_text())
        self.assertFalse((c / "commands" / "old-new.md").exists())   # unchanged files are not staged
        ask = self.ask.read_text()
        self.assertIn(f'cd "{self.live}"', ask)
        self.assertIn("--resume", ask)
        # Verifier note F3 on 01a3bd6: the session must not inherit the user's allowlist (a staged /mm-new could
        # have written the real memo).
        self.assertIn("--setting-sources project", ask)
        self.assertIn('--tools "Read,Grep,Glob"', ask)

    # Verifier note F1 on 01a3bd6: a commit changing only skills/code-review/verifier.md staged nothing.
    def test_skill_with_only_a_side_file_changed_is_staged_once(self):
        write(self.wt, "skills/review/SKILL.md", "---\nname: review\n---\nx\n")
        git(self.wt, "add", ".")
        git(self.wt, "commit", "-qm", "add skill")
        git(self.wt, "push", "-q", "origin", "feat:main")
        write(self.wt, "skills/review/verifier.md", "changed\n")
        write(self.wt, "skills/review/references/rubric.md", "changed\n")
        git(self.wt, "add", ".")
        git(self.wt, "commit", "-qm", "side files")
        git(self.wt, "fetch", "-q", "origin")
        self.assertEqual(self.stage(), ["skill review-new"])
        self.assertTrue((self.live / ".claude" / "skills" / "review-new" / "references" / "rubric.md").exists())

    def test_no_claude_file_changed_stages_nothing(self):
        write(self.wt, "README.md", "changed\n")
        git(self.wt, "add", ".")
        git(self.wt, "commit", "-qm", "docs")
        self.assertEqual(self.stage(), [])
        self.assertFalse(self.ask.exists())
        self.assertFalse(self.live.exists())

    def test_deleted_command_is_skipped(self):
        git(self.wt, "rm", "-q", "commands/old.md")
        git(self.wt, "commit", "-qm", "drop")
        self.assertEqual(self.stage(), [])
        self.assertFalse(self.ask.exists())
        self.assertFalse(self.live.exists())


if __name__ == "__main__":
    unittest.main()
