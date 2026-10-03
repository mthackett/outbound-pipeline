"""Focused semantic contract regression tests; no live API calls in the suite."""
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from job_pipeline.domain.models import TelemetryRule, JobPosting
from job_pipeline.domain.services import JobQualificationService
from job_pipeline.domain.telemetry_service import TelemetryService as T
from job_pipeline.adapters.secondary.openai_adapter import OpenAIEngineAdapter, JobExtractionPayload, JobRequirementsSchema


NORTHSTAR_JD = """Northstar Federal Systems seeks a Revenue Operations Manager.
An active government security clearance is required. This position directly performs
work under a US federal government contract. Professional Spanish proficiency is mandatory.
The role requires a weekly on-call rotation including nights and weekends, and 50% travel.
There is no base salary: earnings are entirely commission-based, with no employee benefits.
You will manage six direct reports. Applicants residing in Arizona are not eligible.
The role maintains COBOL-based applications. We are remote-first and value autonomy and innovation.
"""


def rules():
    return [TelemetryRule(id=rid, name=name, category=category, domain_category='Scope', match_mode='concept',
                          concept_description=condition, patterns=[example]) for rid, name, category, condition, example in [
        ('warn-ad5f99', 'Clearance', 'flag', 'Requires government security clearance.', 'clearance'),
        ('warn-9b2a88', 'Government Job', 'flag', 'Role directly performs government contract work.', 'federal'),
        ('rule-763273', 'Language Requirement', 'flag', 'Requires professional non-English proficiency; exclude preferred languages.', 'Spanish'),
        ('warn-on-call', 'On-Call / Weekend Support Required', 'warning', 'Requires nights, weekends or on-call.', 'on-call'),
        ('warn-excessive-travel', 'Excessive Travel (>25%)', 'warning', 'Requires more than 25% travel.', 'travel'),
        ('warn-no-benefits', 'No Benefits / Commission Only', 'warning', 'No benefits or guaranteed base salary.', 'commission'),
        ('warn-8d7ea8', 'People Management', 'warning', 'Has direct reports.', 'manage'),
        ('rule-2cd292', 'Location Requirement', 'warning', 'Excludes Arizona residents.', 'Arizona')]]


class TestSemanticContract(unittest.TestCase):
    def test_prompt_and_schema_require_exact_id_format(self):
        prompt = T.build_semantic_prompt_section(rules())
        for r in rules():
            self.assertIn(f'[{r.id}]', prompt)
            self.assertIn(r.concept_description, prompt)
            self.assertIn(r.patterns[0], prompt)
        self.assertIn('exact stable rule ID', prompt)
        self.assertIn('Do not substitute', prompt)
        self.assertIn('omit', prompt.lower())
        for field in ('telemetry_flags', 'telemetry_warnings', 'telemetry_benefits'):
            self.assertIn('[rule-id]: rationale', JobRequirementsSchema.model_fields[field].description)

    def test_exact_ids_names_and_configured_authority(self):
        configured = rules()
        for msg in ('[rule-763273]: Required Spanish.', '[Language Requirement]: Required Spanish.',
                    'BENEFIT: [rule-763273]: Required Spanish.'):
            found = T.parse_semantic_infractions([msg], configured)
            self.assertEqual(len(found), 1)
            self.assertEqual((found[0].rule_id, found[0].category, found[0].domain_category), ('rule-763273', 'flag', 'Scope'))

    def test_bracket_identifier_with_wrapped_rationale(self):
        # A valid bracketed identifier must survive line-wrapped evidence.
        found = T.parse_semantic_infractions(['[rule-763273]: Professional Spanish\nproficiency is required.'], rules())
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].reason, 'Professional Spanish proficiency is required.')

    def test_live_bare_id_response_maps_without_inventing_evidence(self):
        messages = ['warn-9b2a88', 'warn-no-benefits', 'warn-8d7ea8', 'rule-2cd292', 'rule-763273']
        found = T.parse_semantic_infractions(messages, rules())
        self.assertEqual([f.rule_id for f in found], messages)
        self.assertTrue(all('rationale' in f.reason.lower() for f in found))
        disabled = rules()
        disabled[0].enabled = False
        self.assertEqual(T.parse_semantic_infractions(['unknown-id', 'Innovative Culture', 'warn-ad5f99'], disabled), [])

    def test_unknown_invented_disabled_and_fuzzy_outputs_rejected(self):
        configured = rules()
        configured[0].enabled = False
        messages = ['[unknown-id]: invented', '[Innovative Culture]: autonomy', 'A role mentioning rule-763273 is concerning',
                    '[warn-ad5f99]: required', '[Language]: required']
        self.assertEqual(T.parse_semantic_infractions(messages, configured), [])

    def test_literal_boundaries_unchanged(self):
        self.assertIsNotNone(T.match_phrase('fluent', 'fluent in Spanish'))
        self.assertIsNone(T.match_phrase('fluent', 'systems-fluent'))
        self.assertIsNotNone(T.match_phrase('COBOL', 'COBOL applications'))
        self.assertIsNone(T.match_phrase('COBOL', 'COBOL-based applications'))

    def test_northstar_response_through_sheet_and_ui(self):
        from job_pipeline.adapters.secondary.google_sheets import GoogleSheetsAdapter
        from streamlit.testing.v1 import AppTest
        configured = rules()
        # Deliberately return findings in the wrong classification array.
        response = JobExtractionPayload(company_name='Northstar', job_title='Manager', title_family='revenue_operations',
            requirements=JobRequirementsSchema(telemetry_benefits=[f'[{r.id}]: {r.concept_description}' for r in configured]
                                               + ['[Innovative Culture]: innovative and remote-first']))
        adapter = OpenAIEngineAdapter(api_key='test-key')
        client = MagicMock()
        client.beta.chat.completions.parse.return_value = SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(parsed=response))])
        adapter._runner._openai_client = client
        with patch.object(T, 'get_cached_extraction', return_value=None):
            payload = adapter.extract_job_telemetry(NORTHSTAR_JD, [r.model_dump() for r in configured])
        req = payload.requirements
        self.assertEqual([len(req.telemetry_flags), len(req.telemetry_warnings), len(req.telemetry_benefits)], [3, 5, 0])
        fit = JobQualificationService.evaluate(company_name='Northstar', job_title='Manager', raw_description=NORTHSTAR_JD,
            telemetry_flags=req.telemetry_flags, telemetry_warnings=req.telemetry_warnings, telemetry_benefits=req.telemetry_benefits)
        with patch.object(GoogleSheetsAdapter, '_init_connection'):
            storage = GoogleSheetsAdapter(spreadsheet_id='test')
        ws = MagicMock()
        ws.row_values.return_value = ['Opportunity ID', 'Job Signals']
        ws.col_count = 50
        ws.get_all_records.return_value = []
        storage._spreadsheet = MagicMock()
        storage._spreadsheet.worksheet.side_effect = lambda name: ws if name == 'Raw Ingestion' else MagicMock(get_all_records=MagicMock(return_value=[]))
        job = JobPosting(opportunity_id='northstar-test', company_name='Northstar', job_title='Manager', title_family='revenue_operations', raw_description=NORTHSTAR_JD)
        self.assertTrue(storage.save_opportunity(job, fit))
        stored = ws.append_row.call_args[0][0][1]
        self.assertEqual([len(g) for g in T.load_display_findings(stored)], [3, 5, 0])
        app = AppTest.from_string('''
import streamlit as st
from job_pipeline.domain.telemetry_service import TelemetryService
from job_pipeline.adapters.primary.telemetry_ui import render_job_signals
render_job_signals(*TelemetryService.load_display_findings(st.session_state.signals))
''')
        app.session_state.signals = stored
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual((len(app.error), len(app.warning), len(app.success)), (1, 1, 0))
