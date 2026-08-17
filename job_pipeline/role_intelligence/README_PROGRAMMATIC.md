# Candidate Cockpit V1

Candidate Cockpit turns a **specific job posting + the candidate's best-fit resume + JAT metadata** into a compact, job-specific interview and negotiation playbook.

The core product is not the DOCX. The core product is the **consultative value-matching layer** that asks:

> What business pain is this employer likely hiring to solve, what source-backed evidence shows the candidate can solve the same class of problem, how should the candidate frame that value, and what questions should they ask to validate the hypothesis?

The final deliverable is a two-page landscape DOCX designed for fast interview recall.

## V1 output

### Page 1: Job-targeted resume recall

- core fit
- proof numbers
- skimmable skill bank
- best-match experience
- strongest project/evidence
- story index
- quick answer recall

### Page 2: Consultative interview + offer playbook

- strong job-specific value thesis
- top 1-3 likely business pain hypotheses
- pain -> evidence -> value framing
- behavioral answer scaffolds + real story seeds
- compensation snapshot
- value-based negotiation anchors
- diagnostic questions to validate pain
- bridge points for adjacent experience
- first-90-day hypothesis
- role-scope prompts
- compact offer scorecard

## Architecture

The recommended production workflow is two-stage:

```text
JAT job record + selected resume
            |
            v
prepare_source_bundle.py
(add J001 / R001 provenance tags)
            |
            v
value_match_strategy_prompt.md
            |
            v
value_match_strategy.json
            |
            v
cockpit_composition_prompt.md
            |
            v
cockpit_content.json
            |
            v
recall_sheet_generator.py
            |
            +--> candidate_cockpit.docx
            +--> candidate_cockpit.manifest.json
```

Why two stages?

1. The strategy layer can be validated, cached, inspected, and improved independently.
2. The visual document can be regenerated without redoing the strategic analysis.
3. Provenance and confidence are easier to audit.
4. The JAT can reuse strategy outputs in future views or workflows.

For prototypes, `prompts/all_in_one_prompt.md` supports a single-call workflow.

## Install

```bash
pip install -r requirements.txt
```

## 1. Build the source bundle

Use `schemas/source_bundle.schema.json` as the JAT-to-Cockpit contract.

Important fields include:

- job ID, company, title
- complete job description
- posted compensation, including the original `raw` string
- work arrangement/location
- application status / interview stage
- extracted requirements if the JAT already has them
- selected resume ID/version
- complete extracted resume text
- optional target/floor/strong-win compensation supplied by the candidate

Start from `source_bundle_template.json`.

Add stable line tags:

```bash
python prepare_source_bundle.py \
  --input source_bundle.json \
  --output source_bundle_tagged.json
```

This adds provenance-friendly lines such as:

```text
[J003] Responsibilities include analyzing lead lifecycle conversion...
[R006] Analyzed lead lifecycle and routing data...
```

## 2. Generate consultative strategy

Use `prompts/value_match_strategy_prompt.md` with the tagged source bundle.

The strategy output conforms to:

```text
schemas/value_match_strategy.schema.json
```

Key outputs:

- 1-3 pain hypotheses with confidence labels
- employer signals supporting each hypothesis
- candidate evidence mapped to each pain
- likely business value + economic levers
- diagnostic questions
- strong one-line + three-pillar value thesis
- behavioral question scaffolds + story seeds
- positive bridge points for adjacent experience
- first-90-day hypothesis
- compensation context

### The most important rule

The strategy prompt optimizes for:

> What business problems is the employer trying to solve, and how can the candidate credibly position source-backed experience as evidence they can help solve them?

It does **not** optimize for keyword overlap alone.

## 3. Compose renderable cockpit JSON

Use `prompts/cockpit_composition_prompt.md` with:

- the original source bundle
- the completed strategy JSON

The output conforms to:

```text
schemas/cockpit_content.schema.json
```

The composition prompt is responsible for prioritizing information so the document remains a quick-glance two-page aid.

## 4. Render DOCX

```bash
python recall_sheet_generator.py \
  --content cockpit_content.json \
  --output candidate_cockpit.docx \
  --manifest auto
```

`--manifest auto` writes:

```text
candidate_cockpit.manifest.json
```

The manifest records the tool/template version, job/resume metadata, generation metadata, runtime variables, and output path.

### Runtime compensation injection

Content can include:

- `{{posted_pay}}`
- `{{target_pay}}`
- `{{floor_pay}}`
- `{{strong_win_pay}}`

Override at render time:

```bash
python recall_sheet_generator.py \
  --content cockpit_content.json \
  --output acme_cockpit.docx \
  --manifest auto \
  --set 'posted_pay=$110K-$135K' \
  --set 'target_pay=$130K'
```

Missing values render as `Set per role` by default. Change `unset_variable_text` in `default_config.json` if desired.

## Python API

```python
from recall_sheet_generator import generate_recall_sheet, load_json

content = load_json("cockpit_content.json")

generate_recall_sheet(
    content,
    "candidate_cockpit.docx",
    variables={"target_pay": "$130K"},
    manifest_path="auto",
)
```

## Validation

Validate every machine-generated intermediate before using it downstream:

```bash
python validate_json.py \
  --schema schemas/source_bundle.schema.json \
  --input source_bundle_tagged.json

python validate_json.py \
  --schema schemas/value_match_strategy.schema.json \
  --input value_match_strategy.json

python validate_json.py \
  --schema schemas/cockpit_content.schema.json \
  --input cockpit_content.json
```

## Provider-agnostic prompt assembly

`build_prompt_bundle.py` creates a single text payload you can send through any LLM client:

```bash
python build_prompt_bundle.py \
  --stage strategy \
  --source source_bundle_tagged.json \
  --output strategy_request.txt

python build_prompt_bundle.py \
  --stage compose \
  --source source_bundle_tagged.json \
  --strategy value_match_strategy.json \
  --output compose_request.txt
```

The helper intentionally does not call an LLM. Your JAT can use its existing model/API layer.

## Provenance model

V1 uses lightweight source IDs:

- `J###`: job-post lines
- `R###`: resume lines

Strategy objects carry `source_refs` and short source excerpts. The rendered DOCX does not display these references, but the JAT can retain them for:

- debugging
- hallucination review
- `Why did the tool choose this?` UI
- future strategy regeneration

### Source discipline

- candidate facts come only from the selected resume
- employer facts come only from the supplied job record/posting
- inferred pain is labeled with confidence
- employer-specific ROI is never invented
- salary targets are never inferred
- unsupported behavioral stories are replaced with answer frameworks rather than fabricated examples

## Job stage support

`interview_stage` is part of the source schema now even though V1 uses one core document format.

This keeps the model open for future stage-specific modes such as:

- recruiter screen
- hiring manager
- technical / analytics interview
- final round
- offer / negotiation

V1 intentionally does not branch into separate stage templates yet.

## File map

```text
README.md
recall_sheet_generator.py       deterministic DOCX renderer
prepare_source_bundle.py        J/R provenance tags
build_prompt_bundle.py          provider-agnostic prompt assembly
validate_json.py                JSON Schema validation
default_config.json             layout / typography settings
content_template.json           blank render-content template
source_bundle_template.json     blank JAT/resume input contract
requirements.txt
JAT_INTEGRATION.md
PUBLISHING_CHECKLIST.md
CHANGELOG.md
tests/

prompts/
  value_match_strategy_prompt.md
  cockpit_composition_prompt.md
  all_in_one_prompt.md

schemas/
  source_bundle.schema.json
  value_match_strategy.schema.json
  cockpit_content.schema.json

examples/fictional/
  source_bundle_raw.json
  source_bundle_tagged.json
  value_match_strategy.json
  cockpit_content.json
  example_candidate_cockpit.docx
  example_candidate_cockpit.manifest.json
```

## V1 scope boundary

Candidate Cockpit V1 deliberately focuses on **interview strategy and offer readiness**.

Out of scope for V1:

- cover-letter generation
- recruiter outreach
- thank-you notes
- live company research
- market compensation research
- automatic resume rewriting
- full scripted STAR answers
- interview transcript analysis

Those can be future modules without diluting the core value-matching engine.

## Visual QA

The renderer is optimized for exactly two landscape pages. LLM composition should remove lower-value content before shrinking typography.

For a publishable integration, render and inspect representative outputs across short, medium, and dense job/resume combinations.

See `PUBLISHING_CHECKLIST.md` before release. See `JAT_INTEGRATION.md` for the application contract.
