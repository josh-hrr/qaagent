"""Turn a run's test cases into the file a tester actually uses.

Two audiences, one set of rows: a CSV that imports into a test-management tool
or opens in Excel, and Markdown that reads well in a pull request or a wiki.
Everything a reviewer can choose — columns, which cases, how steps are laid
out — is applied here, so the preview in the dialog and the downloaded file
come from the same code and cannot drift apart.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date

from .models import Run, TestCase, TestCaseStatus

# Excel on Windows needs the BOM to read UTF-8, and CRLF to avoid one long
# line. Both are wrong for a git diff, which is what the Markdown export is for.
BOM = "\ufeff"
CSV_NEWLINE = "\r\n"

# How many cases the preview renders before it says "… N more".
PREVIEW_CASES = 2


@dataclass(frozen=True)
class Column:
    key: str
    header: str
    required: bool = False


# Order matters: this is the order of the columns in every file, and it reads
# the way a tester works down a case — what it is, what it needs, what to do.
COLUMNS: list[Column] = [
    Column("id", "testcase#", required=True),
    Column("status", "status"),
    Column("priority", "priority"),
    Column("type", "test_type"),
    Column("title", "test_title", required=True),
    Column("description", "test_description"),
    Column("preconditions", "preconditions"),
    Column("steps", "test_steps"),
    Column("expected", "expected_result"),
    Column("actual", "actual_result"),
    Column("traces", "traces_to"),
    Column("suite", "suite"),
    Column("ticket", "ticket"),
    Column("commit", "commit"),
]
COLUMN_KEYS = [c.key for c in COLUMNS]
REQUIRED_KEYS = [c.key for c in COLUMNS if c.required]
# What the dialog opens with: the columns a manual tester fills in during a run.
DEFAULT_COLUMNS = ["id", "status", "priority", "title", "description", "steps", "expected", "actual"]

FORMATS = ["csv", "md"]
LAYOUTS = ["table", "sections"]
SCOPES = ["all", "selected", "approved"]
OPTION_KEYS = ["numbered_steps", "blank_actual", "run_header"]
DEFAULT_OPTIONS = {"numbered_steps": True, "blank_actual": True, "run_header": False}


@dataclass
class ExportSettings:
    file_format: str = "csv"
    layout: str = "table"
    scope: str = "all"
    columns: list[str] = field(default_factory=lambda: list(DEFAULT_COLUMNS))
    case_numbers: list[int] = field(default_factory=list)
    options: dict = field(default_factory=lambda: dict(DEFAULT_OPTIONS))

    @property
    def active(self) -> list[Column]:
        """The chosen columns in canonical order, with the required ones kept."""
        chosen = set(self.columns) | set(REQUIRED_KEYS)
        return [c for c in COLUMNS if c.key in chosen]

    def option(self, key: str) -> bool:
        return bool(self.options.get(key, DEFAULT_OPTIONS.get(key, False)))

    def as_preferences(self) -> dict:
        """What is worth remembering for next time — not which cases."""
        return {
            "fileFormat": self.file_format,
            "layout": self.layout,
            # "selected" belongs to one visit to one run, not to the user.
            "scope": self.scope if self.scope != "selected" else "all",
            "columns": [c.key for c in self.active],
            "options": {key: self.option(key) for key in OPTION_KEYS},
        }


# --- rows -------------------------------------------------------------------


def select_cases(run: Run, settings: ExportSettings) -> list[TestCase]:
    cases = run.test_cases.all()
    if settings.scope == "approved":
        cases = cases.filter(status=TestCaseStatus.APPROVED)
    elif settings.scope == "selected":
        cases = cases.filter(number__in=settings.case_numbers or [])
    # A rejected case is one a reviewer threw out. Exporting it would put work
    # back into the tracker that somebody deliberately removed.
    return list(cases.exclude(status=TestCaseStatus.REJECTED))


def numbering_applies(settings: ExportSettings) -> bool:
    """False for the section layout, which writes steps as a real list — there
    is no single cell for the toggle to change."""
    return not (settings.file_format == "md" and settings.layout == "sections")


def _steps(case: TestCase, settings: ExportSettings) -> str:
    steps = [str(s).strip() for s in case.steps if str(s).strip()]
    if not steps:
        return ""
    if settings.option("numbered_steps"):
        return " ".join(f"{i}. {s}" for i, s in enumerate(steps, start=1))
    return "; ".join(steps)


def _status_label(status: str) -> str:
    return dict(TestCaseStatus.choices).get(status, status)


def _head_commit(run: Run) -> str:
    for entry in (run.pull_requests or []) + (run.branches or []):
        if entry.get("head_commit"):
            return entry["head_commit"]
    return ""


def value(case: TestCase, key: str, run: Run, settings: ExportSettings) -> str:
    return {
        "id": case.identifier,
        "status": _status_label(case.status),
        "priority": case.priority,
        "title": case.title,
        "description": case.description,
        "steps": _steps(case, settings),
        "expected": case.expected_result,
        # Blank by default: this column is for the tester to fill in while
        # running the case, not for us to guess at.
        "actual": case.actual_result or ("" if settings.option("blank_actual") else "Not run"),
        "type": case.test_type,
        "preconditions": case.preconditions,
        "traces": " · ".join(str(t) for t in case.traces_to),
        "suite": case.suite,
        "ticket": run.ticket_identifier,
        "commit": _head_commit(run)[:7],
    }.get(key, "")


# --- the optional run header -------------------------------------------------


def _source_line(run: Run) -> str:
    """Where the code came from: "core-api · PR #7 · head 9f2c1ab"."""
    pr = (run.pull_requests or [{}])[0] if run.pull_requests else {}
    branch = (run.branches or [{}])[0] if run.branches else {}
    parts = [pr.get("repository") or branch.get("repository") or ""]
    if pr.get("number"):
        parts.append(f"PR #{pr['number']}")
    elif branch.get("name"):
        parts.append(f"branch {branch['name']}")
    head = _head_commit(run)
    if head:
        parts.append(f"head {head[:7]}")
    return " · ".join(p for p in parts if p)


def _run_number(run: Run) -> int:
    return Run.objects.filter(ticket_linear_id=run.ticket_linear_id, pk__lte=run.pk).count()


def _coverage(run: Run) -> str:
    criteria = (run.snapshot or {}).get("criteria") or []
    if not criteria:
        return ""
    keys = {c["key"].upper() for c in criteria}
    traced = {
        match.upper()
        for traces in run.test_cases.values_list("traces_to", flat=True)
        for trace in traces
        for match in re.findall(r"\bAC-\d+\b", str(trace), re.I)
    }
    return f"{len(keys & traced)}/{len(keys)} acceptance criteria covered"


def _header_lines(run: Run, cases: list[TestCase]) -> list[str]:
    generated = (run.finished_at or run.created_at).date().isoformat()
    facts = [f"{len(cases)} cases", _coverage(run), f"generated {generated}"]
    return [
        f"{run.ticket_identifier} — {run.ticket_title}".strip(" —"),
        f"run #{_run_number(run)} · {_source_line(run)}".rstrip(" ·"),
        " · ".join(f for f in facts if f),
    ]


def filename(run: Run, settings: ExportSettings) -> str:
    extension = ".md" if settings.file_format == "md" else ".csv"
    identifier = run.ticket_identifier or f"run-{run.pk}"
    return f"{identifier}_test-cases_{date.today().isoformat()}{extension}"


# --- renderers --------------------------------------------------------------


def render_csv(run: Run, cases: list[TestCase], settings: ExportSettings) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator=CSV_NEWLINE, quoting=csv.QUOTE_MINIMAL)
    if settings.option("run_header"):
        for line in _header_lines(run, cases):
            writer.writerow([f"# {line}"])
        writer.writerow([])
    writer.writerow([c.header for c in settings.active])
    for case in cases:
        writer.writerow([value(case, c.key, run, settings) for c in settings.active])
    return buffer.getvalue()


def _md_cell(text: str) -> str:
    # A pipe would end the cell and a newline would end the row.
    cell = str(text).replace("|", "\\|").replace("\r\n", " ").replace("\n", " ").strip()
    return cell or " "


def render_markdown_table(run: Run, cases: list[TestCase], settings: ExportSettings) -> str:
    lines: list[str] = []
    if settings.option("run_header"):
        head = _header_lines(run, cases)
        lines += [f"# {head[0]}", "", f"> {head[1]}", f"> {head[2]}", ""]
    columns = settings.active
    lines.append("| " + " | ".join(c.header for c in columns) + " |")
    lines.append("|" + "|".join("---" for _ in columns) + "|")
    for case in cases:
        lines.append("| " + " | ".join(_md_cell(value(case, c.key, run, settings)) for c in columns) + " |")
    return "\n".join(lines) + "\n"


def render_markdown_sections(run: Run, cases: list[TestCase], settings: ExportSettings) -> str:
    lines: list[str] = []
    if settings.option("run_header"):
        head = _header_lines(run, cases)
        lines += [f"# {head[0]}", "", f"> {head[1]} · {head[2]}", ""]
    for case in cases:
        lines += [f"## {case.identifier} — {case.title}", ""]
        for column in settings.active:
            if column.key in ("id", "title"):
                continue
            if column.key == "steps":
                steps = [str(s).strip() for s in case.steps if str(s).strip()]
                lines += ["**Test steps**", ""]
                lines += [f"{i}. {s}" for i, s in enumerate(steps, start=1)] or ["_(none)_"]
                lines.append("")
                continue
            text = value(case, column.key, run, settings)
            lines += [f"**{column.header}:** {text or '_(blank)_'}", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def render(run: Run, cases: list[TestCase], settings: ExportSettings) -> str:
    """The document as text — what the preview shows and what .csv/.md hold."""
    if settings.file_format == "md" and settings.layout == "sections":
        return render_markdown_sections(run, cases, settings)
    if settings.file_format == "md":
        return render_markdown_table(run, cases, settings)
    return render_csv(run, cases, settings)


def build(run: Run, cases: list[TestCase], settings: ExportSettings) -> tuple[bytes, str]:
    """The bytes to download, and their content type."""
    if settings.file_format == "md":
        return render(run, cases, settings).encode("utf-8"), "text/markdown; charset=utf-8"
    return (BOM + render_csv(run, cases, settings)).encode("utf-8"), "text/csv; charset=utf-8"


def preview(run: Run, cases: list[TestCase], settings: ExportSettings) -> str:
    """The first few cases, rendered exactly as the file will render them."""
    shown = cases[:PREVIEW_CASES]
    text = render(run, shown, settings)
    remaining = len(cases) - len(shown)
    if remaining > 0:
        unit = "cases" if settings.file_format == "md" and settings.layout == "sections" else "rows"
        text = text.rstrip("\n") + f"\n\n… {remaining} more {unit}\n"
    return text
