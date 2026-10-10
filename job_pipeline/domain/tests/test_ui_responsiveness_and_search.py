import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from job_pipeline.domain.services import PipelineConfigService
from job_pipeline.adapters.secondary.mock_adapter import MockDocumentStorageAdapter, MockJobStorageAdapter


class TestUIResponsivenessAndSearch(unittest.TestCase):
    """End-to-end integration tests using Streamlit AppTest for UI responsiveness and pipeline search/pagination."""

    def setUp(self):
        st.cache_resource.clear()
        self.addCleanup(st.cache_resource.clear)
        self.app_path = str(Path(__file__).resolve().parents[2] / 'adapters' / 'primary' / 'app.py')

    def test_intake_typing_and_state_preservation(self):
        """Verify typing in intake fields preserves input and runs smoothly."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = str(Path(tmp) / 'config.json')
            PipelineConfigService.save_config({}, cfg_path)
            with patch.dict(os.environ, {'DEMO_MODE': 'true', 'PIPELINE_CONFIG_PATH': cfg_path, 'ENABLE_CLI_LOGGING': 'false'}), \
                 patch('job_pipeline.domain.services.QuickLinksService.load_quicklinks', return_value=[]), \
                 patch('job_pipeline.domain.story_bank.StoryBankService.load_stories', return_value=[]), \
                 patch('job_pipeline.adapters.secondary.twilio_adapter.TwilioMessagingAdapter._init_client'):
                app = AppTest.from_file(self.app_path, default_timeout=20).run()
                self.assertFalse(app.exception, [e.message for e in app.exception])

                # Enter text in JD area
                jd_text = "Senior Revenue Operations Analyst with SQL, Salesforce, and dbt experience."
                app.text_area(key="jd_text_input_0").input(jd_text).run()
                self.assertFalse(app.exception)
                self.assertEqual(app.text_area(key="jd_text_input_0").value, jd_text)

                # Enter override fields
                app.text_input(key="ov_comp_0").input("Acme Analytics").run()
                self.assertFalse(app.exception)
                self.assertEqual(app.text_input(key="ov_comp_0").value, "Acme Analytics")

                app.text_input(key="ov_title_0").input("RevOps Lead").run()
                self.assertFalse(app.exception)
                self.assertEqual(app.text_input(key="ov_title_0").value, "RevOps Lead")

    def test_crm_search_and_pagination_lifecycle(self):
        """Verify CRM search, clearing search, page reset, and pagination buttons."""
        mock_opps = [
            {
                "Opportunity ID": f"opp-{i}",
                "Company Name": "Planful" if i == 0 else f"Company-{i}",
                "Job Title": "Sales Operations Analyst",
                "Status": "Applied",
                "Category": "Target",
                "Applied Via": "LinkedIn",
                "Priority": "High",
                "Date Created": f"2026-09-{10+i:02d}",
                "Employment Arrangement": "Employee",
            }
            for i in range(12)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = str(Path(tmp) / 'config.json')
            PipelineConfigService.save_config({}, cfg_path)
            with patch.dict(os.environ, {'DEMO_MODE': 'true', 'PIPELINE_CONFIG_PATH': cfg_path, 'ENABLE_CLI_LOGGING': 'false'}), \
                 patch('job_pipeline.adapters.secondary.mock_adapter.MockJobStorageAdapter.fetch_all_opportunities', return_value=mock_opps), \
                 patch('job_pipeline.domain.services.QuickLinksService.load_quicklinks', return_value=[]), \
                 patch('job_pipeline.domain.story_bank.StoryBankService.load_stories', return_value=[]), \
                 patch('job_pipeline.adapters.secondary.twilio_adapter.TwilioMessagingAdapter._init_client'):
                app = AppTest.from_file(self.app_path, default_timeout=20).run()
                self.assertFalse(app.exception, [e.message for e in app.exception])

                # Navigate to CRM section
                SECTION_CRM = "📊 Pipeline Tracker & CRM"
                app.radio(key="active_main_section").set_value(SECTION_CRM).run()
                self.assertFalse(app.exception)

                # Initial state: page should be 1
                self.assertEqual(app.session_state.crm_page, 1)

                # Search for a term that matches
                app.text_input(key="crm_search_input").input("Planful").run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state.crm_page, 1)

                # Clear search: must reset crm_page to 1
                app.text_input(key="crm_search_input").input("").run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state.crm_page, 1)

                # Test pagination: click Next if total_pages > 1
                if app.session_state.crm_page_size < 80:
                    # Click Next
                    if not app.button(key="crm_next_pg").disabled:
                        app.button(key="crm_next_pg").click().run()
                        self.assertFalse(app.exception)
                        self.assertEqual(app.session_state.crm_page, 2)

                        # Click Previous
                        app.button(key="crm_prev_pg").click().run()
                        self.assertFalse(app.exception)
                        self.assertEqual(app.session_state.crm_page, 1)

    def test_screening_qa_ondemand_similarity_workflow(self):
        """Verify on-demand similarity search button performs lookup and applies prior answer."""
        mock_historical_qa = [
            {
                "question": "What is your experience with Salesforce & dbt?",
                "answer": "Over 5 years designing dbt models and Salesforce workflow automation.",
                "company_name": "Past Tech Corp",
                "timestamp": "2026-08-01"
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = str(Path(tmp) / 'config.json')
            PipelineConfigService.save_config({}, cfg_path)
            with patch.dict(os.environ, {'DEMO_MODE': 'true', 'PIPELINE_CONFIG_PATH': cfg_path, 'ENABLE_CLI_LOGGING': 'false'}), \
                 patch('job_pipeline.domain.services.QuickLinksService.load_quicklinks', return_value=[]), \
                 patch('job_pipeline.domain.story_bank.StoryBankService.load_stories', return_value=[]), \
                 patch('job_pipeline.adapters.secondary.twilio_adapter.TwilioMessagingAdapter._init_client'):
                app = AppTest.from_file(self.app_path, default_timeout=20).run()
                self.assertFalse(app.exception)

                # Seed cached historical QA
                app.session_state._cached_historical_qa = mock_historical_qa

                # Add 1 screening question
                app.session_state.num_screening_qa = 1
                app.run()
                self.assertFalse(app.exception)

                # Type question prompt
                app.text_input(key="sq_q_0").input("Describe your experience with Salesforce and dbt").run()
                self.assertFalse(app.exception)

                # Notice: automatic search did NOT run, so btn_recall_qa_0 does NOT exist yet
                self.assertNotIn("btn_recall_qa_0", [b.proto.id for b in app.button])

                # Click on-demand "Find Similar Answers" button
                app.button(key="btn_find_sim_0").click().run()
                self.assertFalse(app.exception)

                # Now similar match is found and "Use Prior Answer" button appears
                self.assertTrue(any("btn_recall_qa_0" in str(b.proto.id) or b.label.startswith("📋 Use Prior Answer") for b in app.button))

                # Click "Use Prior Answer"
                recall_btn = next(b for b in app.button if b.label.startswith("📋 Use Prior Answer"))
                recall_btn.click().run()
                self.assertFalse(app.exception)

                # Verify answer was populated and category updated
                self.assertEqual(app.text_area(key="sq_a_0").value, "Over 5 years designing dbt models and Salesforce workflow automation.")
                self.assertEqual(app.selectbox(key="sq_cat_0").value, "Technical")


if __name__ == "__main__":
    unittest.main()
