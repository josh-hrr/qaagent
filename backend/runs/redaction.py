"""Mask secret-shaped values before code leaves for the model.

Repositories contain credentials more often than anyone admits — a test key in
a fixture, a connection string in a config sample. Sending one to a third-party
model is a leak even if nothing is ever done with it.

This is a heuristic net, not a guarantee: it catches the common shapes and
the obvious assignments. It deliberately errs toward masking — a tester loses
nothing when an API key reads ``[REDACTED]``.
"""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

# Well-known token formats. Specific patterns first so the label is accurate.
_TOKEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("aws key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{20,}\b")),
    ("openai-style key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("linear key", re.compile(r"\blin_(?:api|oauth)_[A-Za-z0-9]{20,}\b")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    (
        "connection string",
        re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:[^\s@/]{3,}@", re.I),
    ),
]

# key = "value" style assignments where the key name says it is a secret.
_ASSIGNMENT = re.compile(
    r"""(?P<key>\b[\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key|client[_-]?secret)[\w.-]*\b)"""
    r"""(?P<sep>\s*[:=]\s*)"""
    r"""(?P<quote>["'])(?P<value>[^"'\n]{6,})(?P=quote)""",
    re.I,
)

# Values that are obviously placeholders, not secrets.
_PLACEHOLDER = re.compile(r"^(?:x+|\*+|<.*>|\$\{.*\}|changeme|your[_-].*|example.*|dummy.*|test|null|none|redacted)$", re.I)


def redact(text: str) -> tuple[str, int]:
    """Return ``(masked_text, count)``."""
    if not text:
        return text, 0

    count = 0

    def _mask_token(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return REDACTED

    for _, pattern in _TOKEN_PATTERNS:
        text = pattern.sub(_mask_token, text)

    def _mask_assignment(match: re.Match[str]) -> str:
        nonlocal count
        value = match.group("value")
        if value == REDACTED or _PLACEHOLDER.match(value.strip()):
            return match.group(0)
        count += 1
        q = match.group("quote")
        return f"{match.group('key')}{match.group('sep')}{q}{REDACTED}{q}"

    text = _ASSIGNMENT.sub(_mask_assignment, text)
    return text, count
