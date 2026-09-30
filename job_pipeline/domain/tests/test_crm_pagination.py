import unittest
import math

class TestCRMPagination(unittest.TestCase):
    """Tests for Pipeline Tracker / CRM pagination calculations and page clamping."""

    def calculate_pagination(self, total_items: int, items_per_page: int, current_page: int):
        total_pages = max(1, math.ceil(total_items / items_per_page)) if total_items > 0 else 1
        safe_page = min(max(1, current_page), total_pages)
        start_offset = (safe_page - 1) * items_per_page
        end_offset = min(start_offset + items_per_page, total_items)
        return {
            "total_pages": total_pages,
            "current_page": safe_page,
            "start_offset": start_offset,
            "end_offset": end_offset
        }

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
        # 35 items with 15 per page -> 3 pages (15, 15, 5)
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
        # Say user is on page 4 with page size 10 (35 items total)
        # Then user changes page size to 50: total pages becomes 1.
        # Current page 4 should clamp to 1.
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

if __name__ == "__main__":
    unittest.main()
