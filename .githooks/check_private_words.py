#!/usr/bin/env python3
# Copyright 2026 sigfridvonshrink
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Keep private words out of the repository: a contributor's real name, a personal address, a home path.

The words themselves are never written in the repository — a check that named them would publish them. They are
read from two places, both outside what git tracks:

  - `.git/private-words` in this clone: one word or phrase to a line, `#` starting a comment;
  - the environment variable `PRIVATE_WORDS`: the same, separated by newlines or commas (CI gives it from a secret).

With no word given the check passes, saying so. Matching ignores case. A match is reported by file and line, the
word itself shown only by its first letter and its length.

Modes:
  --staged          what is about to be committed (the staged content of every staged file)      [pre-commit]
  --message FILE    a commit message                                                            [commit-msg]
  --push            every commit about to be pushed — its message and the lines it adds — read from the
                    `<local ref> <local sha> <remote ref> <remote sha>` lines git gives on stdin   [pre-push]
  --tree            every tracked file as it stands                                              [CI]
  --history         every commit message and every added line of every commit reachable from HEAD [CI, slow]
"""
import os
import re
import subprocess
import sys

ZERO = "0" * 40


def words():
    found = []
    try:
        top = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True).stdout.strip()
        with open(os.path.join(top, "private-words"), encoding="utf-8") as f:
            found += f.read().splitlines()
    except OSError:
        pass
    found += re.split(r"[\n,]", os.environ.get("PRIVATE_WORDS", ""))
    cleaned = []
    for w in found:
        w = w.split("#", 1)[0].strip()
        if w and w.lower() not in (c.lower() for c in cleaned):
            cleaned.append(w)
    return cleaned


def shown(word):
    return f"{word[0]}{'*' * (len(word) - 1)} ({len(word)} letters)"


def git(*args, binary=False):
    out = subprocess.run(["git", *args], capture_output=True)
    return out.stdout if binary else out.stdout.decode("utf-8", "replace")


def scan_text(pattern, text, where, hits):
    for n, line in enumerate(text.splitlines(), 1):
        for m in pattern.finditer(line):
            hits.append(f"{where}:{n}: {shown(m.group(0))}")


def scan_commits(pattern, revs, hits):
    """Each commit's message, and each line it adds."""
    for rev in revs:
        short = rev[:10]
        scan_text(pattern, git("log", "-1", "--format=%an%n%ae%n%cn%n%ce%n%B", rev), f"commit {short} (message)", hits)
        path = "?"
        for line in git("show", "--format=", "--unified=0", "--no-color", "--text", rev).splitlines():
            if line.startswith("+++ "):
                path = line[6:] if line.startswith("+++ b/") else line[4:]
            elif line.startswith("+") and pattern.search(line):
                for m in pattern.finditer(line):
                    hits.append(f"commit {short}: {path}: {shown(m.group(0))}")


def main(argv):
    mode = argv[1] if len(argv) > 1 else ""
    listed = words()
    if not listed:
        print("private-words: no word is set for this clone (.git/private-words, or PRIVATE_WORDS) — nothing checked.")
        return 0
    pattern = re.compile("|".join(re.escape(w) for w in sorted(listed, key=len, reverse=True)), re.IGNORECASE)
    hits = []
    if mode == "--staged":
        for path in git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split("\0"):
            if path:
                scan_text(pattern, path, f"{path} (its name)", hits)
                scan_text(pattern, git("show", f":{path}", binary=True).decode("utf-8", "replace"), path, hits)
    elif mode == "--message":
        with open(argv[2], encoding="utf-8", errors="replace") as f:
            scan_text(pattern, "\n".join(l for l in f.read().splitlines() if not l.startswith("#")),
                      "commit message", hits)
    elif mode == "--push":
        revs = []
        for line in sys.stdin.read().splitlines():
            parts = line.split()
            if len(parts) != 4 or parts[1] == ZERO:          # a deletion pushes nothing
                continue
            rng = [parts[1], "--not", "--remotes"] if parts[3] == ZERO else [f"{parts[3]}..{parts[1]}"]
            revs += [r for r in git("rev-list", *rng).split() if r not in revs]
            scan_text(pattern, parts[0], "ref name", hits)
        scan_commits(pattern, revs, hits)
    elif mode == "--tree":
        for path in git("ls-files", "-z").split("\0"):
            if not path:
                continue
            scan_text(pattern, path, f"{path} (its name)", hits)
            try:
                with open(path, "rb") as f:
                    scan_text(pattern, f.read().decode("utf-8", "replace"), path, hits)
            except OSError:
                pass
    elif mode == "--history":
        scan_commits(pattern, git("rev-list", "HEAD").split(), hits)
    else:
        print(__doc__)
        return 2
    if hits:
        print(f"private-words: {len(hits)} place(s) hold a word that must stay out of the repository:", file=sys.stderr)
        for h in hits[:40]:
            print(f"  {h}", file=sys.stderr)
        if len(hits) > 40:
            print(f"  … and {len(hits) - 40} more", file=sys.stderr)
        print("Take it out (name people by role), then try again.", file=sys.stderr)
        return 1
    print(f"private-words: clean ({len(listed)} word(s) checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
