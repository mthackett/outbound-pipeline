"""Minimal programmatic usage examples for Candidate Cockpit V1."""

from recall_sheet_generator import generate_recall_sheet, load_json
from prepare_source_bundle import prepare_source_bundle

# 1) JAT -> provenance-tagged source bundle.
source = load_json("examples/fictional/source_bundle_raw.json")
tagged_source = prepare_source_bundle(source)

# Your application sends tagged_source through:
#   prompts/value_match_strategy_prompt.md
# then sends tagged_source + strategy through:
#   prompts/cockpit_composition_prompt.md
# The LLM layer should return structured JSON validated against the bundled schemas.

# 2) Deterministic JSON -> DOCX rendering.
content = load_json("examples/fictional/cockpit_content.json")

generate_recall_sheet(
    content,
    "candidate_cockpit.docx",
    variables={
        "posted_pay": "$105,000-$130,000 base",
        "target_pay": "$125,000",
    },
    manifest_path="auto",
)
