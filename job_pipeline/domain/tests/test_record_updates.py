import unittest
from job_pipeline.domain.models import JobPosting, FitEvaluation, TargetPayBounds, ScreeningQA
from job_pipeline.adapters.secondary.mock_adapter import MockJobStorageAdapter


class TestRecordMetadataUpdates(unittest.TestCase):

    def setUp(self):
        self.storage = MockJobStorageAdapter()
        self.opp_id = "opp-1001"
        self.job = JobPosting(
            opportunity_id=self.opp_id,
            company_name="Inferred Company",
            job_title="AI Strategy and Workflow Developer",
            title_family="revenue_operations",
            raw_description="Manage sales operations and CRM data.",
            source_url="https://linkedin.com/jobs/view/123",
            category="Target",
            status="Processed",
            stage_history=[{"stage": "Processed", "entered_at": "2026-09-20T10:00:00"}]
        )
        self.fit_eval = FitEvaluation(
            status="PASS",
            is_qualified=True,
            pay_bounds=TargetPayBounds(display_range="$100,000 - $120,000")
        )
        self.storage.save_opportunity(self.job, self.fit_eval)
        self.storage.save_screening_qa(
            opportunity_id=self.opp_id,
            company_name="Inferred Company",
            job_title="AI Strategy and Workflow Developer",
            qa_items=[ScreeningQA(question="Years of RevOps?", answer=5)]
        )

    def test_update_job_title_and_company_preserves_canonical_record(self):
        """User corrects wrongly inferred title and company name without creating duplicate records."""
        # 1. Verify initial state
        all_opps = self.storage.fetch_all_opportunities()
        self.assertEqual(len(all_opps), 1)
        self.assertEqual(all_opps[0]["Job Title"], "AI Strategy and Workflow Developer")
        self.assertEqual(all_opps[0]["Company Name"], "Inferred Company")

        # 2. Perform user edit
        success = self.storage.update_opportunity_status(
            opportunity_id=self.opp_id,
            status="Applied",
            company_name="Sales & AI Corp",
            job_title="Sales and AI Operations",
            target_pay_range="$120,000 - $135,000",
            source_url="https://company.com/careers/456",
            stage_history=[
                {"stage": "Processed", "entered_at": "2026-09-20T10:00:00"},
                {"stage": "Applied", "entered_at": "2026-09-22T14:30:00"}
            ]
        )
        self.assertTrue(success)

        # 3. Verify exactly one record exists with the updated metadata
        updated_opps = self.storage.fetch_all_opportunities()
        self.assertEqual(len(updated_opps), 1)
        rec = updated_opps[0]
        self.assertEqual(rec["Opportunity ID"], self.opp_id)
        self.assertEqual(rec["Company Name"], "Sales & AI Corp")
        self.assertEqual(rec["Job Title"], "Sales and AI Operations")
        self.assertEqual(rec["Target Pay Range"], "$120,000 - $135,000")
        self.assertEqual(rec["Status"], "Applied")
        self.assertEqual(len(rec["stage_history"]), 2)

        # 4. Verify screening questions are still linked to the same Opportunity ID
        qa_records = self.storage.fetch_screening_qa(self.opp_id)
        self.assertEqual(len(qa_records), 1)
        self.assertEqual(qa_records[0]["opportunity_id"], self.opp_id)
        self.assertEqual(qa_records[0]["answer"], "5")

    def test_pagination_calculation_and_clamping(self):
        """Tests pagination math when total items and page size change."""
        def calc_pages(total_items: int, page_size: int) -> int:
            return max(1, (total_items + page_size - 1) // page_size)

        def clamp_page(current_page: int, total_pages: int) -> int:
            if current_page > total_pages:
                return total_pages
            if current_page < 1:
                return 1
            return current_page

        # With 30 items:
        # At page size 6 -> 5 pages
        self.assertEqual(calc_pages(30, 6), 5)
        # At default page size 15 -> 2 pages
        self.assertEqual(calc_pages(30, 15), 2)
        # At page size 25 -> 2 pages
        self.assertEqual(calc_pages(30, 25), 2)
        # At page size 50 -> 1 page
        self.assertEqual(calc_pages(30, 50), 1)

        # Clamping when switching page size from 6 (was on page 5) to 15 (only 2 pages exist)
        total_p = calc_pages(30, 15)
        clamped = clamp_page(5, total_p)
        self.assertEqual(clamped, 2)


if __name__ == "__main__":
    unittest.main()
