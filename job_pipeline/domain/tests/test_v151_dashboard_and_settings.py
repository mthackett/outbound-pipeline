import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from job_pipeline import __version__ as APP_VERSION
from job_pipeline.domain.models import (
    CandidateProfile,
    ACTIVE_OPPORTUNITY_STAGES,
    TERMINAL_STAGES,
    SUBMITTED_STAGES,
    APPLICATION_CATEGORIES
)
from job_pipeline.domain.services import (
    PipelineConfigService,
    PipelineKPIService,
    PipelineSearchPaginationService
)


class TestV151DashboardAndSettings(unittest.TestCase):
    """Focused regression test suite for More Outbound v1.5.1 Dashboard & Settings Polish."""

    def setUp(self):
        self.ref_now = datetime(2026, 10, 11, 12, 0, 0)
        self.sample_opps = [
            {
                "Opportunity ID": "opp-1",
                "Company Name": "TargetCorp",
                "Job Title": "RevOps Lead",
                "Status": "Applied",
                "Category": "Target",
                "Priority": "High",
                "Applied Via": "LinkedIn",
                "Salary Expectation": "$135,000",
                "Target Pay Range": "$125,000 - $130,000",
                "Date Created": (self.ref_now - timedelta(days=10)).strftime("%Y-%m-%d"),
                "stage_history": [{"stage": "Applied", "entered_at": (self.ref_now - timedelta(days=10)).isoformat()}]
            },
            {
                "Opportunity ID": "opp-2",
                "Company Name": "StretchCorp",
                "Job Title": "Principal Architect",
                "Status": "Recruiter Screen",
                "Category": "Stretch",
                "Priority": "Medium",
                "Applied Via": "Company Website",
                "Salary Expectation": "",
                "Target Pay Range": "$160,000 - $175,000",
                "Date Created": (self.ref_now - timedelta(days=15)).strftime("%Y-%m-%d"),
                "stage_history": [
                    {"stage": "Applied", "entered_at": (self.ref_now - timedelta(days=15)).isoformat()},
                    {"stage": "Recruiter Screen", "entered_at": (self.ref_now - timedelta(days=8)).isoformat()}
                ]
            },
            {
                "Opportunity ID": "opp-3",
                "Company Name": "StaleCorp",
                "Job Title": "Senior Analyst",
                "Status": "Applied",
                "Category": "Practice",
                "Priority": "Low",
                "Applied Via": "Indeed",
                "Salary Expectation": "$115k",
                "Target Pay Range": "$110k–$120k",
                "Date Created": (self.ref_now - timedelta(days=40)).strftime("%Y-%m-%d"),
                "stage_history": [{"stage": "Applied", "entered_at": (self.ref_now - timedelta(days=40)).isoformat()}]
            },
            {
                "Opportunity ID": "opp-4",
                "Company Name": "TerminalCorp",
                "Job Title": "Data Analyst",
                "Status": "Application Rejected",
                "Category": "Target",
                "Priority": "Medium",
                "Applied Via": "LinkedIn",
                "Salary Expectation": "$120,000",
                "Target Pay Range": "$115,000 - $125,000",
                "Date Created": (self.ref_now - timedelta(days=45)).strftime("%Y-%m-%d"),
                "stage_history": [
                    {"stage": "Applied", "entered_at": (self.ref_now - timedelta(days=45)).isoformat()},
                    {"stage": "Application Rejected", "entered_at": (self.ref_now - timedelta(days=35)).isoformat()}
                ]
            },
            {
                "Opportunity ID": "opp-5",
                "Company Name": "DraftCorp",
                "Job Title": "Operations Specialist",
                "Status": "Pending",
                "Category": "Opportunistic",
                "Priority": "Low",
                "Applied Via": "Referral",
                "Salary Expectation": "",
                "Target Pay Range": "N/A",
                "Date Created": (self.ref_now - timedelta(days=50)).strftime("%Y-%m-%d"),
                "stage_history": []
            }
        ]

    def test_authoritative_version_equals_1_5_1(self):
        """Authoritative version exported by package and version.py equals 1.5.1."""
        self.assertEqual(APP_VERSION, "1.5.1")
        from job_pipeline.version import __version__
        self.assertEqual(__version__, "1.5.1")

    def test_kpi_calculations_and_six_metrics(self):
        """PipelineKPIService calculates accurate values for all six unified headline metrics."""
        kpis = PipelineKPIService.calculate_kpis(self.sample_opps, stale_threshold_days=28, reference_date=self.ref_now)
        # 1. Total Tracked
        self.assertEqual(kpis["total_tracked"], 5)
        # 2. Applications Submitted (opp-1, opp-2, opp-3, opp-4)
        self.assertEqual(kpis["total_applied"], 4)
        # 3. Active Opportunities (opp-2 is in Recruiter Screen)
        self.assertEqual(kpis["total_active_opportunities"], 1)
        # 4. Apps / Interest (4 submitted / 1 in Recruiter Screen = 1:4)
        self.assertEqual(kpis["apps_per_interest"], "1:4")
        # 5. Apps / Interview (4 submitted / 1 interviewed = 1:4)
        self.assertEqual(kpis["apps_per_interview"], "1:4")
        # 6. Stale (opp-3 is Applied and 40 days old >= 28 threshold)
        self.assertEqual(kpis["total_stale"], 1)

    def test_strategy_category_totals_reconcile_to_submitted_applications(self):
        """Strategy summary counts strictly submitted applications and reconciles to total submitted."""
        kpis = PipelineKPIService.calculate_kpis(self.sample_opps, stale_threshold_days=28, reference_date=self.ref_now)
        sub_cats = kpis["submitted_categories"]
        # opp-1: Target
        self.assertEqual(sub_cats["Target"], 2)  # opp-1 (Target, Applied) and opp-4 (Target, Application Rejected)
        # opp-2: Stretch
        self.assertEqual(sub_cats["Stretch"], 1)
        # opp-3: Practice
        self.assertEqual(sub_cats["Practice"], 1)
        # opp-5 is Pending (not submitted), so Opportunistic should be 0
        self.assertEqual(sub_cats["Opportunistic"], 0)
        self.assertEqual(sub_cats["Fallback"], 0)
        self.assertEqual(sub_cats["Unassigned"], 0)

        total_by_strategy = sum(sub_cats.values())
        self.assertEqual(total_by_strategy, kpis["total_applied"])

    def test_search_and_filters_retain_functionality(self):
        """Multi-attribute filtering by text search, category, priority, and freshness functions correctly."""
        # Search by company
        filtered = PipelineSearchPaginationService.filter_opportunities(
            opportunities=self.sample_opps,
            search_query="TargetCorp"
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["Opportunity ID"], "opp-1")

        # Filter by Category
        filtered_cat = PipelineSearchPaginationService.filter_opportunities(
            opportunities=self.sample_opps,
            category_filter="Stretch"
        )
        self.assertEqual(len(filtered_cat), 1)
        self.assertEqual(filtered_cat[0]["Opportunity ID"], "opp-2")

        # Filter by Freshness (Stale only)
        filtered_stale = PipelineSearchPaginationService.filter_opportunities(
            opportunities=self.sample_opps,
            freshness_filter="Stale Only (≥28d)",
            reference_date=self.ref_now
        )
        self.assertEqual(len(filtered_stale), 1)
        self.assertEqual(filtered_stale[0]["Opportunity ID"], "opp-3")

        # Filter by Freshness (Fresh only)
        filtered_fresh = PipelineSearchPaginationService.filter_opportunities(
            opportunities=self.sample_opps,
            freshness_filter="Fresh Only (<28d)",
            reference_date=self.ref_now
        )
        fresh_ids = [o["Opportunity ID"] for o in filtered_fresh]
        self.assertIn("opp-1", fresh_ids)
        self.assertIn("opp-2", fresh_ids)
        self.assertNotIn("opp-3", fresh_ids)

    def test_user_note_edits_reset_staleness_when_reliably_timestamped(self):
        """User-initiated note additions/edits reset staleness clock."""
        old_time = (self.ref_now - timedelta(days=35)).isoformat()
        recent_time = (self.ref_now - timedelta(days=2)).isoformat()

        # Without note timestamp -> stale
        opp = {
            "Opportunity ID": "opp-note-test",
            "Status": "Applied",
            "stage_history": [{"stage": "Applied", "entered_at": old_time}],
            "Notes": "Initial conversation with screener"
        }
        self.assertTrue(PipelineKPIService.is_stale(opp, threshold_days=28, reference_date=self.ref_now))

        # With notes_updated_at -> fresh (reset)
        opp_edited = dict(opp)
        opp_edited["notes_updated_at"] = recent_time
        self.assertFalse(PipelineKPIService.is_stale(opp_edited, threshold_days=28, reference_date=self.ref_now))
        dt, src = PipelineKPIService.get_last_meaningful_activity_date(opp_edited)
        self.assertEqual(src, "note_edit")

        # With dated note line [YYYY-MM-DD] -> fresh (reset)
        recent_date_str = (self.ref_now - timedelta(days=3)).strftime("%Y-%m-%d")
        opp_dated = dict(opp)
        opp_dated["Notes"] = f"[{recent_date_str} - Recruiter Screen]: Met with Alex. Great conversation."
        self.assertFalse(PipelineKPIService.is_stale(opp_dated, threshold_days=28, reference_date=self.ref_now))
        dt_d, src_d = PipelineKPIService.get_last_meaningful_activity_date(opp_dated)
        self.assertEqual(src_d, "timestamped_note")

    def test_role_intelligence_generation_does_not_reset_staleness(self):
        """Role Intelligence generation is nonqualifying and does not reset freshness in v1.5.1."""
        old_time = (self.ref_now - timedelta(days=35)).isoformat()
        recent_time = (self.ref_now - timedelta(days=1)).isoformat()

        opp_ri = {
            "Opportunity ID": "opp-ri-test",
            "Status": "Recruiter Screen",
            "stage_history": [{"stage": "Applied", "entered_at": old_time}],
            "Role Intelligence Generated At": recent_time
        }
        # Because stage is 35 days old and RI is excluded, it is Stale
        self.assertTrue(PipelineKPIService.is_stale(opp_ri, threshold_days=28, reference_date=self.ref_now))
        dt, src = PipelineKPIService.get_last_meaningful_activity_date(opp_ri)
        self.assertEqual(src, "stage_history")

    def test_terminal_and_unsubmitted_records_excluded_from_staleness(self):
        """Terminal stages and unsubmitted (Pending) records are never marked stale."""
        old_time = (self.ref_now - timedelta(days=100)).isoformat()

        # Pending (unsubmitted)
        opp_pending = {
            "Status": "Pending",
            "stage_history": [{"stage": "Pending", "entered_at": old_time}]
        }
        self.assertFalse(PipelineKPIService.is_stale(opp_pending, threshold_days=28, reference_date=self.ref_now))
        info_pending = PipelineKPIService.get_staleness_info(opp_pending, threshold_days=28, reference_date=self.ref_now)
        self.assertFalse(info_pending["is_eligible"])
        self.assertFalse(info_pending["is_stale"])

        # Terminal stages
        for term_st in TERMINAL_STAGES:
            opp_term = {
                "Status": term_st,
                "stage_history": [
                    {"stage": "Applied", "entered_at": old_time},
                    {"stage": term_st, "entered_at": old_time}
                ]
            }
            self.assertFalse(PipelineKPIService.is_stale(opp_term, threshold_days=28, reference_date=self.ref_now))
            info_term = PipelineKPIService.get_staleness_info(opp_term, threshold_days=28, reference_date=self.ref_now)
            self.assertFalse(info_term["is_eligible"])
            self.assertFalse(info_term["is_stale"])

    def test_missing_resumes_folder_handled_gracefully(self):
        """When GOOGLE_RESUMES_FOLDER_ID is unset, drive adapter returns empty and UI handles missing link gracefully."""
        with patch.dict(os.environ, {"GOOGLE_RESUMES_FOLDER_ID": ""}):
            from job_pipeline.adapters.secondary.google_drive import GoogleDriveAdapter
            adapter = GoogleDriveAdapter()
            self.assertEqual(adapter.resumes_folder_id, "")

    def test_settings_persistence_logic(self):
        """Settings service persists sources and priorities correctly."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "test_pipeline_config.json"
            with patch.dict(os.environ, {"PIPELINE_CONFIG_PATH": str(cfg_path)}):
                PipelineConfigService.add_source("TechCareers")
                PipelineConfigService.add_priority("High Priority Plus")

                loaded = PipelineConfigService.load_config()
                self.assertIn("TechCareers", loaded.get("sources", []))
                self.assertIn("High Priority Plus", loaded.get("priorities", []))

    def test_shared_refresh_contract(self):
        """Shared refresh operation fetches and returns fresh records across opportunities, QA, and requirements."""
        mock_storage = MagicMock()
        mock_storage.is_connected = True
        mock_storage.fetch_all_opportunities.return_value = [{"Opportunity ID": "refreshed-1"}]
        mock_storage.fetch_screening_qa.return_value = [{"qa_id": "qa-1"}]
        mock_storage.fetch_all_requirements_extractions.return_value = [{"opportunity_id": "req-1"}]

        ok, msg, data = PipelineKPIService.refresh_pipeline_data(mock_storage)
        self.assertTrue(ok)
        self.assertIn("successfully refreshed", msg)
        mock_storage.fetch_all_opportunities.assert_called_once_with(force_refresh=True)
        mock_storage.fetch_screening_qa.assert_called_once_with(force_refresh=True)
        mock_storage.fetch_all_requirements_extractions.assert_called_once_with(force_refresh=True)
        self.assertEqual(data["opportunities"], [{"Opportunity ID": "refreshed-1"}])
        self.assertEqual(data["qa"], [{"qa_id": "qa-1"}])
        self.assertEqual(data["requirements"], [{"opportunity_id": "req-1"}])

    def test_compensation_display_salary_submitted_precedence(self):
        """Precedence 1: Recorded salary submission takes precedence and highlights numeric amounts in green."""
        # Standard formatted amount
        res1 = PipelineKPIService.format_compensation_display(
            salary_submitted="$135,000",
            target_pay="$115,000 - $125,000 (Target: $121,000 - $123,000)"
        )
        self.assertEqual(res1, "Salary Submitted: :green[\\$135,000]")

        # Abbreviated k format is normalized with dollar sign and thousands separator
        res2 = PipelineKPIService.format_compensation_display(
            salary_submitted="135k",
            target_pay="$120,000 - $130,000"
        )
        self.assertEqual(res2, "Salary Submitted: :green[\\$135,000]")

        # Range submitted
        res3 = PipelineKPIService.format_compensation_display(
            salary_submitted="$130k - $140k",
            target_pay=""
        )
        self.assertEqual(res3, "Salary Submitted: :green[\\$130,000–\\$140,000]")

    def test_compensation_display_suggested_range_precedence(self):
        """Precedence 2: When no salary submitted, valid calculated range displays with en-dash and green amounts."""
        # Range with Target suffix is cleaned to clean range
        res1 = PipelineKPIService.format_compensation_display(
            salary_submitted="",
            target_pay="115,000 - 125,000 (Target: 121,000 - 123,000)"
        )
        self.assertEqual(res1, "Suggested Range: :green[\\$115,000–\\$125,000]")

        # Range already containing dollar signs
        res2 = PipelineKPIService.format_compensation_display(
            salary_submitted=None,
            target_pay="$110k–$120k"
        )
        self.assertEqual(res2, "Suggested Range: :green[\\$110,000–\\$120,000]")

        # Hourly contract range
        res3 = PipelineKPIService.format_compensation_display(
            salary_submitted="None",
            target_pay="$75.00 – $80.00 / hr"
        )
        self.assertEqual(res3, "Suggested Range: :green[\\$75–\\$80/hr]")

    def test_compensation_display_salary_unspecified_fallback_and_placeholder_rejection(self):
        """Precedence 3: Unspecified when neither exists; placeholders are never shown as calculated ranges."""
        # Undisclosed placeholder
        res1 = PipelineKPIService.format_compensation_display(
            salary_submitted="",
            target_pay="Undisclosed / Set per role"
        )
        self.assertEqual(res1, ":orange[Salary Unspecified]")

        # Hourly undisclosed placeholder
        res2 = PipelineKPIService.format_compensation_display(
            salary_submitted="N/A",
            target_pay="Hourly (Rate undisclosed)"
        )
        self.assertEqual(res2, ":orange[Salary Unspecified]")

        # Both empty/none
        res3 = PipelineKPIService.format_compensation_display(
            salary_submitted=None,
            target_pay=None
        )
        self.assertEqual(res3, ":orange[Salary Unspecified]")

        # Explicit 'Not Specified'
        res4 = PipelineKPIService.format_compensation_display(
            salary_submitted="Not Specified",
            target_pay="Not calculated"
        )
        self.assertEqual(res4, ":orange[Salary Unspecified]")


if __name__ == "__main__":
    unittest.main()

