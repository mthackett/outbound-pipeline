import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from job_pipeline.domain.models import TelemetryRule, FitEvaluation, JobPosting, DEFAULT_TELEMETRY_RULES
from job_pipeline.domain.services import PipelineConfigService, JobQualificationService
from job_pipeline.domain.telemetry_service import TelemetryService, _TELEMETRY_EXTRACTION_CACHE
from job_pipeline.adapters.secondary.openai_adapter import OpenAIEngineAdapter, JobExtractionPayload, JobRequirementsSchema
from job_pipeline.adapters.secondary.mock_adapter import MockJobStorageAdapter, MockLLMStrategyAdapter
from job_pipeline.adapters.primary.telemetry_ui import MATCH_TYPES, match_type_label, rule_editor_fields


def rule(**fields):
    return dict(id="language", name="Language Required", category="flag", match_mode="concept",
                concept_description="Requires professional non-English proficiency; exclude preferred languages.",
                patterns=["Spanish", "Mandarin", "fluent"], **fields)


class TestJobSignals(unittest.TestCase):
    def setUp(self):
        _TELEMETRY_EXTRACTION_CACHE.clear()

    def test_direct_boundaries_and_punctuation(self):
        for matcher in (TelemetryService.match_token, TelemetryService.match_phrase):
            for term, text in (("fluent", "must be fluent in Spanish"), ("data engineer", "A data engineer role"),
                               ("on-call", "Mandatory on-call rotation"), ("TS/SCI", "Active TS/SCI required"),
                               ("401(k)", "Includes 401(k) matching")):
                with self.subTest(term=term, matcher=matcher):
                    self.assertIsNotNone(matcher(term, text))
            for text in ("systems-fluent", "data-fluent", "fluent-systems", "systems\u2011fluent", "fluently"):
                self.assertIsNone(matcher("fluent", text))
            self.assertIsNone(matcher("SQL", "sql", case_sensitive=True))

    def test_regex_case_and_validation(self):
        self.assertEqual(TelemetryService.match_regex(r"SQL{1,2}", "sql"), "sql")
        self.assertIsNone(TelemetryService.match_regex("SQL", "sql", case_sensitive=True))
        self.assertIsNone(TelemetryService.match_regex("[", "text"))
        ok, error = TelemetryService.validate_rule(TelemetryRule(name="bad", match_mode="regex", patterns=["["]))
        self.assertFalse(ok)
        self.assertIn("Invalid regex", error)

    def test_prompt_only_active_concepts_and_supporting_hints(self):
        active = TelemetryRule(**rule())
        rules = [active, active.model_copy(update={"id": "disabled", "enabled": False}),
                 active.model_copy(update={"id": "literal", "match_mode": "token"})]
        prompt = TelemetryService.build_semantic_prompt_section(rules)
        for value in (active.id, active.name, active.concept_description, "Spanish", "NOT automatic triggers", "complete job-post context", "ONLY"):
            self.assertIn(value, prompt)
        self.assertNotIn("disabled", prompt)
        self.assertNotIn("[literal]", prompt)
        self.assertIsNone(TelemetryService.evaluate_deterministic_rule(active, "Spanish fluent bilingual"))

    def test_semantic_mapping_rejects_unknown_disabled_literal_and_substrings(self):
        active = TelemetryRule(**rule())
        rules = [active, active.model_copy(update={"id": "disabled", "name": "Disabled", "enabled": False}),
                 active.model_copy(update={"id": "literal", "name": "Literal", "match_mode": "token"})]
        messages = ["[unknown]: language is mentioned", "language occurs in unrelated prose",
                    "[disabled]: required", "[literal]: required", "[language-extra]: required"]
        with patch("job_pipeline.domain.telemetry_service.log_warn") as log:
            self.assertEqual(TelemetryService.parse_semantic_infractions(messages, rules), [])
            self.assertEqual(log.call_count, len(messages))
        for identifier in (active.id, active.name):
            found = TelemetryService.parse_semantic_infractions([f"BENEFIT: [{identifier}]: Spanish is mandatory"], rules)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].rule_id, active.id)
            self.assertEqual(found[0].category, "flag")

    def test_ambiguous_names_rejected_but_id_maps(self):
        a = TelemetryRule(**rule())
        b = a.model_copy(update={"id": "second"})
        self.assertEqual(TelemetryService.parse_semantic_infractions(["[Language Required]: text"], [a, b]), [])
        self.assertEqual(TelemetryService.parse_semantic_infractions(["[second]: text"], [a, b])[0].rule_id, "second")

    def test_cache_all_rule_properties_and_order(self):
        base = {**rule(), "match_mode": "phrase", "explanation": "Original", "domain_category": "Experience"}
        other = {**rule(), "id": "other"}
        key = TelemetryService.compute_cache_key("JD", [base, other])
        self.assertEqual(key, TelemetryService.compute_cache_key("JD", [other, dict(reversed(list(base.items())))]))
        changes = dict(id="new", name="Renamed", category="warning", match_mode="concept", patterns=["Portuguese"],
                       keywords=["Arabic"], concept_description="Different condition", explanation="Different explanation",
                       domain_category="Other", case_sensitive=True, enabled=False)
        for field, value in changes.items():
            with self.subTest(field=field):
                self.assertNotEqual(key, TelemetryService.compute_cache_key("JD", [{**base, field: value}, other]))

    def test_legacy_id_and_cache_stable_without_writes(self):
        legacy = {"name": "Legacy", "keywords": ["SQL"]}
        self.assertEqual(TelemetryService.normalize_rule_dict(legacy), TelemetryService.normalize_rule_dict(legacy))
        self.assertEqual(TelemetryService.compute_cache_key("JD", [legacy]), TelemetryService.compute_cache_key("JD", [legacy]))

    def test_cache_does_not_share_mutable_payload(self):
        TelemetryService.set_cached_extraction("key", {"warnings": []})
        a = TelemetryService.get_cached_extraction("key")
        a["warnings"].append("bad")
        self.assertEqual(TelemetryService.get_cached_extraction("key"), {"warnings": []})

    def test_domain_normalization_preserves_original_and_unknown_metadata(self):
        for severity in ("Warning", "Flag", "Benefit"):
            for domain in ("Scope", "Skills", "Experience", "Benefits", "Culture", "Compensation", "Other", "Custom Domain"):
                normalized = TelemetryService.normalize_rule_dict(dict(name="Legacy", category=domain, severity=severity, metadata={"x": 1}))
                self.assertEqual(normalized["domain_category"], domain)
                self.assertEqual(normalized["category"], severity.lower())
                self.assertEqual(normalized["metadata"], {"x": 1})
        normalized = TelemetryService.normalize_rule_dict(dict(name="Legacy", category="Skills", severity="Flag", domain_category="Experience"))
        self.assertEqual(normalized["domain_category"], "Experience")
        self.assertEqual(TelemetryRule(name="Legacy", category="Skills", severity="Flag", domain_category="Experience").domain_category, "Experience")

    def test_repairs_corrupt_domain_for_known_defaults(self):
        for default in DEFAULT_TELEMETRY_RULES:
            fixed = TelemetryService.normalize_rule_dict({**default, "domain_category": "warning"})
            self.assertEqual(fixed["domain_category"], default["domain_category"])
            self.assertEqual(fixed["match_mode"], "concept")
        fixed = TelemetryService.normalize_rule_dict({**rule(), "domain_category": "flag"})
        self.assertEqual(fixed["domain_category"], "Scope")

    @patch.dict(os.environ, {"OPENAI_API_KEY": ""})
    def test_extraction_offline_cache_and_explicit_categories(self):
        adapter = OpenAIEngineAdapter()
        direct = {**rule(), "match_mode": "phrase", "patterns": ["SQL"]}
        rules = [direct, {**direct, "id": "w", "category": "warning"}, {**direct, "id": "b", "category": "benefit"}]
        a = adapter.extract_job_telemetry("SQL", rules).requirements
        self.assertEqual([len(a.telemetry_flags), len(a.telemetry_warnings), len(a.telemetry_benefits)], [1, 1, 1])
        b = adapter.extract_job_telemetry("SQL", [{**r, "patterns": ["Python"]} for r in rules]).requirements
        self.assertEqual(b.telemetry_flags + b.telemetry_warnings + b.telemetry_benefits, [])
        mock = MockLLMStrategyAdapter().extract_job_telemetry("SQL", rules).requirements
        self.assertEqual(mock.telemetry_flags, a.telemetry_flags)

    def test_online_model_cannot_invent_or_override_classification(self):
        adapter = OpenAIEngineAdapter(api_key="test-key")
        parsed = JobExtractionPayload(company_name="Test", job_title="Analyst", title_family="revenue_operations",
                                      requirements=JobRequirementsSchema(telemetry_benefits=["[language]: Spanish is mandatory", "[unknown]: invented"]))
        client = MagicMock()
        client.beta.chat.completions.parse.return_value = SimpleNamespace(usage=SimpleNamespace(total_tokens=100),
                                                                         choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))])
        adapter._runner._openai_client = client
        result = adapter.extract_job_telemetry("Requires Spanish proficiency", [rule()])
        self.assertEqual(len(result.requirements.telemetry_flags), 1)
        self.assertEqual(result.requirements.telemetry_benefits, [])
        adapter.extract_job_telemetry("Requires Spanish proficiency", [rule()])
        self.assertEqual(client.beta.chat.completions.parse.call_count, 1)
        self.assertEqual(adapter.last_telemetry_tokens, 0)

    def test_old_models_load_and_legacy_prefixes_split(self):
        self.assertEqual(JobRequirementsSchema().telemetry_flags, [])
        self.assertEqual(JobPosting(opportunity_id="1", company_name="A", job_title="B", title_family="x", raw_description="JD").telemetry_flags, [])
        groups = TelemetryService.load_display_findings(None, "Flagged Telemetry: Critical warning condition triggered (FLAG: [Language]: Spanish required; [Travel]: 30%).")
        self.assertEqual([len(x) for x in groups], [1, 1, 0])
        self.assertIn("Language", groups[0][0])

    def test_classification_through_qualification_and_persistence(self):
        fit = JobQualificationService.evaluate(company_name="A", job_title="B", raw_description="SQL",
                                               telemetry_flags=["FLAG: [Language]: Spanish required"],
                                               telemetry_warnings=["[Travel]: 30%"], telemetry_benefits=["BENEFIT: [Remote]: Fully remote"])
        self.assertEqual(fit.telemetry_status, "red")
        storage = MockJobStorageAdapter()
        job = JobPosting(opportunity_id="new", company_name="A", job_title="B", title_family="x", raw_description="JD")
        storage.save_opportunity(job, fit)
        saved = next(r for r in storage.fetch_all_opportunities() if r['Opportunity ID'] == 'new')
        groups = TelemetryService.load_display_findings(saved['Job Signals'])
        self.assertEqual([len(x) for x in groups], [1, 1, 1])
        self.assertEqual(groups[0], fit.telemetry_flags)
        self.assertEqual(groups[1], fit.telemetry_warnings)


class TestJobSignalEditing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "pipeline.json")
        PipelineConfigService.save_config({"telemetry_rules": [], "other_config": {"keep": True}}, self.path)

    def test_create_and_edit_preserve_id_disabled_and_hidden_metadata(self):
        initial = {**rule(), "match_mode": "token", "enabled": False, "explanation": "Keep rationale", "extra": {"legacy": True}}
        initial.pop("id")
        created = PipelineConfigService.add_telemetry_rule(initial, self.path)[0]
        self.assertTrue(created['id'])
        self.assertEqual(match_type_label(created['match_mode']), "Direct Match")
        self.assertEqual(match_type_label("phrase"), "Direct Match")
        fields = rule_editor_fields(created, "New name", "warning", "Concept (LLM)", "Experience", ["Spanish"], "Required language", False, False)
        PipelineConfigService.update_telemetry_rule(created['id'], {**fields, "id": "must-not-change"}, self.path)
        saved = PipelineConfigService.get_telemetry_rules(self.path)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]['id'], created['id'])
        self.assertFalse(saved[0]['enabled'])
        self.assertEqual(saved[0]['name'], "New name")
        self.assertEqual(saved[0]['category'], "warning")
        self.assertEqual(saved[0]['match_mode'], "concept")
        self.assertEqual(saved[0]['extra'], {"legacy": True})
        self.assertEqual(saved[0]['explanation'], "Keep rationale")
        self.assertEqual(json.loads(Path(self.path).read_text())['other_config'], {"keep": True})

    def test_direct_edit_retains_hidden_condition_and_independent_keywords(self):
        existing = {**rule(), 'match_mode': 'phrase', 'keywords': ['independent hint']}
        fields = rule_editor_fields(existing, "Renamed", "flag", "Direct Match", "Scope", existing['patterns'], "", False, True)
        self.assertNotIn('concept_description', fields)
        self.assertNotIn('explanation', fields)
        self.assertNotIn('keywords', fields)
        PipelineConfigService.add_telemetry_rule(existing, self.path)
        PipelineConfigService.update_telemetry_rule(existing['id'], fields, self.path)
        saved = PipelineConfigService.get_telemetry_rules(self.path)[0]
        self.assertEqual(saved['concept_description'], existing['concept_description'])
        self.assertEqual(saved['keywords'], ['independent hint'])

    def test_invalid_rules_and_failed_writes_are_reported(self):
        with self.assertRaises(ValueError):
            PipelineConfigService.add_telemetry_rule({**rule(), 'concept_description': ''}, self.path)
        with self.assertRaises(ValueError):
            PipelineConfigService.add_telemetry_rule({**rule(), 'match_mode': 'regex', 'patterns': ['[']}, self.path)
        with patch.object(PipelineConfigService, 'save_config', return_value=False):
            with self.assertRaises(OSError):
                PipelineConfigService.add_telemetry_rule(rule(), self.path)

    def test_new_rules_get_distinct_ids_and_legacy_edit_is_stable(self):
        initial = rule()
        initial.pop('id')
        PipelineConfigService.add_telemetry_rule(initial, self.path)
        saved = PipelineConfigService.add_telemetry_rule(initial, self.path)
        self.assertNotEqual(saved[0]['id'], saved[1]['id'])
        Path(self.path).write_text(json.dumps({'telemetry_rules': [initial]}))
        loaded = PipelineConfigService.get_telemetry_rules(self.path)[0]
        PipelineConfigService.update_telemetry_rule(loaded['id'], {'name': 'Renamed legacy'}, self.path)
        self.assertEqual(PipelineConfigService.get_telemetry_rules(self.path)[0]['id'], loaded['id'])


class TestJobSignalsUI(unittest.TestCase):
    def test_app_recovery_uses_current_rules_instead_of_checkpoint_findings(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        from job_pipeline.adapters.secondary.mock_adapter import MockDocumentStorageAdapter
        st.cache_resource.clear()
        self.addCleanup(st.cache_resource.clear)
        drive = MockDocumentStorageAdapter()
        storage = MockJobStorageAdapter()
        workspace = drive.create_application_workspace('Example', 'Analyst', 'recovery-signals-test')
        folder = workspace['folder_id']
        jd = 'Responsibilities include SQL analytics and maintaining reporting tools.'
        drive.upload_raw_job_description(folder, jd)
        drive.workspaces[folder]['files'].append({'name': 'Role_Intelligence_Report.docx', 'id': 'report'})
        drive.save_ingestion_checkpoint(folder, {
            'opportunity_id': workspace['opportunity_id'], 'company': 'Original Company', 'title': 'Original Title',
            'family': 'revenue_operations', 'jd_text': jd, 'telemetry_warnings': ['[Old Rule]: Stale warning']
        })
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'config.json')
            PipelineConfigService.save_config({'telemetry_rules': [{**rule(), 'match_mode': 'token', 'patterns': ['SQL']}]}, path)
            with patch.dict(os.environ, {'DEMO_MODE': 'true', 'PIPELINE_CONFIG_PATH': path, 'ENABLE_CLI_LOGGING': 'false'}), \
                 patch('job_pipeline.adapters.secondary.mock_adapter.MockDocumentStorageAdapter', return_value=drive), \
                 patch('job_pipeline.adapters.secondary.mock_adapter.MockJobStorageAdapter', return_value=storage), \
                 patch('job_pipeline.domain.services.QuickLinksService.load_quicklinks', return_value=[]), \
                 patch('job_pipeline.domain.story_bank.StoryBankService.load_stories', return_value=[]), \
                 patch('job_pipeline.adapters.secondary.twilio_adapter.TwilioMessagingAdapter._init_client'):
                app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / 'adapters' / 'primary' / 'app.py'), default_timeout=15).run()
                self.assertFalse(app.exception)
                app.button(key=f'btn_res_{folder}').click().run()
                self.assertFalse(app.exception)
                saved = storage.fetch_all_opportunities()
                self.assertEqual(len(saved), 1, [e.value for e in app.error])
                self.assertEqual(saved[0]['Company Name'], 'Original Company')
                groups = TelemetryService.load_display_findings(saved[0]['Job Signals'])
                self.assertEqual([len(g) for g in groups], [1, 0, 0])
                self.assertIn('SQL', groups[0][0])
                self.assertNotIn('Stale', str(groups))

    def test_display_semantic_colors_order_and_empty_sections(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_string('''
from job_pipeline.adapters.primary.telemetry_ui import render_job_signals
render_job_signals(["FLAG: [Language]: Required Spanish"], ["[Travel]: 30%"], ["BENEFIT: [Remote]: Fully remote"])
''').run()
        self.assertFalse(app.exception)
        self.assertIn('Flags', app.error[0].value)
        self.assertIn('Warnings', app.warning[0].value)
        self.assertIn('Positive Signals', app.success[0].value)
        alerts = [element.type for element in app if element.type in ('error', 'warning', 'success')]
        self.assertEqual(alerts, ['error', 'warning', 'success'])
        empty = AppTest.from_string('''
from job_pipeline.adapters.primary.telemetry_ui import render_job_signals
render_job_signals([], [], ["BENEFIT: [Remote]: Fully remote"])
''').run()
        self.assertEqual(len(empty.error) + len(empty.warning), 0)
        self.assertEqual(len(empty.success), 1)

    def test_editor_default_and_reactive_conditional_fields(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_string('''
from job_pipeline.adapters.primary.telemetry_ui import render_rule_editor
render_rule_editor("test")
''').run()
        mode = app.selectbox(key='test_mode')
        self.assertEqual(mode.options, MATCH_TYPES)
        self.assertEqual(mode.value, 'Concept (LLM)')
        self.assertIn('Condition to detect', [w.label for w in app.text_area])
        self.assertNotIn('Case Sensitive', [w.label for w in app.checkbox])
        app.selectbox(key='test_mode').select('Direct Match').run()
        self.assertFalse(app.exception)
        self.assertNotIn('Condition to detect', [w.label for w in app.text_area])
        self.assertIn('Words or phrases to match', [w.label for w in app.text_area])
        self.assertIn('Case Sensitive', [w.label for w in app.checkbox])
        app.selectbox(key='test_mode').select('Regex (Advanced)').run()
        self.assertIn('Regex pattern(s)', [w.label for w in app.text_area])

    def test_editor_saves_to_canonical_config_and_preserves_disabled_id(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'config.json')
            PipelineConfigService.save_config({'telemetry_rules': [{**rule(), 'enabled': False, 'extra': 123}]}, path)
            with patch.dict(os.environ, {'PIPELINE_CONFIG_PATH': path}):
                app = AppTest.from_string('''
from job_pipeline.adapters.primary.telemetry_ui import render_rule_editor
from job_pipeline.domain.services import PipelineConfigService
render_rule_editor("edit", PipelineConfigService.get_telemetry_rules()[0])
''').run()
                app.text_input(key='edit_name').set_value('Edited Language')
                app.button(key='edit_save').click().run()
                self.assertFalse(app.exception)
                self.assertEqual(len(app.success), 1)
            saved = PipelineConfigService.get_telemetry_rules(path)[0]
            self.assertEqual(saved['id'], 'language')
            self.assertFalse(saved['enabled'])
            self.assertEqual(saved['name'], 'Edited Language')
            self.assertEqual(saved['extra'], 123)
