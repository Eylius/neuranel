#!/usr/bin/env python
from __future__ import annotations

import re
import subprocess
import sys


PATTERNS = [
    (re.compile(r"ghp_[A-Za-z0-9]{36,}"), "GitHub token"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "GitHub fine-grained token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key"),
    (re.compile(r"ASIA[0-9A-Z]{16}"), "AWS temporary access key"),
    (re.compile(r"AIza[0-9A-Za-z_-]{35}"), "Google API key"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "OpenAI key"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "Private key block"),
    (re.compile(r"(?i)aws_secret_access_key\\s*[:=]\\s*['\\\"]?[A-Za-z0-9/+=]{16,}"), "AWS secret key"),
    (re.compile(r"(?i)(api_key|secret|token|password)\\s*[:=]\\s*['\\\"][^'\\\"]{8,}['\\\"]"), "Generic secret"),
]


def _run_git(args: list[str]) -> bytes:
    return subprocess.check_output(["git"] + args)


def _staged_files() -> list[str]:
    data = _run_git(["diff", "--cached", "--name-only", "-z"])
    items = [part for part in data.decode("utf-8", "replace").split("\0") if part]
    return items


def _read_staged(path: str) -> bytes:
    try:
        return _run_git(["show", f":{path}"])
    except subprocess.CalledProcessError:
        return b""


def _is_binary(data: bytes) -> bool:
    if not data:
        return False
    return b"\0" in data


def main() -> int:
    violations: list[str] = []
    for path in _staged_files():
        data = _read_staged(path)
        if _is_binary(data):
            continue
        text = data.decode("utf-8", "replace")
        for pattern, label in PATTERNS:
            if pattern.search(text):
                violations.append(f"{path}: {label}")
                break

    if violations:
        print("Secret scan blocked the commit. Potential secrets found:")
        for item in violations:
            print(f" - {item}")
        print("If this is a false positive, remove the secret or use a safer placeholder.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
