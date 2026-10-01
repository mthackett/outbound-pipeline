import unittest
from datetime import datetime
from job_pipeline.domain.services import IngestionRecoveryService
from job_pipeline.adapters.secondary.mock_adapter import MockDocumentStorageAdapter


class TestIncompleteIngestion(unittest.TestCase):
    def setUp(self):
        self.doc_storage = MockDocumentStorageAdapter()

    def test_incomplete_workspace_lifecycle(self):
        # 1. Create a newly created workspace
        ws = self.doc_storage.create_application_workspace("Acme Corp", "Senior Analytics Engineer")
        folder_id = ws["folder_id"]
        folder_link = ws["folder_link"]

        # Upload raw JD text
        raw_jd = "Responsibilities\nLead our revenue data pipeline initiatives, build dbt models, and optimize queries for analytics stakeholders."
        self.doc_storage.upload_raw_job_description(folder_id, raw_jd, company_name="Acme Corp", job_title="Senior Analytics Engineer")

        # 2. Check incomplete detection
        incomplete_list = self.doc_storage.fetch_incomplete_workspaces()
        self.assertEqual(len(incomplete_list), 1)
        item = incomplete_list[0]
        self.assertEqual(item["folder_id"], folder_id)
        self.assertEqual(item["company"], "Acme Corp")
        self.assertEqual(item["title"], "Senior Analytics Engineer")
        self.assertIn("Lead our revenue data pipeline", item["raw_jd_preview"])

        # 3. Mark workspace complete
        self.doc_storage.mark_workspace_complete(folder_id)

        # 4. Incomplete workspaces should now be empty
        self.assertEqual(len(self.doc_storage.fetch_incomplete_workspaces()), 0)

    def test_discard_incomplete_workspace(self):
        ws = self.doc_storage.create_application_workspace("Stripe", "RevOps Analyst")
        folder_id = ws["folder_id"]
        self.doc_storage.upload_raw_job_description(folder_id, "Analyze outbound sales data and automate CRM routing.", company_name="Stripe", job_title="RevOps Analyst")

        self.assertEqual(len(self.doc_storage.fetch_incomplete_workspaces()), 1)

        # Discard the workspace
        deleted = self.doc_storage.delete_application_workspace(folder_id, canonical_opportunities=[])
        self.assertTrue(deleted)

        # Verify it no longer exists
        self.assertEqual(len(self.doc_storage.fetch_incomplete_workspaces()), 0)
        self.assertEqual(self.doc_storage.workspaces[folder_id]["status"], "trashed")

    def test_jd_preview_extraction(self):
        # Test preview with boilerplate at top
        raw_jd = """
        Senior Data Analyst
        MongoDB
        3.5
        New York, NY
        Remote
        $83,000 - $162,000 a year
        Apply on company site
        Job details
        Here's how the job details align with your profile.
        Pay
        $83,000 - $162,000 a year
        Benefits
        Pulled from the full job description
        Responsibilities
        Partner with People teams (business partners, recruiting, culture/talent/development, etc.) to understand their questions, turn analyses into actionable data-driven insights, and make business recommendations
        Requirements
        3+ years of analytics experience
        """
        preview = IngestionRecoveryService.extract_jd_preview(raw_jd, max_chars=140)
        self.assertTrue(preview.endswith("…"))
        self.assertIn("Partner with People teams", preview)
        self.assertIn("turn analyses into actionable data-driven insights", preview)
        # Should be roughly 100-150 characters
        self.assertTrue(80 <= len(preview) <= 160)

    def test_jd_preview_normalization(self):
        # Test newline and whitespace normalization
        messy_text = "Responsibilities\n   Analyze   complex   datasets  \n\n\n  across   all revenue   channels.  "
        preview = IngestionRecoveryService.extract_jd_preview(messy_text)
        self.assertNotIn("\n", preview)
        self.assertNotIn("   ", preview)
        self.assertIn("Analyze complex datasets across all revenue channels.", preview)

    def test_date_formatting(self):
        # ISO timestamp format
        iso_str = "2026-09-30T18:25:08Z"
        formatted = IngestionRecoveryService.format_created_date(iso_str)
        self.assertTrue("Sep" in formatted and "2026" in formatted)

    def test_parse_job_identity(self):
        # Test line parsing
        raw_text = "Senior Data Analyst\nMongoDB\nRemote\n$120,000"
        company, title = IngestionRecoveryService.parse_job_identity(raw_text)
        self.assertEqual(company, "MongoDB")
        self.assertEqual(title, "Senior Data Analyst")

        # Test folder name parsing
        folder_name = "Datadog_Sales_Operations_Manager_2026-09-30"
        comp, role = IngestionRecoveryService.parse_job_identity("", folder_name=folder_name)
        self.assertEqual(comp, "Datadog")
        self.assertEqual(role, "Sales Operations Manager")


if __name__ == "__main__":
    unittest.main()
