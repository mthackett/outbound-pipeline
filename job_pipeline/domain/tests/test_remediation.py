"""
Regression tests for the reliability/security remediation batch.

Covers the twelve requested test cases from code_fix_instructions.md.
Uses mock adapters only — no live Google or OpenAI credentials required.
"""
import json
import os
import re
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch

from job_pipeline.domain.models import (
    CandidateProfile, FitEvaluation, JobPosting, ScreeningQA, TargetPayBounds,
)
from job_pipeline.domain.services import (
    IngestionRecoveryService, JobQualificationService,
)
from job_pipeline.adapters.secondary.mock_adapter import (
    MockDocumentStorageAdapter, MockJobStorageAdapter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fit_eval(**overrides):
    defaults = dict(
        is_qualified=True,
        status="Processed",
        reasoning="Fits well",
        pay_bounds=TargetPayBounds(display_range="$100k-$120k"),
    )
    defaults.update(overrides)
    return FitEvaluation(**defaults)


def _make_job_posting(opp_id="opp-001", company="Acme", title="Analyst", **overrides):
    defaults = dict(
        opportunity_id=opp_id,
        company_name=company,
        job_title=title,
        title_family="revenue_operations",
        raw_description="Analyze revenue data across all GTM motions and build dashboards.",
        selected_resume_name="Test Resume",
        drive_folder_link="https://drive.google.com/drive/folders/folder_abc",
    )
    defaults.update(overrides)
    return JobPosting(**defaults)


SAMPLE_JD = (
    "Responsibilities\n"
    "Analyze revenue data across all GTM motions, build dbt models in BigQuery, "
    "and automate CRM routing for the full sales cycle. We need someone who can "
    "work cross-functionally with Sales, Marketing, and Finance stakeholders."
)


class _WorkspaceHelper:
    """Shared helpers for workspace lifecycle tests."""

    def create_complete_workspace(self, doc_storage, storage, opp_id, company, title):
        ws = doc_storage.create_application_workspace(company, title, opp_id)
        fid = ws["folder_id"]
        doc_storage.upload_raw_job_description(fid, SAMPLE_JD, company, title)
        fit = _make_fit_eval()
        job = _make_job_posting(opp_id, company, title,
                                drive_folder_link=ws["folder_link"])
        storage.save_opportunity(job, fit)
        doc_storage.mark_workspace_complete(fid)
        return ws, job, fit


# ===========================================================================
# TEST 1: Missing sharing-recipient does not create public Drive permissions
# ===========================================================================

class TestDrivePrivateByDefault(unittest.TestCase):
    """Fix #1: absence of CANDIDATE_EMAIL / GOOGLE_USER_EMAIL must never
    cause public sharing."""

    def test_no_public_sharing_when_recipient_absent(self):
        """With no env-configured recipient, _share_with_configured_recipient
        must not create any permission."""
        from job_pipeline.adapters.secondary.google_drive import GoogleDriveAdapter

        adapter = GoogleDriveAdapter.__new__(GoogleDriveAdapter)
        adapter._drive_svc = MagicMock()

        with patch.dict(os.environ, {}, clear=True):
            adapter._share_with_configured_recipient("some_file_id")

        # permissions().create should never have been called
        adapter._drive_svc.permissions.assert_not_called()

    def test_explicit_recipient_shares_correctly(self):
        """With a configured recipient, sharing is attempted."""
        from job_pipeline.adapters.secondary.google_drive import GoogleDriveAdapter

        adapter = GoogleDriveAdapter.__new__(GoogleDriveAdapter)
        adapter._drive_svc = MagicMock()

        with patch.dict(os.environ, {"CANDIDATE_EMAIL": "user@example.com"}, clear=True):
            adapter._share_with_configured_recipient("file_123")

        adapter._drive_svc.permissions().create.assert_called_once()
        call_kwargs = adapter._drive_svc.permissions().create.call_args
        body = call_kwargs[1]["body"] if "body" in (call_kwargs[1] or {}) else call_kwargs[0][0] if call_kwargs[0] else {}
        # Verify it's a user share, not "anyone"
        if isinstance(body, dict):
            self.assertNotEqual(body.get("type"), "anyone")


# ===========================================================================
# TEST 2 & 3: Completion gating on canonical persistence
# ===========================================================================

class TestCompletionGating(unittest.TestCase):
    """Fix #2: workspace must not be marked complete unless required
    persistence succeeds."""

    def test_failed_canonical_save_cannot_mark_complete(self):
        """require_completion raises when canonical save returns False."""
        with self.assertRaises(RuntimeError) as ctx:
            IngestionRecoveryService.require_completion(
                workspace_id="folder_x",
                raw_jd_saved=True,
                report_saved=True,
                canonical_saved=False,
            )
        self.assertIn("canonical opportunity", str(ctx.exception))

    def test_successful_save_allows_completion(self):
        """require_completion passes when all required items are present."""
        # Should not raise
        IngestionRecoveryService.require_completion(
            workspace_id="folder_x",
            raw_jd_saved=True,
            report_saved=True,
            canonical_saved=True,
        )

    def test_missing_report_prevents_completion(self):
        with self.assertRaises(RuntimeError) as ctx:
            IngestionRecoveryService.require_completion(
                workspace_id="folder_x",
                raw_jd_saved=True,
                report_saved=False,
                canonical_saved=True,
            )
        self.assertIn("Role Intelligence report", str(ctx.exception))

    def test_missing_workspace_prevents_completion(self):
        with self.assertRaises(RuntimeError) as ctx:
            IngestionRecoveryService.require_completion(
                workspace_id="",
                raw_jd_saved=True,
                report_saved=True,
                canonical_saved=True,
            )
        self.assertIn("application workspace", str(ctx.exception))


# ===========================================================================
# TEST 4 & 5: Immutable opportunity identity
# ===========================================================================

class TestImmutableOpportunityIdentity(unittest.TestCase, _WorkspaceHelper):
    """Fix #3: company/title must not be used as persistence identity."""

    def setUp(self):
        self.storage = MockJobStorageAdapter()
        self.doc_storage = MockDocumentStorageAdapter()

    def test_same_company_title_different_ids_remain_distinct(self):
        """Two applications with the same company/title but different IDs
        must both exist as separate records."""
        fit = _make_fit_eval()
        job1 = _make_job_posting("opp-aaa", "MongoDB", "Data Analyst")
        job2 = _make_job_posting("opp-bbb", "MongoDB", "Data Analyst")

        self.storage.save_opportunity(job1, fit)
        self.storage.save_opportunity(job2, fit)

        opps = self.storage.fetch_all_opportunities()
        ids = [o.get("Opportunity ID") for o in opps]
        self.assertIn("opp-aaa", ids)
        self.assertIn("opp-bbb", ids)
        self.assertEqual(len(opps), 2)

    def test_update_existing_id_updates_correct_record(self):
        """Updating an existing opportunity by ID must change the correct one."""
        fit = _make_fit_eval()
        job_v1 = _make_job_posting("opp-ccc", "Stripe", "RevOps Engineer",
                                    raw_description="Version 1 description for initial intake.")
        self.storage.save_opportunity(job_v1, fit)

        # Update with same ID, different title
        job_v2 = _make_job_posting("opp-ccc", "Stripe", "Senior RevOps Engineer",
                                    raw_description="Version 2 description with more detail and info.")
        self.storage.save_opportunity(job_v2, fit)

        opps = self.storage.fetch_all_opportunities()
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0]["Job Title"], "Senior RevOps Engineer")
        self.assertEqual(opps[0]["Opportunity ID"], "opp-ccc")


# ===========================================================================
# TEST 6: Resume/retry preserves same logical opportunity identity
# ===========================================================================

class TestRetryPreservesIdentity(unittest.TestCase, _WorkspaceHelper):
    """Fix #3: a retry/resume of the same ingestion must retain the same ID."""

    def setUp(self):
        self.storage = MockJobStorageAdapter()
        self.doc_storage = MockDocumentStorageAdapter()

    def test_retry_preserves_opportunity_id(self):
        """Creating a workspace with the same opportunity_id is idempotent."""
        opp_id = "opp-retry-001"
        ws1 = self.doc_storage.create_application_workspace("Acme", "Analyst", opp_id)
        ws2 = self.doc_storage.create_application_workspace("Acme", "Analyst", opp_id)

        # Same folder returned
        self.assertEqual(ws1["folder_id"], ws2["folder_id"])
        # Only one workspace exists
        workspace_ids = [fid for fid, ws in self.doc_storage.workspaces.items()
                         if ws.get("opportunity_id") == opp_id]
        self.assertEqual(len(workspace_ids), 1)

    def test_ensure_workspace_opportunity_id_idempotent(self):
        """ensure_workspace_opportunity_id returns existing ID and rejects conflicts."""
        ws = self.doc_storage.create_application_workspace("Corp", "Role", "opp-xyz")
        fid = ws["folder_id"]

        # Same ID is fine
        returned = self.doc_storage.ensure_workspace_opportunity_id(fid, "opp-xyz")
        self.assertEqual(returned, "opp-xyz")

        # Conflicting ID raises
        with self.assertRaises(ValueError):
            self.doc_storage.ensure_workspace_opportunity_id(fid, "opp-different")

    def test_screening_qa_ids_preserved_on_retry(self):
        """Screening Q&A answers have stable IDs that survive re-save."""
        qa1 = ScreeningQA(qa_id="qa-001", question="Salary?", answer="$120k", category="Salary")
        qa2 = ScreeningQA(qa_id="qa-002", question="Remote?", answer="Yes", category="Culture")
        job = _make_job_posting("opp-qa", "Test Corp", "Eng", screening_qa=[qa1, qa2])

        self.storage.save_opportunity(job, _make_fit_eval())
        # Re-save (retry)
        self.storage.save_opportunity(job, _make_fit_eval())

        stored = self.storage.fetch_screening_qa("opp-qa")
        ids = [q["qa_id"] for q in stored]
        self.assertEqual(sorted(ids), ["qa-001", "qa-002"])
        self.assertEqual(len(stored), 2)  # No duplicates


# ===========================================================================
# TEST 7 & 8: Conservative reversible discard
# ===========================================================================

class TestConservativeDiscard(unittest.TestCase, _WorkspaceHelper):
    """Fix #4: discard must refuse when canonical state is unverifiable
    and use reversible cleanup."""

    def setUp(self):
        self.storage = MockJobStorageAdapter()
        self.doc_storage = MockDocumentStorageAdapter()

    def test_discard_refuses_when_canonical_state_unverified(self):
        """Passing canonical_opportunities=None means 'unverified' and must refuse."""
        ws = self.doc_storage.create_application_workspace("Test", "Role", "opp-discard-1")
        fid = ws["folder_id"]
        self.doc_storage.upload_raw_job_description(fid, SAMPLE_JD, "Test", "Role")

        result = self.doc_storage.delete_application_workspace(fid, canonical_opportunities=None)
        self.assertFalse(result)
        # Workspace should still be intact
        self.assertEqual(self.doc_storage.workspaces[fid]["status"], "incomplete")

    def test_discard_uses_reversible_trash(self):
        """Successful discard should set status to 'trashed', not delete the workspace."""
        ws = self.doc_storage.create_application_workspace("Test2", "Role2", "opp-discard-2")
        fid = ws["folder_id"]
        self.doc_storage.upload_raw_job_description(fid, SAMPLE_JD, "Test2", "Role2")

        result = self.doc_storage.delete_application_workspace(fid, canonical_opportunities=[])
        self.assertTrue(result)
        # Workspace exists but is trashed
        self.assertIn(fid, self.doc_storage.workspaces)
        self.assertEqual(self.doc_storage.workspaces[fid]["status"], "trashed")
        # Trashed workspaces should not appear in incomplete list
        incomplete = self.doc_storage.fetch_incomplete_workspaces()
        self.assertEqual(len([w for w in incomplete if w["folder_id"] == fid]), 0)

    def test_discard_refuses_when_canonical_record_exists(self):
        """If the workspace has a matching canonical record, discard should refuse."""
        ws = self.doc_storage.create_application_workspace("SavedCo", "SavedRole", "opp-saved")
        fid = ws["folder_id"]
        self.doc_storage.upload_raw_job_description(fid, SAMPLE_JD, "SavedCo", "SavedRole")

        # Simulate a canonical record referencing this folder
        canonical = [{"Drive Folder Link": ws["folder_link"], "Opportunity ID": "opp-saved"}]
        result = self.doc_storage.delete_application_workspace(fid, canonical_opportunities=canonical)
        self.assertFalse(result)
        self.assertEqual(self.doc_storage.workspaces[fid]["status"], "incomplete")


# ===========================================================================
# TEST 9 & 10: Recovery source identity safety
# ===========================================================================

class TestRecoverySourceSafety(unittest.TestCase):
    """Fix #5: recovery must not use unrelated local JD backups or
    substitute sample content."""

    def setUp(self):
        self.doc_storage = MockDocumentStorageAdapter()

    def test_recovery_does_not_use_unrelated_backup(self):
        """A workspace with no JD should raise, not return content from another workspace."""
        # Create workspace A with JD
        ws_a = self.doc_storage.create_application_workspace("CoA", "RoleA", "opp-a")
        self.doc_storage.upload_raw_job_description(ws_a["folder_id"], SAMPLE_JD, "CoA", "RoleA")

        # Create workspace B WITHOUT JD
        ws_b = self.doc_storage.create_application_workspace("CoB", "RoleB", "opp-b")
        # Do not upload JD to workspace B

        # Fetching JD from workspace B should fail, not return workspace A's content
        with self.assertRaises(RuntimeError) as ctx:
            self.doc_storage.fetch_raw_job_description(ws_b["folder_id"])
        self.assertIn("missing or unreadable", str(ctx.exception))

    def test_missing_jd_produces_recoverable_failure(self):
        """Missing JD raises RuntimeError so workspace remains incomplete for retry."""
        ws = self.doc_storage.create_application_workspace("NoJD", "NoRole", "opp-nojd")

        with self.assertRaises(RuntimeError):
            self.doc_storage.fetch_raw_job_description(ws["folder_id"])

        # Workspace should still be incomplete (not modified)
        self.assertEqual(self.doc_storage.workspaces[ws["folder_id"]]["status"], "incomplete")

    def test_nonexistent_workspace_raises(self):
        """Fetching JD from a workspace that doesn't exist should raise."""
        with self.assertRaises(RuntimeError):
            self.doc_storage.fetch_raw_job_description("nonexistent_folder_id")


# ===========================================================================
# TEST 11: Valid Role Intelligence output satisfies the renderer contract
# ===========================================================================

class TestRoleIntelligenceContract(unittest.TestCase):
    """Fix #6: content schema and renderer must agree on structure."""

    def setUp(self):
        self.schema_path = Path(__file__).resolve().parent.parent.parent / "resources" / "schemas" / "cockpit_content.schema.json"
        self.fixture_path = Path(__file__).resolve().parent.parent.parent / "examples" / "fixtures" / "mock_cockpit_content.json"

    def test_valid_output_satisfies_schema(self):
        """The existing mock fixture should pass JSON schema validation
        against the content schema."""
        from jsonschema import Draft202012Validator

        with open(self.schema_path) as f:
            schema = json.load(f)
        with open(self.fixture_path) as f:
            content = json.load(f)

        validator = Draft202012Validator(schema)
        errors = list(validator.iter_errors(content))
        self.assertEqual(len(errors), 0, f"Schema validation errors: {errors}")

    def test_schema_requires_three_columns(self):
        """The schema must enforce exactly 3 columns per page."""
        from jsonschema import Draft202012Validator

        with open(self.schema_path) as f:
            schema = json.load(f)

        # Build a valid-ish content with 2 columns instead of 3
        content_2col = {
            "pages": [
                {
                    "title": "Page 1",
                    "columns": [
                        [{"title": "Sec1", "kind": "bullets", "items": ["a"]}],
                        [{"title": "Sec2", "kind": "bullets", "items": ["b"]}],
                    ],
                },
                {
                    "title": "Page 2",
                    "columns": [
                        [{"title": "Sec3", "kind": "bullets", "items": ["c"]}],
                        [{"title": "Sec4", "kind": "bullets", "items": ["d"]}],
                    ],
                },
            ]
        }
        validator = Draft202012Validator(schema)
        errors = list(validator.iter_errors(content_2col))
        self.assertGreater(len(errors), 0, "2-column content should fail validation")

    def test_renderer_config_has_three_column_widths(self):
        """Report config must specify exactly 3 column widths."""
        from job_pipeline.adapters.secondary.docx_report_generator import load_config

        cfg = load_config()
        self.assertEqual(len(cfg["column_widths_in"]), 3)


# ===========================================================================
# TEST 12: Renderer failure never substitutes mock career data in live workflow
# ===========================================================================

class TestNoMockSubstitutionInLiveWorkflow(unittest.TestCase):
    """Fix #6: live report failures must NOT silently render mock content."""

    def test_runner_raises_without_api_key_when_not_demo(self):
        """With demo_mode=False and no API key, the runner must raise
        rather than silently using fixture data."""
        from job_pipeline.role_intelligence_runner import RoleIntelligenceRunner

        runner = RoleIntelligenceRunner.__new__(RoleIntelligenceRunner)
        runner.api_key = None
        runner._openai_client = None

        with tempfile.TemporaryDirectory() as td:
            output_path = os.path.join(td, "report.docx")
            with self.assertRaises(RuntimeError) as ctx:
                runner.run_pipeline(
                    job_data={"company": "TestCo", "title": "Analyst", "description": SAMPLE_JD},
                    resume_data={"resume_id": "r1", "text": "Built dbt models."},
                    output_docx_path=output_path,
                    target_pay_bounds={},
                    demo_mode=False,
                )
            self.assertIn("OPENAI_API_KEY", str(ctx.exception))

    def test_demo_mode_uses_fixture(self):
        """With demo_mode=True, the runner should use the fixture
        and successfully generate a DOCX."""
        from job_pipeline.role_intelligence_runner import RoleIntelligenceRunner

        runner = RoleIntelligenceRunner.__new__(RoleIntelligenceRunner)
        runner.api_key = None
        runner._openai_client = None

        with tempfile.TemporaryDirectory() as td:
            output_path = os.path.join(td, "report.docx")
            runner.run_pipeline(
                job_data={"company": "TestCo", "title": "Analyst", "description": SAMPLE_JD},
                resume_data={"resume_id": "r1", "text": "Built dbt models."},
                output_docx_path=output_path,
                target_pay_bounds={},
                demo_mode=True,
            )
            self.assertTrue(os.path.exists(output_path))

    def test_invalid_content_raises_not_substitutes(self):
        """If content_json fails schema validation, the runner must raise
        rather than falling back to mock fixture."""
        from job_pipeline.role_intelligence_runner import RoleIntelligenceRunner

        runner = RoleIntelligenceRunner.__new__(RoleIntelligenceRunner)
        runner.api_key = "fake-key"
        runner._openai_client = MagicMock()

        # Mock the OpenAI response to return invalid content (missing columns)
        bad_content = json.dumps({"pages": [{"title": "P1", "columns": [[], []]}, {"title": "P2", "columns": [[], []]}]})
        mock_message = MagicMock()
        mock_message.content = bad_content
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]
        mock_completion.usage = MagicMock(total_tokens=100)
        runner._openai_client.chat.completions.create = MagicMock(return_value=mock_completion)

        with tempfile.TemporaryDirectory() as td:
            output_path = os.path.join(td, "report.docx")
            with self.assertRaises(ValueError) as ctx:
                runner.run_pipeline(
                    job_data={"company": "TestCo", "title": "Analyst", "description": SAMPLE_JD},
                    resume_data={"resume_id": "r1", "text": "Built dbt models."},
                    output_docx_path=output_path,
                    target_pay_bounds={},
                    demo_mode=False,
                )
            self.assertIn("schema", str(ctx.exception).lower())


# ===========================================================================
# Additional: find_workspace_record safety
# ===========================================================================

class TestFindWorkspaceRecord(unittest.TestCase):
    """Tests for the IngestionRecoveryService.find_workspace_record helper."""

    def test_finds_by_folder_id_in_link(self):
        records = [{"Drive Folder Link": "https://drive.google.com/drive/folders/abc123", "Opportunity ID": "opp-1"}]
        result = IngestionRecoveryService.find_workspace_record(records, "abc123", "opp-1")
        self.assertIsNotNone(result)
        self.assertEqual(result["Opportunity ID"], "opp-1")

    def test_returns_none_when_not_found(self):
        records = [{"Drive Folder Link": "https://drive.google.com/drive/folders/xyz", "Opportunity ID": "opp-2"}]
        result = IngestionRecoveryService.find_workspace_record(records, "not_found")
        self.assertIsNone(result)

    def test_raises_on_conflicting_ids(self):
        records = [{"Drive Folder Link": "https://drive.google.com/drive/folders/abc", "Opportunity ID": "opp-A"}]
        with self.assertRaises(ValueError):
            IngestionRecoveryService.find_workspace_record(records, "abc", "opp-B")

    def test_raises_on_multiple_matches(self):
        records = [
            {"Drive Folder Link": "https://drive.google.com/drive/folders/abc", "Opportunity ID": "opp-1"},
            {"Drive Folder Link": "https://drive.google.com/drive/folders/abc", "Opportunity ID": "opp-1"},
        ]
        with self.assertRaises(ValueError):
            IngestionRecoveryService.find_workspace_record(records, "abc", "opp-1")



# ===========================================================================
# Persistence: Raw JD excluded from Sheet; Drive JD link persisted
# ===========================================================================

class TestRawJDPersistencePolicy(unittest.TestCase, _WorkspaceHelper):
    """Verifies that full raw job-description text is removed from canonical
    Google Sheets opportunity persistence, while the Drive JD URI/link is
    persisted reliably, and existing ingestion/recovery behavior is preserved."""

    def test_mock_storage_raw_jd_excluded_and_link_persisted(self):
        """Mock storage fetch_all_opportunities must reflect canonical sheet rows:
        empty Job Description and populated Raw JD Link."""
        storage = MockJobStorageAdapter()
        fit = _make_fit_eval()
        job = _make_job_posting(
            opp_id="opp-jd-01",
            company="Snowflake",
            title="RevOps Lead",
            raw_description=SAMPLE_JD,
            drive_jd_link="https://docs.google.com/document/d/mock_raw_jd_01/edit",
        )
        storage.save_opportunity(job, fit)

        # In-memory model preserves raw JD for downstream workflows
        self.assertEqual(job.raw_description, SAMPLE_JD)
        self.assertEqual(job.drive_jd_link, "https://docs.google.com/document/d/mock_raw_jd_01/edit")

        # Canonical Sheet record representation excludes raw text and includes Drive link
        opps = storage.fetch_all_opportunities()
        self.assertEqual(len(opps), 1)
        rec = opps[0]
        self.assertEqual(rec["Raw JD Link"], "https://docs.google.com/document/d/mock_raw_jd_01/edit")
        self.assertEqual(rec["Job Description"], "")
        self.assertNotIn(SAMPLE_JD, rec.values())

    def test_google_sheets_adapter_save_does_not_persist_raw_text(self):
        """GoogleSheetsAdapter.save_opportunity must write empty string for Job Description
        and the document URI for Raw JD Link into the canonical sheet."""
        from job_pipeline.adapters.secondary.google_sheets import GoogleSheetsAdapter

        headers = [
            "Opportunity ID", "Company Name", "Job Title", "Title Family", "Status",
            "Date Created", "Job Description", "Raw JD Link", "Last Modified",
            "Tokens", "Fit Warning", "Selected Resume",
            "Target Pay Range", "Drive Folder Link", "Screening Doc Link", "Screening QA Count",
            "Stage History", "Category", "Applied Via", "Priority",
            "Employment Arrangement", "Worker Classification", "Pay Basis",
            "Contract Duration", "Contract Value", "Staffing Agency",
            "Client Company", "Extension Possible", "FTE Conversion"
        ]
        with patch.object(GoogleSheetsAdapter, "_init_connection"):
            adapter = GoogleSheetsAdapter(spreadsheet_id="mock_sheet_id")
            mock_sheet = MagicMock()
            mock_ingest_ws = MagicMock()
            mock_ingest_ws.row_values.return_value = headers
            mock_ingest_ws.col_count = len(headers)
            mock_ingest_ws.get_all_records.return_value = []
            mock_sheet.worksheet.side_effect = lambda name: mock_ingest_ws if name == "Raw Ingestion" else MagicMock(get_all_records=MagicMock(return_value=[]))
            adapter._spreadsheet = mock_sheet

        fit = _make_fit_eval()
        job = _make_job_posting(
            opp_id="opp-live-01",
            company="Datadog",
            title="GTM Systems Architect",
            raw_description=SAMPLE_JD,
            drive_jd_link="https://docs.google.com/document/d/drive_jd_live_123/edit",
        )
        saved = adapter.save_opportunity(job, fit)
        self.assertTrue(saved)

        # Raw description remains on in-memory JobPosting
        self.assertEqual(job.raw_description, SAMPLE_JD)

        # Inspect appended row
        mock_ingest_ws.append_row.assert_called_once()
        appended_row = mock_ingest_ws.append_row.call_args[0][0]
        jd_col_idx = headers.index("Job Description")
        link_col_idx = headers.index("Raw JD Link")

        # Full raw text is NOT persisted
        self.assertEqual(appended_row[jd_col_idx], "")
        self.assertNotIn(SAMPLE_JD, appended_row)

        # Drive JD link IS persisted
        self.assertEqual(appended_row[link_col_idx], "https://docs.google.com/document/d/drive_jd_live_123/edit")

    def test_retry_preserves_drive_jd_link_without_persisting_raw_text(self):
        """Retrying or updating an opportunity retains drive_jd_link and leaves raw JD text out."""
        from job_pipeline.adapters.secondary.google_sheets import GoogleSheetsAdapter

        headers = [
            "Opportunity ID", "Company Name", "Job Title", "Title Family", "Status",
            "Date Created", "Job Description", "Raw JD Link", "Last Modified",
            "Tokens", "Fit Warning", "Selected Resume",
            "Target Pay Range", "Drive Folder Link", "Screening Doc Link", "Screening QA Count",
            "Stage History", "Category", "Applied Via", "Priority",
            "Employment Arrangement", "Worker Classification", "Pay Basis",
            "Contract Duration", "Contract Value", "Staffing Agency",
            "Client Company", "Extension Possible", "FTE Conversion"
        ]
        with patch.object(GoogleSheetsAdapter, "_init_connection"):
            adapter = GoogleSheetsAdapter(spreadsheet_id="mock_sheet_id")
            mock_sheet = MagicMock()
            mock_ingest_ws = MagicMock()
            mock_ingest_ws.row_values.return_value = headers
            mock_ingest_ws.col_count = len(headers)
            # Existing record in sheet already has Raw JD Link and Date Created, but had old raw text
            existing_record = {
                "Opportunity ID": "opp-retry-01",
                "Company Name": "Stripe",
                "Job Title": "RevOps Analyst",
                "Status": "Pending",
                "Date Created": "2026-09-30 10:00:00",
                "Job Description": "Old pasted text",
                "Raw JD Link": "https://docs.google.com/document/d/stripe_jd_existing/edit",
            }
            mock_ingest_ws.get_all_records.return_value = [existing_record]
            mock_sheet.worksheet.side_effect = lambda name: mock_ingest_ws if name == "Raw Ingestion" else MagicMock(get_all_records=MagicMock(return_value=[]))
            adapter._spreadsheet = mock_sheet

        fit = _make_fit_eval()
        # Job on retry may have raw_description in memory but None drive_jd_link
        job_retry = _make_job_posting(
            opp_id="opp-retry-01",
            company="Stripe",
            title="RevOps Analyst",
            raw_description=SAMPLE_JD,
            drive_jd_link=None,
        )
        saved = adapter.save_opportunity(job_retry, fit)
        self.assertTrue(saved)

        # Updated cells should update Job Description to empty and preserve Raw JD Link
        mock_ingest_ws.update_cells.assert_called_once()
        cell_updates = mock_ingest_ws.update_cells.call_args[0][0]
        jd_col_1based = headers.index("Job Description") + 1
        link_col_1based = headers.index("Raw JD Link") + 1

        jd_cells = [c for c in cell_updates if c.col == jd_col_1based]
        link_cells = [c for c in cell_updates if c.col == link_col_1based]

        self.assertTrue(len(jd_cells) == 1)
        self.assertEqual(jd_cells[0].value, "")
        self.assertTrue(len(link_cells) == 1)
        self.assertEqual(link_cells[0].value, "https://docs.google.com/document/d/stripe_jd_existing/edit")
        self.assertEqual(job_retry.drive_jd_link, "https://docs.google.com/document/d/stripe_jd_existing/edit")

    def test_ingestion_and_recovery_flow_preserves_jd_in_drive_and_recovers_link(self):
        """Ingestion and recovery behavior: raw JD is durably kept in Drive, recovered
        as a URI link, completion-gated with raw_jd_saved, and persisted without raw text."""
        doc_storage = MockDocumentStorageAdapter()
        storage = MockJobStorageAdapter()

        # Step 1: Incomplete workspace intake
        ws = doc_storage.create_application_workspace("Figma", "Data Analyst", "opp-rec-01")
        folder_id = ws["folder_id"]
        jd_upload = doc_storage.upload_raw_job_description(folder_id, SAMPLE_JD, "Figma", "Data Analyst")
        self.assertIsNotNone(jd_upload)
        self.assertIn("file_link", jd_upload)

        # Incomplete detection works from Drive workspace raw text
        incomplete = doc_storage.fetch_incomplete_workspaces()
        self.assertEqual(len(incomplete), 1)
        self.assertEqual(incomplete[0]["company"], "Figma")
        self.assertIn("Analyze revenue data", incomplete[0]["raw_jd_preview"])

        # Step 2: Recovery finds existing file link and raw text from workspace
        files = doc_storage.list_workspace_files(folder_id)
        raw_jd_doc = next((f for f in files if "raw job description" in f.get("name", "").lower()), None)
        self.assertIsNotNone(raw_jd_doc)
        recovered_link = raw_jd_doc.get("webViewLink") or f"https://docs.google.com/document/d/{raw_jd_doc.get('id')}/edit"
        recovered_text = doc_storage.fetch_raw_job_description(folder_id)
        self.assertEqual(recovered_text, SAMPLE_JD)

        # Step 3: Complete recovery and persist opportunity
        fit = _make_fit_eval()
        job = _make_job_posting(
            opp_id="opp-rec-01",
            company="Figma",
            title="Data Analyst",
            raw_description=recovered_text,
            drive_folder_link=ws["folder_link"],
            drive_jd_link=recovered_link,
        )
        canonical_saved = storage.save_opportunity(job, fit)
        self.assertTrue(canonical_saved)

        # Completion gating passes because raw_jd_saved=bool(drive_jd_link) is True
        IngestionRecoveryService.require_completion(
            workspace_id=folder_id,
            raw_jd_saved=bool(job.drive_jd_link),
            report_saved=True,
            canonical_saved=canonical_saved,
        )
        marked = doc_storage.mark_workspace_complete(folder_id)
        self.assertTrue(marked)

        # Workspace is now complete
        self.assertEqual(len(doc_storage.fetch_incomplete_workspaces()), 0)

        # Sheet persistence contains Drive link, not raw text
        opps = storage.fetch_all_opportunities()
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0]["Raw JD Link"], recovered_link)
        self.assertEqual(opps[0]["Job Description"], "")
        self.assertNotIn(SAMPLE_JD, opps[0].values())


if __name__ == "__main__":
    unittest.main()

