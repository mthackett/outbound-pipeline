# Candidate Cockpit V1 prompt entry point

The V1 tool now uses a two-stage prompt architecture.

For production, use:

1. `prompts/value_match_strategy_prompt.md`
2. `prompts/cockpit_composition_prompt.md`

For a single model call, use:

- `prompts/all_in_one_prompt.md`

The strategy stage is intentionally separate because the most valuable output is the consultative matching layer: likely employer pain -> source-backed candidate evidence -> business value -> validation questions -> interview positioning.
