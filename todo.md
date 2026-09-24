# Outbound Job Application Pipeline & Role Intelligence Engine - TODO & Master Context

A comprehensive system handbook, operational runbook, status checklist, and feature roadmap for future development.

---

## 🚀 Quick Start / Operational Runbook

| Action | Command | Purpose |
| :--- | :--- | :--- |
| **Launch CRM & Dashboard** | `.\.venv\Scripts\streamlit run job_pipeline/adapters/primary/app.py` | Web UI at `http://localhost:8501` |
| **Process Sheet Batch** | `.\.venv\Scripts\python -m job_pipeline.adapters.primary.sheets_batch` | Processes pending rows in Google Sheets |
| **CLI Single Job Evaluator** | `.\.venv\Scripts\python -m job_pipeline.adapters.primary.sheets_batch --demo` | Dry run test without OpenAI charges |
| **CLI Single File Evaluator** | `.\.venv\Scripts\python -m job_pipeline.adapters.primary.cli_runner --jd jd.txt` | Evaluates raw text in `jd.txt` |

---

## 📌 One-Time Setup Checklist

- [ ] **Google Drive Service Account Sharing**:
  - Open your root applications folder in Google Drive.
  - Click **Share** -> Add your service account `client_email` (from `credentials.json`) as **Editor**.
  - *This completes 100% cloud file upload syncing into your personal Google Drive folder!*
- [ ] **Optional `.env` Configuration**:
  - Add your personal Google login email to `.env`: `GOOGLE_USER_EMAIL=your_email@gmail.com` to automatically grant direct browser view permissions to all generated drive links.

---

## ✅ Completed System Capabilities (Milestones 1 & 2 Released)

### 1. Hexagonal Architecture Base (`job_pipeline/`)
- **Domain Core (`job_pipeline/domain/`)**: Pure domain models (`JobPosting`, `FitEvaluation`, `TargetPayBounds`, `CandidateProfile`, `Company`, `StakeholderContact`, `Touchpoint`) and domain services (`PayCalculatorService`, `JobQualificationService`).
- **Ports (`job_pipeline/ports/`)**: Decoupled interface definitions (`JobStoragePort`, `DocumentStoragePort`, `ResumeRepositoryPort`, `LLMStrategyPort`, `MessagingPort`, `EmailIngestionPort`).

### 2. Secondary Driven Adapters (`job_pipeline/adapters/secondary/`)
- **Google Sheets Adapter (`google_sheets.py`)**: Exact row targeting ($N \rightarrow N$) for `Raw Ingestion` and `Requirements Extraction` (`gid=1967659859`). Preserves pasted raw text in Column A (**Job Description**), writes target pay, fit warnings, resume names, drive links, and token counts.
- **Google Drive Adapter (`google_drive.py`)**: Creates application workspace subfolders (`<Company>_<Role>_<Date>`). Creates zero-quota Google Docs for `Raw Job Description`, copies candidate resume Google Docs, and uploads `.docx` Role Intelligence Reports.
- **Title-Based Resume Router (`resume_selector.py`)**: Routes role titles to best-fit resume files (e.g. `<Name> Revenue Operations Analyst Resume`).
- **OpenAI Engine Adapter (`openai_adapter.py`)**: Structured `gpt-4o-mini` telemetry extraction and 2-stage LLM strategy + 2-page landscape `.docx` report generator. Tracks total tokens consumed across all calls.
- **Twilio Adapter (`twilio_adapter.py`)**: SMS and Voice call transcript simulation/integration.
- **Gmail Ingestion Adapter (`gmail_adapter.py`)**: Job alert parser prototype.

### 3. Primary Driving Adapters (`job_pipeline/adapters/primary/`)
- **Streamlit Web Application (`app.py`)**: Live dashboard at `http://localhost:8501`. Features single-click job evaluator, fit cards, **10-Second Recruiter Phone Screen Recall Cards**, and `.docx` downloads. Fixed `sys.path` and `JobPosting` import bugs.
- **Batch Processor (`sheets_batch.py`)**: CLI orchestrator for bulk sheet evaluation.
- **Single Job CLI (`cli_runner.py`)**: Command line tool for evaluating text files.

### 4. Application Guardrails & ATS Protection (`job_pipeline/domain/services.py`)
- **Duplicate Prevention & Repost Detection**: Automatically checks new opportunities against historical applications. Distinguishes between recent duplicates (< 60 days, high ATS rejection risk) and potential renewed reposts (>= 60 days). Provides advisory warning with 1-click user override in Streamlit.
- **Company Application Velocity Guardrail**: Enforces configurable concurrency limit (default: max 2 active/recent applications per company in a 60-day window) to prevent triggering recruiter spam filters.
- **Pre-flight Advisory Confirmation**: Halts before consuming OpenAI tokens or generating Drive folders, presenting full historical context and allowing user to "Proceed Anyway" or "Cancel".

### 5. Application Screening Questions & Answers System
- **Interactive UI Recording**: Ingest screening questions and answers dynamically with category tagging (Technical, Salary, Experience, Culture, General) and optional 1-click "✨ Draft with AI" assist.
- **Dedicated Google Doc ('Screening Questions')**: Automatically generated in the application's Google Drive workspace folder (`<Company>_<Role>_<Date>`) with clean formatting and direct web link.
- **Cross-Job Reusable Library**: Synced to master Google Sheet (`Screening QA` worksheet) and searchable in the dashboard to reuse strong answers across applications.
- **1-Tap ATS Application Kit**: Immediate clipboard copy blocks for lightning-fast application form submission.

### 6. Personal OAuth 2.0 User Authentication (`google_auth.py`, `setup_oauth.py`)
- Greenfielded OAuth 2.0 Desktop App authorization (`token.json`), linking pipeline directly to personal Google Account (`M4tth@live.com`) with 5 TB available quota.
- Eliminated 0-byte Service Account Drive quota errors (`403 storageQuotaExceeded`).
- Independent Google Doc copies of tailored resumes, raw job descriptions, and screening question documents created directly in application Drive folders.
- Maintained backward-compatible fallback to Service Account (`credentials.json`) and zero-cost mock fixtures.

### 7. CRM In-Place Application Editing & Live Drive Sync
- **Structured Call & Interview Logger**: Record phone screens, recruiter calls, and hiring manager interviews with timestamps, interviewer metadata, and key takeaways appended to Google Sheets tracker.
- **Reactive Stage & Status Synchronization**: Updating an application's interview stage (e.g. from `Processed` to `Applied` or `Recruiter Screen`) immediately synchronizes with Google Sheets, updates in-memory CRM state, and re-renders the Cockpit with `st.rerun()`.
- **Per-Job Screening Q&A Manager**: Review past screening answers and append new questions with 1-click "✨ Draft with AI" assist.
- **In-Place Drive Document Sync**: Idempotently updates the `Screening Questions` Google Doc in the application's Drive folder in place, preserving document URLs.

### 8. Google Sheets Rate-Limiting & Quota Protections
- **`st.form` Batching**: Encapsulated CRM note and Q&A editors inside `st.form`. Typing in fields no longer fires background API requests; requests execute strictly on Submit/Enter.
- **120-Second TTL Caching**: Added in-memory caching to `fetch_all_opportunities` and `fetch_screening_qa`. Tab 2 indexes records into a dictionary in-memory with 0 extra Sheets API requests inside card loops.
- **429 Rate Limit Guardrail**: Graceful fallback to cached data if Google Sheets 60 req/min quota is approached.

### 9. Screening Question Intelligence & Similarity/Archetyping
- **Question Archetype Taxonomy**: Automatically classifies screening questions into canonical archetypes (`Compensation`, `Work Authorization`, `Technical Experience`, `Domain/Lifecycle`, `Behavioral Motivation`, `Remote/Location`, `Leadership/Conflict`, `Questions for Company`).
- **Fuzzy & Lexical Similarity Matching**: Zero-cost, offline-first similarity search across all historical screening Q&As using token overlap and sequence ratio scoring.
- **Prior-Answer 1-Click Recall**: In Tab 1 (Apply Kit) and Tab 2 (CRM), detects similar questions as the user types, surfacing prior answers, company context, and a 1-tap "📋 Use Prior Answer" button.
- **Competency Signal Tagging**: Automatically extracts target competencies and skills evaluated by the question (e.g. `SQL`, `Pipeline Diagnostics`, `Stakeholder Communication`).
- **Archetype Grouping in CRM**: Tab 2 Cross-Job Q&A library with archetype filtering, competency pills, and similarity grouping.

### 10. Global Professional Story Bank & Breadcrumb Visual Map
- **12 Global Canonical Stories (`stories.json`)**: High-impact RevOps/GTM behavioral stories seeded from `canonical_stories.json` and persisted locally on disk (`The Revenue Pipeline Black Box`, `Lead Routing & SLA Crisis`, `Modernizing Reporting Stack`, `Disputed Attribution`, `Silent CRM Sync Breakdown`, `Territory Realignment`, `Rep Process Adoption`, `Executive Fire Drill`, `Churn Signal Model`, `Self-Serve Enablement`, `Vendor Consolidation`, `M&A Integration`). A generic 2-story schema template with placeholders is provided in `stories.json.example`.
- **High-Visibility Breadcrumb Stepper Cards**: Prominently display narrative progression milestones with bold step numbers, category badges (`CONTEXT`, `PIVOT`, `METRIC`), and high-contrast soundbite taglines for instant recall on phone or Zoom calls.
- **Full In-App Story & Breadcrumb Editor**: Complete editing interface in Tab 3 to modify story titles, archetype tags, competency signals, target industries, narrative blocks (hook, problem, turning point, result, learning), trigger keywords, behavioral question types, and breadcrumb milestones (edit, add, delete).
- **Story Control & Lock / Unlock Guardrails**: Enforce `is_locked: bool` protection to safeguard approved personal stories against automated system rewrites while allowing direct user overrides.
- **Context-Aware Story Cue Cards**: Dynamically matches and surfaces 3–4 targeted Story Cue Cards in Tab 1 (Apply Kit) and Tab 2 (CRM) based on JD tech stack, pain points, resume match, and industry.
- **Story Navigator & Behavioral Recon Tool**: Dedicated cockpit interface for browsing canonical stories, story transitions, and testing behavioral prompts against the narrative map.

---

## 🔮 Future Roadmap & Features (Milestone 3 Expansion)

### M3.1: Cloud Hosting Deployment & Automated Background Watcher
- [ ] **Daemon Watcher Service**: Create a persistent background worker script (`watcher.py`) that polls Google Sheets every 60 seconds and auto-processes pending rows without requiring manual command invocation.
- [ ] **Cloud Deployment**: Package application with Docker / Procfile and deploy to cloud hosting (Streamlit Community Cloud, Railway, Render, or AWS EC2).

### M3.2: Advanced Vector & LLM Resume Router
- [ ] **Embedding Vector Router**: Upgrade `TitleBasedResumeSelector` to calculate OpenAI cosine similarity vector scores between JD text and candidate resume bullet points.
- [ ] **Hybrid Resume Synthesizer**: Support generating dynamic, custom-tailored candidate resumes based on specific job requirements.

### M3.3: Twilio Real-Time Phone Screen Assistant
- [ ] **Twilio Webhooks Receiver**: Endpoint to catch inbound/outbound recruiter calls.
- [ ] **OpenAI Whisper Audio Transcription**: Automatic speech-to-text pipeline for recruiter calls.
- [ ] **Real-Time Recruiter Cheat Sheet**: Instant SMS or web push notification providing key talking points during live phone screens.

### M3.4: Inbound Email Ingestion Engine
- [ ] **Gmail API / IMAP Listener**: Automatically process incoming job alert emails from LinkedIn, Indeed, ZipRecruiter, and Glassdoor.
- [ ] **Auto-Ingestion Pipeline**: Extract company, title, job link, and JD text from email bodies directly into the `Raw Ingestion` worksheet.

### M3.5: Comprehensive Outbound Pipeline CRM
- [ ] **Relational Graph**: Visual UI mapping Companies $\leftrightarrow$ Contacts (Hiring Managers, Recruiters) $\leftrightarrow$ Applications $\leftrightarrow$ Touchpoints.
- [ ] **Automated Follow-up Reminders**: Automated alerts for following up 5 days post-application.
- [ ] **Custom Outreach Email Generator**: 1-click LLM cold outreach and networking email generator tailored to specific job pain points.

### M3.6: Lightweight Analytics Dashboard
- [ ] **Conversion Funnel Metrics**: Visual funnel tracking progression from Applied $\rightarrow$ Recruiter Screen $\rightarrow$ Hiring Manager $\rightarrow$ Technical Screen $\rightarrow$ Offer.
- [ ] **Application Velocity & Cadence**: Weekly/monthly trend charts of jobs ingested vs applied to monitor search momentum.
- [ ] **Compensation & Spread Analytics**: Distribution charts comparing posted salary ranges against 60%–80% target compensation anchors.
- [ ] **Skill Demand Frequency**: Aggregated breakdown of most frequently requested tech stack requirements across all evaluated JDs.
- [ ] **Response & Ghosting Rates**: Track average days to recruiter response and identify pipeline drop-off bottlenecks.
- [ ] **LLM Cost & Token Analytics**: Total token consumption, cumulative dollar spend, and average cost per processed application.

### M3.7: Hiring Process & Interview Stages Intelligence
- [ ] **Automated Stage Extraction**: Upgrade OpenAI telemetry extractor to parse outlined hiring process steps from JD text when available (e.g. Initial Recruiter Screen $\rightarrow$ Take-Home / Assessment $\rightarrow$ Hiring Manager $\rightarrow$ Team Panel $\rightarrow$ Offer).
- [ ] **Cockpit Apply Kit & Recall Card Integration**: Prominently display expected hiring stages in Tab 1 (1-Tap Apply Kit & 10-Second Recruiter Screen Recall Card) to prepare before speaking with recruiters.
- [ ] **Interactive Stage Checklist in CRM**: Display the company's specific interview pipeline inside each application card in Tab 2 to track progress through their stated stages.
- [ ] **Persistent Sheet & Doc Logging**: Save extracted interview stages into a dedicated column in Google Sheets (`Interview Process`) and embed into the generated Role Intelligence Report DOCX.

### M3.8: LLM Token Usage & Cost Telemetry Tracker
- [ ] **Comprehensive Token Accounting**: Track prompt (input) and completion (output) tokens across all LLM touchpoints: JD telemetry extraction, 2-stage role intelligence reports, and screening question AI drafts.
- [ ] **Dynamic Cost Calculator**: Maintain model pricing tables (e.g. `gpt-4o-mini` at $0.15/1M input, $0.60/1M output) to calculate exact per-job and cumulative dollar spend.
- [ ] **Google Sheets Cost Logging**: Add an `Estimated Cost ($)` column to the `Raw Ingestion` worksheet alongside existing `Tokens` data.
- [ ] **Per-Application & Cockpit Visibility**: Display token and cost metrics in the Tab 1 Apply Kit summary and connection status sidebar.

### M3.9: Company-Level Guardrail Overrides & Staffing Agency Whitelisting
- [ ] **Staffing Agency / Recruiter Whitelist**: Allow designating companies as Staffing Agencies, Recruiters, or Job Aggregators (e.g. JobGether, CyberCoders, Robert Half) with zero or elevated application velocity limits.
- [ ] **Granular Company-Level Overrides**: Ability to customize concurrency caps (max applications and rolling window days) on a per-company basis while preserving the global baseline (default: 2 apps / 60 days).
- [ ] **Pre-Flight Warning Action ("Mark as Agency")**: When a velocity cap warning triggers, provide a 1-click option to designate the organization as a staffing agency and permanently exempt it from aggressive ATS velocity blocks.
- [ ] **Persistent Rules Storage**: Store custom company rules in persistent storage (e.g. `company_guardrails.json` or a dedicated worksheet) with an interactive management table in Tab 3.

### M3.10: Location-Aware Geo-Tiered Compensation Extraction
- [ ] **Configurable Candidate Location**: Add candidate location configuration (default: `AZ` / `Phoenix, Arizona`) to `CandidateProfile`, `.env` (`CANDIDATE_LOCATION=AZ`), and Streamlit sidebar settings.
- [ ] **Geo-Differentiated Salary Prompting**: Enhance OpenAI telemetry extractor to parse multi-tier pay tables (Zone A / B / C, geographic cost-of-labor tiers, or CA/NY/CO vs other US states) and choose the specific salary tier matching the candidate's location.
- [ ] **External Geo-Zone Policy Link Catch**: Detect when compensation requires following an external company link to see regional/zone tier definitions (e.g. *"See our Geographic Pay Policy at https://..."*):
  - Extract and surface the external policy URL in the Target Salary Box with a 1-click **"↗ Open Geo-Zone Policy Table"** button.
  - Automatically flag the range as a wide national aggregate until verified.
  - Optional automated enrichment: Fetch the linked page content via HTTP request to auto-resolve the candidate's AZ tier without manual lookup.
- [ ] **Fallback Hierarchy**: If the candidate's exact state is not listed separately, automatically default to the national/remote baseline tier rather than inflating the anchor to Tier 1 (SF/NYC).
- [ ] **Tier Selection Transparency**: Record a `salary_tier_matched` explanation (e.g., *"Matched Zone 3 (National/AZ) at $110k–$135k instead of Zone 1 (Bay Area) at $135k–$160k"*) in the Apply Kit and Google Sheets.

### M3.11: Application Source & Channel Tracking (Configurable Dropdown)
- [ ] **Configurable Application Sources**: Support a customizable channel list (defaults: `LinkedIn`, `Indeed`, `ZipRecruiter`, `Direct (Company Website)`, `Referral`, `JobGether`, `Other`) managed via `sources.json` or persistent config.
- [ ] **Tab 1 Ingestion Integration**: Add an "Application Source / Channel" selector when ingesting or evaluating new job descriptions.
- [ ] **Tab 2 CRM Card Selector**: Add an interactive source dropdown in the application card header / "Update Stage & Recruiter Contact" block with immediate Google Sheets synchronization.
- [ ] **Master Google Sheet Column**: Add and auto-provision an `Application Source` column in the `Raw Ingestion` worksheet.
- [ ] **Channel Analytics (M3.6 Tie-in)**: Track and visualize response rates, conversion-to-screen rates, and velocity broken down by job board / source.

### M3.12: Reinforcement / Retrieval Layer & Semantic Idea Graph (Future TODO)
- [x] **Architecture Spec**: Complete architecture and data model specification in `docs/specs/03-reinforcement-retrieval-layer-todo.md`.
- [ ] **Semantic Linking Graph**:
  - Connect related **Screening / Behavioral Questions ⟷ Canonical Stories** (and specific narrative angles).
  - Connect **Stories ⟷ Job Postings** (linking specific employer pains to candidate proof points).
  - Connect **Stories ⟷ Modular Breadcrumbs** for structured recall.
- [ ] **Real-Time Interview Breadcrumb Navigator**: Surface the right breadcrumbs, metrics, and segue transitions dynamically during live phone screens and interviews to keep conversations flowing smoothly.
- [ ] **Per-Application Custom Stories**: Allow authoring role-specific bespoke stories that branch off the global canonical library when an application requires a unique case study.
- [ ] **Hybrid Semantic Retrieval**: Combine lexical BM25 matching with vector embeddings (e.g. OpenAI `text-embedding-3-small`) for deep semantic retrieval of prior questions and story segments.
- [ ] **Post-Interview Flywheel Feedback Loop**: Structured capture of interview questions and recruiter reactions to reinforce, grade, and improve future application prep (`application → capture → classify → connect → prepare → use → learn → improve`).

---

## 📁 Key File Map

```text
outbound-pipeline/
├── docs/
│   └── specs/
│       ├── 01-screening-question-intelligence.md     # Feature 1: Screening Archetyping & Recall
│       ├── 02-professional-story-bank.md             # Feature 2: 12 Canonical Stories & Narrative Map
│       └── 03-reinforcement-retrieval-layer-todo.md  # Feature 3: Semantic Idea Graph & Flywheel (TODO)
├── stories.json                       # Local story bank & custom breadcrumbs
├── stories.json.example               # Story bank schema template
├── quicklinks.json                    # Local candidate application quicklinks store 
├── quicklinks.json.example            # Candidate application quicklinks template
├── job_pipeline/
│   ├── domain/
│   │   ├── models.py                  # Domain models (JobPosting, Story, Breadcrumb, CueCard, etc.)
│   │   ├── canonical_stories.json     # Pristine seed dataset of 12 canonical RevOps stories
│   │   ├── story_bank.py              # 12 Canonical stories bank, storage, locks & cue card suggester
│   │   ├── screening_intelligence.py  # Archetype classification, competency signals & similarity recall
│   │   └── services.py                # Pay calculator, guardrails & service facades
│   ├── ports/
│   │   └── storage_port.py            # Interface definitions for storage & LLM ports
│   ├── adapters/
│   │   ├── primary/
│   │   │   ├── app.py                 # Streamlit CRM Dashboard (Tabs 1-4)
│   │   │   ├── cli_runner.py          # Single job evaluator CLI
│   │   │   └── sheets_batch.py        # Batch Google Sheets processor CLI
│   │   └── secondary/
│   │       ├── google_sheets.py       # Raw Ingestion & Requirements Extraction adapter
│   │       ├── google_drive.py        # Drive folder & zero-quota Google Docs adapter
│   │       ├── openai_adapter.py      # Structured extraction & LLM strategy runner
│   │       ├── resume_selector.py     # Title-based resume router
│   │       ├── twilio_adapter.py      # Phone screen SMS & voice adapter
│   │       └── gmail_adapter.py       # Email alert ingestion adapter
│   └── role_intelligence_runner.py   # 2-stage LLM strategy + recall sheet composer
├── output_reports/                    # Local disk backup folder for JDs and DOCX reports
├── .env                               # API keys & Google Cloud Folder IDs
├── credentials.json                   # Google Service Account credentials
└── todo.md                            # Master project handbook & roadmap
```
