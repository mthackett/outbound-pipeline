# Candidate Cockpit V1 Publishing Checklist

## Product behavior

- [ ] Validate source bundle, strategy JSON, and cockpit content against schemas.
- [ ] Test roles with explicit business pain and roles where pain must be inferred.
- [ ] Test job posts with and without posted compensation.
- [ ] Test direct skill matches and adjacent/bridge cases.
- [ ] Confirm unsupported behavioral themes produce frameworks, not invented stories.
- [ ] Confirm inferred business pain is visibly framed as a hypothesis when appropriate.
- [ ] Confirm employer-specific ROI is not fabricated.

## Layout

- [ ] Render representative outputs and confirm exactly two pages.
- [ ] Test short, typical, and dense resumes/job posts.
- [ ] Prefer content pruning over smaller fonts when a page is too dense.
- [ ] Test in Microsoft Word and LibreOffice if both are supported targets.

## JAT integration

- [ ] Stable job ID and resume ID are passed through.
- [ ] Best-fit resume selection is resolved before generation.
- [ ] Original posted compensation string is preserved.
- [ ] Interview stage is passed when known.
- [ ] Strategy and generated document are stored against the same job record.
- [ ] Provenance refs are retained even though they are not rendered.
- [ ] Generation manifest is stored with the generated document.

## Repository hygiene

- [ ] Replace/remove personal examples before public release.
- [ ] Keep the fictional example marked as fictional.
- [ ] Add the license you want to publish under.
- [ ] Add screenshots only after the document layout is final.
- [ ] Add CI validation for example JSON files.
- [ ] Remove generated caches and temporary render folders from commits.
