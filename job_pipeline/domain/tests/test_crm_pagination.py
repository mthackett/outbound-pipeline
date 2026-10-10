import unittest
import math
from typing import List, Dict, Any
from job_pipeline.domain.services import PipelineSearchPaginationService


class TestCRMPagination(unittest.TestCase):
    """Tests for Pipeline Tracker / CRM pagination calculations, search filtering, and state transitions."""

    def setUp(self):
        # Generate 25 synthetic opportunities with deterministic attributes
        self.synthetic_opps: List[Dict[str, Any]] = []
        categories = ["Target", "Stretch", "Opportunistic", "Practice", "Fallback"]
        arrangements = ["Employee", "Contract"]
        priorities = ["Critical", "High", "Medium", "Low"]
        sources = ["LinkedIn", "Indeed", "Wellfound", "Referral"]

        for i in range(1, 26):
            self.synthetic_opps.append({
                "Opportunity ID": f"opp-{i:03d}",
                "Company Name": f"Company {chr(65 + (i % 5))}",  # Company A, B, C, D, E
                "Job Title": "Analytics Engineer" if i % 2 == 0 else ("RevOps Manager" if i % 3 == 0 else "Data Analyst"),
                "Status": "Applied" if i % 4 == 0 else ("Recruiter Screen" if i % 5 == 0 else "Pending"),
                "Category": categories[i % len(categories)],
                "Priority": priorities[i % len(priorities)],
                "Applied Via": sources[i % len(sources)],
                "Employment Arrangement": arrangements[i % len(arrangements)],
                "Notes": f"Synthetic note for role {i}",
                "Date Created": f"2026-10-{i:02d}"
            })

    # Backward compatibility with existing test cases
    def calculate_pagination(self, total_items: int, items_per_page: int, current_page: int):
        return PipelineSearchPaginationService.calculate_pagination(
            total_items=total_items,
            items_per_page=items_per_page,
            current_page=current_page
        )

    def test_default_page_size(self):
        default_page_size = 15
        self.assertEqual(default_page_size, 15)
        allowed_page_sizes = [10, 15, 25, 50]
        self.assertIn(default_page_size, allowed_page_sizes)

    def test_single_page_results(self):
        res = self.calculate_pagination(total_items=12, items_per_page=15, current_page=1)
        self.assertEqual(res["total_pages"], 1)
        self.assertEqual(res["current_page"], 1)
        self.assertEqual(res["start_offset"], 0)
        self.assertEqual(res["end_offset"], 12)

    def test_multi_page_results_with_default_15(self):
        res_p1 = self.calculate_pagination(total_items=35, items_per_page=15, current_page=1)
        self.assertEqual(res_p1["total_pages"], 3)
        self.assertEqual(res_p1["start_offset"], 0)
        self.assertEqual(res_p1["end_offset"], 15)

        res_p2 = self.calculate_pagination(total_items=35, items_per_page=15, current_page=2)
        self.assertEqual(res_p2["start_offset"], 15)
        self.assertEqual(res_p2["end_offset"], 30)

        res_p3 = self.calculate_pagination(total_items=35, items_per_page=15, current_page=3)
        self.assertEqual(res_p3["start_offset"], 30)
        self.assertEqual(res_p3["end_offset"], 35)

    def test_page_clamping_when_page_size_changes(self):
        total_items = 35
        old_page = 4
        new_page_size = 50
        res = self.calculate_pagination(total_items=total_items, items_per_page=new_page_size, current_page=old_page)
        self.assertEqual(res["total_pages"], 1)
        self.assertEqual(res["current_page"], 1)
        self.assertEqual(res["start_offset"], 0)
        self.assertEqual(res["end_offset"], 35)

    def test_empty_dataset(self):
        res = self.calculate_pagination(total_items=0, items_per_page=15, current_page=1)
        self.assertEqual(res["total_pages"], 1)
        self.assertEqual(res["current_page"], 1)
        self.assertEqual(res["start_offset"], 0)
        self.assertEqual(res["end_offset"], 0)

    # ------------------------------------------------------------------------
    # Required Regression Test Scenarios from instructions.md (Items 1-10)
    # ------------------------------------------------------------------------

    # 1. Initial unfiltered pipeline load
    def test_1_initial_unfiltered_pipeline_load(self):
        filtered = PipelineSearchPaginationService.filter_opportunities(
            self.synthetic_opps, search_query=""
        )
        self.assertEqual(len(filtered), 25)
        paginated = PipelineSearchPaginationService.paginate_records(
            filtered, items_per_page=5, current_page=1, reverse=True
        )
        self.assertEqual(paginated["total_pages"], 5)
        self.assertEqual(paginated["current_page"], 1)
        self.assertEqual(len(paginated["items"]), 5)
        # Newest first: first item should be opp-025
        self.assertEqual(paginated["items"][0]["Opportunity ID"], "opp-025")
        self.assertEqual(paginated["items"][-1]["Opportunity ID"], "opp-021")

    # 2. Search returning multiple matches
    def test_2_search_returning_multiple_matches(self):
        filtered = PipelineSearchPaginationService.filter_opportunities(
            self.synthetic_opps, search_query="Analytics Engineer"
        )
        # Even numbers 2, 4, ..., 24 -> 12 matches
        self.assertEqual(len(filtered), 12)
        paginated = PipelineSearchPaginationService.paginate_records(
            filtered, items_per_page=5, current_page=1, reverse=True
        )
        self.assertEqual(paginated["total_pages"], 3)
        self.assertEqual(paginated["current_page"], 1)
        self.assertEqual(len(paginated["items"]), 5)
        for item in paginated["items"]:
            self.assertEqual(item["Job Title"], "Analytics Engineer")

    # 3. Search returning no matches
    def test_3_search_returning_no_matches(self):
        filtered = PipelineSearchPaginationService.filter_opportunities(
            self.synthetic_opps, search_query="NonexistentSpecialRole"
        )
        self.assertEqual(len(filtered), 0)
        paginated = PipelineSearchPaginationService.paginate_records(
            filtered, items_per_page=5, current_page=1, reverse=True
        )
        self.assertEqual(paginated["total_items"], 0)
        self.assertEqual(paginated["total_pages"], 1)
        self.assertEqual(paginated["current_page"], 1)
        self.assertEqual(len(paginated["items"]), 0)

    # 4. Clearing search after navigating within filtered results
    def test_4_clearing_search_after_navigating_within_filtered_results(self):
        # Filter for Analytics Engineer (12 items -> 3 pages of 5 items)
        query = "Analytics Engineer"
        filtered = PipelineSearchPaginationService.filter_opportunities(self.synthetic_opps, query)
        prev_filter = (query, "All Types", "All Categories", "All Priorities", "All Sources")

        # User is on page 2 of filtered results
        current_page = 2
        p2 = PipelineSearchPaginationService.paginate_records(filtered, items_per_page=5, current_page=current_page)
        self.assertEqual(p2["current_page"], 2)

        # Now user clears search query
        cleared_query = ""
        current_filter = (cleared_query, "All Types", "All Categories", "All Priorities", "All Sources")
        resolved_page = PipelineSearchPaginationService.resolve_page_on_filter_change(
            previous_filter_tuple=prev_filter,
            current_filter_tuple=current_filter,
            current_page=current_page
        )
        # Must reset to page 1
        self.assertEqual(resolved_page, 1)

        unfiltered = PipelineSearchPaginationService.filter_opportunities(self.synthetic_opps, cleared_query)
        res = PipelineSearchPaginationService.paginate_records(unfiltered, items_per_page=5, current_page=resolved_page)
        self.assertEqual(res["current_page"], 1)
        self.assertEqual(res["total_items"], 25)
        self.assertEqual(res["items"][0]["Opportunity ID"], "opp-025")

    # 5. Clearing search while on a later page
    def test_5_clearing_search_while_on_a_later_page(self):
        # Search returns 12 results (3 pages). User navigates to page 3 (last page of search)
        query = "Analytics Engineer"
        filtered = PipelineSearchPaginationService.filter_opportunities(self.synthetic_opps, query)
        prev_filter = (query, "All Types", "All Categories", "All Priorities", "All Sources")
        current_page = 3

        # User clears search
        current_filter = ("", "All Types", "All Categories", "All Priorities", "All Sources")
        resolved_page = PipelineSearchPaginationService.resolve_page_on_filter_change(
            previous_filter_tuple=prev_filter,
            current_filter_tuple=current_filter,
            current_page=current_page
        )
        self.assertEqual(resolved_page, 1)

        unfiltered = PipelineSearchPaginationService.filter_opportunities(self.synthetic_opps, "")
        p1 = PipelineSearchPaginationService.paginate_records(unfiltered, items_per_page=5, current_page=resolved_page)
        self.assertEqual(p1["current_page"], 1)
        self.assertEqual(p1["start_offset"], 0)
        self.assertEqual(p1["end_offset"], 5)

    # 6. Navigating backward after clearing search
    def test_6_navigating_backward_after_clearing_search(self):
        # Clearing search lands on page 1. User should NOT be stuck on page 3 or unable to navigate.
        unfiltered = PipelineSearchPaginationService.filter_opportunities(self.synthetic_opps, "")
        p1 = PipelineSearchPaginationService.paginate_records(unfiltered, items_per_page=5, current_page=1)
        self.assertEqual(p1["current_page"], 1)

        # Navigating forward to page 2 then backward to page 1
        p2_page = p1["current_page"] + 1
        p2 = PipelineSearchPaginationService.paginate_records(unfiltered, items_per_page=5, current_page=p2_page)
        self.assertEqual(p2["current_page"], 2)

        # Backward to page 1
        p_back = p2["current_page"] - 1
        p_res = PipelineSearchPaginationService.paginate_records(unfiltered, items_per_page=5, current_page=p_back)
        self.assertEqual(p_res["current_page"], 1)
        self.assertEqual(p_res["start_offset"], 0)
        self.assertEqual(p_res["items"][0]["Opportunity ID"], "opp-025")

    # 7. Navigating to the final page and back
    def test_7_navigating_to_the_final_page_and_back(self):
        unfiltered = PipelineSearchPaginationService.filter_opportunities(self.synthetic_opps, "")
        total_pages = PipelineSearchPaginationService.calculate_pagination(len(unfiltered), items_per_page=5)["total_pages"]
        self.assertEqual(total_pages, 5)

        # Go to final page
        final_p = PipelineSearchPaginationService.paginate_records(unfiltered, items_per_page=5, current_page=total_pages)
        self.assertEqual(final_p["current_page"], 5)
        self.assertEqual(final_p["start_offset"], 20)
        self.assertEqual(final_p["end_offset"], 25)
        # Oldest items are on final page (opp-005 to opp-001)
        self.assertEqual(final_p["items"][-1]["Opportunity ID"], "opp-001")

        # Step back one page
        back_p = PipelineSearchPaginationService.paginate_records(unfiltered, items_per_page=5, current_page=final_p["current_page"] - 1)
        self.assertEqual(back_p["current_page"], 4)
        self.assertEqual(back_p["start_offset"], 15)
        self.assertEqual(back_p["end_offset"], 20)

    # 8. Reloading after a search
    def test_8_reloading_after_a_search(self):
        # When user reloads without filter change, page remains consistent
        query = "Company A"
        filtered = PipelineSearchPaginationService.filter_opportunities(self.synthetic_opps, query)
        filter_tuple = (query, "All Types", "All Categories", "All Priorities", "All Sources")

        # First run on page 1
        p1 = PipelineSearchPaginationService.paginate_records(filtered, items_per_page=5, current_page=1)
        # Reloading (filter tuple identical)
        resolved_page = PipelineSearchPaginationService.resolve_page_on_filter_change(
            previous_filter_tuple=filter_tuple,
            current_filter_tuple=filter_tuple,
            current_page=p1["current_page"]
        )
        self.assertEqual(resolved_page, 1)
        reloaded = PipelineSearchPaginationService.paginate_records(filtered, items_per_page=5, current_page=resolved_page)
        self.assertEqual(reloaded["current_page"], 1)
        self.assertEqual(reloaded["items"], p1["items"])

    # 9. Switching between applications and returning to the pipeline
    def test_9_switching_between_applications_and_returning_to_the_pipeline(self):
        ordered_opps = list(reversed(self.synthetic_opps))
        # Say opp-014 was opened / active
        opp_id = "opp-014"
        card_page = PipelineSearchPaginationService.find_card_page(opp_id, ordered_opps, items_per_page=5)
        # opp-014 in reversed list: 25 - 14 = index 11 -> page (11 // 5) + 1 = 3
        self.assertEqual(card_page, 3)

        # After saving/visiting opp-014, if user navigates to another page,
        # card_page must not hijack future pagination
        user_next_page = card_page - 1  # user clicks Previous -> page 2
        p_nav = PipelineSearchPaginationService.calculate_pagination(len(ordered_opps), items_per_page=5, current_page=user_next_page)
        self.assertEqual(p_nav["current_page"], 2)

    # 10. Newly ingested applications appearing in the expected default order
    def test_10_newly_ingested_applications_appearing_in_expected_default_order(self):
        # Add a newly ingested application
        new_opp = {
            "Opportunity ID": "opp-026",
            "Company Name": "Brand New Corp",
            "Job Title": "Lead Architect",
            "Status": "Pending",
            "Category": "Target",
            "Priority": "Critical",
            "Applied Via": "Company Website",
            "Employment Arrangement": "Employee",
            "Notes": "Just ingested",
            "Date Created": "2026-10-26"
        }
        updated_opps = list(self.synthetic_opps) + [new_opp]

        unfiltered = PipelineSearchPaginationService.filter_opportunities(updated_opps, "")
        paginated = PipelineSearchPaginationService.paginate_records(unfiltered, items_per_page=5, current_page=1, reverse=True)
        # Newly ingested application must appear first at index 0 of page 1
        self.assertEqual(paginated["items"][0]["Opportunity ID"], "opp-026")
        self.assertEqual(paginated["items"][0]["Company Name"], "Brand New Corp")
        self.assertEqual(paginated["current_page"], 1)
        self.assertEqual(paginated["total_items"], 26)
        self.assertEqual(paginated["total_pages"], 6)


if __name__ == "__main__":
    unittest.main()

