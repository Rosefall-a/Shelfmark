#!/usr/bin/env python3
"""Redact common credentials and bearer tokens from operator-facing logs."""

from __future__ import annotations

import re
import sys

PATTERNS = (
    (
        re.compile(r"(postgres(?:ql)?(?:\+[-\w]+)?://[^:/\s]+:)[^@\s]+(@)", re.IGNORECASE),
        r"\1REDACTED\2",
    ),
    (
        re.compile(
            r"(\b(?:password|passwd|secret|token|api[_-]?key|client[_-]?secret|"
            r"webhook(?:[_-]?secret)?|private[_-]?key|smtp[_-]?(?:password|secret)|"
            r"authorization)\b\s*[:=]\s*)(?:Bearer\s+)?[^\s,;]+",
            re.IGNORECASE,
        ),
        r"\1REDACTED",
    ),
    (
        re.compile(
            r"((?:[\"'])(?:password|passwd|secret|token|api[_-]?key|client[_-]?secret|"
            r"webhook(?:[_-]?secret)?|private[_-]?key|smtp[_-]?(?:password|secret))"
            r"(?:[\"'])\s*:\s*[\"'])[^\"']*(\")",
            re.IGNORECASE,
        ),
        r"\1REDACTED\2",
    ),
)


def redact(line: str) -> str:
    for pattern, replacement in PATTERNS:
        line = pattern.sub(replacement, line)
    return line


def main() -> int:
    for line in sys.stdin:
        sys.stdout.write(redact(line))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
