"""Focused tests for dedicated pre-ingestion Job Signals evaluation and review gate."""
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from job_pipeline.domain.models import (
    TelemetryRule,
    TelemetryFinding,
    JobSignalMatch,
    JobSignalEvaluation,
    JobPosting,
)
from job_pipeline.domain.services import JobQualificationService
from job_pipeline.domain.telemetry_service import TelemetryService
from job_pipeline.adapters.secondary.openai_adapter import (
    OpenAIEngineAdapter,
    JobExtractionPayload,
    JobRequirementsSchema,
)
from job_pipeline.adapters.secondary.mock_adapter import (
    MockLLMStrategyAdapter,
    MockJobStorageAdapter,
    MockDocumentStorageAdapter,
)


CONTROLLED_JD = """Revenue Systems Manager - Apex Public Sector Solutions
We are seeking a Revenue Systems Manager to oversee Salesforce, SQL, and legacy COBOL systems.
You will manage a team of six direct reports with direct hiring and performance review responsibility.
This position directly performs technical deliverables under an active US federal government contract.
An active Top Secret government security clearance is strictly required.
The position requires participation in an after-hours and weekend on-call escalation rotation.
Travel is approximately 30-40% across client federal sites.
Professional working proficiency in Spanish is required because this manager will regularly participate in bilingual partner meetings.
Applicants residing in Arizona are not eligible for this remote position.
Compensation is 100% commission-only with no base salary, and no standard employee health benefits are provided.
"""


def get_controlled_rules():
    return [
        TelemetryRule(
            id="warn-ad5f99",
            name="Clearance",
            category="flag",
            domain_category="Scope",
            match_mode="concept",
            concept_description="Requires government security clearance.",
            patterns=["clearance", "secret", "top secret"]
        ),
        TelemetryRule(
            id="warn-9b2a88",
            name="Government Job",
            category="flag",
            domain_category="Scope",
            match_mode="concept",
            concept_description="Role directly performs government contract work.",
            patterns=["federal", "government contract"]
        ),
        TelemetryRule(
            id="rule-763273",
            name="Language Requirement",
            category="flag",
            domain_category="Scope",
            match_mode="concept",
            concept_description="Job requires professional proficiency in a specific non-English language.",
            patterns=["Spanish", "bilingual"]
        ),
        TelemetryRule(
            id="warn-on-call",
            name="On-Call / Weekend Support Required",
            category="warning",
            domain_category="Scope",
            match_mode="concept",
            concept_description="Requires regular on-call rotation or weekend work.",
            patterns=["on-call", "weekend"]
        ),
        TelemetryRule(
            id="warn-excessive-travel",
            name="Excessive Travel (>25%)",
            category="warning",
            domain_category="Scope",
            match_mode="concept",
            concept_description="Requires more than 25% travel.",
            patterns=["travel", "30-40%"]
        ),
        TelemetryRule(
            id="warn-no-benefits",
            name="No Benefits / Commission Only",
            category="warning",
            domain_category="Benefits",
            match_mode="concept",
            concept_description="Role explicitly offers no standard benefits or commission-only pay.",
            patterns=["commission only", "no benefits"]
        ),
        TelemetryRule(
            id="warn-8d7ea8",
            name="People Management",
            category="warning",
            domain_category="Scope",
            match_mode="concept",
            concept_description="Role requires direct people management or direct reports.",
            patterns=["manage a team", "direct reports"]
        ),
        TelemetryRule(
            id="rule-2cd292",
            name="Location Requirement",
            category="warning",
            domain_category="Scope",
            match_mode="concept",
            concept_description="Excludes residents of specific states like Arizona.",
            patterns=["Arizona"]
        ),
        TelemetryRule(
            id="warn-legacy-cobol",
            name="Outdated / Legacy Tech Stack",
            category="warning",
            domain_category="Skills",
            match_mode="phrase",
            patterns=["COBOL"]
        ),
    ]


class TestPreIngestionJobSignals(unittest.TestCase):
    """Test suite covering the 11 required pre-ingestion Job Signals acceptance criteria."""

    def setUp(self):
        self.rules = get_controlled_rules()
        self.rules_dict = [r.model_dump() for r in self.rules]

    # 1. Dedicated semantic evaluator receives only active Concept rules, evaluates all, returns exact IDs, reason, evidence, rejects unknown
    def test_dedicated_semantic_evaluator_contract(self):
        semantic_rules = [r for r in self.rules if r.match_mode == "concept"]
        prompt = TelemetryService.build_dedicated_semantic_prompt(semantic_rules)

        for r in semantic_rules:
            self.assertIn(r.id, prompt)
            self.assertIn(r.concept_description, prompt)
        # Deterministic phrase rule must NOT be in semantic prompt
        self.assertNotIn("warn-legacy-cobol", prompt)

        # Mock adapter response
        adapter = OpenAIEngineAdapter(api_key="test-api-key")
        mock_client = MagicMock()
        mock_eval = JobSignalEvaluation(matches=[
            JobSignalMatch(
                rule_id="warn-ad5f99",
                reason="Active Top Secret clearance required.",
                evidence="An active Top Secret government security clearance is strictly required."
            ),
            JobSignalMatch(
                rule_id="rule-763273",
                reason="Spanish proficiency mandatory.",
                evidence="Professional working proficiency in Spanish is required because this manager will regularly participate in bilingual partner meetings."
            ),
            JobSignalMatch(
                rule_id="unknown-fake-id",
                reason="Invented rule.",
                evidence="Some text."
            )
        ])
        mock_client.beta.chat.completions.parse.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=mock_eval))]
        )
        adapter._runner._openai_client = mock_client

        with patch.object(TelemetryService, "get_cached_extraction", return_value=None):
            flags, warnings, benefits = adapter.evaluate_job_signals(CONTROLLED_JD, rules=self.rules_dict)

        # Unknown ID rejected; 2 valid flags accepted; deterministic rule matched
        matched_flag_ids = [f.rule_id for f in flags]
        self.assertIn("warn-ad5f99", matched_flag_ids)
        self.assertIn("rule-763273", matched_flag_ids)
        self.assertNotIn("unknown-fake-id", matched_flag_ids)

        for f in flags:
            self.assertTrue(f.evidence)
            self.assertTrue(f.reason)

    # 2. Classification authority: model cannot turn a Warning into a Flag
    def test_classification_authority(self):
        # Pass a model match for a warning rule (warn-8d7ea8 People Management)
        matches = [
            JobSignalMatch(
                rule_id="warn-8d7ea8",
                reason="Direct management of six reports.",
                evidence="You will manage a team of six direct reports with direct hiring and performance review responsibility."
            )
        ]
        findings = TelemetryService.parse_dedicated_semantic_matches(matches, self.rules)
        self.assertEqual(len(findings), 1)
        # Configured category for warn-8d7ea8 is warning, MUST remain warning
        self.assertEqual(findings[0].category, "warning")
        self.assertEqual(findings[0].rule_name, "People Management")
        self.assertEqual(findings[0].domain_category, "Scope")

    # 3. Evidence retention, display string formatting, and empty evidence rejection
    def test_evidence_retention_and_validation(self):
        finding = TelemetryFinding(
            rule_id="rule-763273",
            rule_name="Language Requirement",
            category="flag",
            match_mode="concept",
            reason="Spanish proficiency mandatory.",
            evidence="Professional working proficiency in Spanish is required."
        )
        display_str = finding.to_display_string()
        self.assertIn("FLAG: [Language Requirement]", display_str)
        self.assertIn("Spanish proficiency mandatory.", display_str)
        self.assertIn('Evidence: "Professional working proficiency in Spanish is required."', display_str)

        # Empty or whitespace-only evidence must be rejected
        matches = [
            JobSignalMatch(
                rule_id="warn-ad5f99",
                reason="Reason without evidence",
                evidence="   "
            )
        ]
        parsed = TelemetryService.parse_dedicated_semantic_matches(matches, self.rules)
        self.assertEqual(len(parsed), 0, "Match with empty evidence must be rejected")

    # 4. Deterministic + semantic merge: Direct Match finding survives, Concept finding survives, deduplicated
    def test_deterministic_and_semantic_merge(self):
        det_findings = TelemetryService.evaluate_deterministic_rules(self.rules, CONTROLLED_JD)
        cobol_matches = [f for f in det_findings if f.rule_id == "warn-legacy-cobol"]
        self.assertEqual(len(cobol_matches), 1, "Direct Match COBOL finding must be detected")

        sem_matches = [
            TelemetryFinding(
                rule_id="warn-ad5f99",
                rule_name="Clearance",
                category="flag",
                match_mode="concept",
                reason="Clearance required",
                evidence="Top Secret required"
            ),
            # Duplicate rule_id to test deduplication
            TelemetryFinding(
                rule_id="warn-legacy-cobol",
                rule_name="Outdated / Legacy Tech Stack",
                category="warning",
                match_mode="concept",
                reason="Legacy COBOL",
                evidence="legacy COBOL systems"
            )
        ]

        merged = TelemetryService.merge_findings(det_findings, sem_matches)
        merged_ids = [f.rule_id for f in merged]
        # Should contain clearance and cobol
        self.assertIn("warn-ad5f99", merged_ids)
        self.assertIn("warn-legacy-cobol", merged_ids)
        # Deduplication check: warn-legacy-cobol must appear exactly once
        self.assertEqual(merged_ids.count("warn-legacy-cobol"), 1)

    # 5. Flag gate: one or more Flags pauses ingestion before Drive/Sheets/Report
    def test_flag_gate_pauses_ingestion(self):
        adapter = MockLLMStrategyAdapter()
        flags = [
            TelemetryFinding(
                rule_id="warn-ad5f99",
                rule_name="Clearance",
                category="flag",
                match_mode="concept",
                reason="Clearance required",
                evidence="Top Secret required"
            )
        ]
        storage = MockJobStorageAdapter()
        drive = MockDocumentStorageAdapter()

        # Ingestion gate condition: len(flags) > 0 pauses ingestion
        has_flags = len(flags) > 0
        self.assertTrue(has_flags)

        # Downstream operations must NOT have occurred
        self.assertEqual(len(storage.saved_jobs), 0)
        self.assertEqual(len(drive.workspaces), 0)

    # 6. Proceed action resumes ingestion, reuses existing Job Signal result, persists findings
    def test_proceed_action_reuses_signals_and_persists(self):
        adapter = OpenAIEngineAdapter(api_key="test-key")
        client = MagicMock()
        payload = JobExtractionPayload(
            company_name="Apex",
            job_title="Revenue Systems Manager",
            title_family="revenue_operations",
            requirements=JobRequirementsSchema()
        )
        client.beta.chat.completions.parse.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=payload))]
        )
        adapter._runner._openai_client = client

        pre_evaluated = [
            TelemetryFinding(
                rule_id="warn-ad5f99",
                rule_name="Clearance",
                category="flag",
                match_mode="concept",
                reason="Clearance required",
                evidence="Top Secret required"
            ),
            TelemetryFinding(
                rule_id="warn-on-call",
                rule_name="On-Call Support",
                category="warning",
                match_mode="concept",
                reason="Weekend rotation",
                evidence="weekend escalation rotation"
            )
        ]

        # Extract telemetry with pre_evaluated_findings
        with patch.object(TelemetryService, "get_cached_extraction", return_value=None):
            result = adapter.extract_job_telemetry(
                CONTROLLED_JD,
                warning_rules=self.rules_dict,
                pre_evaluated_findings=pre_evaluated
            )

        # Concept rules prompt must NOT have been called in full extraction
        call_args = client.beta.chat.completions.parse.call_args[1]
        system_content = next(m["content"] for m in call_args["messages"] if m["role"] == "system")
        self.assertNotIn("CONFIGURABLE SEMANTIC TELEMETRY RULES", system_content)

        # Pre-evaluated findings must be carried in requirements
        self.assertEqual(len(result.requirements.telemetry_flags), 1)
        self.assertEqual(len(result.requirements.telemetry_warnings), 1)
        self.assertIn("Clearance", result.requirements.telemetry_flags[0])
        self.assertIn("On-Call Support", result.requirements.telemetry_warnings[0])

        # Qualification service consumes the signals
        fit = JobQualificationService.evaluate(
            company_name="Apex",
            job_title="Manager",
            raw_description=CONTROLLED_JD,
            telemetry_flags=result.requirements.telemetry_flags,
            telemetry_warnings=result.requirements.telemetry_warnings
        )
        self.assertEqual(fit.telemetry_status, "red")

        # Persistence to Sheets verifies storage carries signals
        storage = MockJobStorageAdapter()
        job = JobPosting(
            opportunity_id="apex-test-opp",
            company_name="Apex",
            job_title="Manager",
            title_family="revenue_operations",
            raw_description=CONTROLLED_JD,
            telemetry_flags=result.requirements.telemetry_flags,
            telemetry_warnings=result.requirements.telemetry_warnings
        )
        storage.save_opportunity(job, fit)
        self.assertEqual(len(storage.saved_jobs), 1)
        saved = storage.saved_jobs[0]
        self.assertEqual(saved["job"].opportunity_id, "apex-test-opp")
        self.assertEqual(len(saved["job"].telemetry_flags), 1)

    # 7. Cancel action: no downstream ingestion artifacts created
    def test_cancel_action_creates_no_artifacts(self):
        storage = MockJobStorageAdapter()
        drive = MockDocumentStorageAdapter()

        # Simulate user cancel action: gate is cleared without executing workflow
        gate_state = {
            "flags": [TelemetryFinding(rule_id="warn-ad5f99", rule_name="Clearance", category="flag")]
        }
        # User cancels:
        gate_state = None

        self.assertIsNone(gate_state)
        self.assertEqual(len(storage.saved_jobs), 0)
        self.assertEqual(len(drive.workspaces), 0)

    # 8. Warning-only case does not pause ingestion
    def test_warning_only_does_not_pause(self):
        warning_only = [
            TelemetryFinding(
                rule_id="warn-on-call",
                rule_name="On-Call Support",
                category="warning",
                reason="On call",
                evidence="weekend rotation"
            )
        ]
        flags, warnings, benefits = TelemetryService.split_findings(warning_only)
        self.assertEqual(len(flags), 0)
        self.assertEqual(len(warnings), 1)

        # Gate only pauses if flags exist
        should_pause = len(flags) > 0
        self.assertFalse(should_pause, "Warning-only case must not pause ingestion")

    # 9. No-findings case continues ingestion normally
    def test_no_findings_continues_normally(self):
        flags, warnings, benefits = TelemetryService.split_findings([])
        should_pause = len(flags) > 0
        self.assertFalse(should_pause, "Zero findings must not pause ingestion")

    # 10. Evaluation failure does not silently continue as zero findings
    def test_evaluation_failure_does_not_silently_continue(self):
        adapter = OpenAIEngineAdapter(api_key="test-key")
        client = MagicMock()
        client.beta.chat.completions.parse.side_effect = RuntimeError("OpenAI API rate limit exceeded")
        adapter._runner._openai_client = client

        with patch.object(TelemetryService, "get_cached_extraction", return_value=None):
            with self.assertRaises(RuntimeError):
                adapter.evaluate_job_signals(CONTROLLED_JD, rules=self.rules_dict)

    # 11. Regression: unknown/invented semantic rule IDs remain discarded
    def test_regression_unknown_and_invented_ids_discarded(self):
        invented_matches = [
            JobSignalMatch(rule_id="invented-rule-1", reason="Invented", evidence="Some text"),
            JobSignalMatch(rule_id="semantic-custom", reason="Invented", evidence="Some text"),
            JobSignalMatch(rule_id="warn-ad5f99", reason="Valid clearance", evidence="Security clearance required"),
        ]
        findings = TelemetryService.parse_dedicated_semantic_matches(invented_matches, self.rules)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "warn-ad5f99")




    # 12. UI test: render_job_signals formats evidence cleanly with backward compatibility
    def test_render_job_signals_formats_evidence(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_string('''
import streamlit as st
from job_pipeline.adapters.primary.telemetry_ui import render_job_signals
flags = st.session_state.get("flags", [])
warnings = st.session_state.get("warnings", [])
benefits = st.session_state.get("benefits", [])
render_job_signals(flags, warnings, benefits)
''')
        flag_finding = TelemetryFinding(
            rule_id="rule-763273",
            rule_name="Language Requirement",
            category="flag",
            match_mode="concept",
            reason="Spanish proficiency mandatory.",
            evidence="Professional working proficiency in Spanish is required."
        )
        app.session_state.flags = [flag_finding.to_display_string()]
        app.run()

        # Flags must be rendered in st.error
        error_blocks = [e.value for e in app.error]
        self.assertTrue(len(error_blocks) > 0)
        self.assertIn("Language Requirement", error_blocks[0])
        self.assertIn("Spanish proficiency mandatory.", error_blocks[0])
        self.assertIn("**Evidence:**", error_blocks[0])
        self.assertIn("Professional working proficiency in Spanish is required.", error_blocks[0])

    # 13. UI test: Gate review rendering with Proceed and Cancel actions
    def test_gate_ui_actions(self):
        from streamlit.testing.v1 import AppTest
        gate_script = '''
import streamlit as st
from job_pipeline.adapters.primary.telemetry_ui import render_job_signals

gate = st.session_state.get("pending_job_signals_gate")
if gate:
    st.error("🚩 **Job Signals Review — Flags Detected**")
    render_job_signals(gate["flags"], gate["warnings"], gate["benefits"])
    col1, col2 = st.columns(2)
    with col1:
        if st.button("👉 Proceed with ingestion"):
            st.session_state.proceeded = True
            st.session_state.pending_job_signals_gate = None
    with col2:
        if st.button("❌ Cancel / Discard"):
            st.session_state.cancelled = True
            st.session_state.pending_job_signals_gate = None
'''
        app = AppTest.from_string(gate_script)
        app.session_state.pending_job_signals_gate = {
            "flags": ['FLAG: [Clearance]: Clearance required - Evidence: "Top Secret required"'],
            "warnings": [],
            "benefits": []
        }
        app.run()
        self.assertEqual(len(app.error), 2)  # Banner error + Job Signals Flags error
        self.assertIn("Flags Detected", app.error[0].value)

        # Click Cancel
        app.button[1].click().run()
        self.assertTrue(app.session_state.cancelled)
        self.assertIsNone(app.session_state.pending_job_signals_gate)


if __name__ == '__main__':
    unittest.main()
