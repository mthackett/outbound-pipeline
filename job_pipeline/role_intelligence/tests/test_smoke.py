from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]

import sys
sys.path.insert(0, str(ROOT))

from prepare_source_bundle import prepare_source_bundle
from recall_sheet_generator import generate_recall_sheet


class CandidateCockpitSmokeTest(unittest.TestCase):
    def validate(self, schema_name: str, payload_name: str) -> None:
        schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
        payload = json.loads((ROOT / payload_name).read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema).iter_errors(payload))
        self.assertFalse(errors, errors)

    def test_examples_validate(self) -> None:
        self.validate("source_bundle.schema.json", "examples/fictional/source_bundle_tagged.json")
        self.validate("value_match_strategy.schema.json", "examples/fictional/value_match_strategy.json")
        self.validate("cockpit_content.schema.json", "examples/fictional/cockpit_content.json")

    def test_source_tagger(self) -> None:
        raw = json.loads((ROOT / "examples/fictional/source_bundle_raw.json").read_text(encoding="utf-8"))
        tagged = prepare_source_bundle(raw)
        self.assertIn("[J001]", tagged["job"]["tagged_description"])
        self.assertIn("[R001]", tagged["resume"]["tagged_text"])

    def test_docx_generation(self) -> None:
        content = json.loads((ROOT / "examples/fictional/cockpit_content.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cockpit.docx"
            generate_recall_sheet(content, out, manifest_path="auto")
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 10_000)
            self.assertTrue(out.with_suffix(".manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
