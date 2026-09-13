from unittest import skip
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from connections.linear import LinearError
from connections.models import (
    AuthMethod,
    Connection,
    DiffScopeStrategy,
    LinearTeam,
    Provider,
    Repository,
)

from .criteria import extract_criteria
from .linear_issues import LinearIssue, SubIssue, _parse_issue
from .pull_requests import PullRequestRef, deduplicate, extract_pull_requests
from .readiness import BLOCKED, OK, WARNING, assess

TEST_ENCRYPTION_KEY = "zqLxwEdiY2j8ta4ERsIrf2UPQgDSmRnRm6ZvCk5p_74="


def pr(repository="core-api", number=884, source="attachment") -> PullRequestRef:
    return PullRequestRef(
        provider="azure_devops", organization="acme", project="Core", repository=repository,
        number=number, url=f"https://dev.azure.com/acme/Core/_git/{repository}/pullrequest/{number}",
        source=source,
    )


def issue(**overrides) -> LinearIssue:
    defaults = dict(
        id="i1",
        identifier="ENG-2481",
        title="Refresh token rotation on silent re-auth",
        description="",
        url="https://linear.app/x/issue/ENG-2481",
        branch_name="josue/eng-2481-refresh-token-rotation",
        updated_at="2026-09-13T10:00:00Z",
        state_name="In Review",
        state_type="started",
        assignee_name="D. Okafor",
        team_key="ENG",
        team_name="Platform",
        comment_count=0,
        unresolved_comment_count=0,
        sub_issues=[],
        pull_requests=[],
    )
    defaults.update(overrides)
    return LinearIssue(**defaults)


class CriteriaExtractionTests(TestCase):
    def texts(self, description: str) -> list[str]:
        return [c.text for c in extract_criteria(description)]

    def keys(self, description: str) -> list[str]:
        return [c.key for c in extract_criteria(description)]

    def test_markdown_heading_with_a_bullet_list(self):
        description = """
Short summary of the change.

## Acceptance Criteria
- The client refreshes silently before expiry
- Each refresh rotates the token

## Notes
- not a criterion
"""
        self.assertEqual(
            self.texts(description),
            ["The client refreshes silently before expiry", "Each refresh rotates the token"],
        )

    def test_a_following_heading_ends_the_section(self):
        description = "## Acceptance criteria\n- one\n\n## Out of scope\n- two\n"
        self.assertEqual(self.texts(description), ["one"])

    def test_labelled_criteria_win_over_plain_list_items(self):
        description = """
### Acceptance criteria
- AC-1: Silent refresh happens before expiry
- AC-2: Replay is rejected
"""
        self.assertEqual(self.keys(description), ["AC-1", "AC-2"])

    def test_labels_are_found_without_any_heading(self):
        description = "Some preamble.\n\nAC1 - refresh works\nAC 2) replay fails\n"
        self.assertEqual(self.keys(description), ["AC-1", "AC-2"])
        self.assertEqual(self.texts(description), ["refresh works", "replay fails"])

    def test_checkbox_list_without_a_heading(self):
        description = "Plan:\n\n- [ ] Rotate on every refresh\n- [x] Revoke on logout\n"
        self.assertEqual(self.texts(description), ["Rotate on every refresh", "Revoke on logout"])

    def test_numbered_list_under_a_bold_heading(self):
        description = "**Acceptance criteria**\n1. Token rotates\n2. Reuse is detected\n"
        self.assertEqual(self.texts(description), ["Token rotates", "Reuse is detected"])

    def test_prose_section_becomes_one_criterion_per_line(self):
        description = "Acceptance criteria\nThe session must survive a reload.\n"
        self.assertEqual(self.texts(description), ["The session must survive a reload."])

    def test_markdown_emphasis_is_stripped(self):
        description = "## Acceptance criteria\n- **Must** rotate the `token`\n"
        self.assertEqual(self.texts(description), ["Must rotate the token"])

    def test_heading_with_both_hashes_and_bold(self):
        # Linear's editor emits this constantly: "### **Requirements**".
        description = "### **Requirements**\n- Token rotates\n- Replay is rejected\n"
        self.assertEqual(self.texts(description), ["Token rotates", "Replay is rejected"])

    def test_common_misspellings_of_acceptance_are_accepted(self):
        # "Accepance Criteria" is what a real ticket in this workspace says.
        for heading in ["**Accepance Criteria**", "## Acceptence criteria", "Acceptance Criteria:"]:
            with self.subTest(heading=heading):
                self.assertEqual(self.texts(f"{heading}\n- it works\n"), ["it works"])

    def test_bare_criteria_heading(self):
        self.assertEqual(self.texts("### Criteria\n- it works\n"), ["it works"])

    def test_a_heading_with_nothing_under_it_yields_nothing(self):
        self.assertEqual(extract_criteria("Some prose.\n\n### Requirements"), [])

    def test_no_criteria_is_an_empty_list_not_a_guess(self):
        for description in ["", None, "Just a sentence with no structure at all."]:
            with self.subTest(description=description):
                self.assertEqual(extract_criteria(description), [])

    def test_a_plain_bullet_list_alone_is_not_treated_as_criteria(self):
        # Most tickets contain bullets that are notes, not requirements.
        description = "Some context:\n- background one\n- background two\n"
        self.assertEqual(extract_criteria(description), [])


class ReadinessTests(TestCase):
    def assess(self, ticket, criteria=None, repositories=1, strategy=DiffScopeStrategy.LINKED_PR, connected=None):
        from .criteria import Criterion

        return assess(
            ticket,
            criteria if criteria is not None else [Criterion("AC-1", "does a thing")],
            repository_count=repositories,
            strategy=strategy,
            connected_repositories=connected if connected is not None else {"core-api"},
        )

    def check(self, readiness, key):
        return next(c for c in readiness.checks if c.key == key)

    def test_a_complete_ticket_is_ready(self):
        ready = self.assess(
            issue(pull_requests=[pr()])
        )
        self.assertEqual(ready.status, OK)

    def test_a_description_without_criteria_only_warns(self):
        # The common real-world case: prose, no formal AC section. The agent
        # infers intent and raises ambiguities rather than refusing to run.
        result = self.assess(issue(description="Make the session survive a reload."), criteria=[])
        self.assertEqual(self.check(result, "criteria").status, WARNING)
        self.assertNotEqual(result.status, BLOCKED)

    def test_an_empty_description_blocks(self):
        blocked = self.assess(issue(description=""), criteria=[])
        self.assertEqual(blocked.status, BLOCKED)
        self.assertEqual(self.check(blocked, "criteria").status, BLOCKED)

    def test_no_repository_blocks(self):
        blocked = self.assess(issue(), repositories=0)
        self.assertEqual(blocked.status, BLOCKED)
        self.assertEqual(self.check(blocked, "repository").status, BLOCKED)

    def test_missing_pull_request_warns_rather_than_blocks(self):
        # It falls back to branch matching, so the run can still happen.
        result = self.assess(issue())
        self.assertEqual(result.status, WARNING)
        self.assertEqual(self.check(result, "diff_scope").status, WARNING)

    def test_branch_strategy_is_satisfied_by_a_branch_name(self):
        result = self.assess(issue(), strategy=DiffScopeStrategy.BRANCH_NAME)
        self.assertEqual(self.check(result, "diff_scope").status, OK)

    def test_manual_strategy_never_complains_about_scope(self):
        result = self.assess(issue(), strategy=DiffScopeStrategy.MANUAL)
        self.assertEqual(self.check(result, "diff_scope").status, OK)

    @skip("Unresolved-comments check is disabled in readiness.assess — see the note there.")
    def test_unresolved_comments_warn(self):
        result = self.assess(
            issue(
                comment_count=5,
                unresolved_comment_count=3,
                pull_requests=[pr()],
            )
        )
        self.assertEqual(self.check(result, "comments").status, WARNING)
        self.assertIn("3", self.check(result, "comments").detail)

    def test_a_closed_ticket_warns(self):
        result = self.assess(
            issue(
                state_type="completed",
                state_name="Done",
                pull_requests=[pr()],
            )
        )
        self.assertEqual(self.check(result, "state").status, WARNING)

    def test_an_open_ticket_has_no_state_check(self):
        result = self.assess(issue())
        self.assertFalse(any(c.key == "state" for c in result.checks))

    def test_blocked_wins_over_warning(self):
        result = self.assess(issue(description="", unresolved_comment_count=2), criteria=[])
        self.assertEqual(result.status, BLOCKED)


@override_settings(CREDENTIAL_ENCRYPTION_KEY=TEST_ENCRYPTION_KEY)
class TicketListApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("dev@example.com")
        self.client.force_login(self.user)
        self.url = reverse("tickets:list")

    def connect_linear(self, selected=True):
        connection = Connection.objects.create(
            provider=Provider.LINEAR, auth_method=AuthMethod.API_KEY, organization_name="Acme"
        )
        connection.set_credential("lin_api_x")
        connection.save()
        LinearTeam.objects.create(
            connection=connection, linear_id="team_eng", key="ENG", name="Platform", selected=selected
        )
        return connection

    def connect_source(self, repositories=1):
        connection = Connection.objects.create(
            provider=Provider.AZURE_DEVOPS, diff_scope_strategy=DiffScopeStrategy.LINKED_PR
        )
        connection.set_credential("pat")
        connection.save()
        for index in range(repositories):
            Repository.objects.create(
                connection=connection, external_id=f"r{index}",
                name="core-api" if index == 0 else f"repo-{index}", selected=True
            )
        return connection

    def test_requires_linear(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "linear_not_connected")

    def test_requires_a_selected_team(self):
        self.connect_linear(selected=False)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "no_teams_selected")

    def test_returns_tickets_with_criteria_and_readiness(self):
        self.connect_linear()
        self.connect_source()
        sample = issue(
            description="## Acceptance criteria\n- Rotates the token\n- Rejects a replay\n",
            pull_requests=[pr()],
        )
        with patch("tickets.views.fetch_issues", return_value=[sample]):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        ticket = response.json()["tickets"][0]
        self.assertEqual(ticket["identifier"], "ENG-2481")
        self.assertEqual(len(ticket["criteria"]), 2)
        self.assertEqual(ticket["readiness"]["status"], OK)

    def test_open_tickets_sort_before_finished_ones(self):
        self.connect_linear()
        self.connect_source()
        issues = [
            issue(id="a", identifier="ENG-1", state_type="completed", updated_at="2026-09-13T12:00:00Z"),
            issue(id="b", identifier="ENG-2", state_type="backlog", updated_at="2026-09-13T11:00:00Z"),
            issue(id="c", identifier="ENG-3", state_type="started", updated_at="2026-09-13T09:00:00Z"),
        ]
        with patch("tickets.views.fetch_issues", return_value=issues):
            response = self.client.get(self.url)
        order = [t["identifier"] for t in response.json()["tickets"]]
        self.assertEqual(order, ["ENG-3", "ENG-2", "ENG-1"])

    def test_newest_first_within_a_state(self):
        self.connect_linear()
        self.connect_source()
        issues = [
            issue(id="a", identifier="ENG-1", state_type="started", updated_at="2026-09-10T10:00:00Z"),
            issue(id="b", identifier="ENG-2", state_type="started", updated_at="2026-09-13T10:00:00Z"),
        ]
        with patch("tickets.views.fetch_issues", return_value=issues):
            response = self.client.get(self.url)
        self.assertEqual([t["identifier"] for t in response.json()["tickets"]], ["ENG-2", "ENG-1"])

    def test_without_a_repository_every_ticket_is_blocked(self):
        self.connect_linear()
        sample = issue(description="## Acceptance criteria\n- Rotates\n")
        with patch("tickets.views.fetch_issues", return_value=[sample]):
            response = self.client.get(self.url)
        body = response.json()
        self.assertEqual(body["workspace"]["repositoryCount"], 0)
        self.assertEqual(body["tickets"][0]["readiness"]["status"], BLOCKED)

    def test_a_revoked_key_is_recorded_on_the_connection(self):
        connection = self.connect_linear()
        self.connect_source()
        with patch(
            "tickets.views.fetch_issues",
            side_effect=LinearError("invalid_key", "Linear rejected that API key."),
        ):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)
        connection.refresh_from_db()
        self.assertEqual(connection.status, "error")
        self.assertIn("rejected", connection.last_error)

    def test_sub_issues_and_comment_counts_are_exposed(self):
        self.connect_linear()
        self.connect_source()
        sample = issue(
            description="AC-1: works\n",
            sub_issues=[SubIssue("ENG-2482", "Add audit event")],
            comment_count=4,
            unresolved_comment_count=1,
        )
        with patch("tickets.views.fetch_issues", return_value=[sample]):
            ticket = self.client.get(self.url).json()["tickets"][0]
        self.assertEqual(ticket["subIssues"][0]["identifier"], "ENG-2482")
        self.assertEqual(ticket["unresolvedCommentCount"], 1)

    def test_requires_a_session(self):
        self.client.logout()
        self.assertIn(self.client.get(self.url).status_code, (401, 403))


class PullRequestExtractionTests(TestCase):
    AZURE = "https://dev.azure.com/acme/Core%20Platform/_git/core-api/pullrequest/12"

    def test_azure_devops_link(self):
        (ref,) = extract_pull_requests(f"Fix is in {self.AZURE}", "comment")
        self.assertEqual(
            (ref.provider, ref.organization, ref.project, ref.repository, ref.number),
            ("azure_devops", "acme", "Core Platform", "core-api", 12),
        )

    def test_markdown_escaped_underscore_is_still_found(self):
        # Seen in a real ticket: Linear stores "\_git" in comment markdown.
        escaped = r"https://dev.azure.com/acme/Core/\_git/core-api/pullrequest/7"
        (ref,) = extract_pull_requests(escaped, "comment")
        self.assertEqual(ref.number, 7)
        self.assertIn("/_git/", ref.url)

    def test_markdown_link_syntax(self):
        text = f"See [the PR]({self.AZURE}) for details."
        self.assertEqual(len(extract_pull_requests(text, "comment")), 1)

    def test_legacy_visualstudio_host(self):
        (ref,) = extract_pull_requests(
            "https://acme.visualstudio.com/Core/_git/core-api/pullrequest/3", "comment"
        )
        self.assertEqual((ref.organization, ref.number), ("acme", 3))
        self.assertTrue(ref.url.startswith("https://dev.azure.com/acme/"))

    def test_github_link(self):
        (ref,) = extract_pull_requests("https://github.com/acme/web-client/pull/88", "description")
        self.assertEqual((ref.provider, ref.repository, ref.number), ("github", "web-client", 88))

    def test_several_different_prs_are_all_kept(self):
        text = (
            "Backend https://dev.azure.com/acme/Core/_git/core-api/pullrequest/1 "
            "and frontend https://dev.azure.com/acme/Core/_git/web-client/pullrequest/2"
        )
        refs = extract_pull_requests(text, "comment")
        self.assertEqual([r.repository for r in refs], ["core-api", "web-client"])

    def test_the_same_pr_pasted_twice_is_deduplicated(self):
        # The exact real-world case: one plain copy, one markdown-escaped copy.
        plain = extract_pull_requests("https://dev.azure.com/acme/Core/_git/core-api/pullrequest/1", "comment")
        escaped = extract_pull_requests(r"https://dev.azure.com/acme/Core/\_git/core-api/pullrequest/1", "comment")
        self.assertEqual(len(deduplicate(plain + escaped)), 1)

    def test_deduplication_ignores_case(self):
        a = extract_pull_requests("https://dev.azure.com/ACME/Core/_git/Core-API/pullrequest/1", "comment")
        b = extract_pull_requests("https://dev.azure.com/acme/core/_git/core-api/pullrequest/1", "comment")
        self.assertEqual(len(deduplicate(a + b)), 1)

    def test_attachment_wins_over_a_comment_for_the_same_pr(self):
        merged = deduplicate([pr(source="comment"), pr(source="attachment")])
        self.assertEqual([m.source for m in merged], ["attachment"])

    def test_text_without_links(self):
        self.assertEqual(extract_pull_requests("no links here, just PR 12", "comment"), [])
        self.assertEqual(extract_pull_requests(None, "comment"), [])


class IssueParsingTests(TestCase):
    def node(self, **overrides):
        base = {
            "id": "i1", "identifier": "TES-8", "title": "t", "description": "", "url": "u",
            "branchName": "b", "updatedAt": "2026-09-13T10:00:00Z",
            "state": {"name": "In Progress", "type": "started"},
            "assignee": None, "team": {"id": "t", "key": "TES", "name": "Team"},
            "children": {"nodes": []},
            "comments": {"nodes": []},
            "attachments": {"nodes": []},
        }
        base.update(overrides)
        return base

    def test_prs_pasted_in_comments_are_found(self):
        parsed = _parse_issue(self.node(comments={"nodes": [
            {"id": "c1", "resolvedAt": None, "body": "PR: https://dev.azure.com/acme/Core/_git/core-api/pullrequest/1"},
            {"id": "c2", "resolvedAt": None, "body": r"again https://dev.azure.com/acme/Core/\_git/core-api/pullrequest/1"},
            {"id": "c3", "resolvedAt": None, "body": "follow-up https://dev.azure.com/acme/Core/_git/core-api/pullrequest/4"},
        ]}))
        self.assertEqual([p.number for p in parsed.pull_requests], [1, 4])

    def test_non_pr_attachments_are_ignored(self):
        parsed = _parse_issue(self.node(attachments={"nodes": [
            {"id": "a1", "url": "https://example.com/spec.pdf", "sourceType": "api"},
        ]}))
        self.assertEqual(parsed.pull_requests, [])


class MultiplePullRequestReadinessTests(TestCase):
    def assess(self, prs, connected):
        from .criteria import Criterion

        return assess(
            issue(pull_requests=prs),
            [Criterion("AC-1", "x")],
            repository_count=len(connected),
            strategy=DiffScopeStrategy.LINKED_PR,
            connected_repositories=connected,
        )

    def diff(self, result):
        return next(c for c in result.checks if c.key == "diff_scope")

    def test_two_prs_across_two_connected_repos(self):
        result = self.assess([pr("core-api", 1), pr("web-client", 2)], {"core-api", "web-client"})
        self.assertEqual(self.diff(result).status, OK)
        self.assertEqual(self.diff(result).detail, "2 PRs · 2 repos")

    def test_only_prs_in_connected_repos_count(self):
        result = self.assess([pr("core-api", 1), pr("other-repo", 9)], {"core-api"})
        self.assertEqual(self.diff(result).detail, "PR #1 · core-api")

    def test_prs_only_in_unconnected_repos_warn(self):
        result = self.assess([pr("other-repo", 9)], {"core-api"})
        self.assertEqual(self.diff(result).status, WARNING)
        self.assertIn("haven't connected", self.diff(result).detail)

    def test_repository_names_match_case_insensitively(self):
        result = self.assess([pr("Core-API", 1)], {"core-api"})
        self.assertEqual(self.diff(result).status, OK)
