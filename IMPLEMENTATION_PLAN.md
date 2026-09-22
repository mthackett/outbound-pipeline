# Implementation Plan: Duplicate Guardrails, Company Velocity, Screening QA & 24/7 Cloud Hosting

## Goal
Incorporate intelligent duplicate prevention (with repost/renewed interest detection), company application concurrency guardrails (maximum active applications per company in a rolling time window), and an **Application Screening Questions & Answers recorder** (with dedicated native Google Doc storage in Google Drive) into the Outbound Job Application Pipeline, alongside end-to-end testing and cloud hosting.

---

## 1. Feature Specifications

### A. Repost & Duplicate Prevention
- **Rule**:
  - If applied within **< 60 days**: Issue a **Duplicate Application Warning** displaying previous apply date and status.
  - If applied **$\ge$ 60 days ago**: Issue a **Potential Repost / Reopened Requisition Notice** informing you that this role was previously applied to, but is old enough to warrant a refreshed application.

### B. Company Application Velocity Guardrail
- **Rule**:
  - **Default Threshold**: Max `2` applications per company within a rolling `60-day window`.
  - If exceeded: Display a **Company Application Cap Warning** showing recent applications at that company (Dates, Titles, Statuses).
- **Advisory Warning**: Both guardrails halt before generating Drive folders or consuming OpenAI tokens, allowing you to **"Proceed & Apply Anyway"** or **"Cancel"**.

### C. Application Screening Questions & Answers Recorder
- **Input Flow**:
  - An optional interactive section in the Streamlit UI to input screening questions and answers for every application.
  - Optional **"✨ Draft Answer with AI"** button for each question using your resume bullet points and the JD.
- **Dedicated Google Doc Storage (`Screening Questions`)**:
  - When questions are provided, the system automatically creates a native Google Doc titled **`Screening Questions`** directly in that application's Google Drive workspace folder (`<Company>_<Role>_<Date>`).
  - Zero quota impact (`application/vnd.google-apps.document`).
  - Contains formatted headers, numbered questions, clear answers, and timestamps.
  - Clickable direct link: `📄 Open Screening Questions (Google Doc)` provided in the 1-Tap Apply Kit.
- **Master Sheet & Searchable Library**:
  - Stored in a dedicated **`Screening QA` worksheet** in Google Sheets (`opportunity_id`, `company`, `job_title`, `question`, `answer`, `timestamp`, `doc_link`).
  - Surfaced in a **Screening Answer Library** in the dashboard to reuse strong answers across future applications.

---

## 2. Proposed Changes

### Domain Core (`job_pipeline/domain/`)
- **[MODIFY] `models.py`**:
  - Add `ScreeningQA` model (`question`, `answer`, `category`, `created_at`).
  - Add `screening_qa: List[ScreeningQA]` and `drive_screening_doc_link: Optional[str]` to `JobPosting`.
  - Add guardrail parameters to `CandidateProfile`.
  - Add guardrail status fields to `FitEvaluation`.
- **[MODIFY] `services.py`**:
  - Implement `ApplicationGuardrailService` (`check_duplicate()`, `check_company_velocity()`).
  - Implement `ScreeningQAService` (formatting text for Google Doc, clipboard export, and recall summary).

### Storage Ports & Adapters (`job_pipeline/ports/` & `job_pipeline/adapters/`)
- **[MODIFY] `storage_port.py`**:
  - Add `create_screening_questions_doc()` to `DocumentStoragePort`.
  - Add `fetch_all_opportunities()`, `save_screening_qa()`, and `fetch_screening_qa()` to `JobStoragePort`.
- **[MODIFY] `google_drive.py`**:
  - Implement `create_screening_questions_doc()` to create and format the **`Screening Questions`** Google Doc inside the application folder.
- **[MODIFY] `google_sheets.py`**:
  - Implement `Screening QA` worksheet creation and appending.
  - Implement in-memory cache for `fetch_all_opportunities()`.
- **[MODIFY] `mock_adapter.py`**:
  - Implement mock methods for test suites.

### Primary UI & CLI (`job_pipeline/adapters/primary/`)
- **[MODIFY] `app.py`**:
  - Add pre-flight duplicate and company velocity guardrail warnings with override buttons.
  - Add interactive "📝 Screening Questions & Answers" card input with AI drafting support.
  - Render screening Q&A in the 1-Tap Apply Kit (with 1-click copy and button to open the Google Doc).
  - Add Screening Answer Library tab to browse and reuse past answers.
  - Add sidebar configuration controls to tune guardrail limits.
- **[MODIFY] `sheets_batch.py`**:
  - Include guardrail logging in batch runs.

### Cloud Deployment & Environment
- **[MODIFY] `requirements.txt`**: Pin runtime dependencies.
- **[NEW] `.streamlit/config.toml`**: Streamlit theme and headless settings.
- **[MODIFY] `README.md`**: Update usage documentation.

---

## 3. Verification Plan

### Automated Unit Tests
- `job_pipeline/domain/tests/test_guardrails.py`: Duplicate detection, repost detection, company cap limits.
- `job_pipeline/domain/tests/test_screening_qa.py`: Model validation, Google Doc text formatting, sheet serialization.

### Interactive UI Verification
- Launch Streamlit (`streamlit run job_pipeline/adapters/primary/app.py`).
- Test screening Q&A input and verify creation of the **`Screening Questions`** Google Doc in Drive.
- Verify direct link in the 1-Tap Apply Kit.
- Test duplicate and company velocity alerts with mock and live data.
