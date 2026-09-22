# Multi-Purpose Outbound & Correspondence Engine: Cold Outreach Extension Architecture

This document outlines the architectural blueprint, data models, and deployment strategies for adapting the Outbound Pipeline core into a **B2B Cold Outreach Email & Correspondence Tracking System**.

---

## 1. Executive Summary & Design Rationale

The existing system was built using **Hexagonal Architecture (Ports and Adapters)**. Because the core pipeline is decoupled from specific I/O systems:
- The **Domain Core** focuses on entity evaluation, guardrails, and structured intelligence synthesis.
- The **Driven Adapters** (Google Sheets, Google Drive, OpenAI, Gmail, Twilio) handle storage, dossiers, LLM drafting, and messaging.

Adapting this engine for cold outreach is a natural domain mapping:
* **Job Opportunity** $\longrightarrow$ **Prospect Lead / Account**
* **Job Description** $\longrightarrow$ **Company Website / Prospect LinkedIn Profile / Pain Points**
* **Tailored Resume** $\longrightarrow$ **Tailored Pitch, Case Study, or Offer Deck**
* **Interview Notes & Screening Q&A** $\longrightarrow$ **Correspondence Log & Touchpoint History**

---

## 2. Deployment Architecture: Unified vs. Separate

When launching the cold outreach system, you can choose between two deployment models:

```mermaid
graph TD
    subgraph Option A: Unified Multi-Purpose Tenant
        App1[Single Streamlit Dashboard] --> Tabs[Tabs: Job Pipeline | Cold Outreach CRM]
        Tabs --> Sheets1[Master Google Sheet: Separate Worksheets]
        Tabs --> Drive1[Google Drive: Folders for Jobs & Accounts]
    end

    subgraph Option B: Separate Specialized Deployments
        AppJob[Job Application Cockpit] --> SheetsJob[Job Tracker Sheet]
        AppJob --> DriveJob[Job Applications Folder]
        AppSales[Cold Outreach Cockpit] --> SheetsSales[Sales CRM Sheet]
        AppSales --> DriveSales[Sales Accounts Folder]
    end
```

### Option A: Unified Cockpit (Single Multi-Purpose Tenant)
* **How It Works**: A single Streamlit application with dedicated tabs (`Job Pipeline` and `Cold Outreach`). Shares the same authenticated `token.json` and OpenAI API key.
* **Pros**: Single deployment to manage (one Railway / local server), single Google OAuth consent screen, unified interface for all outbound activity.
* **Cons**: Larger dashboard with both career and sales data visible together.

### Option B: Isolated Deployments (White-Label Clone)
* **How It Works**: Fork or clone this repository to `outbound-email-engine`, configure dedicated `.env` folder IDs pointing to a dedicated Sales Drive folder and Sales CRM spreadsheet.
* **Pros**: Complete separation of concerns, zero clutter, independent release cycles and custom branding.
* **Cons**: Two independent deployment instances to monitor.

---

## 3. Required Changes by Architectural Layer

### 3.1 Domain Models (`job_pipeline/domain/models.py`)

Add first-class entities for prospect accounts, contacts, and touchpoints:

```python
class ProspectAccount(BaseModel):
    account_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    company_name: str
    website_url: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    icp_fit_score: float = 0.0          # 0 to 100 ICP fit
    status: str = "Uncontacted"         # Uncontacted, Contacted, In Discussion, Qualified, Lost
    drive_folder_link: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))

class ProspectContact(BaseModel):
    contact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    account_id: str
    full_name: str
    title: str                          # e.g. VP of Sales, Head of RevOps
    email: str
    linkedin_url: Optional[str] = None
    tier: str = "Tier 1"                # Tier 1 (Decision Maker), Tier 2 (Influencer)

class Touchpoint(BaseModel):
    touchpoint_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    account_id: str
    contact_id: Optional[str] = None
    channel: str                        # "Email", "LinkedIn", "Phone", "Meeting"
    direction: str                      # "Outbound", "Inbound"
    subject: str
    body_content: str
    timestamp: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))
    follow_up_date: Optional[str] = None
    outcome: Optional[str] = None       # "Opened", "Replied", "Booked Call", "No Response"
```

---

### 3.2 Secondary Adapters

#### A. Gmail Adapter (`job_pipeline/adapters/secondary/gmail_adapter.py`)
* **OAuth Scope Extension**:
  Add `https://www.googleapis.com/auth/gmail.send` and `https://www.googleapis.com/auth/gmail.modify` to `SCOPES` in `google_auth.py`.
* **Capabilities**:
  1. `create_draft(to_email, subject, body_html)`: Saves a polished draft directly in your personal Gmail account (`M4tth@live.com`) for review.
  2. `send_email(to_email, subject, body_html)`: 1-click send from the Streamlit UI.
  3. `check_thread_replies(message_id)`: Checks whether the prospect has replied, updating the CRM stage automatically.

#### B. Google Sheets Adapter (`job_pipeline/adapters/secondary/google_sheets.py`)
* **Worksheet 1: `Outreach Leads`**:
  * Columns: `Account ID`, `Company`, `Domain`, `Contact Name`, `Title`, `Email`, `Status`, `Last Touchpoint Date`, `Next Follow-up`, `Folder Link`, `Notes`.
* **Worksheet 2: `Correspondence Log`**:
  * Columns: `Touchpoint ID`, `Account ID`, `Company`, `Contact`, `Channel`, `Subject`, `Body/Summary`, `Timestamp`, `Outcome`.
* Utilizes the existing in-memory TTL cache to ensure zero quota errors.

#### C. Google Drive Adapter (`job_pipeline/adapters/secondary/google_drive.py`)
* Automatically creates an **Account Workspace Folder**:
  `Outreach_<Company>_<ContactName>_<Date>`
* Inside each folder:
  1. **Account Dossier** (Google Doc): Research on the company, current initiatives, pain points, and talking points.
  2. **Email Sequence Drafts** (Google Doc): 3-touch sequence (Initial Hook, Value Follow-up, Break-up).
  3. **Master Sales Tracker** (Shortcut to your Outreach Google Sheet).

#### D. OpenAI Strategy Engine (`job_pipeline/adapters/secondary/openai_adapter.py`)
* **Lead Intelligence Prompt**: Given a company description or URL and lead title, extracts:
  1. Core operational pain points.
  2. The high-relevance value proposition hook.
  3. A 3-step cold email sequence optimized for high reply rates (sub-120 words, personalized hook, low-friction call-to-action).

---

### 3.3 Primary UI (Streamlit Cockpit)

A dedicated **Cold Outreach Cockpit** tab featuring:
1. **Prospect Ingestion Form**:
   * Paste prospect LinkedIn bio, company URL, or pain points.
   * Auto-generates personalized 3-step email sequence with 1-click **"✨ Draft with AI"**.
2. **1-Tap Action Bar**:
   * **"📥 Create Gmail Draft"**: Creates draft in your actual Gmail inbox.
   * **"🚀 Send Email Immediately"**: Sends email via Gmail API and logs the touchpoint.
3. **Interactive Correspondence Log**:
   * Expandable cards showing previous email threads and logged calls for each prospect.
   * "Add Touchpoint" form to log offline LinkedIn DMs or phone calls with automatic Google Sheets and Drive synchronization.

---

## 4. Implementation Roadmap (When Ready to Build)

1. **Step 1 (Scopes & Auth)**: Add Gmail scopes to `google_auth.py` and run `python -m job_pipeline.setup_oauth` once to authorize Gmail sending.
2. **Step 2 (Domain & Models)**: Add `ProspectAccount`, `ProspectContact`, and `Touchpoint` models.
3. **Step 3 (Sheets Schema)**: Create `Outreach Leads` and `Correspondence Log` tabs in Google Sheets.
4. **Step 4 (Gmail Sender Adapter)**: Implement `send_email` and `create_draft` in `gmail_adapter.py`.
5. **Step 5 (UI Tab)**: Add the "Outreach Cockpit" tab to `app.py`.
