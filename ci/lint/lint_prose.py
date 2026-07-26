#!/usr/bin/env python3
"""Checks the repository prose style rules.

Rule 1: no em dashes anywhere in tracked text files.
Rule 2: no semicolons in Markdown prose. Fenced code blocks and
inline code spans are exempt, since they quote code or oracle
output verbatim.

docs/execution-plan.md and the evaluation doc predate these rules
and are exempt, as is everything under vectors/upstream/, which
holds third-party material stored verbatim.
"""

import re
import subprocess
import sys

TEXT_SUFFIXES = (".md", ".py", ".sh", ".yml", ".yaml", ".toml", ".txt")
EXEMPT = {
    "docs/execution-plan.md",
    "docs/bitcoin-script-successor-evaluation.md",
}

INLINE_CODE = re.compile(r"`[^`]*`")


def tracked_files():
    out = subprocess.run(
        ["git", "ls-files"], check=True, capture_output=True, text=True
    ).stdout
    return [
        f
        for f in out.splitlines()
        if f.endswith(TEXT_SUFFIXES)
        and f not in EXEMPT
        and not f.startswith("vectors/upstream/")
    ]


def main():
    problems = []
    for path in tracked_files():
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        in_fence = False
        for lineno, line in enumerate(lines, start=1):
            if "\u2014" in line:
                problems.append(f"{path}:{lineno}: em dash in prose")
            if not path.endswith(".md"):
                continue
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            prose = INLINE_CODE.sub("", line)
            if ";" in prose:
                problems.append(f"{path}:{lineno}: semicolon in Markdown prose")
    for problem in problems:
        print(problem)
    if problems:
        print(f"lint_prose: {len(problems)} problem(s) found", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
