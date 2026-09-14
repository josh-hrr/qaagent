"""Turn fetched changes into something a model can read, and fingerprint tickets."""

from __future__ import annotations

import difflib
import hashlib
import json

from .azure_code import ChangedFile

# Enough surrounding lines to see what a change sits inside, without resending
# the whole file for a one-line edit.
DIFF_CONTEXT_LINES = 6


def unified_diff(changed: ChangedFile) -> tuple[str, int, int]:
    """Return ``(diff_text, lines_added, lines_removed)`` for one file."""
    before = (changed.base_content or "").splitlines()
    after = (changed.head_content or "").splitlines()
    lines = list(
        difflib.unified_diff(
            before,
            after,
            fromfile=f"a{changed.path}",
            tofile=f"b{changed.path}",
            n=DIFF_CONTEXT_LINES,
            lineterm="",
        )
    )
    added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    return "\n".join(lines), added, removed


def snapshot_hash(snapshot: dict) -> str:
    """Stable fingerprint of the parts of a ticket that affect tests.

    Keys are sorted so the same content always produces the same hash — an
    unsorted dict would make every comparison look like a change.
    """
    relevant = {
        "title": snapshot.get("title", ""),
        "description": snapshot.get("description", ""),
        "criteria": snapshot.get("criteria", []),
        "pull_requests": sorted(snapshot.get("pull_request_urls", [])),
    }
    encoded = json.dumps(relevant, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
