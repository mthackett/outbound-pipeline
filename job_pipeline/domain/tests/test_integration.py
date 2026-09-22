import unittest
from datetime import datetime, timedelta
from job_pipeline.domain.models import CandidateProfile, JobPosting, ScreeningQA
from job_pipeline.domain.services import (
    JobQualificationService,
    ApplicationGuardrailService,
    ScreeningQAService
)
from job_pipeline.adapters.secondary.mock_adapter import (
    MockJobStorageAdapter,
    MockDocumentStorageAdapter
)


class TestPipelineIntegration(unittest.TestCase):

    def setUp(self):
        self.profile = CandidateProfile(
            max_company_applications_limit=2,
            company_application_window_days=60,
            repost_detection_threshold_days=60
        )
        self.storage = MockJobStorageAdapter()
        self.drive = MockDocumentStorageAdapter()

    def test_full_screening_and_guardrail_lifecycle(self):
        # 1. Ingest first job with screening questions
        qa1 = ScreeningQA(
            question="Experience with Salesforce?",
            answer="5+ years managing enterprise Salesforce, custom objects, and CPQ flows.",
            category="Technical"
        )
        qa2 = ScreeningQA(
            question="Target compensation?",
            answer="$120,000 - $135,000 base.",
            category="Salary"
        )

        job1 = JobPosting(
            opportunity_id="opp_int_1",
            company_name="Snowflake Solutions",
            job_title="Revenue Operations Analyst",
            title_family="revenue_operations",
            raw_description="Salesforce, SQL, and dbt required. Lead pipeline operations.",
            screening_qa=[qa1, qa2]
        )

        # Pre-flight check on clean slate
        all_opps = self.storage.fetch_all_opportunities()
        dup_res = ApplicationGuardrailService.check_duplicate(
            job1.company_name, job1.job_title, all_opps
        )
        self.assertFalse(dup_res["is_duplicate"])

        vel_res = ApplicationGuardrailService.check_company_velocity(
            job1.company_name, all_opps, max_limit=2, window_days=60
        )
        self.assertFalse(vel_res["velocity_exceeded"])

        # Create drive workspace
        workspace = self.drive.create_application_workspace(job1.company_name, job1.job_title)
        folder_id = workspace["folder_id"]

        # Upload raw job description (returns dict with file link)
        jd_res = self.drive.upload_raw_job_description(
            folder_id, job1.raw_description, company_name=job1.company_name, job_title=job1.job_title
        )
        self.assertIn("file_link", jd_res)
        job1.drive_jd_link = jd_res["file_link"]

        # Create screening doc
        sq_res = self.drive.create_screening_questions_doc(
            folder_id, job1.company_name, job1.job_title, job1.screening_qa, job1.opportunity_id
        )
        self.assertIn("file_link", sq_res)
        job1.drive_screening_doc_link = sq_res["file_link"]

        # Evaluate fit
        fit_eval = JobQualificationService.evaluate(
            company_name=job1.company_name,
            job_title=job1.job_title,
            raw_description=job1.raw_description,
            required_skills=["Salesforce", "SQL"],
            salary_min=110000,
            salary_max=135000,
            profile=self.profile,
            existing_company_titles=all_opps
        )
        self.assertEqual(fit_eval.status, "PASS")

        # Save opportunity and screening QAs
        self.storage.save_opportunity(job1, fit_eval)
        self.storage.save_screening_qa(
            job1.opportunity_id, job1.company_name, job1.job_title, job1.screening_qa, job1.drive_screening_doc_link
        )

        # 2. Verify stored state
        saved_opps = self.storage.fetch_all_opportunities()
        self.assertEqual(len(saved_opps), 1)
        self.assertEqual(saved_opps[0]["Company Name"], "Snowflake Solutions")

        saved_qa = self.storage.fetch_screening_qa(job1.opportunity_id)
        self.assertEqual(len(saved_qa), 2)
        self.assertEqual(saved_qa[0]["question"], "Experience with Salesforce?")

        # 3. Test Duplicate Guardrail when attempting same job
        dup_check = ApplicationGuardrailService.check_duplicate(
            "Snowflake Solutions", "Revenue Operations Analyst", saved_opps, repost_threshold_days=60
        )
        self.assertTrue(dup_check["is_duplicate"])
        self.assertFalse(dup_check["is_repost"])

        # 4. Ingest second different role at same company
        job2 = JobPosting(
            opportunity_id="opp_int_2",
            company_name="Snowflake Solutions",
            job_title="GTM Systems Engineer",
            title_family="gtm_engineering",
            raw_description="Salesforce automation and API integrations.",
        )
        self.storage.save_opportunity(job2, fit_eval)

        # 5. Test Velocity Guardrail when attempting 3rd application
        updated_opps = self.storage.fetch_all_opportunities()
        vel_check = ApplicationGuardrailService.check_company_velocity(
            "Snowflake Solutions", updated_opps, max_limit=2, window_days=60
        )
        self.assertTrue(vel_check["velocity_exceeded"])
        self.assertEqual(vel_check["active_count"], 2)


if __name__ == "__main__":
    unittest.main()
