# Candidate Cockpit V1: Strategy -> Two-Page Cockpit Composition Prompt

You are composing a two-page landscape candidate cockpit from:

1. the original `source_bundle`
2. the completed `value_match_strategy`

The cockpit is a quick-glance interview aid for the candidate. It is not a resume rewrite and not prose for a recruiter.

Return valid JSON only conforming to `schemas/cockpit_content.schema.json`.

Do not wrap the JSON in markdown fences.

## Global rules

- Candidate facts must remain source-backed by the selected resume.
- Employer facts must remain source-backed by the job record/posting.
- Inferred employer pain must be labeled as a hypothesis in wording such as `Likely pain:` or `Hypothesis:` unless confidence is explicit.
- Preserve metrics and compensation exactly.
- Use fragments, arrows, compact labels, and short memory triggers.
- Use ASCII punctuation. Do not use em dashes.
- Do not include contact information.
- Do not include negative reminders such as `never say`, `avoid`, or prohibited scripts.
- Prefer fewer, higher-value points over completeness.
- Add `source_refs` to resume/job-specific items when the schema allows. These source refs are metadata and are not rendered by the DOCX generator.

# PAGE 1: JOB-TARGETED RESUME RECALL

Page 1 should still function as a memory jogger for the selected resume, but selection and emphasis should reflect the job's top pain hypotheses.

## Column 1

### Core Fit
3-5 fragments describing the candidate's role identity, high-value capabilities, and the domains most relevant to this job.

### Proof Numbers
3-6 memorable, source-backed numbers that strengthen credibility for this role.

### Skill Bank
3-5 skimmable categories. Prioritize skills relevant to the job while staying faithful to the resume.

### Credentials
Only materially useful reminders.

## Column 2

### Best-Match Experience
Compress the strongest 4-7 resume bullets for this job using:

`topic: problem/input -> analysis/action -> decision/change -> outcome`

### Value Pattern
One short recurring pattern explaining how the candidate creates business value.

## Column 3

### Best Evidence / Project
Use the strongest project or evidence block for the job.

### Story Index
Map 5-8 interview themes to real source-backed stories.

### Quick Recall
Use a compact answer shape such as:

`Context -> Problem -> Analysis/Action -> Result -> Learning`

# PAGE 2: CONSULTATIVE INTERVIEW + OFFER PLAYBOOK

Keep the previously established three-column structure, but make the page strategically job-specific.

## Column 1: Value Positioning + Behavioral Prep

### Value Thesis
Make this section strong. Include:

- one-line value thesis
- three short value pillars or pain-specific value matches

The framing should answer: `Why is this candidate unusually useful for solving the employer's biggest 1-3 likely problems?`

### Likely Business Pain
Show the top 1-3 pain hypotheses compactly with confidence-aware wording.

For each, pair the pain with the strongest candidate proof or capability.

Example shape:

`Likely pain: fragmented pipeline visibility -> proof: dbt/BigQuery + BI reporting -> value: trusted, faster decisions`

If a pain can be connected to a source-backed candidate metric, include it. Do not invent employer ROI.

### Behavioral Question Map
Touch the most likely role-specific behavioral themes plus important baseline themes.

Each line should combine:

`Question/theme -> good-answer scaffold | story seed`

Example:

`Client/stakeholder clash -> issue -> understand needs -> constraints -> tailored solution -> result | seed: SLA alignment`

Use a real story seed only when supported. Otherwise use a framework without inventing a story.

Prioritize 7-10 lines based on likely interview value.

## Column 2: Negotiation

### Compensation Snapshot
Use:

- `Posted range: {{posted_pay}}`
- `Target: {{target_pay}}`
- `Floor: {{floor_pay}}`
- `Strong win: {{strong_win_pay}}`

### Value-Based Negotiation Anchor
Use 2-4 compact points connecting compensation to:

- top business pain
- candidate evidence
- economic levers
- role scope

Do not claim unsupported ROI.

### Negotiation Sequence
Positive action cue only, for example:

`Enthusiasm -> full package -> written offer -> evaluate -> counter -> wait`

### Counter Structure
Fit -> value -> scope/market -> specific ask -> collaborative close.

### Package Check / Tradeables
Keep concise and actionable.

## Column 3: Diagnose + Scope + Decide

### Questions to Validate Pain
Choose 4-5 high-value diagnostic questions tied to the strategy. They should help the candidate discover the current-state problem, its business consequence, ownership, and success criteria.

### Bridge Points
Include 1-3 high-value transferable bridges only when relevant.

### First 90 Days
Compact 30/60/90 hypothesis tied to the top pain.

### Role Scope Check
2-4 concise prompts that clarify actual ownership and work mix.

### Offer Scorecard
Keep only the highest-value decision factors.

### Close Strong
Reinforce fit + interest, invite remaining concerns, confirm next step + timeline.

## Density target

The final DOCX should fit on exactly two landscape pages using the supplied renderer and default configuration. If content is too dense, compress or remove lower-priority material rather than shrinking the font.
