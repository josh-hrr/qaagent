"""Pull acceptance criteria out of a ticket description.

Deliberately heuristic. Nobody writes tickets to a schema, so this recognises the
shapes people actually use and reports honestly when it finds nothing — a ticket
with no stated criteria is a real finding, not a parser failure. Screen 06 raises
it as an ambiguity rather than inventing criteria to cover.

Order matters: an explicit "Acceptance criteria" heading wins over loose AC-1
labels, which win over a bare checklist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Headings people actually write:
#   "## Acceptance criteria"      "**Acceptance Criteria:**"
#   "### **Requirements**"        "Success criteria:"
#
# The markdown hashes and the bold markers can BOTH be present — Linear's editor
# emits "### **Requirements**" routinely — so neither is exclusive of the other.
# `accep\w*` stops at "accep" on purpose — the misspelling seen in real tickets
# is "Accepance", which drops the 't' rather than mangling what follows it.
# Requiring " criteria" after keeps it from matching unrelated words.
HEADING_RE = re.compile(
    r"^\s{0,3}"
    r"(?:#{1,6}\s*)?"
    r"(?:\*{1,2}\s*)?"
    r"(?:accep\w*\s+criteria|success\s+criteria|acceptance|requirements?|criteria)"
    r"\s*:?\s*"
    r"(?:\*{1,2}\s*)?:?\s*$",
    re.IGNORECASE,
)
# Any markdown heading, used to find where a section ends.
ANY_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")
# "- item", "* item", "1. item", "- [ ] item"
LIST_ITEM_RE = re.compile(r"^\s{0,6}(?:[-*+]|\d{1,2}[.)])\s+(?:\[[ xX]\]\s*)?(?P<text>\S.*)$")
# "AC-1: ...", "AC1 – ...", "AC 2) ..."
LABELLED_RE = re.compile(
    r"^\s{0,6}(?:[-*+]\s+)?(?P<key>AC[-\s]?\d{1,2})\s*[:.)–—-]\s*(?P<text>\S.*)$",
    re.IGNORECASE,
)
CHECKBOX_RE = re.compile(r"^\s{0,6}[-*+]\s+\[[ xX]\]\s*(?P<text>\S.*)$")


@dataclass(frozen=True)
class Criterion:
    key: str
    text: str


def _clean(text: str) -> str:
    # Strip markdown emphasis and trailing punctuation noise, keep the sentence.
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"[*_`]", "", text)
    return text.strip().rstrip(";")


def _normalise_key(raw: str) -> str:
    """`AC1`, `AC 2`, `ac-03` all become `AC-1`, `AC-2`, `AC-3`."""
    match = re.match(r"AC[\s-]?0*(\d{1,2})", raw.strip(), re.IGNORECASE)
    return f"AC-{match.group(1)}" if match else raw.strip().upper()


def _labelled(lines: list[str]) -> list[Criterion]:
    found = []
    for line in lines:
        match = LABELLED_RE.match(line)
        if match:
            found.append(
                Criterion(key=_normalise_key(match.group("key")), text=_clean(match.group("text")))
            )
    return found


def _section_after_heading(lines: list[str]) -> list[str]:
    """Lines belonging to an acceptance-criteria section, if there is one."""
    start = None
    for index, line in enumerate(lines):
        if HEADING_RE.match(line):
            start = index + 1
            break
    if start is None:
        return []

    section = []
    for line in lines[start:]:
        # A following heading ends the section; blank lines do not.
        if ANY_HEADING_RE.match(line) or HEADING_RE.match(line):
            break
        section.append(line)
    return section


def extract_criteria(description: str | None) -> list[Criterion]:
    """Best-effort list of acceptance criteria. Empty list means none found."""
    if not description or not description.strip():
        return []

    lines = description.splitlines()

    # 1. An explicit section wins.
    section = _section_after_heading(lines)
    if section:
        labelled = _labelled(section)
        if labelled:
            return labelled
        items = [
            Criterion(key=f"AC-{i + 1}", text=_clean(m.group("text")))
            for i, m in enumerate(filter(None, (LIST_ITEM_RE.match(line) for line in section)))
        ]
        if items:
            return items
        # A section written as prose: treat each non-empty line as a criterion.
        prose = [_clean(line) for line in section if line.strip()]
        if prose:
            return [Criterion(key=f"AC-{i + 1}", text=t) for i, t in enumerate(prose)]

    # 2. AC-n labels anywhere in the body.
    labelled = _labelled(lines)
    if labelled:
        return labelled

    # 3. A checklist anywhere — teams often use one without a heading.
    checkboxes = [
        Criterion(key=f"AC-{i + 1}", text=_clean(m.group("text")))
        for i, m in enumerate(filter(None, (CHECKBOX_RE.match(line) for line in lines)))
    ]
    if checkboxes:
        return checkboxes

    return []
