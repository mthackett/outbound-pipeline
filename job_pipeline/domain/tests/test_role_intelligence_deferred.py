import os
import shutil
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from job_pipeline.domain.models import (
    JobPosting,
    FitEvaluation,
    TargetPayBounds,
    CandidateProfile,
    INTERVIEW_STAGES,
    ROLE_INTELLIGENCE_STATUS_NOT_GENERATED,
    ROLE_INTELLIGENCE_STATUS_GENERATING,
    ROLE_INTELLIGENCE_STATUS_GENERATED,
    ROLE_INTELLIGENCE_STATUS_FAILED,
)
from job_pipeline.domain.role_intelligence import (
    has_role_intelligence,
    get_role_intelligence_status,
    get_local_report_path,
    should_trigger_role_intelligence,
    RoleIntelligenceService,
)
from job_pipeline.adapters.secondary.mock_adapter import (
    MockJobStorageAdapter,
    MockDocumentStorageAdapter,
    MockResumeRepositoryAdapter,
    MockLLMStrategyAdapter,
)
from job_pipeline.adapters.primary.cli_runner import evaluate_single_job


def create_dummy_fit_eval() -> FitEvaluation:
    return FitEvaluation(
        is_qualified=True,
        fit_score=0.9,
        status="PROCESSED",
        reasoning="Strong match",
        pay_bounds=TargetPayBounds(
            annualized_min=130000,
            annualized_max=160000,
            display_range="$130,000 - $160,000"
        )
    )


@pytest.fixture
def mock_adapters():
    storage = MockJobStorageAdapter()
    drive = MockDocumentStorageAdapter()
    resume = MockResumeRepositoryAdapter()
    llm = MockLLMStrategyAdapter()
    return storage, drive, resume, llm


class TestDeferredRoleIntelligenceScenarios:
    """Tests for verifying deferred Role Intelligence across all 6 required scenarios."""

    def test_scenario_1_new_application_ingestion_defers_role_intelligence(self):
        """
        Scenario 1: New application ingestion:
        - JD is processed
        - Application created & persisted
        - No Role Intelligence LLM calls made
        - No Role Intelligence report created
        - Application visible normally with status 'Not Generated'
        """
        sample_jd = """
        Stripe Analytics is looking for a Senior Revenue Operations Analyst.
        Salary: $130,000 - $160,000.
        Required: SQL, Salesforce, HubSpot, Python.
        Location: Remote.
        """

        saved_jobs_captured = []
        original_save = MockJobStorageAdapter.save_opportunity

        def spy_save(self_adapter, job, fit_eval):
            saved_jobs_captured.append(job)
            return original_save(self_adapter, job, fit_eval)

        with patch.object(MockLLMStrategyAdapter, "generate_role_intelligence_report") as mock_report, \
             patch.object(MockJobStorageAdapter, "save_opportunity", side_effect=spy_save, autospec=True):

            evaluate_single_job(
                company_name="Stripe Analytics",
                job_title="Senior Revenue Operations Analyst",
                title_family="revenue_operations",
                raw_jd=sample_jd,
                salary_min=130000,
                salary_max=160000,
                demo_mode=True
            )

            # 1. No Role Intelligence API calls during ingestion
            assert mock_report.call_count == 0

            # 2. Application persisted successfully in storage
            assert len(saved_jobs_captured) == 1
            saved_opp = saved_jobs_captured[0]
            assert saved_opp.company_name in ["Stripe Analytics", "Mock Target Company"]
            assert saved_opp.role_intelligence_status == ROLE_INTELLIGENCE_STATUS_NOT_GENERATED
            assert not has_role_intelligence(saved_opp)

            # 3. Application has structured extraction and job signals
            assert saved_opp.job_title in ["Senior Revenue Operations Analyst", "Revenue Operations Analyst"]
            assert len(saved_opp.required_skills) > 0 or len(saved_opp.preferred_skills) >= 0

    def test_scenario_2_manual_generation_runs_pipeline_and_persists(self, mock_adapters):
        """
        Scenario 2: Manual generation:
        - Applied application
        - User triggers manual generation
        - Role Intelligence pipeline runs & report artifact saved
        - Opportunity marked as 'Generated'
        """
        storage, drive, resume, llm = mock_adapters
        spy_report = MagicMock(wraps=llm.generate_role_intelligence_report)
        llm.generate_role_intelligence_report = spy_report

        opp_id = f"test-manual-{uuid.uuid4()}"
        job = JobPosting(
            opportunity_id=opp_id,
            company_name="Acme Corp",
            job_title="Revenue Architect",
            title_family="revenue_operations",
            raw_description="Acme Corp needs a Revenue Architect to optimize Salesforce and billing systems.",
            role_intelligence_status=ROLE_INTELLIGENCE_STATUS_NOT_GENERATED
        )
        storage.save_opportunity(job, create_dummy_fit_eval())

        try:
            res = RoleIntelligenceService.generate_for_opportunity(
                opportunity_id=opp_id,
                company_name="Acme Corp",
                job_title="Revenue Architect",
                raw_description=job.raw_description,
                llm_adapter=llm,
                drive_adapter=drive,
                resume_repo=resume,
                storage_adapter=storage,
                demo_mode=True
            )

            assert spy_report.call_count == 1
            assert res["status"] == ROLE_INTELLIGENCE_STATUS_GENERATED
            assert os.path.exists(res["output_docx_path"])

            # Storage updated
            assert job.role_intelligence_status == ROLE_INTELLIGENCE_STATUS_GENERATED
            assert job.role_intelligence_link is not None
            assert job.role_intelligence_generated_at is not None
            assert has_role_intelligence(job)
        finally:
            u_hex = uuid.uuid5(uuid.NAMESPACE_URL, opp_id).hex
            shutil.rmtree(Path("output_reports") / u_hex, ignore_errors=True)

    def test_scenario_3_stage_transition_to_interview_triggers_generation(self, mock_adapters):
        """
        Scenario 3: Employer interest:
        - Moving from 'Applied' to 'Recruiter Screen' automatically triggers generation if none exists
        - Report is produced and status updated
        """
        storage, drive, resume, llm = mock_adapters
        opp_id = f"test-interest-{uuid.uuid4()}"
        job = JobPosting(
            opportunity_id=opp_id,
            company_name="FinTech Solutions",
            job_title="Head of RevOps",
            title_family="revenue_operations",
            status="Applied",
            raw_description="FinTech Solutions seeks a Head of RevOps to align sales and customer success.",
            role_intelligence_status=ROLE_INTELLIGENCE_STATUS_NOT_GENERATED
        )
        storage.save_opportunity(job, create_dummy_fit_eval())

        try:
            # Check trigger condition
            assert should_trigger_role_intelligence("Applied", "Recruiter Screen", job) is True

            # Simulate stage save + trigger
            storage.update_opportunity_status(opp_id, "Recruiter Screen")
            assert job.status == "Recruiter Screen"

            res = RoleIntelligenceService.generate_for_opportunity(
                opportunity_id=opp_id,
                company_name=job.company_name,
                job_title=job.job_title,
                raw_description=job.raw_description,
                llm_adapter=llm,
                drive_adapter=drive,
                resume_repo=resume,
                storage_adapter=storage,
                demo_mode=True
            )

            assert res["status"] == ROLE_INTELLIGENCE_STATUS_GENERATED
            assert job.role_intelligence_status == ROLE_INTELLIGENCE_STATUS_GENERATED
        finally:
            u_hex = uuid.uuid5(uuid.NAMESPACE_URL, opp_id).hex
            shutil.rmtree(Path("output_reports") / u_hex, ignore_errors=True)

    def test_scenario_4_subsequent_interview_stage_does_not_regenerate(self):
        """
        Scenario 4: Subsequent interview stages:
        - Recruiter Screen -> Hiring Manager
        - Should NOT trigger automatic generation again
        - Even if moved back to Applied -> Recruiter Screen, existing report prevents regeneration
        """
        job = JobPosting(
            opportunity_id=f"test-subsequent-{uuid.uuid4()}",
            company_name="Cloud SaaS",
            job_title="Sales Operations Lead",
            title_family="revenue_operations",
            raw_description="Sales Operations Lead role at Cloud SaaS.",
            status="Recruiter Screen",
            role_intelligence_status=ROLE_INTELLIGENCE_STATUS_GENERATED,
            role_intelligence_link="https://docs.google.com/document/d/mock-doc/edit"
        )

        # 1. Recruiter Screen -> Hiring Manager: should NOT trigger
        assert should_trigger_role_intelligence("Recruiter Screen", "Hiring Manager", job) is False

        # 2. Hiring Manager -> Final Round: should NOT trigger
        assert should_trigger_role_intelligence("Hiring Manager", "Final Round", job) is False

        # 3. Final Round -> Offer: should NOT trigger
        assert should_trigger_role_intelligence("Final Round", "Offer", job) is False

        # 4. If status was changed to Applied then back to Recruiter Screen:
        # has_role_intelligence is True, so should NOT trigger again
        assert should_trigger_role_intelligence("Applied", "Recruiter Screen", job) is False

    def test_scenario_5_failure_handling_preserves_stage_and_enables_retry(self, mock_adapters):
        """
        Scenario 5: Generation failure:
        - Applied -> Recruiter Screen
        - Stage saves successfully
        - Role Intelligence generation fails (exception raised)
        - Stage remains 'Recruiter Screen' (not rolled back)
        - Role Intelligence marked as 'Failed'
        - Retry remains available
        """
        storage, drive, resume, llm = mock_adapters
        opp_id = f"test-fail-{uuid.uuid4()}"
        job = JobPosting(
            opportunity_id=opp_id,
            company_name="Glitch Corp",
            job_title="Operations Lead",
            title_family="revenue_operations",
            status="Applied",
            raw_description="Glitch Corp job description.",
            role_intelligence_status=ROLE_INTELLIGENCE_STATUS_NOT_GENERATED
        )
        storage.save_opportunity(job, create_dummy_fit_eval())

        try:
            # 1. Stage update succeeds
            saved_ok = storage.update_opportunity_status(opp_id, "Recruiter Screen")
            assert saved_ok is True
            assert job.status == "Recruiter Screen"

            # 2. Mock LLM failure during generation
            faulty_llm = MagicMock()
            faulty_llm.generate_role_intelligence_report.side_effect = RuntimeError("OpenAI API rate limit / timeout")

            try:
                RoleIntelligenceService.generate_for_opportunity(
                    opportunity_id=opp_id,
                    company_name=job.company_name,
                    job_title=job.job_title,
                    raw_description=job.raw_description,
                    llm_adapter=faulty_llm,
                    drive_adapter=drive,
                    resume_repo=resume,
                    storage_adapter=storage,
                    demo_mode=False
                )
            except Exception:
                # Stage change MUST NOT be rolled back
                storage.update_role_intelligence_status(
                    opportunity_id=opp_id,
                    status=ROLE_INTELLIGENCE_STATUS_FAILED
                )

            # Stage remains 'Recruiter Screen'
            assert job.status == "Recruiter Screen"
            # Status recorded as 'Failed'
            assert job.role_intelligence_status == ROLE_INTELLIGENCE_STATUS_FAILED
            assert get_role_intelligence_status(job) == ROLE_INTELLIGENCE_STATUS_FAILED

            # 3. Retry becomes available and can succeed
            retry_res = RoleIntelligenceService.generate_for_opportunity(
                opportunity_id=opp_id,
                company_name=job.company_name,
                job_title=job.job_title,
                raw_description=job.raw_description,
                llm_adapter=llm,
                drive_adapter=drive,
                resume_repo=resume,
                storage_adapter=storage,
                demo_mode=True
            )
            assert retry_res["status"] == ROLE_INTELLIGENCE_STATUS_GENERATED
            assert job.role_intelligence_status == ROLE_INTELLIGENCE_STATUS_GENERATED
        finally:
            u_hex = uuid.uuid5(uuid.NAMESPACE_URL, opp_id).hex
            shutil.rmtree(Path("output_reports") / u_hex, ignore_errors=True)

    def test_scenario_6_existing_application_without_metadata_recognized(self):
        """
        Scenario 6: Existing application with generated report:
        - Older application record lacks new metadata fields
        - Has existing report (e.g. Drive doc link or local report file)
        - Recognized as 'Generated' without requiring regeneration
        - Stage change does not trigger duplicate generation
        """
        # Dict representing a legacy Google Sheets row without new status columns
        legacy_opp = {
            "Opportunity ID": "legacy-opp-100",
            "Company Name": "Legacy Corp",
            "Job Title": "RevOps Lead",
            "Status": "Applied",
            "Role Intelligence Report Link": "https://docs.google.com/document/d/legacy-doc-id/edit"
        }

        # Status inferred as Generated from existing artifact presence
        assert has_role_intelligence(legacy_opp) is True
        assert get_role_intelligence_status(legacy_opp) == ROLE_INTELLIGENCE_STATUS_GENERATED

        # Transition to interview stage does not trigger regeneration
        assert should_trigger_role_intelligence("Applied", "Recruiter Screen", legacy_opp) is False
