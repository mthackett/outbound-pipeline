import unittest
import json
from datetime import datetime
from job_pipeline.domain.models import (
    JobPosting,
    FitEvaluation,
    APPLICATION_CATEGORIES,
    CATEGORY_ICONS,
    APPLICATION_STAGES
)
from job_pipeline.adapters.secondary.mock_adapter import MockJobStorageAdapter


class TestStageHistoryAndCategories(unittest.TestCase):

    def test_application_categories_definitions(self):
        """Verify all 5 strategic application categories exist with expected descriptions."""
        expected_categories = ["Target", "Stretch", "Opportunistic", "Practice", "Fallback"]
        for cat in expected_categories:
            self.assertIn(cat, APPLICATION_CATEGORIES)
            self.assertTrue(len(APPLICATION_CATEGORIES[cat]) > 10)
            self.assertIn(cat, CATEGORY_ICONS)

        self.assertIn("Strong fit and genuinely desirable", APPLICATION_CATEGORIES["Target"])
        self.assertIn("meaningful experience, seniority, domain, or tooling gap", APPLICATION_CATEGORIES["Stretch"])
        self.assertIn("Not part of the normal search profile", APPLICATION_CATEGORIES["Opportunistic"])
        self.assertIn("primarily useful for gaining application/interview reps", APPLICATION_CATEGORIES["Practice"])
        self.assertIn("below your preferred role/compensation/trajectory", APPLICATION_CATEGORIES["Fallback"])

    def test_application_stages_list(self):
        """Verify standard application stages are defined."""
        expected_stages = [
            "Pending", "Processed", "Applied", "Application Rejected",
            "Recruiter Screen", "Hiring Manager",
            "Technical Screen", "Final Round", "Offer",
            "Archived / Rejected"
        ]
        for stage in expected_stages:
            self.assertIn(stage, APPLICATION_STAGES)

    def test_job_posting_category_and_stage_history(self):
        """Verify JobPosting domain model supports category and stage_history."""
        history_entries = [
            {"stage": "Processed", "entered_at": "2026-09-22T08:14:00"},
            {"stage": "Applied", "entered_at": "2026-09-22T08:31:00"},
            {"stage": "Application Rejected", "entered_at": "2026-09-24T14:07:00"}
        ]
        job = JobPosting(
            opportunity_id="opp-test-1",
            company_name="Planful",
            job_title="Sales Operations Analyst",
            title_family="revenue_operations",
            raw_description="Salesforce, SQL, and pipeline analytics.",
            category="Target",
            stage_history=history_entries
        )
        self.assertEqual(job.category, "Target")
        self.assertEqual(len(job.stage_history), 3)
        self.assertEqual(job.stage_history[0]["stage"], "Processed")
        self.assertEqual(job.stage_history[1]["stage"], "Applied")
        self.assertEqual(job.stage_history[2]["stage"], "Application Rejected")

    def test_mock_storage_stage_history_and_category_lifecycle(self):
        """Verify updating status and category updates stage history in storage."""
        storage = MockJobStorageAdapter()
        job = JobPosting(
            opportunity_id="opp-test-lifecycle",
            company_name="Braze",
            job_title="GTM Systems Architect",
            title_family="gtm_engineering",
            raw_description="Architect CRM and pipeline data workflows.",
            status="Processed",
            category="Target",
            stage_history=[{"stage": "Processed", "entered_at": "2026-09-22T08:14:00"}]
        )
        fit_eval = FitEvaluation(status="PASS", is_qualified=True)
        storage.save_opportunity(job, fit_eval)

        # Transition 1: Applied
        new_history = list(job.stage_history)
        new_history.append({"stage": "Applied", "entered_at": "2026-09-22T08:31:00"})
        storage.update_opportunity_status(
            opportunity_id="opp-test-lifecycle",
            status="Applied",
            notes="Applied on company portal.",
            stage_history=new_history,
            category="Target"
        )

        # Fetch and verify
        opps = storage.fetch_all_opportunities()
        target_opp = next(o for o in opps if o["Opportunity ID"] == "opp-test-lifecycle")
        self.assertEqual(target_opp["Status"], "Applied")
        self.assertEqual(target_opp["Category"], "Target")
        self.assertEqual(len(target_opp["Stage History"]), 2)
        self.assertEqual(target_opp["Stage History"][1]["stage"], "Applied")

        # Transition 2: Application Rejected and Category changed to Fallback
        new_history.append({"stage": "Application Rejected", "entered_at": "2026-09-24T14:07:00"})
        storage.update_opportunity_status(
            opportunity_id="opp-test-lifecycle",
            status="Application Rejected",
            notes="Rejected after review.",
            stage_history=new_history,
            category="Fallback"
        )

        opps = storage.fetch_all_opportunities()
        target_opp = next(o for o in opps if o["Opportunity ID"] == "opp-test-lifecycle")
        self.assertEqual(target_opp["Status"], "Application Rejected")
        self.assertEqual(target_opp["Category"], "Fallback")
        self.assertEqual(len(target_opp["Stage History"]), 3)
        self.assertEqual(target_opp["Stage History"][2]["stage"], "Application Rejected")
        self.assertEqual(target_opp["Stage History"][2]["entered_at"], "2026-09-24T14:07:00")

    def test_stage_history_json_serialization(self):
        """Verify serialization to and from JSON matches Google Sheets format."""
        stage_history = [
            {"stage": "Processed", "entered_at": "2026-09-22T08:14:00"},
            {"stage": "Applied", "entered_at": "2026-09-22T08:31:00"},
            {"stage": "Application Rejected", "entered_at": "2026-09-24T14:07:00"},
        ]
        json_str = json.dumps(stage_history)
        deserialized = json.loads(json_str)
        self.assertEqual(stage_history, deserialized)
        self.assertEqual(deserialized[0]["stage"], "Processed")
        self.assertEqual(deserialized[1]["stage"], "Applied")
        self.assertEqual(deserialized[2]["stage"], "Application Rejected")

    def test_job_posting_source_and_priority_attributes(self):
        """Verify JobPosting supports applied_via and priority attributes."""
        job = JobPosting(
            opportunity_id="opp-test-src",
            company_name="Snowflake",
            job_title="RevOps Lead",
            title_family="revenue_operations",
            raw_description="SQL and Salesforce.",
            applied_via="LinkedIn",
            priority="High"
        )
        self.assertEqual(job.applied_via, "LinkedIn")
        self.assertEqual(job.priority, "High")

    def test_sources_and_priorities_config_service(self):
        """Verify PipelineConfigService can load, add, and save sources and priorities."""
        import os
        from job_pipeline.domain.services import PipelineConfigService
        test_cfg_path = "test_pipeline_config.json"
        try:
            if os.path.exists(test_cfg_path):
                os.remove(test_cfg_path)

            cfg = PipelineConfigService.load_config(test_cfg_path)
            self.assertIn("LinkedIn", cfg["sources"])
            self.assertIn("Indeed", cfg["sources"])
            self.assertIn("ZipRecruiter", cfg["sources"])
            self.assertIn("Company Website", cfg["sources"])
            self.assertIn("High", cfg["priorities"])
            self.assertIn("Medium", cfg["priorities"])
            self.assertIn("Low", cfg["priorities"])

            # Add a new source
            updated_sources = PipelineConfigService.add_source("Wellfound", test_cfg_path)
            self.assertIn("Wellfound", updated_sources)

            # Add a new priority
            updated_priorities = PipelineConfigService.add_priority("Critical", test_cfg_path)
            self.assertIn("Critical", updated_priorities)

            # Reload to verify persistence
            reloaded = PipelineConfigService.load_config(test_cfg_path)
            self.assertIn("Wellfound", reloaded["sources"])
            self.assertIn("Critical", reloaded["priorities"])
        finally:
            if os.path.exists(test_cfg_path):
                os.remove(test_cfg_path)

    def test_mock_storage_source_and_priority_lifecycle(self):
        """Verify updating source and priority in storage."""
        storage = MockJobStorageAdapter()
        job = JobPosting(
            opportunity_id="opp-test-attrs",
            company_name="Datadog",
            job_title="GTM Ops Analyst",
            title_family="revenue_operations",
            raw_description="DataDog RevOps.",
            status="Applied",
            applied_via="LinkedIn",
            priority="High"
        )
        fit_eval = FitEvaluation(status="PASS", is_qualified=True)
        storage.save_opportunity(job, fit_eval)

        # Update attributes
        storage.update_opportunity_status(
            opportunity_id="opp-test-attrs",
            status="Recruiter Screen",
            applied_via="Company Website",
            priority="Medium"
        )

        opps = storage.fetch_all_opportunities()
        target_opp = next(o for o in opps if o["Opportunity ID"] == "opp-test-attrs")
        self.assertEqual(target_opp["Applied Via"], "Company Website")
        self.assertEqual(target_opp["Priority"], "Medium")


if __name__ == "__main__":
    unittest.main()
