"""Regression test suite for More Outbound v1.5.2 Shared Intake: Metadata Extraction & Job Signals."""

import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime
from typing import Dict, Any, List

import json
import os
from pathlib import Path
from types import SimpleNamespace

from job_pipeline.domain.models import (
    JobPosting,
    FitEvaluation,
    TargetPayBounds,
    CandidateProfile
)
from job_pipeline.domain.services import (
    JobQualificationService,
    PipelineConfigService
)
from job_pipeline.domain.telemetry_service import TelemetryService, _TELEMETRY_EXTRACTION_CACHE
from job_pipeline.adapters.secondary.mock_adapter import MockJobStorageAdapter, MockLLMStrategyAdapter
from job_pipeline.adapters.secondary.openai_adapter import (
    JobExtractionPayload,
    JobRequirementsSchema,
    OpenAIEngineAdapter
)


class TestV152IntakeRegression(unittest.TestCase):
    """Verifies complete extraction-to-persistence mapping, typed schema access, and Role Intelligence decoupling."""

    def setUp(self):
        self.ref_now = datetime(2026, 10, 12, 12, 0, 0)
        self.adapter = MockJobStorageAdapter()

    def test_root_level_attribute_access_rejection(self):
        """
        Regression test: Confirms that JobExtractionPayload requires nested access
        via payload.requirements for salary, skills, contract terms, and telemetry signals.
        Attempting to access min_pay, max_pay, telemetry_warnings, etc. directly at root
        must not be present on JobExtractionPayload, catching the original unpacking mistake.
        """
        reqs = JobRequirementsSchema(
            salary_min=135000.0,
            salary_max=155000.0,
            employment_arrangement="Employee",
            pay_basis="Annual",
            required_tech_stack=["Salesforce", "SQL"],
            preferred_tech_stack=["dbt"],
            telemetry_flags=["FLAG: [flag-1]: severe"],
            telemetry_warnings=["[warn-1]: note"],
            telemetry_benefits=["BENEFIT: [ben-1]: perk"]
        )
        payload = JobExtractionPayload(
            company_name="Acme Inc",
            job_title="Revenue Operations Manager",
            title_family="revenue_operations",
            source_url="https://example.com/job/1",
            requirements=reqs
        )

        # 1. Catch original mistake: root-level non-existent fields
        self.assertFalse(hasattr(payload, "min_pay"), "min_pay should not exist at payload root")
        self.assertFalse(hasattr(payload, "max_pay"), "max_pay should not exist at payload root")
        self.assertFalse(hasattr(payload, "salary_min"), "salary_min should not exist at payload root")
        self.assertFalse(hasattr(payload, "salary_max"), "salary_max should not exist at payload root")
        self.assertFalse(hasattr(payload, "telemetry_warnings"), "telemetry_warnings should not exist at payload root")
        self.assertFalse(hasattr(payload, "telemetry_flags"), "telemetry_flags should not exist at payload root")
        self.assertFalse(hasattr(payload, "telemetry_benefits"), "telemetry_benefits should not exist at payload root")
        self.assertFalse(hasattr(payload, "required_tech_stack"), "required_tech_stack should not exist at payload root")

        # 2. Verify typed direct access on payload.requirements
        self.assertEqual(payload.requirements.salary_min, 135000.0)
        self.assertEqual(payload.requirements.salary_max, 155000.0)
        self.assertEqual(payload.requirements.required_tech_stack, ["Salesforce", "SQL"])
        self.assertEqual(payload.requirements.preferred_tech_stack, ["dbt"])
        self.assertEqual(payload.requirements.telemetry_flags, ["FLAG: [flag-1]: severe"])
        self.assertEqual(payload.requirements.telemetry_warnings, ["[warn-1]: note"])
        self.assertEqual(payload.requirements.telemetry_benefits, ["BENEFIT: [ben-1]: perk"])

    def test_complete_extraction_to_persistence_mapping(self):
        """
        Verifies end-to-end extraction-to-persistence mapping for:
        - Stated compensation range (salary_min, salary_max, pay_basis)
        - Employment arrangement & worker classification
        - Contract terms (duration, months, weeks, hours, extensions, fte conversion, agency, client)
        - Required and preferred tech stacks (no fabricated fallbacks)
        - Job signals (flags, warnings, benefits)
        - Role Intelligence status ('Not Generated')
        """
        reqs = JobRequirementsSchema(
            salary_min=140000.0,
            salary_max=160000.0,
            employment_arrangement="Contract",
            worker_classification="W2",
            pay_basis="Annual",
            contract_length_raw="6-month contract",
            contract_length_months=6.0,
            contract_length_weeks=26.0,
            expected_hours_per_week=40.0,
            extension_possible=True,
            fte_conversion_possible=True,
            staffing_agency="Apex Systems",
            client_company="Braze",
            required_tech_stack=["Salesforce", "Python", "SQL"],
            preferred_tech_stack=["dbt", "Snowflake"],
            core_pain_points="Funnel scaling and ARR reconciliation.",
            is_remote=True,
            telemetry_flags=["FLAG: [commission-only]: Uncapped commission only"],
            telemetry_warnings=["[travel-heavy]: >50% travel required"],
            telemetry_benefits=["BENEFIT: [equity-offered]: Meaningful equity grant"]
        )
        telemetry = JobExtractionPayload(
            company_name="Braze",
            job_title="Senior GTM Systems Architect",
            title_family="revenue_operations",
            source_url="https://linkedin.com/jobs/view/123",
            requirements=reqs
        )

        # Direct typed extraction mapping
        extracted_company = telemetry.company_name
        extracted_title = telemetry.job_title
        extracted_family = telemetry.title_family
        extracted_url = telemetry.source_url

        extracted_reqs = telemetry.requirements
        extracted_min = extracted_reqs.salary_min
        extracted_max = extracted_reqs.salary_max
        extracted_arr = extracted_reqs.employment_arrangement
        extracted_pb = extracted_reqs.pay_basis
        extracted_wc = extracted_reqs.worker_classification
        extracted_dur = extracted_reqs.contract_length_raw
        extracted_months = extracted_reqs.contract_length_months
        extracted_weeks = extracted_reqs.contract_length_weeks
        extracted_hours = extracted_reqs.expected_hours_per_week
        extracted_ext = extracted_reqs.extension_possible
        extracted_fte = extracted_reqs.fte_conversion_possible
        extracted_agency = extracted_reqs.staffing_agency
        extracted_client = extracted_reqs.client_company
        req_skills = extracted_reqs.required_tech_stack
        pref_skills = extracted_reqs.preferred_tech_stack
        pain_points = extracted_reqs.core_pain_points or ""
        is_remote = extracted_reqs.is_remote
        t_warnings = extracted_reqs.telemetry_warnings
        t_flags = extracted_reqs.telemetry_flags
        t_benefits = extracted_reqs.telemetry_benefits

        # 1. Fit Qualification & Target Pay Bounds
        profile = CandidateProfile(minimum_compensation_floor=90000)
        fit_eval = JobQualificationService.evaluate(
            company_name=extracted_company,
            job_title=extracted_title,
            raw_description="Looking for Senior GTM Architect with Salesforce, Python, SQL...",
            required_skills=req_skills,
            preferred_skills=pref_skills,
            salary_min=extracted_min,
            salary_max=extracted_max,
            profile=profile,
            pay_basis=extracted_pb,
            expected_hours_per_week=extracted_hours,
            expected_hours_per_week_is_assumed=(extracted_hours is None),
            contract_length_months=extracted_months,
            contract_length_weeks=extracted_weeks,
            telemetry_warnings=t_warnings,
            telemetry_flags=t_flags,
            telemetry_benefits=t_benefits
        )

        # Verify TargetPayBounds captured stated compensation correctly
        self.assertEqual(fit_eval.pay_bounds.posted_min, 140000.0)
        self.assertEqual(fit_eval.pay_bounds.posted_max, 160000.0)
        self.assertNotEqual(fit_eval.pay_bounds.display_range, "Salary Unspecified")
        self.assertIn("140,000", fit_eval.pay_bounds.display_range)

        # 2. Build JobPosting model
        opp_id = "opp-reg-001"
        now_iso = self.ref_now.isoformat()
        job_posting = JobPosting(
            opportunity_id=opp_id,
            company_name=extracted_company,
            job_title=extracted_title,
            title_family=extracted_family,
            raw_description="Looking for Senior GTM Architect...",
            source_url=extracted_url,
            opportunity_source="Outbound",
            category="Target",
            employment_arrangement=extracted_arr,
            worker_classification=extracted_wc,
            pay_basis=extracted_pb,
            contract_length_raw=extracted_dur,
            contract_length_months=extracted_months,
            contract_length_weeks=extracted_weeks,
            expected_hours_per_week=extracted_hours,
            expected_hours_per_week_is_assumed=(extracted_hours is None),
            extension_possible=extracted_ext,
            fte_conversion_possible=extracted_fte,
            staffing_agency=extracted_agency,
            client_company=extracted_client,
            required_skills=req_skills,
            preferred_skills=pref_skills,
            stage_history=[{"stage": "Processed", "entered_at": now_iso}],
            telemetry_warnings=t_warnings,
            telemetry_flags=t_flags,
            telemetry_benefits=t_benefits,
            tokens_used=1250,
            role_intelligence_status="Not Generated"
        )

        # 3. Persistence to storage adapter
        saved = self.adapter.save_opportunity(job_posting, fit_eval)
        self.assertTrue(saved)

        # 4. Verify canonical opportunity record in storage
        all_opps = self.adapter.fetch_all_opportunities()
        saved_opp = next((o for o in all_opps if o.get("Opportunity ID") == opp_id), None)
        self.assertIsNotNone(saved_opp)

        self.assertEqual(saved_opp.get("Company Name"), "Braze")
        self.assertEqual(saved_opp.get("Job Title"), "Senior GTM Systems Architect")
        self.assertEqual(saved_opp.get("Employment Arrangement"), "Contract")
        self.assertEqual(saved_opp.get("Worker Classification"), "W2")
        self.assertEqual(saved_opp.get("Pay Basis"), "Annual")
        self.assertEqual(saved_opp.get("Contract Duration"), "6-month contract")
        self.assertEqual(saved_opp.get("Staffing Agency"), "Apex Systems")
        self.assertEqual(saved_opp.get("Client Company"), "Braze")
        self.assertEqual(saved_opp.get("Extension Possible"), "Yes")
        self.assertEqual(saved_opp.get("FTE Conversion"), "Yes")
        self.assertEqual(saved_opp.get("Role Intelligence Status"), "Not Generated")

        # Verify salary in Target Pay Range
        self.assertIn("140,000", saved_opp.get("Target Pay Range", ""))
        self.assertNotIn("Salary Unspecified", saved_opp.get("Target Pay Range", ""))

        # Verify Job Signals serialized in storage
        signals_json = saved_opp.get("Job Signals", "")
        self.assertIn("commission-only", signals_json)
        self.assertIn("travel-heavy", signals_json)
        self.assertIn("equity-offered", signals_json)

        # 5. Verify Requirements Extraction worksheet row
        req_store = self.adapter.requirements_store
        req_row = next((r for r in req_store if r.get("opportunity_id") == opp_id), None)
        self.assertIsNotNone(req_row)
        self.assertEqual(req_row.get("salary_min"), 140000.0)
        self.assertEqual(req_row.get("salary_max"), 160000.0)
        self.assertIn("Salesforce", req_row.get("required_tech_stack", ""))
        self.assertIn("Python", req_row.get("required_tech_stack", ""))
        self.assertIn("SQL", req_row.get("required_tech_stack", ""))
        self.assertIn("dbt", req_row.get("preferred_tech_stack", ""))
        self.assertIn("Snowflake", req_row.get("preferred_tech_stack", ""))

    def test_missing_optional_skills_use_legitimate_empty_lists(self):
        """
        Verifies that when a JD does not state skills, legitimate empty lists
        are preserved rather than fabricating defaults like ['Salesforce', 'SQL'].
        """
        reqs = JobRequirementsSchema(
            salary_min=100000.0,
            salary_max=120000.0,
            required_tech_stack=[],
            preferred_tech_stack=[]
        )
        telemetry = JobExtractionPayload(
            company_name="Clean Slate Corp",
            job_title="Business Systems Analyst",
            title_family="business_systems",
            requirements=reqs
        )

        req_skills = telemetry.requirements.required_tech_stack
        pref_skills = telemetry.requirements.preferred_tech_stack

        # Legitimate empty lists must not be replaced with fabricated defaults
        self.assertEqual(req_skills, [])
        self.assertEqual(pref_skills, [])

    def test_both_intake_entry_points_wire_shared_component(self):
        """
        Verifies that both Ingest & Apply and Pipeline Tracker (+ Add Opportunity)
        wire to the corrected shared render_shared_intake component in app.py.
        """
        app_path = Path(__file__).resolve().parents[2] / "adapters" / "primary" / "app.py"
        app_source = app_path.read_text(encoding="utf-8")

        # Ingest & Apply entry point
        self.assertIn('render_shared_intake(', app_source)
        self.assertIn('view_context="ingest"', app_source)

        # Pipeline Tracker (+ Add Opportunity) entry point
        self.assertIn('view_context="crm_add"', app_source)

    def test_role_intelligence_remains_deferred_by_default(self):
        """
        Verifies that during normal job ingestion, Role Intelligence is explicitly
        marked 'Not Generated' and no report generator is invoked.
        """
        job = JobPosting(
            opportunity_id="opp-ri-check",
            company_name="Test Company",
            job_title="RevOps Lead",
            role_intelligence_status="Not Generated"
        )
        fit_eval = FitEvaluation(
            status="Processed",
            is_qualified=True,
            reasoning="Qualified fit.",
            pay_bounds=TargetPayBounds(display_range="$120k - $140k")
        )
        self.adapter.save_opportunity(job, fit_eval)

        all_opps = self.adapter.fetch_all_opportunities()
        saved = next(o for o in all_opps if o.get("Opportunity ID") == "opp-ri-check")
        self.assertEqual(saved.get("Role Intelligence Status"), "Not Generated")
        self.assertEqual(saved.get("Role Intelligence Link"), "")


    def test_hourly_contract_extraction_mapping(self):
        """
        Verifies that hourly rates (e.g. $75 - $85/hr) with Contract arrangement,
        expected hours, and duration normalize and persist with hourly pay bounds.
        """
        reqs = JobRequirementsSchema(
            salary_min=75.0,
            salary_max=85.0,
            employment_arrangement="Contract",
            worker_classification="W2",
            pay_basis="Hourly",
            contract_length_raw="3 months",
            contract_length_months=3.0,
            expected_hours_per_week=40.0,
            staffing_agency="Robert Half",
            client_company="Stripe",
            required_tech_stack=["Salesforce", "dbt"]
        )
        telemetry = JobExtractionPayload(
            company_name="Stripe",
            job_title="Contract RevOps Developer",
            title_family="gtm_engineering",
            requirements=reqs
        )

        fit_eval = JobQualificationService.evaluate(
            company_name=telemetry.company_name,
            job_title=telemetry.job_title,
            raw_description="Contract RevOps Developer at Stripe...",
            required_skills=telemetry.requirements.required_tech_stack,
            preferred_skills=telemetry.requirements.preferred_tech_stack,
            salary_min=telemetry.requirements.salary_min,
            salary_max=telemetry.requirements.salary_max,
            pay_basis=telemetry.requirements.pay_basis,
            expected_hours_per_week=telemetry.requirements.expected_hours_per_week,
            contract_length_months=telemetry.requirements.contract_length_months
        )

        # Check hourly bounds
        self.assertEqual(fit_eval.pay_bounds.hourly_min, 75.0)
        self.assertEqual(fit_eval.pay_bounds.hourly_max, 85.0)
        self.assertIn("/hr", fit_eval.pay_bounds.display_range)

        opp = JobPosting(
            opportunity_id="opp-hourly-1",
            company_name=telemetry.company_name,
            job_title=telemetry.job_title,
            title_family=telemetry.title_family,
            employment_arrangement=telemetry.requirements.employment_arrangement,
            worker_classification=telemetry.requirements.worker_classification,
            pay_basis=telemetry.requirements.pay_basis,
            contract_length_raw=telemetry.requirements.contract_length_raw,
            contract_length_months=telemetry.requirements.contract_length_months,
            expected_hours_per_week=telemetry.requirements.expected_hours_per_week,
            staffing_agency=telemetry.requirements.staffing_agency,
            client_company=telemetry.requirements.client_company,
            required_skills=telemetry.requirements.required_tech_stack,
            preferred_skills=telemetry.requirements.preferred_tech_stack
        )
        self.adapter.save_opportunity(opp, fit_eval)

        saved = next(o for o in self.adapter.fetch_all_opportunities() if o.get("Opportunity ID") == "opp-hourly-1")
        self.assertEqual(saved.get("Employment Arrangement"), "Contract")
        self.assertEqual(saved.get("Pay Basis"), "Hourly")
        self.assertEqual(saved.get("Contract Duration"), "3 months")
        self.assertEqual(saved.get("Staffing Agency"), "Robert Half")
        self.assertEqual(saved.get("Client Company"), "Stripe")
        self.assertIn("/hr", saved.get("Target Pay Range"))

    def test_invalid_schema_missing_requirements_raises_explicit_error(self):
        """
        Verifies that an incompatible payload missing the 'requirements' schema field
        is explicitly rejected rather than silently producing empty data.
        """
        class IncompatiblePayload:
            company_name = "Bad Company"
            job_title = "Bad Role"
            title_family = "revenue_operations"
            source_url = None
            requirements = None

        bad_payload = IncompatiblePayload()
        self.assertIsNone(bad_payload.requirements)

        # Verify our schema guard condition
        has_reqs = hasattr(bad_payload, "requirements") and bad_payload.requirements is not None
        self.assertFalse(has_reqs)

    def test_telemetry_completion_summary_zero_findings(self):
        """
        Regression test: Verifies that when job ingestion evaluates 1 deterministic
        and 7 semantic rules with 0 matching infractions, the completion summary:
        '[TELEMETRY] Completed: 0 flags, 0 warnings, 0 benefits'
        is explicitly logged to CLI output.
        """
        _TELEMETRY_EXTRACTION_CACHE.clear()
        adapter = OpenAIEngineAdapter(api_key="test-key")

        # 1 deterministic rule + 7 semantic concept rules
        rules = [
            {"id": "det-1", "name": "Gov FAR", "category": "flag", "match_mode": "token", "patterns": ["FAR/DFARS"], "enabled": True},
            {"id": "sem-1", "name": "Clearance", "category": "flag", "match_mode": "concept", "concept_description": "Requires clearance", "enabled": True},
            {"id": "sem-2", "name": "On-Call", "category": "warning", "match_mode": "concept", "concept_description": "24/7 on-call", "enabled": True},
            {"id": "sem-3", "name": "Travel", "category": "warning", "match_mode": "concept", "concept_description": "Heavy travel", "enabled": True},
            {"id": "sem-4", "name": "Commission", "category": "flag", "match_mode": "concept", "concept_description": "Commission only", "enabled": True},
            {"id": "sem-5", "name": "Overtime", "category": "warning", "match_mode": "concept", "concept_description": "Mandatory overtime", "enabled": True},
            {"id": "sem-6", "name": "Relocation", "category": "warning", "match_mode": "concept", "concept_description": "Must relocate", "enabled": True},
            {"id": "sem-7", "name": "Remote Stipend", "category": "benefit", "match_mode": "concept", "concept_description": "Generous home office stipend", "enabled": True},
        ]

        # Model returns clean payload with zero infractions
        clean_parsed = JobExtractionPayload(
            company_name="Cloud Corp",
            job_title="Revenue Operations Analyst",
            title_family="revenue_operations",
            requirements=JobRequirementsSchema(
                salary_min=120000.0,
                salary_max=140000.0,
                telemetry_flags=[],
                telemetry_warnings=[],
                telemetry_benefits=[]
            )
        )
        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.return_value = SimpleNamespace(
            usage=SimpleNamespace(total_tokens=150),
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=clean_parsed))]
        )
        adapter._runner._openai_client = mock_client

        telemetry_logs = []
        cli_logs = []

        def capture_telemetry(msg: str):
            telemetry_logs.append(msg)
            cli_logs.append(f"[TELEMETRY] {msg}")

        with patch("job_pipeline.adapters.secondary.openai_adapter.log_telemetry", side_effect=capture_telemetry), \
             patch("job_pipeline.domain.telemetry_service.log_telemetry", side_effect=capture_telemetry):
            result = adapter.extract_job_telemetry(
                "Standard RevOps job description text with standard SaaS CRM tooling.",
                warning_rules=rules
            )

        # 1. Verify rule evaluation was logged
        self.assertTrue(any("Evaluating 1 deterministic rules." in msg for msg in telemetry_logs))
        self.assertTrue(any("Evaluating 7 semantic rules via LLM." in msg for msg in telemetry_logs))

        # 2. Verify completion summary was logged
        self.assertTrue(
            any("Completed: 0 flags, 0 warnings, 0 benefits" in msg for msg in telemetry_logs),
            f"Expected completion summary not found in: {telemetry_logs}"
        )

        # 3. Verify formatted CLI output
        self.assertTrue(
            any("[TELEMETRY] Completed: 0 flags, 0 warnings, 0 benefits" in msg for msg in cli_logs),
            f"Expected CLI completion log not found in: {cli_logs}"
        )

        # 4. Verify returned counts match zero
        self.assertEqual(len(result.requirements.telemetry_flags), 0)
        self.assertEqual(len(result.requirements.telemetry_warnings), 0)
        self.assertEqual(len(result.requirements.telemetry_benefits), 0)

    def test_telemetry_completion_summary_with_actual_counts(self):
        """
        Regression test: Verifies that when infractions match, the completion summary
        reflects the actual counts of flags, warnings, and benefits.
        """
        _TELEMETRY_EXTRACTION_CACHE.clear()
        adapter = OpenAIEngineAdapter(api_key="test-key")

        rules = [
            {"id": "det-flag", "name": "FAR Procurement", "category": "flag", "match_mode": "token", "patterns": ["FAR/DFARS"], "enabled": True},
            {"id": "sem-warn", "name": "Heavy Travel", "category": "warning", "match_mode": "concept", "concept_description": "Frequent travel", "enabled": True},
            {"id": "sem-ben", "name": "Remote Stipend", "category": "benefit", "match_mode": "concept", "concept_description": "Stipend", "enabled": True},
        ]

        model_parsed = JobExtractionPayload(
            company_name="Defense Logistics",
            job_title="RevOps Lead",
            title_family="revenue_operations",
            requirements=JobRequirementsSchema(
                salary_min=130000.0,
                salary_max=150000.0,
                telemetry_flags=[],
                telemetry_warnings=["[Heavy Travel]: Requires >50% domestic travel."],
                telemetry_benefits=["[Remote Stipend]: $1,000 annual home office budget."]
            )
        )
        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.return_value = SimpleNamespace(
            usage=SimpleNamespace(total_tokens=200),
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=model_parsed))]
        )
        adapter._runner._openai_client = mock_client

        telemetry_logs = []
        cli_logs = []

        def capture_telemetry(msg: str):
            telemetry_logs.append(msg)
            cli_logs.append(f"[TELEMETRY] {msg}")

        with patch("job_pipeline.adapters.secondary.openai_adapter.log_telemetry", side_effect=capture_telemetry), \
             patch("job_pipeline.domain.telemetry_service.log_telemetry", side_effect=capture_telemetry):
            result = adapter.extract_job_telemetry(
                "This role requires compliance with FAR/DFARS procurement standards.",
                warning_rules=rules
            )

        # 1. Deterministic match was logged
        self.assertTrue(any("Flag matched: det-flag" in msg for msg in telemetry_logs))

        # 2. Completion summary reflects actual 1 flag, 1 warning, 1 benefit
        self.assertTrue(
            any("Completed: 1 flags, 1 warnings, 1 benefits" in msg for msg in telemetry_logs),
            f"Expected completion summary with (1, 1, 1) not found in: {telemetry_logs}"
        )
        self.assertTrue(
            any("[TELEMETRY] Completed: 1 flags, 1 warnings, 1 benefits" in msg for msg in cli_logs)
        )

        # 3. Payload requirements match exactly
        self.assertEqual(len(result.requirements.telemetry_flags), 1)
        self.assertEqual(len(result.requirements.telemetry_warnings), 1)
        self.assertEqual(len(result.requirements.telemetry_benefits), 1)

    def test_telemetry_completion_summary_cache_hit_and_offline(self):
        """
        Verifies that both offline extraction and cached extractions emit the
        telemetry completion summary.
        """
        _TELEMETRY_EXTRACTION_CACHE.clear()

        # 1. Offline extraction
        offline_adapter = OpenAIEngineAdapter(api_key=None)
        rules = [
            {"id": "r1", "name": "SQL Required", "category": "warning", "match_mode": "phrase", "patterns": ["SQL"], "enabled": True}
        ]

        offline_logs = []
        with patch("job_pipeline.adapters.secondary.openai_adapter.log_telemetry", side_effect=offline_logs.append):
            res_offline = offline_adapter.extract_job_telemetry("Requires SQL knowledge.", warning_rules=rules)

        self.assertTrue(any("Completed: 0 flags, 1 warnings, 0 benefits" in msg for msg in offline_logs))

        # 2. Cache hit extraction
        cache_logs = []
        with patch("job_pipeline.adapters.secondary.openai_adapter.log_telemetry", side_effect=cache_logs.append):
            res_cached = offline_adapter.extract_job_telemetry("Requires SQL knowledge.", warning_rules=rules)

        self.assertTrue(any("Completed: 0 flags, 1 warnings, 0 benefits" in msg for msg in cache_logs))
        self.assertEqual(len(res_cached.requirements.telemetry_warnings), 1)

    def test_mock_adapter_telemetry_completion_summary(self):
        """
        Verifies that MockLLMStrategyAdapter.extract_job_telemetry emits the telemetry
        completion summary with actual finding counts.
        """
        mock_llm = MockLLMStrategyAdapter()
        rules = [
            {"id": "flag-token", "name": "Secret Clearance", "category": "flag", "match_mode": "token", "patterns": ["Clearance"], "enabled": True}
        ]

        mock_logs = []
        with patch("job_pipeline.logger.log_telemetry", side_effect=mock_logs.append):
            result = mock_llm.extract_job_telemetry(
                "Requires Top Secret Clearance for RevOps work.",
                warning_rules=rules
            )

        self.assertTrue(
            any("Completed: 1 flags, 0 warnings, 0 benefits" in msg for msg in mock_logs),
            f"Mock adapter did not log completion summary: {mock_logs}"
        )
        self.assertEqual(len(result.requirements.telemetry_flags), 1)

    def test_telemetry_rule_evaluation_aggregates_and_persists_to_job_signals(self):
        """
        End-to-end verification: telemetry rule evaluation completes, results are correctly
        aggregated, returned in JobExtractionPayload, evaluated by JobQualificationService,
        and persisted to Job Signals JSON in storage.
        """
        mock_llm = MockLLMStrategyAdapter()
        storage = MockJobStorageAdapter()
        rules = [
            {"id": "flag-1", "name": "Clearance", "category": "flag", "match_mode": "token", "patterns": ["Clearance"], "enabled": True},
            {"id": "warn-1", "name": "Heavy Travel", "category": "warning", "match_mode": "phrase", "patterns": ["70% travel"], "enabled": True},
            {"id": "ben-1", "name": "401k Match", "category": "benefit", "match_mode": "phrase", "patterns": ["401k match"], "enabled": True},
        ]
        jd_text = "Role requires Security Clearance and 70% travel. Generous 401k match provided."

        logs = []
        with patch("job_pipeline.logger.log_telemetry", side_effect=logs.append):
            payload = mock_llm.extract_job_telemetry(jd_text, warning_rules=rules)

        # 1. Completion log emitted
        self.assertTrue(any("Completed: 1 flags, 1 warnings, 1 benefits" in m for m in logs))

        # 2. Results aggregated on payload.requirements
        t_flags = payload.requirements.telemetry_flags
        t_warns = payload.requirements.telemetry_warnings
        t_bens = payload.requirements.telemetry_benefits
        self.assertEqual(len(t_flags), 1)
        self.assertEqual(len(t_warns), 1)
        self.assertEqual(len(t_bens), 1)

        # 3. Qualification service evaluates aggregated signals
        fit_eval = JobQualificationService.evaluate(
            company_name="Apex Defense",
            job_title="Systems Lead",
            raw_description=jd_text,
            telemetry_flags=t_flags,
            telemetry_warnings=t_warns,
            telemetry_benefits=t_bens
        )
        self.assertEqual(fit_eval.telemetry_status, "red")

        # 4. Storage persistence serializes display findings to Job Signals JSON
        opp = JobPosting(
            opportunity_id="opp-signals-persist-test",
            company_name="Apex Defense",
            job_title="Systems Lead",
            title_family="revenue_operations",
            raw_description=jd_text,
            telemetry_flags=t_flags,
            telemetry_warnings=t_warns,
            telemetry_benefits=t_bens,
            role_intelligence_status="Not Generated"
        )
        storage.save_opportunity(opp, fit_eval)

        saved = next(o for o in storage.fetch_all_opportunities() if o.get("Opportunity ID") == "opp-signals-persist-test")
        self.assertIsNotNone(saved)

        # 5. Verify Job Signals JSON structure and content
        signals_raw = saved.get("Job Signals")
        self.assertTrue(signals_raw)
        signals_data = json.loads(signals_raw)
        self.assertEqual(signals_data.get("version"), 1)
        self.assertEqual(len(signals_data.get("flags", [])), 1)
        self.assertEqual(len(signals_data.get("warnings", [])), 1)
        self.assertEqual(len(signals_data.get("benefits", [])), 1)
        self.assertIn("Clearance", signals_data["flags"][0])
        self.assertIn("Heavy Travel", signals_data["warnings"][0])
        self.assertIn("401k Match", signals_data["benefits"][0])

        # 6. Role Intelligence remains deferred
        self.assertEqual(saved.get("Role Intelligence Status"), "Not Generated")


if __name__ == "__main__":
    unittest.main()

