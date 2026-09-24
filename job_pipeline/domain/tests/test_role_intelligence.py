from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from job_pipeline.domain.role_intelligence import prepare_source_bundle
from job_pipeline.adapters.secondary.docx_report_generator import generate_recall_sheet

ROOT = Path(__file__).resolve().parents[2]  # job_pipeline
SCHEMAS_DIR = ROOT / "resources" / "schemas"
FIXTURES_DIR = ROOT / "examples" / "fixtures"


class RoleIntelligenceTests(unittest.TestCase):
    def validate(self, schema_name: str, payload_path: Path) -> None:
        schema = json.loads((SCHEMAS_DIR / schema_name).read_text(encoding="utf-8"))
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema).iter_errors(payload))
        self.assertFalse(errors, errors)

    def test_examples_validate_against_schemas(self) -> None:
        self.validate("source_bundle.schema.json", FIXTURES_DIR / "source_bundle_tagged.json")
        self.validate("value_match_strategy.schema.json", FIXTURES_DIR / "value_match_strategy.json")
        self.validate("cockpit_content.schema.json", FIXTURES_DIR / "mock_cockpit_content.json")

    def test_source_tagger(self) -> None:
        raw = json.loads((FIXTURES_DIR / "source_bundle_raw.json").read_text(encoding="utf-8"))
        tagged = prepare_source_bundle(raw)
        self.assertIn("[J001]", tagged["job"]["tagged_description"])
        self.assertIn("[R001]", tagged["resume"]["tagged_text"])

    def test_docx_generation(self) -> None:
        content = json.loads((FIXTURES_DIR / "mock_cockpit_content.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cockpit.docx"
            generate_recall_sheet(content, out, manifest_path="auto")
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 10_000)
            self.assertTrue(out.with_suffix(".manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
