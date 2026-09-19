# Outbound Job Application Pipeline & Role Intelligence Engine
## Getting Started & Self-Testing Guide

This guide walks you through the architecture, operational runbook, pre-flight setup, and step-by-step testing plan to start using this pipeline for outbound job applications.

---

## 1. System Overview & Architecture

This repository implements a **Hexagonal Architecture** pipeline designed for GTM, RevOps, and Analytics job applications.

```text
                     ┌─────────────────────────────────────────┐
                     │          Primary Driving Adapters       │
                     │  - Streamlit Dashboard (Web UI)         │
                     │  - CLI Runner (Single Job Evaluation)   │
                     │  - Sheets Batch (Bulk Processor)        │
                     └────────────────────┬────────────────────┘
                                          │
                                          ▼
                     ┌─────────────────────────────────────────┐
                     │               Domain Core               │
                     │  - 60%–80% Target Pay Calculator        │
                     │  - Dealbreaker & Fit Guardrail Service  │
                     │  - 10-Second Recall Card Generator      │
                     └────────────────────┬────────────────────┘
                                          │
                                          ▼
                     ┌─────────────────────────────────────────┐
                     │         Secondary Driven Adapters       │
                     │  - OpenAI Engine (gpt-4o-mini & DOCX)   │
                     │  - Google Sheets (Pipeline Table Sync)  │
                     │  - Google Drive (Workspace Folders)     │
                     │  - Resume Router (Title-Based Selector) │
                     │  - Twilio & Gmail (Simulated / Live)    │
                     └─────────────────────────────────────────┘
```

### Core Value Props:
1. **60%–80% Target Pay Bounds**: Automatically extracts posted salary bounds and computes your target negotiation anchor:
   $$\text{Target Min} = \text{Posted Min} + (0.60 \times \text{Spread})$$
   $$\text{Target Max} = \text{Posted Min} + (0.80 \times \text{Spread})$$
2. **Fit Guardrails & Dealbreakers**: Flags unwanted tech stacks (e.g. legacy EHRs like Epic, Cerner) and scores match against your core strengths (Salesforce, dbt, SQL, Python, Tableau, etc.).
3. **10-Second Recruiter Phone Screen Recall Card**: Real-time briefing card giving you instant talking points, compensation targets, matched resume, and key strengths when a recruiter calls.
4. **Automated Application Workspaces**: Automatically generates Google Drive folders (`<Company>_<Role>_<Date>`), converts raw JD text into zero-quota Google Docs, copies your tailored resume, and uploads a 2-page landscape Word report.
5. **Google Sheets Integration**: Two-way sync with your **Pipeline Table** spreadsheet (`Raw Ingestion` and `Requirements Extraction` worksheets).

---

## 2. Quickstart Runbook

All dependencies are pre-installed in the local `.venv`.

| Action | Command | What It Does |
| :--- | :--- | :--- |
| **Launch Web Dashboard** | `.\.venv\Scripts\streamlit run job_pipeline/adapters/primary/app.py` | Opens the full UI at `http://localhost:8501` |
| **Process Sheets Batch** | `.\.venv\Scripts\python -m job_pipeline.adapters.primary.sheets_batch` | Evaluates all pending rows in Google Sheets |
| **Batch Dry-Run (Demo)** | `.\.venv\Scripts\python -m job_pipeline.adapters.primary.sheets_batch --demo` | Safe test using mock fixtures (no API charges) |
| **CLI Single Job Evaluator** | `.\.venv\Scripts\python -m job_pipeline.adapters.primary.cli_runner --jd jd.txt` | Evaluates the job description in `jd.txt` |
| **CLI Single Job Dry-Run** | `.\.venv\Scripts\python -m job_pipeline.adapters.primary.cli_runner --jd jd.txt --demo` | Tests CLI evaluation in zero-cost demo mode |

---

## 3. Pre-Flight Setup & Configuration Checklist

Before processing live applications, confirm the following settings:

- [ ] **1. Google Drive Root Folder Permission**:
  * Locate your service account email inside your `credentials.json` (under `"client_email"`).
  * Open your root applications folder in Google Drive.
  * Click **Share** and ensure the service account email is added as **Editor**.
  * *(Without this, folder creation may fail with storage quota errors).*

- [ ] **2. Add Your Google Email to `.env`**:
  * Open `.env` and add your personal Google account email:
    ```env
    GOOGLE_USER_EMAIL=your_email@gmail.com
    ```
  * This ensures all newly created application folders grant direct edit/view permissions to your personal Google account so links open without authentication roadblocks.

- [ ] **3. Candidate Resume Storage in Drive**:
  * Your configured Google Drive resume folder (`GOOGLE_RESUMES_FOLDER_ID`) currently holds:
    * `Matthew Hackett Revenue Operations Analyst Resume`
  * If targeting additional tracks (e.g., *GTM Engineering*, *Business Analytics*, *Solutions Implementation*), create Google Docs inside that folder with matching naming conventions:
    `<Name> <Role Track> Resume`.

- [ ] **4. Candidate Profile Guardrails**:
  * Located in `job_pipeline/domain/models.py`:
    * `dealbreaker_skills`: `["Epic", "HL7", "Cerner", "Meditech"]`
    * `core_strengths`: `["Salesforce", "dbt", "HubSpot", "SQL", "Python", "Tableau", "RevOps", "GTM Engineering"]`
    * `minimum_compensation_floor`: `$90,000`
  * Modify these values in `CandidateProfile` if you want to customize your target criteria.

---

## 4. Step-by-Step Self-Testing Plan

Run through these 4 verification tests in order:

### Test 1: Zero-Cost Web UI Dry Run (Demo Mode)
* **Goal**: Validate UI rendering, pay formula calculation, recall card generation, and document export without calling external APIs.
1. Launch Streamlit:
   ```powershell
   .\.venv\Scripts\streamlit run job_pipeline/adapters/primary/app.py
   ```
2. In the left sidebar under **Pipeline Controls**, check **"Zero-Cost Demo Mode"**.
3. Under **Tab 1 ("🚀 Role Intelligence & Evaluator")**:
   * Keep the prefilled company/title or enter test details.
   * Paste any sample JD into the text area.
   * Click **"⚡ Evaluate Job Posting & Generate Report"**.
4. **Verify**:
   * Status indicators display: Fit status (PASS/FLAGGED), Skill match score, and Matched resume.
   * The purple **Target Salary Range (60%–80%)** box calculates correct numbers.
   * The green **10-Second Recruiter Phone Screen Recall Card** populates.
   * Click **"📄 Download 2-Page Role Intelligence Report (.docx)"** and open the downloaded Word document.

---

### Test 2: Live CLI Single Job Evaluation
* **Goal**: Test live OpenAI telemetry extraction (`gpt-4o-mini`), skill parsing, and report generation using a real job description.
1. Check that `jd.txt` contains a job description (e.g., Planful Sales Operations Analyst).
2. Run the CLI tool:
   ```powershell
   .\.venv\Scripts\python -m job_pipeline.adapters.primary.cli_runner --jd jd.txt
   ```
3. **Verify**:
   * Console outputs parsed required skills (Salesforce, Clari, Power BI, Tableau, etc.).
   * Target compensation is displayed (e.g. `$110k–$135k` posted $\rightarrow$ target `$125k–$130k`).
   * A local Word report is generated in `output_reports/Planful_Role_Intelligence_Report.docx`.
   * A Google Drive application workspace link is output and accessible in your browser.

---

### Test 3: Google Sheets Batch Ingestion Workflow (End-to-End)
* **Goal**: Test the primary daily workflow — adding a new row to Google Sheets and batch syncing.
1. Open your **Pipeline Table** Google Spreadsheet.
2. In the **`Raw Ingestion`** worksheet:
   * Add a new row at the bottom.
   * Paste raw job description text into **Column A (`Job Description`)**.
   * *(Optional)* Fill in Company Name or Job Title, or leave them blank for the LLM to extract.
   * Ensure **Column G (`Status`)** is blank or set to `Pending`.
3. Run the batch processor:
   ```powershell
   .\.venv\Scripts\python -m job_pipeline.adapters.primary.sheets_batch
   ```
   *(Or click **"🔄 Sync & Process Pending Jobs from Google Sheets"** in Tab 2 of the Streamlit dashboard).*
4. **Verify in Google Sheets**:
   * **`Raw Ingestion` sheet**:
     * Status updates to `Processed` (or `FLAGGED_...`).
     * `Target Pay Range` shows the computed 60%–80% range.
     * `Selected Resume` shows the matched resume file.
     * `Tokens` shows the OpenAI token count consumed.
     * `Drive Folder Link` contains the direct URL.
   * **`Requirements Extraction` sheet**:
     * A matching record is appended containing Postgres array formatting (`required_tech_stack`, `preferred_tech_stack`, salary min/max).
5. **Verify in Google Drive**:
   * Open the link from `Drive Folder Link`.
   * Verify the folder contains:
     1. `Raw Job Description` (Google Doc)
     2. Candidate Resume copy (Google Doc)
     3. `<Company>_Role_Intelligence_Report` (Uploaded Word doc)

---

### Test 4: CRM & Twilio Simulation
* **Goal**: Verify recruiter touchpoint logging and interview transcript summarization.
1. Open the Streamlit web dashboard.
2. Go to **Tab 3 ("🏢 Lightweight CRM & Contacts")**:
   * Add a recruiter or hiring manager contact (Name, Company, Role, Email, Phone, Notes).
   * Confirm the contact appears in the registered contacts list.
3. Go to **Tab 4 ("📞 Twilio & Call Transcripts")**:
   * Click **"📱 Send Twilio SMS"** $\rightarrow$ verifies simulated SMS delivery.
   * Paste interview transcript notes into the call transcript area and click **"🎙️ Summarize Call Transcript"**.
   * Verify the summarized touchpoint is appended with key points and compensation details.

---

## 5. Daily Usage Workflow

Once verified, your standard operational routine is:

```text
1. Find a job posting online (LinkedIn, Indeed, Company Site).
2. Paste the text into Column A of the 'Raw Ingestion' tab in Google Sheets.
3. Run: .\.venv\Scripts\python -m job_pipeline.adapters.primary.sheets_batch
   (or click 'Sync' in the Streamlit Web UI).
4. Review the generated Drive folder & 10-Second Recall Card before phone screens.
```

---

## 6. Key File Reference Map

```text
outbound-pipeline/
├── GETTING_STARTED.md             # This handbook and testing guide
├── todo.md                        # Master project roadmap and architecture spec
├── .env                           # API keys & Google Cloud Folder IDs
├── credentials.json               # Google Service Account credentials
├── jd.txt                         # Sample job description for CLI testing
├── output_reports/                # Local disk backup of generated DOCX reports
│
└── job_pipeline/
    ├── domain/
    │   ├── models.py              # Pure domain models (JobPosting, FitEvaluation, Profile)
    │   └── services.py            # Pay calculator (60%-80%) & dealbreaker fit service
    │
    ├── ports/
    │   ├── storage_port.py        # Storage & document interfaces
    │   ├── resume_port.py         # Resume repository port
    │   ├── messaging_port.py      # Twilio messaging port
    │   └── email_port.py          # Email ingestion port
    │
    └── adapters/
        ├── primary/
        │   ├── app.py             # Streamlit CRM & Dashboard (localhost:8501)
        │   ├── cli_runner.py      # Single job evaluator CLI
        │   └── sheets_batch.py    # Batch Google Sheets processor CLI
        │
        └── secondary/
            ├── google_sheets.py   # Raw Ingestion & Requirements Extraction adapter
            ├── google_drive.py    # Drive workspace folder & Docs adapter
            ├── openai_adapter.py  # Structured extraction & 2-page DOCX generator
            ├── resume_selector.py # Title-based resume router
            ├── mock_adapter.py    # In-memory mock adapters for zero-cost demo mode
            ├── twilio_adapter.py  # Phone screen SMS & voice transcript adapter
            └── gmail_adapter.py   # Email alert ingestion adapter
```

---

## 7. Troubleshooting & FAQ

* **Issue: "storageQuotaExceeded" on Google Drive upload**
  * **Solution**: Ensure your root applications folder is shared with your service account email as **Editor**. Files created inside shared folders do not consume service account quota.
* **Issue: Generated Drive links require permission request when clicked**
  * **Solution**: Make sure `GOOGLE_USER_EMAIL=your_email@gmail.com` is defined in your `.env`.
* **Issue: Missing resume warning**
  * **Solution**: Check that your resume Google Docs in Drive match the convention `<Name> <Role Track> Resume` (e.g. `<Your Name> Revenue Operations Analyst Resume`).
* **Issue: OpenAI rate limit or timeout**
  * **Solution**: The pipeline uses `gpt-4o-mini` with fallback to basic regex extraction if an API issue occurs. Check your OpenAI balance/key in `.env`.
