"""Focused test suite for More Outbound v1.5.2: Opportunity Card Job Signal Flag Indicator."""

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import streamlit as st
from streamlit.testing.v1 import AppTest

from job_pipeline.domain.models import JobPosting
from job_pipeline.domain.services import (
    PipelineConfigService,
    PipelineKPIService
)
from job_pipeline.domain.telemetry_service import TelemetryService


class TestOpportunityCardFlagIndicator(unittest.TestCase):
    """
    Test suite verifying the Job Signal Flag indicator on Pipeline Tracker opportunity cards.
    Covers:
    - Domain flag detection logic from persisted Job Signals JSON
    - Single flag vs multiple flags
    - Exclusion of warnings and benefits
    - Missing, empty, and malformed signals
    - End-to-end UI rendering via Streamlit AppTest (expander title and inner card)
    - Persistence after pipeline refresh
    """

    def setUp(self):
        st.cache_resource.clear()
        self.addCleanup(st.cache_resource.clear)
        self.app_path = str(Path(__file__).resolve().parents[2] / "adapters" / "primary" / "app.py")

    # -------------------------------------------------------------------------
    # Unit Tests for PipelineKPIService.has_job_signal_flags
    # -------------------------------------------------------------------------

    def test_single_flag_detected(self):
        """Opportunity with one Job Signal flag returns True."""
        signals_json = json.dumps({
            "version": 1,
            "flags": ["FLAG: [clearance-req]: Secret Clearance Required"],
            "warnings": [],
            "benefits": []
        })
        opp = {"Company Name": "Apex Defense", "Job Title": "Security Analyst", "Job Signals": signals_json}
        self.assertTrue(PipelineKPIService.has_job_signal_flags(opp))

    def test_multiple_flags_detected(self):
        """Opportunity with multiple Job Signal flags returns True."""
        signals_json = json.dumps({
            "version": 1,
            "flags": [
                "FLAG: [clearance-req]: Secret Clearance Required",
                "FLAG: [onsite-mandate]: 5 days onsite non-negotiable"
            ],
            "warnings": [],
            "benefits": []
        })
        opp = {"Company Name": "Lockheed", "Job Title": "Systems Eng", "Job Signals": signals_json}
        self.assertTrue(PipelineKPIService.has_job_signal_flags(opp))

    def test_warnings_only_do_not_trigger_flag(self):
        """Job Signals containing warnings but no flags must NOT trigger the indicator."""
        signals_json = json.dumps({
            "version": 1,
            "flags": [],
            "warnings": ["[heavy-travel]: 75% domestic travel", "[on-call]: 24/7 rotation"],
            "benefits": []
        })
        opp = {"Company Name": "Consulting Corp", "Job Title": "Field Consultant", "Job Signals": signals_json}
        self.assertFalse(PipelineKPIService.has_job_signal_flags(opp))

    def test_benefits_only_do_not_trigger_flag(self):
        """Job Signals containing benefits only must NOT trigger the indicator."""
        signals_json = json.dumps({
            "version": 1,
            "flags": [],
            "warnings": [],
            "benefits": ["BENEFIT: [401k-match]: 6% 401k match"]
        })
        opp = {"Company Name": "Generous Co", "Job Title": "Backend Eng", "Job Signals": signals_json}
        self.assertFalse(PipelineKPIService.has_job_signal_flags(opp))

    def test_warnings_and_benefits_together_do_not_trigger_flag(self):
        """Job Signals with both warnings and benefits (but 0 flags) must NOT trigger the indicator."""
        signals_json = json.dumps({
            "version": 1,
            "flags": [],
            "warnings": ["[on-call]: Off-hours pager duty"],
            "benefits": ["BENEFIT: [equity]: Generous stock options"]
        })
        opp = {"Company Name": "StartupX", "Job Title": "DevOps Lead", "Job Signals": signals_json}
        self.assertFalse(PipelineKPIService.has_job_signal_flags(opp))

    def test_empty_and_missing_signals(self):
        """Missing, None, or empty signal records return False."""
        self.assertFalse(PipelineKPIService.has_job_signal_flags({}))
        self.assertFalse(PipelineKPIService.has_job_signal_flags({"Job Signals": None}))
        self.assertFalse(PipelineKPIService.has_job_signal_flags({"Job Signals": ""}))
        self.assertFalse(PipelineKPIService.has_job_signal_flags(None))

    def test_populated_json_with_empty_flags_list(self):
        """Field is populated JSON, but flags collection is empty: returns False."""
        signals_json = json.dumps({"version": 1, "flags": [], "warnings": [], "benefits": []})
        opp = {"Company Name": "Clean Role Inc", "Job Title": "Product Manager", "Job Signals": signals_json}
        self.assertFalse(PipelineKPIService.has_job_signal_flags(opp))

    def test_malformed_signal_data_handled_gracefully(self):
        """Malformed or corrupt JSON string handles gracefully without raising and returns False."""
        corrupt_opp = {"Company Name": "Bad JSON Inc", "Job Title": "QA Analyst", "Job Signals": "not { valid: json"}
        self.assertFalse(PipelineKPIService.has_job_signal_flags(corrupt_opp))

        dict_missing_fields = {"Company Name": "Weird Dict", "Job Signals": json.dumps({"version": 2})}
        self.assertFalse(PipelineKPIService.has_job_signal_flags(dict_missing_fields))

    def test_legacy_fit_warning_resolution(self):
        """Legacy sheet records without 'Job Signals' JSON resolve flags from 'Fit Warning'."""
        legacy_with_flag = {
            "Company Name": "Legacy Corp",
            "Job Title": "Architect",
            "Job Signals": "",
            "Fit Warning": "FLAG: [clearance]: Top Secret Required; normal warning note"
        }
        self.assertTrue(PipelineKPIService.has_job_signal_flags(legacy_with_flag))

        legacy_warnings_only = {
            "Company Name": "Legacy Corp",
            "Job Title": "Architect",
            "Job Signals": "",
            "Fit Warning": "[oncall]: Weekend shifts required; [travel]: 40% travel"
        }
        self.assertFalse(PipelineKPIService.has_job_signal_flags(legacy_warnings_only))

    def test_job_posting_model_resolution(self):
        """JobPosting model instances evaluate correctly."""
        model_flagged = JobPosting(
            opportunity_id="opp-model-1",
            company_name="Apex Defense",
            job_title="Lead Eng",
            telemetry_flags=["FLAG: [clearance]: TS/SCI"]
        )
        self.assertTrue(PipelineKPIService.has_job_signal_flags(model_flagged))

        model_clean = JobPosting(
            opportunity_id="opp-model-2",
            company_name="Stripe",
            job_title="RevOps Analyst",
            telemetry_warnings=["[travel]: occasional travel"]
        )
        self.assertFalse(PipelineKPIService.has_job_signal_flags(model_clean))

    # -------------------------------------------------------------------------
    # End-to-End UI Integration via Streamlit AppTest
    # -------------------------------------------------------------------------

    def test_ui_opportunity_card_flag_indicator_integration(self):
        """
        End-to-end verification in Pipeline Tracker:
        - 1 flag: indicator visible in expander title (:red[Flag]) and inner card HTML badge.
        - Multiple flags: only one indicator visible.
        - Warnings / benefits but no flags: NO indicator.
        - Missing / empty signals: NO indicator.
        - Long job title: wraps naturally, indicator remains inline.
        - Persists across refresh.
        """
        flag_single_json = json.dumps({
            "version": 1,
            "flags": ["FLAG: [clearance]: Active Security Clearance Required"],
            "warnings": [],
            "benefits": []
        })
        flags_multi_json = json.dumps({
            "version": 1,
            "flags": [
                "FLAG: [clearance]: Active Security Clearance Required",
                "FLAG: [travel-extreme]: 80% mandatory travel"
            ],
            "warnings": ["[warn-1]: Legacy codebase"],
            "benefits": []
        })
        warns_only_json = json.dumps({
            "version": 1,
            "flags": [],
            "warnings": ["[on-call]: Rotating pager duty"],
            "benefits": ["BENEFIT: [match]: 401k match"]
        })

        mock_opps = [
            # Opp 0: Single Flag
            {
                "Opportunity ID": "opp-flag-1",
                "Company Name": "Apex Aerospace",
                "Job Title": "Systems Engineer",
                "Status": "Applied",
                "Category": "Target",
                "Applied Via": "LinkedIn",
                "Priority": "High",
                "Date Created": "2026-10-01",
                "Job Signals": flag_single_json,
            },
            # Opp 1: Multiple Flags
            {
                "Opportunity ID": "opp-flag-multi",
                "Company Name": "Titan Defense",
                "Job Title": "Infrastructure Lead",
                "Status": "Recruiter Screen",
                "Category": "Stretch",
                "Applied Via": "Indeed",
                "Priority": "High",
                "Date Created": "2026-10-02",
                "Job Signals": flags_multi_json,
            },
            # Opp 2: Warnings & Benefits only (NO flag)
            {
                "Opportunity ID": "opp-warn-only",
                "Company Name": "CloudConsulting",
                "Job Title": "Implementation Consultant",
                "Status": "Applied",
                "Category": "Opportunistic",
                "Applied Via": "LinkedIn",
                "Priority": "Medium",
                "Date Created": "2026-10-03",
                "Job Signals": warns_only_json,
            },
            # Opp 3: Empty / missing signals (NO flag)
            {
                "Opportunity ID": "opp-clean",
                "Company Name": "Normal Corp",
                "Job Title": "Sales Operations Specialist",
                "Status": "Pending",
                "Category": "Practice",
                "Applied Via": "Company Website",
                "Priority": "Low",
                "Date Created": "2026-10-04",
                "Job Signals": "",
            },
            # Opp 4: Long Job Title with Flag
            {
                "Opportunity ID": "opp-long-title",
                "Company Name": "Global Enterprises Inc",
                "Job Title": "Principal Enterprise Systems Integration Architect and Global Data Operations Lead",
                "Status": "Applied",
                "Category": "Target",
                "Applied Via": "LinkedIn",
                "Priority": "High",
                "Date Created": "2026-10-05",
                "Job Signals": flag_single_json,
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = str(Path(tmp) / "config.json")
            PipelineConfigService.save_config({}, cfg_path)
            with patch.dict(os.environ, {
                "DEMO_MODE": "true",
                "PIPELINE_CONFIG_PATH": cfg_path,
                "ENABLE_CLI_LOGGING": "false"
            }), \
                 patch("job_pipeline.adapters.secondary.mock_adapter.MockJobStorageAdapter.fetch_all_opportunities", return_value=mock_opps), \
                 patch("job_pipeline.domain.services.QuickLinksService.load_quicklinks", return_value=[]), \
                 patch("job_pipeline.domain.story_bank.StoryBankService.load_stories", return_value=[]), \
                 patch("job_pipeline.adapters.secondary.twilio_adapter.TwilioMessagingAdapter._init_client"):

                app = AppTest.from_file(self.app_path, default_timeout=20).run()
                self.assertFalse(app.exception, [e.message for e in app.exception])

                # Navigate to Pipeline Tracker section
                SECTION_CRM = "📊 Pipeline Tracker"
                app.radio(key="active_main_section").set_value(SECTION_CRM).run()
                self.assertFalse(app.exception, [e.message for e in app.exception])

                # Locate the opportunity card expanders (note: reversed order for pagination: Opp 4, 3, 2, 1, 0)
                # Filter down to CRM opportunity expanders
                opp_expanders = [
                    exp for exp in app.expander
                    if any(c in exp.label for c in ("Apex Aerospace", "Titan Defense", "CloudConsulting", "Normal Corp", "Global Enterprises"))
                ]
                self.assertEqual(len(opp_expanders), 5)

                # Check opp-long-title (index 0 in reversed order: Global Enterprises)
                exp_long = next(e for e in opp_expanders if "Global Enterprises" in e.label)
                self.assertIn(":red[Flag]", exp_long.label)
                # Verify Flag appears immediately to the right of the job title
                self.assertIn("Global Data Operations Lead :red[Flag]", exp_long.label)

                # Check opp-clean (Normal Corp) - NO flag
                exp_clean = next(e for e in opp_expanders if "Normal Corp" in e.label)
                self.assertNotIn("Flag", exp_clean.label)

                # Check opp-warn-only (CloudConsulting) - NO flag
                exp_warn = next(e for e in opp_expanders if "CloudConsulting" in e.label)
                self.assertNotIn("Flag", exp_warn.label)

                # Check opp-flag-multi (Titan Defense) - exactly ONE flag indicator in title
                exp_multi = next(e for e in opp_expanders if "Titan Defense" in e.label)
                self.assertIn(":red[Flag]", exp_multi.label)
                self.assertEqual(exp_multi.label.count(":red[Flag]"), 1)

                # Check opp-flag-1 (Apex Aerospace) - single flag indicator
                exp_single = next(e for e in opp_expanders if "Apex Aerospace" in e.label)
                self.assertIn(":red[Flag]", exp_single.label)
                self.assertEqual(exp_single.label.count(":red[Flag]"), 1)
                self.assertIn("Systems Engineer :red[Flag]", exp_single.label)

                # Verify inner card markdown markup has subtle red-highlighted Flag badge
                # for flagged opportunities, and none for clean opportunities
                all_markdown_texts = [m.value for m in app.markdown]
                # Flagged card inner HTML badge:
                self.assertTrue(any('>Flag</span>' in m and 'Apex Aerospace' in m for m in all_markdown_texts))
                self.assertTrue(any('>Flag</span>' in m and 'Titan Defense' in m for m in all_markdown_texts))
                self.assertTrue(any('>Flag</span>' in m and 'Global Enterprises' in m for m in all_markdown_texts))

                # Unflagged cards MUST NOT have the Flag badge
                self.assertFalse(any('>Flag</span>' in m and 'CloudConsulting' in m for m in all_markdown_texts))
                self.assertFalse(any('>Flag</span>' in m and 'Normal Corp' in m for m in all_markdown_texts))

                # Refresh Pipeline Tracker and verify indicators persist
                app.button(key="btn_inline_crm_refresh").click().run()
                self.assertFalse(app.exception)

                opp_expanders_after = [
                    exp for exp in app.expander
                    if any(c in exp.label for c in ("Apex Aerospace", "Titan Defense", "CloudConsulting", "Normal Corp", "Global Enterprises"))
                ]
                self.assertEqual(len(opp_expanders_after), 5)
                exp_single_after = next(e for e in opp_expanders_after if "Apex Aerospace" in e.label)
                self.assertIn(":red[Flag]", exp_single_after.label)
                exp_clean_after = next(e for e in opp_expanders_after if "Normal Corp" in e.label)
                self.assertNotIn("Flag", exp_clean_after.label)


if __name__ == "__main__":
    unittest.main()
