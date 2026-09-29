import os
import unittest
from job_pipeline.domain.models import (
    CandidateProfile, JobPosting, FitEvaluation,
    DEFAULT_TELEMETRY_WARNING_RULES, TELEMETRY_WARNING_CATEGORIES
)
from job_pipeline.domain.services import JobQualificationService, PipelineConfigService
from job_pipeline.adapters.secondary.mock_adapter import MockLLMStrategyAdapter
from job_pipeline.adapters.secondary.openai_adapter import OpenAIEngineAdapter


class TestTelemetryWarnings(unittest.TestCase):
    def setUp(self):
        self.test_cfg_path = "test_telemetry_warnings_config.json"
        if os.path.exists(self.test_cfg_path):
            os.remove(self.test_cfg_path)

    def tearDown(self):
        if os.path.exists(self.test_cfg_path):
            os.remove(self.test_cfg_path)

    def test_default_warning_rules_in_config(self):
        """Verify PipelineConfigService loads default telemetry warning rules."""
        cfg = PipelineConfigService.load_config(self.test_cfg_path)
        self.assertIn("telemetry_warnings", cfg)
        rules = cfg["telemetry_warnings"]
        self.assertGreaterEqual(len(rules), 5)
        rule_ids = [r["id"] for r in rules]
        self.assertIn("warn-on-call", rule_ids)
        self.assertIn("warn-excessive-travel", rule_ids)
        self.assertIn("warn-no-benefits", rule_ids)
        self.assertIn("warn-legacy-stack", rule_ids)
        self.assertIn("warn-overbroad-scope", rule_ids)

    def test_add_toggle_and_remove_warning_rule(self):
        """Verify adding, toggling, updating, and removing warning rules."""
        # 1. Add new custom rule
        custom_rule = {
            "name": "Security Clearance Mandatory",
            "category": "Scope",
            "keywords": ["TS/SCI", "polygraph", "top secret clearance"],
            "concept_description": "Role requires candidate to hold active top secret clearance.",
            "severity": "Flag",
            "enabled": True
        }
        rules = PipelineConfigService.add_warning_rule(custom_rule, self.test_cfg_path)
        added = next((r for r in rules if r["name"] == "Security Clearance Mandatory"), None)
        self.assertIsNotNone(added)
        self.assertTrue(added["id"].startswith("warn-"))
        self.assertTrue(added["enabled"])
        rule_id = added["id"]

        # 2. Toggle rule
        toggled_rules = PipelineConfigService.toggle_warning_rule(rule_id, self.test_cfg_path)
        toggled = next((r for r in toggled_rules if r["id"] == rule_id), None)
        self.assertFalse(toggled["enabled"])

        # Toggle back on
        active_rules = PipelineConfigService.toggle_warning_rule(rule_id, self.test_cfg_path)
        toggled_on = next((r for r in active_rules if r["id"] == rule_id), None)
        self.assertTrue(toggled_on["enabled"])

        # 3. Update rule
        updated_rules = PipelineConfigService.update_warning_rule(
            rule_id,
            {"concept_description": "Updated clearance condition text."},
            self.test_cfg_path
        )
        updated = next((r for r in updated_rules if r["id"] == rule_id), None)
        self.assertEqual(updated["concept_description"], "Updated clearance condition text.")

        # 4. Remove rule
        remaining_rules = PipelineConfigService.remove_warning_rule(rule_id, self.test_cfg_path)
        self.assertIsNone(next((r for r in remaining_rules if r["id"] == rule_id), None))

        # 5. Reset to defaults
        reset_rules = PipelineConfigService.reset_default_warning_rules(self.test_cfg_path)
        self.assertEqual(len(reset_rules), len(DEFAULT_TELEMETRY_WARNING_RULES))

    def test_evaluate_with_telemetry_warnings(self):
        """Verify JobQualificationService highlights each telemetry warning infraction."""
        profile = CandidateProfile(minimum_compensation_floor=100000)
        telemetry_warns = [
            "[On-Call / Weekend Support Required]: Mentions '24/7 on-call rotation'",
            "[Excessive Travel (>25%)]: Role requires 'frequent travel 50%'"
        ]

        fit_eval = JobQualificationService.evaluate(
            company_name="Acme Corp",
            job_title="Revenue Operations Analyst",
            raw_description="Salesforce SQL dbt revops analyst role.",
            required_skills=["Salesforce", "SQL"],
            salary_min=120000,
            salary_max=140000,
            profile=profile,
            telemetry_warnings=telemetry_warns
        )

        self.assertTrue(fit_eval.is_qualified)
        self.assertEqual(fit_eval.status, "PASS")
        self.assertIn("Passed with telemetry warning(s)", fit_eval.reasoning)
        for w in telemetry_warns:
            self.assertIn(w, fit_eval.warnings)
            self.assertIn(w, fit_eval.reasoning)

    def test_evaluate_critical_flag_telemetry(self):
        """Verify severe Flag telemetry triggers FLAGGED_TELEMETRY."""
        profile = CandidateProfile(minimum_compensation_floor=100000)
        critical_warns = [
            "FLAG: [Security Clearance Mandatory]: Role requires active polygraph clearance"
        ]

        fit_eval = JobQualificationService.evaluate(
            company_name="Defense Contractors Inc",
            job_title="Revenue Operations Analyst",
            raw_description="Salesforce SQL role with active polygraph requirement.",
            required_skills=["Salesforce", "SQL"],
            salary_min=120000,
            salary_max=140000,
            profile=profile,
            telemetry_warnings=critical_warns
        )

        self.assertFalse(fit_eval.is_qualified)
        self.assertEqual(fit_eval.status, "FLAGGED_TELEMETRY")
        self.assertIn("Flagged Telemetry", fit_eval.reasoning)
        self.assertIn("Security Clearance Mandatory", fit_eval.reasoning)

    def test_mock_adapter_telemetry_keyword_extraction(self):
        """Verify MockLLMStrategyAdapter detects warning keywords in raw JD."""
        mock_llm = MockLLMStrategyAdapter()
        raw_jd = (
            "We are seeking a RevOps Analyst. Note: This position requires 24/7 on-call pagerduty "
            "coverage every other week and frequent travel to client sites."
        )
        rules = [
            {
                "id": "warn-on-call",
                "name": "On-Call Support",
                "category": "Scope",
                "keywords": ["on-call", "24/7", "pagerduty"],
                "concept_description": "On call required",
                "severity": "Warning",
                "enabled": True
            },
            {
                "id": "warn-travel",
                "name": "Frequent Travel",
                "category": "Scope",
                "keywords": ["frequent travel", "extensive travel"],
                "concept_description": "Travel required",
                "severity": "Warning",
                "enabled": True
            }
        ]

        payload = mock_llm.extract_job_telemetry(raw_jd, warning_rules=rules)
        warns = payload.requirements.telemetry_warnings
        self.assertEqual(len(warns), 2)
        self.assertTrue(any("On-Call Support" in w for w in warns))
        self.assertTrue(any("Frequent Travel" in w for w in warns))

    def test_openai_adapter_offline_keyword_detection(self):
        """Verify OpenAIEngineAdapter detects keywords even when running offline without API key."""
        adapter = OpenAIEngineAdapter(api_key=None)
        raw_jd = "Looking for an engineer to maintain COBOL codebase. Commission only, no benefits offered."
        rules = [
            {
                "name": "No Benefits / Commission Only",
                "category": "Benefits",
                "keywords": ["commission only", "no benefits"],
                "concept_description": "No benefits or commission only",
                "severity": "Warning",
                "enabled": True
            },
            {
                "name": "Legacy Tech Stack",
                "category": "Skills",
                "keywords": ["COBOL", "VB6"],
                "concept_description": "Legacy languages",
                "severity": "Warning",
                "enabled": True
            }
        ]

        payload = adapter.extract_job_telemetry(raw_jd, warning_rules=rules)
        warns = payload.requirements.telemetry_warnings
        self.assertGreaterEqual(len(warns), 2)
        self.assertTrue(any("No Benefits / Commission Only" in w for w in warns))
        self.assertTrue(any("Legacy Tech Stack" in w for w in warns))


if __name__ == "__main__":
    unittest.main()
