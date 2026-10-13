"""Automated test suite for More Outbound v1.5.2: Inbound Intake, Opportunity Source & Analytics Dashboard."""

import unittest
from datetime import datetime, timedelta
from typing import Dict, Any, List

from job_pipeline.domain.models import (
    JobPosting,
    AUTHORITATIVE_PIPELINE_STAGES,
    APPLICATION_STAGES,
    TERMINAL_STAGES
)
from job_pipeline.domain.services import (
    PipelineKPIService,
    PipelineSearchPaginationService
)
from job_pipeline.adapters.secondary.mock_adapter import MockJobStorageAdapter


class TestV152InboundAndAnalytics(unittest.TestCase):
    """Verifies domain rules, denominators, persistence, and filtering for v1.5.2."""

    def setUp(self):
        self.ref_now = datetime(2026, 10, 12, 12, 0, 0)

    def test_new_lead_in_authoritative_stages(self):
        """Verify 'New Lead' is recognized in pipeline stages."""
        self.assertIn("New Lead", AUTHORITATIVE_PIPELINE_STAGES)
        self.assertIn("New Lead", APPLICATION_STAGES)

    def test_contact_only_and_company_only_inbound_models(self):
        """Verify contact-only and company-only inbound leads instantiate without validation errors."""
        # 1. Contact-only inbound lead (no company, no title)
        lead_contact_only = JobPosting(
            opportunity_id="lead-001",
            company_name="",
            job_title="",
            contact_name="Sarah Jenkins (Recruiter)",
            opportunity_source="Inbound",
            notes="Reached out via LinkedIn",
            stage_history=[{"stage": "New Lead", "entered_at": self.ref_now.isoformat()}]
        )
        self.assertEqual(lead_contact_only.opportunity_source, "Inbound")
        self.assertEqual(lead_contact_only.contact_name, "Sarah Jenkins (Recruiter)")
        self.assertEqual(lead_contact_only.company_name, "")
        self.assertEqual(lead_contact_only.job_title, "")

        # 2. Company-only inbound lead (company specified, no contact)
        lead_company_only = JobPosting(
            opportunity_id="lead-002",
            company_name="Acme Corp",
            job_title="",
            contact_name=None,
            opportunity_source="Inbound",
            stage_history=[{"stage": "New Lead", "entered_at": self.ref_now.isoformat()}]
        )
        self.assertEqual(lead_company_only.opportunity_source, "Inbound")
        self.assertEqual(lead_company_only.company_name, "Acme Corp")
        self.assertIsNone(lead_company_only.contact_name)

        # 3. Default job posting is Outbound
        outbound_job = JobPosting(
            opportunity_id="out-001",
            company_name="Stripe",
            job_title="RevOps Analyst"
        )
        self.assertEqual(outbound_job.opportunity_source, "Outbound")

    def test_mock_storage_adapter_persistence_and_update(self):
        """Verify MockJobStorageAdapter persists and updates Opportunity Source and Contact Name."""
        adapter = MockJobStorageAdapter()
        now_iso = self.ref_now.isoformat()

        lead = JobPosting(
            opportunity_id="lead-100",
            company_name="Braze",
            job_title="Lead RevOps",
            contact_name="Dave Miller",
            opportunity_source="Inbound",
            stage_history=[{"stage": "New Lead", "entered_at": now_iso}]
        )
        saved = adapter.save_opportunity(lead, None)
        self.assertTrue(saved)

        all_opps = adapter.fetch_all_opportunities()
        saved_opp = next((o for o in all_opps if o.get("Opportunity ID") == "lead-100"), None)
        self.assertIsNotNone(saved_opp)
        self.assertEqual(saved_opp.get("Opportunity Source"), "Inbound")
        self.assertEqual(saved_opp.get("Contact Name"), "Dave Miller")

        # Update opportunity details
        updated = adapter.update_opportunity_status(
            opportunity_id="lead-100",
            status="Recruiter Screen",
            contact_name="David Miller (VP)",
            opportunity_source="Inbound"
        )
        self.assertTrue(updated)

        all_opps_refreshed = adapter.fetch_all_opportunities()
        upd_opp = next((o for o in all_opps_refreshed if o.get("Opportunity ID") == "lead-100"), None)
        self.assertEqual(upd_opp.get("Status"), "Recruiter Screen")
        self.assertEqual(upd_opp.get("Contact Name"), "David Miller (VP)")
        self.assertEqual(upd_opp.get("Opportunity Source"), "Inbound")

    def test_search_and_pagination_filtering_by_opportunity_source_and_contact(self):
        """Verify PipelineSearchPaginationService filters by Opportunity Source and searches Contact Name."""
        sample_data = [
            {
                "Opportunity ID": "1",
                "Company Name": "Alpha Corp",
                "Job Title": "Analyst",
                "Contact Name": "Alice Smith",
                "Opportunity Source": "Outbound",
                "Status": "Applied",
                "Category": "Target"
            },
            {
                "Opportunity ID": "2",
                "Company Name": "Beta LLC",
                "Job Title": "Manager",
                "Contact Name": "Bob Jones",
                "Opportunity Source": "Inbound",
                "Status": "New Lead",
                "Category": "Target"
            },
            {
                "Opportunity ID": "3",
                "Company Name": "",
                "Job Title": "",
                "Contact Name": "Charlie Recruiter",
                "Opportunity Source": "Inbound",
                "Status": "New Lead",
                "Category": "Target"
            }
        ]

        # 1. Source filter: Inbound only
        inbound_res = PipelineSearchPaginationService.filter_opportunities(
            sample_data,
            opportunity_source_filter="Inbound"
        )
        self.assertEqual(len(inbound_res), 2)
        self.assertTrue(all(o.get("Opportunity Source") == "Inbound" for o in inbound_res))

        # 2. Source filter: Outbound only
        outbound_res = PipelineSearchPaginationService.filter_opportunities(
            sample_data,
            opportunity_source_filter="Outbound"
        )
        self.assertEqual(len(outbound_res), 1)
        self.assertEqual(outbound_res[0]["Opportunity ID"], "1")

        # 3. Search query matching Contact Name
        search_res = PipelineSearchPaginationService.filter_opportunities(
            sample_data,
            search_query="Charlie"
        )
        self.assertEqual(len(search_res), 1)
        self.assertEqual(search_res[0]["Contact Name"], "Charlie Recruiter")

    def test_analytics_dashboard_metrics_denominators(self):
        """
        Verify source-specific denominators:
        - Outbound conversion = interviewed outbound / submitted outbound
        - Inbound conversion = interviewed inbound / tracked inbound
        Adding unsubmitted inbound leads must not distort outbound metrics.
        """
        test_opps = [
            # 2 Outbound applications: 1 submitted, 1 interviewed (100% conversion)
            {
                "Opportunity ID": "out-1",
                "Company Name": "Target A",
                "Job Title": "RevOps",
                "Opportunity Source": "Outbound",
                "Status": "Applied",
                "Date Created": (self.ref_now - timedelta(days=5)).strftime("%Y-%m-%d"),
                "stage_history": [{"stage": "Applied", "entered_at": (self.ref_now - timedelta(days=5)).isoformat()}]
            },
            {
                "Opportunity ID": "out-2",
                "Company Name": "Target B",
                "Job Title": "GTM Ops",
                "Opportunity Source": "Outbound",
                "Status": "Recruiter Screen",
                "Date Created": (self.ref_now - timedelta(days=10)).strftime("%Y-%m-%d"),
                "stage_history": [
                    {"stage": "Applied", "entered_at": (self.ref_now - timedelta(days=10)).isoformat()},
                    {"stage": "Recruiter Screen", "entered_at": (self.ref_now - timedelta(days=2)).isoformat()}
                ]
            },
            # 5 Inbound leads: 1 reached interview, 4 in New Lead (1 / 5 = 20% conversion)
            {
                "Opportunity ID": "in-1",
                "Company Name": "Inbound Co",
                "Job Title": "Lead Analyst",
                "Opportunity Source": "Inbound",
                "Status": "Recruiter Screen",
                "Date Created": (self.ref_now - timedelta(days=3)).strftime("%Y-%m-%d"),
                "stage_history": [{"stage": "Recruiter Screen", "entered_at": (self.ref_now - timedelta(days=3)).isoformat()}]
            },
            {
                "Opportunity ID": "in-2",
                "Contact Name": "Recruiter Jane",
                "Opportunity Source": "Inbound",
                "Status": "New Lead",
                "Date Created": (self.ref_now - timedelta(days=1)).strftime("%Y-%m-%d"),
                "stage_history": [{"stage": "New Lead", "entered_at": (self.ref_now - timedelta(days=1)).isoformat()}]
            },
            {
                "Opportunity ID": "in-3",
                "Contact Name": "Recruiter Mark",
                "Opportunity Source": "Inbound",
                "Status": "New Lead",
                "Date Created": (self.ref_now - timedelta(days=1)).strftime("%Y-%m-%d"),
                "stage_history": [{"stage": "New Lead", "entered_at": (self.ref_now - timedelta(days=1)).isoformat()}]
            },
            {
                "Opportunity ID": "in-4",
                "Contact Name": "Recruiter Lisa",
                "Opportunity Source": "Inbound",
                "Status": "New Lead",
                "Date Created": (self.ref_now - timedelta(days=1)).strftime("%Y-%m-%d"),
                "stage_history": [{"stage": "New Lead", "entered_at": (self.ref_now - timedelta(days=1)).isoformat()}]
            },
            {
                "Opportunity ID": "in-5",
                "Contact Name": "Recruiter Tom",
                "Opportunity Source": "Inbound",
                "Status": "New Lead",
                "Date Created": (self.ref_now - timedelta(days=1)).strftime("%Y-%m-%d"),
                "stage_history": [{"stage": "New Lead", "entered_at": (self.ref_now - timedelta(days=1)).isoformat()}]
            }
        ]

        metrics = PipelineKPIService.calculate_analytics_dashboard_metrics(
            opportunities=test_opps,
            stale_threshold_days=7,
            reference_date=self.ref_now
        )

        ov = metrics["overview"]
        sp = metrics["source_performance"]

        # Overview counts
        self.assertEqual(ov["total_tracked"], 7)
        self.assertEqual(ov["total_outbound"], 2)
        self.assertEqual(ov["total_inbound"], 5)
        # Only outbound records with actual submission count as applications submitted
        self.assertEqual(ov["applications_submitted"], 2)
        self.assertEqual(ov["interviews_total"], 2)

        # Outbound source performance: 1 interviewed / 2 submitted = 50.0%
        self.assertEqual(sp["outbound"]["submitted"], 2)
        self.assertEqual(sp["outbound"]["interviewed"], 1)
        self.assertEqual(sp["outbound"]["conversion_pct"], 50.0)

        # Inbound source performance: 1 interviewed / 5 total tracked = 20.0%
        self.assertEqual(sp["inbound"]["tracked"], 5)
        self.assertEqual(sp["inbound"]["interviewed"], 1)
        self.assertEqual(sp["inbound"]["conversion_pct"], 20.0)

    def test_staleness_logic_for_inbound_and_terminal(self):
        """Verify staleness detection for inbound leads and terminal exclusion."""
        old_date = (self.ref_now - timedelta(days=12)).isoformat()
        recent_date = (self.ref_now - timedelta(days=2)).isoformat()

        # 1. Stale Inbound New Lead (12 days without activity)
        stale_lead = {
            "Opportunity ID": "stale-1",
            "Contact Name": "Stale Contact",
            "Opportunity Source": "Inbound",
            "Status": "New Lead",
            "Date Created": (self.ref_now - timedelta(days=12)).strftime("%Y-%m-%d"),
            "stage_history": [{"stage": "New Lead", "entered_at": old_date}]
        }
        self.assertTrue(PipelineKPIService.is_stale(stale_lead, threshold_days=7, reference_date=self.ref_now))

        # 2. Fresh Inbound Lead (2 days old)
        fresh_lead = {
            "Opportunity ID": "fresh-1",
            "Contact Name": "Fresh Contact",
            "Opportunity Source": "Inbound",
            "Status": "New Lead",
            "Date Created": (self.ref_now - timedelta(days=2)).strftime("%Y-%m-%d"),
            "stage_history": [{"stage": "New Lead", "entered_at": recent_date}]
        }
        self.assertFalse(PipelineKPIService.is_stale(fresh_lead, threshold_days=7, reference_date=self.ref_now))

        # 3. Terminal opportunity is NEVER stale, even if months old
        terminal_opp = {
            "Opportunity ID": "term-1",
            "Company Name": "Old Company",
            "Status": "Application Rejected",
            "Opportunity Source": "Outbound",
            "Date Created": (self.ref_now - timedelta(days=60)).strftime("%Y-%m-%d"),
            "stage_history": [{"stage": "Application Rejected", "entered_at": old_date}]
        }
        self.assertFalse(PipelineKPIService.is_stale(terminal_opp, threshold_days=7, reference_date=self.ref_now))


if __name__ == "__main__":
    unittest.main()
