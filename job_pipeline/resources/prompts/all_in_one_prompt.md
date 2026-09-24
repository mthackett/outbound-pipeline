# Candidate Cockpit V1: One-Call Prompt

Use this prompt when you want one model call instead of the recommended two-stage workflow.

You will receive a `source_bundle` containing the selected resume, JAT job metadata, job description, and optional compensation variables.

First perform the full consultative value-matching analysis described in `value_match_strategy_prompt.md`. Then compose the two-page cockpit described in `cockpit_composition_prompt.md`.

Return one JSON object with:

- `strategy`: the complete strategy object conforming to `schemas/value_match_strategy.schema.json`
- the normal cockpit rendering fields: `document_title`, `subject`, `author`, `variables`, `job`, `resume`, `generation`, and `pages`

The DOCX renderer ignores the top-level `strategy` field, so the same JSON can be rendered directly while retaining internal provenance and reasoning outputs for the JAT.

All source, inference, confidence, compensation, and anti-fabrication rules from both canonical prompts apply.

The two-stage workflow is preferred for production because it is easier to validate, debug, cache, and regenerate when only presentation changes.
