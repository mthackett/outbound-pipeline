# JAT Integration Contract

Candidate Cockpit is designed to run from a job-application-tracker record once the JAT has selected the best-fit resume for that application.

## Required before generation

The JAT should resolve:

- `job.job_id`
- `job.title`
- `job.company`
- complete `job.description`
- `resume.resume_id`
- complete extracted `resume.text`

If any of those are missing, generation should stop rather than guess.

## Strongly recommended metadata

Pass through when available:

- `posted_compensation.raw`
- parsed compensation min/max/currency/period
- location and work arrangement
- seniority
- application status
- interview stage/date
- source URL / source name
- JAT-extracted required/preferred skills
- recruiter or hiring-manager names
- resume version/label/path
- candidate target/floor/strong-win compensation

The strategy model should still use the complete job description as the primary source for business-pain inference. JAT-extracted requirements are helpful metadata, not a substitute for the posting.

## Recommended artifact model

Store the following against the same application/job record:

```text
job_id
resume_id
source_bundle_version
strategy_version
cockpit_template_version
value_match_strategy_json
cockpit_content_json
generated_docx_path_or_asset_id
generation_manifest_json
generated_at
```

This makes the output reproducible and lets the UI expose strategy independently of the DOCX.

## Recommended generation sequence

```text
1. User/app selects job
2. JAT resolves best-fit resume
3. Build source_bundle.json
4. Add source line tags
5. Validate source bundle
6. LLM call: consultative value-match strategy
7. Validate strategy JSON
8. LLM call: cockpit composition
9. Validate cockpit JSON
10. Render DOCX + manifest
11. Store artifacts against application
```

## Regeneration rules

Re-run the **strategy stage** when:

- job description changes materially
- selected resume changes
- new employer information is intentionally added to the source bundle

Re-run only the **composition/render stage** when:

- layout or prompt framing changes
- interview stage changes but the underlying job/resume evidence does not
- compensation variables change
- the candidate wants a denser or lighter document

Re-run only the **renderer** when:

- typography, spacing, colors, banners, margins, or other visual configuration changes

## Failure behavior

Prefer explicit failure states over silent fallback:

- no selected resume -> `resume_required`
- no job description -> `job_description_required`
- invalid strategy JSON -> `strategy_validation_failed`
- invalid cockpit JSON -> `cockpit_validation_failed`
- document exceeds two pages in QA -> `layout_density_failed`

The application can then retry the relevant stage or surface the issue to the user.

## Provenance

`prepare_source_bundle.py` creates `J###` and `R###` line IDs. Retain them with the strategy even though the visible document omits them.

This supports:

- auditability
- hallucination review
- explainability UI
- source-aware regeneration
- debugging when an LLM overstates a match

## Compensation handling

Use `posted_compensation.raw` for display so the employer's wording is preserved exactly.

Parsed min/max fields are useful for JAT logic, sorting, and analytics, but the cockpit model should not reconstruct a display range from parsed values when the original raw string exists.

Candidate target/floor/strong-win values must come from caller-supplied preferences. The model should never infer them.
