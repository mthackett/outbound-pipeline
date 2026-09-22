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
- **Per-Job Screening Q&A Manager**: Review past screening answers and append new questions with 1-click "✨ Draft with AI" assist.
- **In-Place Drive Document Sync**: Idempotently updates the `Screening Questions` Google Doc in the application's Drive folder in place, preserving document URLs.

### 8. Google Sheets Rate-Limiting & Quota Protections
- **`st.form` Batching**: Encapsulated CRM note and Q&A editors inside `st.form`. Typing in fields no longer fires background API requests; requests execute strictly on Submit/Enter.
- **120-Second TTL Caching**: Added in-memory caching to `fetch_all_opportunities` and `fetch_screening_qa`. Tab 2 indexes records into a dictionary in-memory with 0 extra Sheets API requests inside card loops.
- **429 Rate Limit Guardrail**: Graceful fallback to cached data if Google Sheets 60 req/min quota is approached.

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

---

## 📁 Key File Map

```text
outbound-pipeline/
├── job_pipeline/
│   ├── domain/
│   │   ├── models.py              # Pure domain models (JobPosting, FitEvaluation, etc.)
│   │   └── services.py            # Pay calculator (60-80%) & dealbreaker fit service
│   ├── ports/
│   │   └── storage_port.py        # Interface definitions for storage & LLM ports
│   ├── adapters/
│   │   ├── primary/
│   │   │   ├── app.py             # Streamlit CRM Dashboard (localhost:8501)
│   │   │   ├── cli_runner.py      # Single job evaluator CLI
│   │   │   └── sheets_batch.py    # Batch Google Sheets processor CLI
│   │   └── secondary/
│   │       ├── google_sheets.py   # Raw Ingestion & Requirements Extraction adapter
│   │       ├── google_drive.py    # Drive folder & zero-quota Google Docs adapter
│   │       ├── openai_adapter.py  # Structured extraction & LLM strategy runner
│   │       ├── resume_selector.py # Title-based resume router
│   │       ├── twilio_adapter.py  # Phone screen SMS & voice adapter
│   │       └── gmail_adapter.py   # Email alert ingestion adapter
│   └── role_intelligence_runner.py # 2-stage LLM strategy + recall sheet composer
├── output_reports/                # Local disk backup folder for JDs and DOCX reports
├── .env                           # API keys & Google Cloud Folder IDs
├── credentials.json               # Google Service Account credentials
└── todo.md                        # Master project handbook & roadmap
```
