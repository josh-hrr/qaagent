"""Execute one run end to end: ticket → scope → changes → generate → cross-check.

Runs inside the task worker, never in a web request. Every stage writes
progress to the database so the run screen can poll it, and every failure
lands on the run with a code the UI can explain.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from connections.azure import AzureError
from connections.linear import LinearError
from connections.models import Connection, DiffScopeStrategy, Provider
from tickets.criteria import extract_criteria
from tickets.linear_issues import fetch_issue

from .agent import AgentContext, AgentError, RunCancelled, run_agent
from .azure_code import CodeReader, PullRequestChanges
from .models import (
    Ambiguity,
    FileRead,
    FileSource,
    Finding,
    Priority,
    Run,
    RunEvent,
    RunStatus,
    Stage,
    TestCase,
    TestCaseStatus,
)
from .redaction import redact
from .scope import snapshot_hash, unified_diff

log = logging.getLogger(__name__)

# Keep the first prompt to a size a run can afford. Past this, later files are
# listed by path and the agent can fetch the ones it needs.
MAX_DIFF_CHARS_IN_PROMPT = 60_000


class PipelineError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# --- helpers ---------------------------------------------------------------


def _event(run: Run, stage: str, message: str) -> None:
    RunEvent.objects.create(run=run, stage=stage, message=message[:500])


def _enter(run: Run, stage: str) -> None:
    run.refresh_from_db(fields=["cancel_requested"])
    if run.cancel_requested:
        raise RunCancelled()
    run.stage = stage
    run.save(update_fields=["stage"])


# --- stages ----------------------------------------------------------------


def _fetch_ticket(run: Run):
    linear = Connection.objects.filter(provider=Provider.LINEAR).first()
    if linear is None:
        raise PipelineError("linear_not_connected", "Linear is not connected.")

    issue = fetch_issue(linear.credential, run.ticket_linear_id)
    criteria = extract_criteria(issue.description)

    snapshot = {
        "identifier": issue.identifier,
        "title": issue.title,
        "description": issue.description,
        "criteria": [{"key": c.key, "text": c.text} for c in criteria],
        "sub_issues": [{"identifier": s.identifier, "title": s.title} for s in issue.sub_issues],
        "pull_request_urls": [p.url for p in issue.pull_requests],
        "linear_updated_at": issue.updated_at,
        "team_name": issue.team_name,
        "fetched_at": timezone.now().isoformat(),
    }
    run.ticket_identifier = issue.identifier
    run.ticket_title = issue.title[:300]
    run.ticket_url = issue.url
    run.snapshot = snapshot
    run.snapshot_hash = snapshot_hash(snapshot)
    run.save(update_fields=["ticket_identifier", "ticket_title", "ticket_url", "snapshot", "snapshot_hash"])

    _event(
        run,
        Stage.FETCH_TICKET,
        f"{issue.identifier}: {len(criteria)} acceptance criteria, {len(issue.sub_issues)} sub-issues, "
        f"{issue.comment_count} comments, {len(issue.pull_requests)} pull request link(s)",
    )
    return issue, criteria


def _pull_request_scopes(run: Run, issue, source: Connection, connected: set[str]):
    """Linked pull requests that can be read, plus the ones skipped and why."""
    used, skipped, scoped = [], [], []
    excluded = {url for url in (run.excluded_pull_requests or [])}
    for ref in issue.pull_requests:
        if ref.url in excluded:
            skipped.append({"url": ref.url, "reason": "unticked before the run"})
            _event(run, Stage.RESOLVE_SCOPE, f"skipped {ref.url}: unticked before the run")
            continue
        if ref.provider != "azure_devops" or not ref.number:
            skipped.append({"url": ref.url, "reason": "not an Azure DevOps pull request"})
            continue
        if ref.repository.lower() not in connected:
            skipped.append({"url": ref.url, "reason": f"repository {ref.repository} is not connected"})
            continue

        reader = CodeReader(ref.organization, ref.project, ref.repository, source.credential)
        info = reader.pull_request(ref.number)
        if info.status == "abandoned":
            # Abandoned work would pollute the diff with code that never shipped.
            skipped.append({"url": ref.url, "reason": "abandoned"})
            _event(run, Stage.RESOLVE_SCOPE, f"skipped PR #{ref.number} in {ref.repository}: abandoned")
            continue

        used.append(
            {
                "url": ref.url,
                "repository": ref.repository,
                "organization": ref.organization,
                "project": ref.project,
                "number": info.number,
                "title": info.title,
                "status": info.status,
                "source_ref": info.source_ref.removeprefix("refs/heads/"),
                "target_ref": info.target_ref.removeprefix("refs/heads/"),
                "head_commit": info.head_commit,
                "base_commit": info.base_commit,
            }
        )
        scoped.append((reader, reader.changes(info)))
        _event(
            run,
            Stage.RESOLVE_SCOPE,
            f"PR #{info.number} in {ref.repository} ({info.status}) · merge base {info.base_commit[:7]} → head {info.head_commit[:7]}",
        )
    return used, skipped, scoped


def branch_pattern(identifier: str) -> re.Pattern[str]:
    """Matches the ticket id as a whole token: TES-8 matches "josue/tes-8-login",
    not "TES-80" or "XTES-8". Case-insensitive, as Linear suggests lowercase names."""
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(identifier)}(?![0-9])", re.IGNORECASE)


def _branch_scopes(run: Run, issue, source: Connection):
    """Branches named after the ticket, in each connected repository."""
    pattern = branch_pattern(issue.identifier)
    suggested = (getattr(issue, "branch_name", "") or "").lower()
    used, skipped, scoped = [], [], []

    for repo in source.repositories.filter(selected=True):
        reader = CodeReader(source.organization_name, repo.project_name, repo.name, source.credential)
        matches = [name for name, _ in reader.branches() if pattern.search(name) or name.lower() == suggested]
        if len(matches) > 1:
            # Linear's suggested name settles a tie. Otherwise guessing would
            # mean writing tests for code that may not be this ticket's.
            exact = [name for name in matches if name.lower() == suggested]
            if len(exact) != 1:
                skipped.append({"repository": repo.name, "reason": f"several branches match: {', '.join(matches[:5])}"})
                _event(run, Stage.RESOLVE_SCOPE, f"{repo.name}: several branches match {issue.identifier}, skipped")
                continue
            matches = exact
        if not matches:
            continue

        branch = matches[0]
        default = repo.default_branch.removeprefix("refs/heads/") or "main"
        changes = reader.branch_changes(branch, default)
        if changes.info.ahead_count == 0 or not changes.files:
            skipped.append({"repository": repo.name, "reason": f"branch {branch} has no changes of its own (probably merged, link the PR)"})
            _event(run, Stage.RESOLVE_SCOPE, f"{repo.name}: branch {branch} has nothing beyond {default}, probably merged")
            continue

        used.append(
            {
                "repository": repo.name,
                "name": branch,
                "target_ref": default,
                "head_commit": changes.info.head_commit,
                "base_commit": changes.info.base_commit,
                "ahead_count": changes.info.ahead_count,
                "url": f"{repo.web_url}?version=GB{quote(branch)}" if repo.web_url else "",
            }
        )
        scoped.append((reader, changes))
        _event(
            run,
            Stage.RESOLVE_SCOPE,
            f"branch {branch} in {repo.name}: {changes.info.ahead_count} commit(s) ahead of {default} · merge base {changes.info.base_commit[:7]}",
        )
    return used, skipped, scoped


def _resolve_scope(run: Run, issue) -> tuple[Connection, list[tuple[CodeReader, PullRequestChanges]]]:
    source = Connection.objects.filter(provider=Provider.AZURE_DEVOPS).first()
    if source is None:
        raise PipelineError("source_not_connected", "No Azure DevOps connection. Connect a repository first.")

    run.diff_scope_strategy = source.diff_scope_strategy
    connected = {name.lower() for name in source.repositories.filter(selected=True).values_list("name", flat=True)}

    # The configured rule goes first and the other is the fallback. Manual
    # base/head picking is not built, so it behaves like linked PR.
    order = ["branch", "pr"] if source.diff_scope_strategy == DiffScopeStrategy.BRANCH_NAME else ["pr", "branch"]
    prs, skipped_prs, branches, skipped_branches, scoped = [], [], [], [], []
    for kind in order:
        if kind == "pr":
            prs, skipped_prs, found = _pull_request_scopes(run, issue, source, connected)
        else:
            branches, skipped_branches, found = _branch_scopes(run, issue, source)
        if found:
            scoped = found
            break

    # Only one kind is ever used: the loop stops at the first that yields code.
    run.pull_requests = prs
    run.branches = branches
    run.skipped_pull_requests = skipped_prs + skipped_branches
    run.save(update_fields=["diff_scope_strategy", "pull_requests", "branches", "skipped_pull_requests"])

    if scoped:
        return source, scoped

    reasons = "; ".join(f"{s.get('url') or s.get('repository')} ({s['reason']})" for s in run.skipped_pull_requests)
    if skipped_prs:
        raise PipelineError(
            "no_usable_pull_request",
            f"Every pull request on this ticket was skipped and no branch named {issue.identifier} could be used: {reasons}",
        )
    raise PipelineError(
        "no_pull_request",
        f"No pull request is linked on {issue.identifier} and no branch named after it has changes."
        + (f" {reasons}." if reasons else "")
        + " Paste the PR link into a comment on the ticket, or put the ticket ID in the branch name.",
    )


def _read_changes(run: Run, scoped) -> tuple[str, int]:
    """Record every changed file and build the diff section of the prompt."""
    sections, redactions, budget_used = [], 0, 0
    for reader, changes in scoped:
        for changed in changes.files:
            if changed.skipped_reason:
                FileRead.objects.create(
                    run=run, repository=reader.repository, path=changed.path, source=FileSource.DIFF,
                    change_type=changed.change_type, reason=f"skipped: {changed.skipped_reason.replace('_', ' ')}",
                )
                continue

            diff, added, removed = unified_diff(changed)
            masked, count = redact(diff)
            redactions += count
            FileRead.objects.create(
                run=run, repository=reader.repository, path=changed.path, source=FileSource.DIFF,
                change_type=changed.change_type, lines_added=added, lines_removed=removed,
            )

            header = f"### {reader.repository}{changed.path} ({changed.change_type}, +{added} −{removed})"
            if budget_used + len(masked) > MAX_DIFF_CHARS_IN_PROMPT:
                sections.append(f"{header}\n(diff omitted for size — use read_file if this file matters)")
                continue
            budget_used += len(masked)
            sections.append(f"{header}\n```diff\n{masked}\n```")

    file_count = sum(len(c.files) for _, c in scoped)
    _event(
        run, Stage.READ_CHANGES,
        f"{file_count} changed file(s), {redactions} secret-shaped value(s) masked before sending",
    )
    return "\n\n".join(sections), redactions


def _clarifications(run: Run) -> list[dict]:
    """Answers reviewers gave on earlier runs of the same ticket, newest first."""
    answered = (
        Ambiguity.objects.filter(run__ticket_linear_id=run.ticket_linear_id, run__created_at__lt=run.created_at)
        .exclude(answer="")
        .order_by("-answered_at")
    )
    seen, result = set(), []
    for item in answered[:30]:
        key = item.question.strip().lower()
        if key not in seen:
            seen.add(key)
            result.append({"question": item.question, "answer": item.answer})
    return result


def _prompt(issue, criteria, diff_text: str, pull_requests: list[dict], clarifications: list[dict] | None = None) -> str:
    criteria_text = (
        "\n".join(f"- {c.key}: {c.text}" for c in criteria)
        if criteria
        else "(No formal acceptance criteria found. Infer intent from the description, and raise what is unclear as ambiguities.)"
    )
    prs = "\n".join(f"- PR #{p['number']} in {p['repository']}: {p['title']} ({p['status']})" for p in pull_requests)
    prs = prs or "(none linked — the diff comes from a branch named after the ticket)"
    sub_issues = "\n".join(f"- {s.identifier}: {s.title}" for s in issue.sub_issues) or "(none)"
    description = redact(issue.description or "")[0] or "(empty)"
    answers = "\n".join(
        f"- Q: {redact(c['question'])[0]}\n  A: {redact(c['answer'])[0]}" for c in clarifications or []
    )
    clarification_block = f"\n<clarifications>\n{answers}\n</clarifications>\n" if answers else ""

    return f"""<ticket>
Identifier: {issue.identifier}
Title: {issue.title}

Description:
{description}

Acceptance criteria:
{criteria_text}

Sub-issues:
{sub_issues}
</ticket>
{clarification_block}
<pull_requests>
{prs}
</pull_requests>

<diff>
{diff_text or "(no text changes)"}
</diff>

Write the test cases, findings and ambiguities for this change, then call submit_results."""


def _minutes(value) -> int | None:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None
    return minutes if 0 < minutes <= 600 else None


def _save_results(run: Run, result, criteria) -> None:
    with transaction.atomic():
        for index, case in enumerate(result.test_cases, start=1):
            TestCase.objects.create(
                run=run,
                number=index,
                title=case.get("title", "")[:300],
                description=case.get("description", ""),
                preconditions=case.get("preconditions", ""),
                steps=[str(s) for s in case.get("steps", [])],
                expected_result=case.get("expected_result", ""),
                priority=case.get("priority") if case.get("priority") in Priority.values else Priority.P2,
                test_type=case.get("test_type", "")[:30],
                status=TestCaseStatus.NEEDS_INFO if case.get("needs_info") else TestCaseStatus.DRAFT,
                traces_to=[str(t) for t in case.get("traces_to", [])],
                suite=str(case.get("suite", ""))[:120],
                estimate_minutes=_minutes(case.get("estimate_minutes")),
            )
        for finding in result.findings:
            Finding.objects.create(
                run=run,
                severity=finding.get("severity", "low"),
                title=finding.get("title", "")[:300],
                explanation=finding.get("explanation", ""),
                location=finding.get("location", "")[:500],
            )
        for ambiguity in result.ambiguities:
            Ambiguity.objects.create(
                run=run,
                kind=ambiguity.get("kind", "unspecified")[:20],
                question=ambiguity.get("question", "")[:500],
                explanation=ambiguity.get("explanation", ""),
                source=ambiguity.get("source", "")[:300],
                blocks_test_cases=[int(n) for n in ambiguity.get("blocks_test_cases", []) if str(n).isdigit()],
            )

    # Deterministic coverage check: no model call, just which criteria no test
    # case claims to cover. An uncovered criterion is exactly what a reviewer
    # should look at first.
    covered = {
        key.upper()
        for case in result.test_cases
        for trace in case.get("traces_to", [])
        for key in re.findall(r"\bAC-\d+\b", str(trace), re.I)
    }
    uncovered = [c.key for c in criteria if c.key.upper() not in covered]
    if criteria:
        _event(
            run, Stage.CROSS_CHECK,
            f"coverage: {len(criteria) - len(uncovered)}/{len(criteria)} acceptance criteria mapped"
            + (f" — not covered: {', '.join(uncovered)}" if uncovered else ""),
        )
    _event(
        run, Stage.CROSS_CHECK,
        f"{len(result.test_cases)} test cases, {len(result.findings)} findings, {len(result.ambiguities)} ambiguities",
    )


# --- entry point -----------------------------------------------------------


def execute(run_id: int) -> None:
    run = Run.objects.get(pk=run_id)
    if run.is_terminal:
        return

    run.status = RunStatus.RUNNING
    run.started_at = timezone.now()
    run.model = settings.LLM_MODEL
    run.cost_cap_usd = Decimal(str(settings.RUN_COST_CAP_USD))
    run.save(update_fields=["status", "started_at", "model", "cost_cap_usd"])

    try:
        _enter(run, Stage.FETCH_TICKET)
        issue, criteria = _fetch_ticket(run)

        _enter(run, Stage.RESOLVE_SCOPE)
        source, scoped = _resolve_scope(run, issue)

        _enter(run, Stage.READ_CHANGES)
        diff_text, _ = _read_changes(run, scoped)

        _enter(run, Stage.GENERATE)
        reader, changes = scoped[0]
        already = {f.path for _, c in scoped for f in c.files}
        context = AgentContext(
            reader=reader,
            head_commit=changes.info.head_commit,
            log_event=lambda message: _event(run, Stage.GENERATE, message),
            record_read=lambda record: FileRead.objects.create(
                run=run, repository=reader.repository, path=record.path,
                source=FileSource.AGENT, reason=record.reason[:500],
            ),
            should_cancel=lambda: Run.objects.filter(pk=run.pk, cancel_requested=True).exists(),
            already_read=already,
        )
        clarifications = _clarifications(run)
        if clarifications:
            _event(run, Stage.GENERATE, f"{len(clarifications)} answered question(s) from earlier runs included")
        result = run_agent(_prompt(issue, criteria, diff_text, run.pull_requests, clarifications), context)

        run.input_tokens = result.usage.input_tokens
        run.output_tokens = result.usage.output_tokens
        run.cache_read_tokens = result.usage.cache_read_tokens
        run.cache_write_tokens = result.usage.cache_write_tokens
        run.cost_usd = result.usage.cost_usd.quantize(Decimal("0.0001"))
        run.stopped_early = bool(result.stopped_early_reason)
        run.stopped_early_reason = result.stopped_early_reason
        # Explicit fields only: a bare save() would write back the stale
        # cancel_requested=False and silently undo a Cancel pressed mid-run.
        run.save(update_fields=[
            "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
            "cost_usd", "stopped_early", "stopped_early_reason",
        ])

        _enter(run, Stage.CROSS_CHECK)
        _save_results(run, result, criteria)

        run.status = RunStatus.SUCCEEDED
    except RunCancelled:
        run.status = RunStatus.CANCELLED
        _event(run, run.stage or Stage.FETCH_TICKET, "cancelled")
    except (PipelineError, AgentError, AzureError, LinearError) as exc:
        run.status = RunStatus.FAILED
        run.error_code = exc.code
        run.error_message = exc.message
        _event(run, run.stage or Stage.FETCH_TICKET, f"failed: {exc.message}")
    except Exception:  # noqa: BLE001 — the run must never be left "running" forever
        log.exception("Run %s crashed", run.pk)
        run.status = RunStatus.FAILED
        run.error_code = "internal_error"
        run.error_message = "Something went wrong on our side. The error has been logged."
        _event(run, run.stage or Stage.FETCH_TICKET, "failed: internal error")
    finally:
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_code", "error_message", "finished_at"])
