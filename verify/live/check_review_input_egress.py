"""Nothing outside the repo reaches Codex through the review input."""
import pathlib
import subprocess
import tempfile

import gpt_review_input as gi

PATHS = ["scripts/gpt_review_input.py"]
INVARIANT = "gpt_review_input.build never includes the contents of a file outside the repo, whatever links the change adds."
ORIGIN = "review finding on hhmode ac095e1 (Codex, P2): a committed symlink sent its target's contents to Codex."

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(repo, *args):
    import os
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env={**os.environ, **ENV})


def check(rng):
    with tempfile.TemporaryDirectory() as outside, tempfile.TemporaryDirectory() as d:
        secret = f"OUTSIDE-{rng.getrandbits(64):x}"
        target = pathlib.Path(outside) / "secret.txt"
        target.write_text(secret + "\n", encoding="utf-8")
        repo = pathlib.Path(d)
        _git(repo, "init", "-q")
        (repo / "base.txt").write_text("base\n", encoding="utf-8")
        _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "base")
        base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        for i in range(rng.randint(1, 4)):
            kind = rng.choice(["file", "link-out", "link-in", "link-dir-out"])
            name = f"f{i}" + rng.choice(["", ".txt", ".py"])
            if kind == "file":
                (repo / name).write_text(f"inside {i}\n", encoding="utf-8")
            elif kind == "link-out":
                (repo / name).symlink_to(target)
            elif kind == "link-in":
                (repo / name).symlink_to("base.txt")
            else:
                (repo / name).symlink_to(outside, target_is_directory=True)
        _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "change")
        out = gi.build(repo, base)
        assert secret not in out, f"contents of a file outside the repo reached the review input ({sorted(p.name for p in repo.iterdir())})"
