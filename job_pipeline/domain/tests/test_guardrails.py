import unittest
from datetime import datetime, timedelta
from job_pipeline.domain.models import CandidateProfile
from job_pipeline.domain.services import ApplicationGuardrailService, JobQualificationService


class TestApplicationGuardrailService(unittest.TestCase):

    def setUp(self):
        self.today = datetime.now()
        self.profile = CandidateProfile(
            max_company_applications_limit=2,
            company_application_window_days=60,
            repost_detection_threshold_days=60
        )

    def test_duplicate_recent_detection(self):
        recent_date = (self.today - timedelta(days=15)).strftime("%Y-%m-%d")
        existing_records = [
            {
                "Company Name": "Acme RevOps",
                "Job Title": "Sales Operations Analyst",
                "Date Created": recent_date,
                "Status": "Processed"
            }
        ]

        dup_res = ApplicationGuardrailService.check_duplicate(
            company_name="Acme RevOps",
            job_title="Sales Operations Analyst",
            existing_records=existing_records,
            repost_threshold_days=60
        )

        self.assertTrue(dup_res["is_duplicate"])
        self.assertFalse(dup_res["is_repost"])
        self.assertEqual(dup_res["days_elapsed"], 15)
        self.assertIn("Duplicate Application Detected", dup_res["warning"])

    def test_duplicate_repost_detection(self):
        old_date = (self.today - timedelta(days=75)).strftime("%Y-%m-%d")
        existing_records = [
            {
                "Company Name": "Acme RevOps",
                "Job Title": "Sales Operations Analyst",
                "Date Created": old_date,
                "Status": "Processed"
            }
        ]

        dup_res = ApplicationGuardrailService.check_duplicate(
            company_name="Acme RevOps",
            job_title="Sales Operations Analyst",
            existing_records=existing_records,
            repost_threshold_days=60
        )

        self.assertTrue(dup_res["is_duplicate"])
        self.assertTrue(dup_res["is_repost"])
        self.assertGreaterEqual(dup_res["days_elapsed"], 60)
        self.assertIn("Potential Repost / Reopened Requisition", dup_res["warning"])

    def test_company_velocity_within_limit(self):
        d1 = (self.today - timedelta(days=20)).strftime("%Y-%m-%d")
        existing_records = [
            {
                "Company Name": "CloudScale Inc",
                "Job Title": "GTM Systems Engineer",
                "Date Created": d1,
                "Status": "Processed"
            }
        ]

        vel_res = ApplicationGuardrailService.check_company_velocity(
            company_name="CloudScale Inc",
            existing_records=existing_records,
            max_limit=2,
            window_days=60
        )

        self.assertFalse(vel_res["velocity_exceeded"])
        self.assertEqual(vel_res["active_count"], 1)

    def test_company_velocity_exceeded(self):
        d1 = (self.today - timedelta(days=10)).strftime("%Y-%m-%d")
        d2 = (self.today - timedelta(days=25)).strftime("%Y-%m-%d")
        existing_records = [
            {
                "Company Name": "CloudScale Inc",
                "Job Title": "GTM Systems Engineer",
                "Date Created": d1,
                "Status": "Processed"
            },
            {
                "Company Name": "CloudScale Inc",
                "Job Title": "RevOps Analyst",
                "Date Created": d2,
                "Status": "Processed"
            }
        ]

        vel_res = ApplicationGuardrailService.check_company_velocity(
            company_name="CloudScale Inc",
            existing_records=existing_records,
            max_limit=2,
            window_days=60
        )

        self.assertTrue(vel_res["velocity_exceeded"])
        self.assertEqual(vel_res["active_count"], 2)
        self.assertIn("Company Application Cap Warning", vel_res["warning"])

    def test_job_qualification_service_integration(self):
        recent_date = (self.today - timedelta(days=5)).strftime("%Y-%m-%d")
        existing = [
            {"Company Name": "TestCo", "Job Title": "RevOps Lead", "Date Created": recent_date}
        ]
        eval_res = JobQualificationService.evaluate(
            company_name="TestCo",
            job_title="RevOps Lead",
            raw_description="Salesforce SQL dbt experience",
            required_skills=["Salesforce", "SQL"],
            existing_company_titles=existing,
            profile=self.profile
        )
        self.assertEqual(eval_res.status, "FLAGGED_DUPLICATE")
        self.assertFalse(eval_res.is_qualified)
        self.assertTrue(eval_res.duplicate_detected)


if __name__ == "__main__":
    unittest.main()
