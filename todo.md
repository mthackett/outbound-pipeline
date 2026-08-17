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
  - Open root folder `your-google-drive-applications-root-folder-id-here` in Google Drive web UI:
    👉 [https://drive.google.com/drive/folders/your-google-drive-applications-root-folder-id-here](https://drive.google.com/drive/folders/your-google-drive-applications-root-folder-id-here)
  - Click **Share** -> Add `your-service-account@your-project.iam.gserviceaccount.com` as **Editor**.
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

### 4. Local Disk Backups
- All raw JDs, candidate resumes, and DOCX reports are backed up locally under `output_reports/`.

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
