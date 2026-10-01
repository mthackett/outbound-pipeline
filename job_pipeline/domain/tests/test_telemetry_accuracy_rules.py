import os
import unittest
from unittest.mock import MagicMock
from job_pipeline.domain.models import (
    TelemetryRule,
    TelemetryFinding,
    CandidateProfile,
    FitEvaluation
)
from job_pipeline.domain.telemetry_service import TelemetryService
from job_pipeline.domain.services import JobQualificationService, PipelineConfigService
from job_pipeline.adapters.secondary.mock_adapter import MockLLMStrategyAdapter


class TestTelemetryAccuracyAndRuleSystem(unittest.TestCase):
    def setUp(self):
        self.test_cfg = "test_telemetry_accuracy_config.json"
        if os.path.exists(self.test_cfg):
            os.remove(self.test_cfg)

    def tearDown(self):
        if os.path.exists(self.test_cfg):
            os.remove(self.test_cfg)

    # -------------------------------------------------------------
    # 1. False-Positive Keyword Matching & Boundary Awareness
    # -------------------------------------------------------------
    def test_token_matching_far_boundary_awareness(self):
        """
        Verify exact token rule for 'FAR' matches only actual tokens
        and eliminates false positives inside other words (farewell, software, etc.).
        """
        far_rule = TelemetryRule(
            id="flag-far",
            name="Government Scope (FAR)",
            category="flag",
            match_mode="token",
            patterns=["FAR"],
            explanation="Role references Federal Acquisition Regulation (FAR) compliance.",
            domain_category="Scope"
        )

        # Negative cases: substrings inside words should NOT match
        non_matching_texts = [
            "We are seeking a software engineer to build web platforms.",
            "Please join us in bidding farewell to legacy tools.",
            "Experience working with local farmer markets.",
            "Modern cyber warfare defense analysis.",
            "Tested extensively on Apple Safari and Google Chrome browsers.",
            "A far-off target date for project delivery." # Note: lower case 'far' if case-insensitive, but let's test substrings
        ]

        for text in non_matching_texts[:5]:  # substrings: software, farewell, farmer, warfare, safari
            finding = TelemetryService.evaluate_deterministic_rule(far_rule, text)
            self.assertIsNone(
                finding,
                f"False positive detected: 'FAR' erroneously matched in: '{text}'"
            )

        # Positive cases: boundary-aware token matches
        matching_texts = [
            "Must have extensive FAR compliance experience.",
            "Hands-on experience with FAR and government procurement contracts.",
            "Strong understanding of FAR regulations.",
            "Compliance with applicable provisions of the FAR.",
            "Position requires FAR/DFARS knowledge."
        ]

        for text in matching_texts:
            finding = TelemetryService.evaluate_deterministic_rule(far_rule, text)
            self.assertIsNotNone(
                finding,
                f"Expected match for token 'FAR' in: '{text}'"
            )
            self.assertEqual(finding.category, "flag")
            self.assertEqual(finding.rule_id, "flag-far")
            self.assertIn("FAR", finding.matched_text)

    def test_token_matching_special_characters(self):
        """Verify tokens with punctuation like '401(k)' or 'TS/SCI' match cleanly."""
        rule_401k = TelemetryRule(
            id="benefit-401k",
            name="401(k) Match",
            category="benefit",
            match_mode="token",
            patterns=["401(k)"],
            explanation="Offers 401(k) retirement matching."
        )

        finding = TelemetryService.evaluate_deterministic_rule(
            rule_401k,
            "We provide health insurance and competitive 401(k) matching."
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.matched_text, "401(k)")

    # -------------------------------------------------------------
    # 2. Phrase Matching (Case-Insensitive)
    # -------------------------------------------------------------
    def test_phrase_matching_case_insensitive(self):
        """Verify phrase match mode works case-insensitively with whole phrase boundaries."""
        phrase_rule = TelemetryRule(
            id="flag-fed-contractor",
            name="Federal Contractor Scope",
            category="flag",
            match_mode="phrase",
            patterns=["Federal Acquisition Regulation", "government contractor"],
            explanation="Position is tied to federal contracting requirements."
        )

        text_upper = "WE ARE A LEADING GOVERNMENT CONTRACTOR SERVING DEFENSE CLIENTS."
        finding1 = TelemetryService.evaluate_deterministic_rule(phrase_rule, text_upper)
        self.assertIsNotNone(finding1)
        self.assertEqual(finding1.category, "flag")
        self.assertEqual(finding1.match_mode, "phrase")

        text_mixed = "Candidate must ensure adherence to the Federal Acquisition Regulation guidelines."
        finding2 = TelemetryService.evaluate_deterministic_rule(phrase_rule, text_mixed)
        self.assertIsNotNone(finding2)
        self.assertIn("Federal Acquisition Regulation", finding2.matched_text)

    # -------------------------------------------------------------
    # 3. Regex Matching & Graceful Failure
    # -------------------------------------------------------------
    def test_valid_regex_matching(self):
        """Verify valid regex pattern is correctly evaluated."""
        regex_rule = TelemetryRule(
            id="flag-clearance",
            name="Security Clearance Required",
            category="flag",
            match_mode="regex",
            patterns=[r"\b(TS/SCI|Top\s+Secret)\b"],
            explanation="Requires active government security clearance."
        )

        finding = TelemetryService.evaluate_deterministic_rule(
            regex_rule,
            "Active TS/SCI clearance is strictly mandatory prior to day 1."
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.matched_text, "TS/SCI")

    def test_invalid_regex_fails_gracefully(self):
        """Verify invalid regex syntax logs a warning and does not crash execution."""
        bad_regex_rule = TelemetryRule(
            id="rule-bad-regex",
            name="Broken Regex Rule",
            category="warning",
            match_mode="regex",
            patterns=[r"(unclosed group[a-z+"],
            explanation="Broken pattern"
        )

        # Validation fails safely
        is_valid, err = TelemetryService.validate_rule(bad_regex_rule)
        self.assertFalse(is_valid)
        self.assertIn("Invalid regex pattern", err)

        # Evaluation fails safely with None, no exception raised
        finding = TelemetryService.evaluate_deterministic_rule(
            bad_regex_rule,
            "Sample text that should not crash processing."
        )
        self.assertIsNone(finding)

    # -------------------------------------------------------------
    # 4. Multiple Simultaneous Findings Preserved
    # -------------------------------------------------------------
    def test_multiple_findings_preserved(self):
        """
        Verify one posting can trigger multiple flags, warnings, and benefits simultaneously
        without stopping at the first match or collapsing them into an opaque blob.
        """
        rules = [
            TelemetryRule(
                id="flag-gov",
                name="Government Scope",
                category="flag",
                match_mode="token",
                patterns=["FAR", "DFARS"],
                explanation="Federal contractor scope."
            ),
            TelemetryRule(
                id="warn-travel",
                name="Heavy Travel",
                category="warning",
                match_mode="phrase",
                patterns=["frequent travel", "travel 50%"],
                explanation="Role requires frequent travel."
            ),
            TelemetryRule(
                id="warn-salesforce",
                name="Salesforce Required",
                category="warning",
                match_mode="token",
                patterns=["Salesforce"],
                explanation="Requires hands-on Salesforce administration."
            ),
            TelemetryRule(
                id="benefit-remote",
                name="Remote-First",
                category="benefit",
                match_mode="phrase",
                patterns=["remote-first", "100% remote"],
                explanation="Fully remote work culture."
            ),
            TelemetryRule(
                id="benefit-equity",
                name="Equity Offered",
                category="benefit",
                match_mode="token",
                patterns=["equity", "stock options"],
                explanation="Provides equity participation."
            )
        ]

        raw_jd = (
            "We are a remote-first organization offering competitive salary and equity. "
            "Note: This role is supporting a defense contract with FAR regulations, "
            "requires mandatory Salesforce administration, and involves frequent travel to customer sites."
        )

        findings = TelemetryService.evaluate_deterministic_rules(rules, raw_jd)

        # Verify all 5 rules fired independently
        self.assertEqual(len(findings), 5)

        rule_ids_fired = [f.rule_id for f in findings]
        self.assertIn("flag-gov", rule_ids_fired)
        self.assertIn("warn-travel", rule_ids_fired)
        self.assertIn("warn-salesforce", rule_ids_fired)
        self.assertIn("benefit-remote", rule_ids_fired)
        self.assertIn("benefit-equity", rule_ids_fired)

        flags, warnings, benefits = TelemetryService.split_findings(findings)
        self.assertEqual(len(flags), 1)
        self.assertEqual(len(warnings), 2)
        self.assertEqual(len(benefits), 2)

        # Each finding contains full explainability
        gov_finding = next(f for f in findings if f.rule_id == "flag-gov")
        self.assertEqual(gov_finding.matched_text, "FAR")
        self.assertEqual(gov_finding.category, "flag")
        self.assertIn("Federal contractor scope", gov_finding.reason)

    # -------------------------------------------------------------
    # 5. Category Precedence & Status Calculation
    # -------------------------------------------------------------
    def test_telemetry_status_precedence(self):
        """
        Verify:
        - No warnings or flags -> green
        - Warning present, no flags -> yellow
        - Flag present -> red (flags take precedence over warnings)
        - Benefits do not affect negative-severity status
        """
        flag_finding = TelemetryFinding(
            rule_id="f1", rule_name="Clearance Required", category="flag", match_mode="token", reason="Clearance"
        )
        warn_finding = TelemetryFinding(
            rule_id="w1", rule_name="On-Call Support", category="warning", match_mode="token", reason="On-call"
        )
        benefit_finding = TelemetryFinding(
            rule_id="b1", rule_name="Remote-First", category="benefit", match_mode="token", reason="Remote"
        )

        # Case 1: Clean (no warnings or flags) -> green
        self.assertEqual(TelemetryService.compute_telemetry_status([]), "green")
        # Case 1b: Only benefits -> still green!
        self.assertEqual(TelemetryService.compute_telemetry_status([benefit_finding]), "green")

        # Case 2: Only warnings -> yellow
        self.assertEqual(TelemetryService.compute_telemetry_status([warn_finding]), "yellow")
        # Case 2b: Warnings + benefits -> still yellow
        self.assertEqual(TelemetryService.compute_telemetry_status([warn_finding, benefit_finding]), "yellow")

        # Case 3: Flag present -> red
        self.assertEqual(TelemetryService.compute_telemetry_status([flag_finding]), "red")
        # Case 3b: Flag + Warnings -> red (Flag takes precedence)
        self.assertEqual(TelemetryService.compute_telemetry_status([flag_finding, warn_finding]), "red")
        # Case 3c: Flag + Warnings + Benefits -> red
        self.assertEqual(TelemetryService.compute_telemetry_status([flag_finding, warn_finding, benefit_finding]), "red")

    # -------------------------------------------------------------
    # 6. FitEvaluation Integration with Telemetry Findings
    # -------------------------------------------------------------
    def test_job_qualification_evaluates_telemetry_findings(self):
        """Verify JobQualificationService uses structured findings and sets telemetry_status."""
        profile = CandidateProfile(minimum_compensation_floor=90000)

        flag = TelemetryFinding(
            rule_id="f1", rule_name="Gov Contract", category="flag", match_mode="token",
            matched_text="FAR", reason="Federal procurement work"
        )
        benefit = TelemetryFinding(
            rule_id="b1", rule_name="Remote", category="benefit", match_mode="phrase",
            matched_text="remote-first", reason="Work from home"
        )

        fit_eval = JobQualificationService.evaluate(
            company_name="Defense Logistics",
            job_title="Revenue Operations Analyst",
            raw_description="Salesforce SQL analyst role.",
            required_skills=["Salesforce", "SQL"],
            salary_min=110000,
            salary_max=130000,
            profile=profile,
            telemetry_findings=[flag, benefit]
        )

        self.assertFalse(fit_eval.is_qualified)
        self.assertEqual(fit_eval.status, "FLAGGED_TELEMETRY")
        self.assertEqual(fit_eval.telemetry_status, "red")
        self.assertEqual(len(fit_eval.telemetry_findings), 2)
        self.assertEqual(len(fit_eval.telemetry_benefits), 1)

    # -------------------------------------------------------------
    # 7. Disabled Rules Do Not Execute
    # -------------------------------------------------------------
    def test_disabled_rules_do_not_execute(self):
        """Verify rules with enabled=False are ignored."""
        disabled_rule = TelemetryRule(
            id="rule-disabled",
            name="Disabled Rule",
            category="flag",
            match_mode="token",
            patterns=["Salesforce"],
            enabled=False
        )

        finding = TelemetryService.evaluate_deterministic_rule(
            disabled_rule,
            "Requires expert knowledge of Salesforce CRM."
        )
        self.assertIsNone(finding)

    # -------------------------------------------------------------
    # 8. User-Configurable Rules Persistence & Normalization
    # -------------------------------------------------------------
    def test_user_configured_rules_persistence_and_update(self):
        """Verify adding, updating, toggling, and removing rules via PipelineConfigService."""
        # 1. Add benefit rule
        new_rule = {
            "name": "Generous PTO",
            "category": "benefit",
            "match_mode": "phrase",
            "patterns": ["unlimited PTO", "4 weeks vacation"],
            "explanation": "Offers generous paid time off.",
            "enabled": True
        }
        rules = PipelineConfigService.add_telemetry_rule(new_rule, self.test_cfg)
        saved = next((r for r in rules if r["name"] == "Generous PTO"), None)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["category"], "benefit")
        self.assertEqual(saved["match_mode"], "phrase")
        rule_id = saved["id"]

        # 2. Evaluate against text using saved rule
        active_rules = PipelineConfigService.get_active_telemetry_rules(self.test_cfg)
        findings = TelemetryService.evaluate_deterministic_rules(
            active_rules,
            "We offer unlimited PTO and health benefits."
        )
        self.assertTrue(any(f.rule_id == rule_id for f in findings))

        # 3. Toggle rule to disabled
        PipelineConfigService.toggle_telemetry_rule(rule_id, self.test_cfg)
        active_after_toggle = PipelineConfigService.get_active_telemetry_rules(self.test_cfg)
        self.assertFalse(any(r["id"] == rule_id for r in active_after_toggle))

        # 4. Remove rule
        PipelineConfigService.remove_telemetry_rule(rule_id, self.test_cfg)
        all_after_del = PipelineConfigService.get_telemetry_rules(self.test_cfg)
        self.assertFalse(any(r["id"] == rule_id for r in all_after_del))

    # -------------------------------------------------------------
    # 9. Semantic Rule Parsing (Mocked, No Live OpenAI Calls)
    # -------------------------------------------------------------
    def test_semantic_rule_prompt_generation_and_parsing(self):
        """Verify semantic prompt formatting and structured parsing from LLM response messages."""
        semantic_rules = [
            TelemetryRule(
                id="sem-fed-scope",
                name="Federal Procurement Scope",
                category="flag",
                match_mode="concept",
                concept_description="Role primarily supports federal government contracting and procurement.",
                explanation="Federal contractor scope condition."
            ),
            TelemetryRule(
                id="sem-ai-culture",
                name="AI-Forward Culture",
                category="benefit",
                match_mode="concept",
                concept_description="Engineering team leverages AI-assisted development tools and autonomy.",
                explanation="AI-forward developer scope."
            )
        ]

        # Verify prompt builder generates section
        prompt_sec = TelemetryService.build_semantic_prompt_section(semantic_rules)
        self.assertIn("CONFIGURABLE SEMANTIC TELEMETRY RULES", prompt_sec)
        self.assertIn("sem-fed-scope", prompt_sec)
        self.assertIn("sem-ai-culture", prompt_sec)

        # Mock LLM returned messages
        llm_messages = [
            "[Federal Procurement Scope]: The job post references prime contractor deliverables for civilian agencies.",
            "[AI-Forward Culture]: Team actively uses AI coding copilots and LLM workflows."
        ]

        parsed_findings = TelemetryService.parse_semantic_infractions(llm_messages, semantic_rules)
        self.assertEqual(len(parsed_findings), 2)

        fed_f = next(f for f in parsed_findings if f.rule_id == "sem-fed-scope")
        self.assertEqual(fed_f.category, "flag")
        self.assertEqual(fed_f.match_mode, "concept")
        self.assertIn("civilian agencies", fed_f.reason)

        ai_f = next(f for f in parsed_findings if f.rule_id == "sem-ai-culture")
        self.assertEqual(ai_f.category, "benefit")
        self.assertEqual(ai_f.match_mode, "concept")

    # -------------------------------------------------------------
    # 10. Rule Safety Validation
    # -------------------------------------------------------------
    def test_rule_validation_safeguards(self):
        """Verify invalid rule configurations fail safely with informative validation errors."""
        # Missing display name
        r1 = TelemetryRule(name="", category="warning", match_mode="token", patterns=["test"])
        ok1, err1 = TelemetryService.validate_rule(r1)
        self.assertFalse(ok1)
        self.assertIn("display name", err1)

        # Token rule with no patterns
        r2 = TelemetryRule(name="Empty Token", category="warning", match_mode="token", patterns=[])
        ok2, err2 = TelemetryService.validate_rule(r2)
        self.assertFalse(ok2)
        self.assertIn("at least one non-empty keyword", err2)

        # Concept rule with no concept_description
        r3 = TelemetryRule(name="Empty Concept", category="warning", match_mode="concept", concept_description="")
        ok3, err3 = TelemetryService.validate_rule(r3)
        self.assertFalse(ok3)
        self.assertIn("concept_description", err3)


if __name__ == "__main__":
    unittest.main()
