"""Any change builds a review input, and every changed text file is in it."""
import os
import pathlib
import subprocess
import tempfile

import gpt_review_input as gi

PATHS = ["scripts/gpt_review_input.py"]
INVARIANT = ("gpt_review_input.build never raises on a changed file's bytes or name, and every changed UTF-8 text "
             "file inside the repo appears in the input with its contents.")
ORIGIN = ("review finding on hhmode ac095e1 (Opus + Codex, P2): a non-UTF-8 byte raised UnicodeDecodeError and the "
          "gate ended before the verifier started; property test 2026-11-03: a non-ASCII name was quoted by git.")

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
NAME_CHARS = "abcxyz_- é한中"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env={**os.environ, **ENV})


def check(rng):
    with tempfile.TemporaryDirectory() as d:
        repo = pathlib.Path(d)
        _git(repo, "init", "-q")
        _git(repo, "config", "core.quotePath", rng.choice(["true", "false"]))
        (repo / "base.txt").write_text("base\n", encoding="utf-8")
        _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "base")
        base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        texts = {}
        for i in range(rng.randint(1, 3)):
            name = "".join(rng.choice(NAME_CHARS) for _ in range(rng.randint(1, 6))).strip() or "x"
            name = f"{name}{i}.txt"
            if rng.random() < 0.5:
                body = f"text {i} {rng.getrandbits(32):x}\n"
                (repo / name).write_text(body, encoding="utf-8")
                texts[name] = body.strip()
            else:
                (repo / name).write_bytes(bytes(rng.randrange(256) for _ in range(rng.randint(1, 40))))
        _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "change")
        out = gi.build(repo, base)                 # must not raise
        for name, body in texts.items():
            assert body in out, f"changed text file {name!r} is missing from the review input"
