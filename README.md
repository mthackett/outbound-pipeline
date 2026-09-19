# Outbound Job Application Pipeline & Role Intelligence Engine

A consultative, automated job application intelligence engine and lightweight CRM designed for Revenue Operations, GTM Engineering, and Analytics roles. Built with clean **Hexagonal Architecture** in Python, Streamlit, OpenAI, and Google Workspace.

---

## ⚡ Quick Links & Documentation

* 📖 **[Getting Started & Testing Guide](GETTING_STARTED.md)**: Operational runbook, setup checklist, and 4-phase testing plan to start using this pipeline today.
* 📋 **[Master Roadmap & System Context (`todo.md`)](todo.md)**: Hexagonal architecture details, completed milestones, and roadmap items.

---

## 🚀 Quick Launch

### 1. Launch Streamlit Web UI
```powershell
.\.venv\Scripts\streamlit run job_pipeline/adapters/primary/app.py
```
Open **`http://localhost:8501`** in your browser.

### 2. Process Google Sheets Batch
```powershell
.\.venv\Scripts\python -m job_pipeline.adapters.primary.sheets_batch
```

### 3. CLI Single Job Evaluator
```powershell
.\.venv\Scripts\python -m job_pipeline.adapters.primary.cli_runner --jd jd.txt
```

---

## 🌟 Key Features

1. **Zero-Friction Ingestion**: Paste raw job descriptions without manual data entry. `gpt-4o-mini` extracts Company, Title, Family, Compensation bounds, and Skills.
2. **1-Tap Application Kit**: Instant clickable link to open your matched Google Doc resume, direct link to your newly generated Google Drive workspace folder, and 2-page `.docx` briefing document.
3. **60%–80% Target Pay Calculator**: Dynamically computes negotiation bounds from posted salary ranges:
   $$\text{Target Min} = \text{Posted Min} + 0.60 \times (\text{Posted Max} - \text{Posted Min})$$
   $$\text{Target Max} = \text{Posted Min} + 0.80 \times (\text{Posted Max} - \text{Posted Min})$$
4. **Interactive CRM & Pipeline Tracker**: Live stage updater (`Applied` $\rightarrow$ `Recruiter Screen` $\rightarrow$ `Hiring Manager` $\rightarrow$ `Offer`) synced to your Google Sheet with recruiter notes.
5. **Google Drive Workspace Sync**: Auto-generates application folders (`[Company]_[Role]_[Date]`), zero-quota JD docs, and tailored resume copies.

---

## 🚂 Railway Cloud Deployment Guide

To deploy this web app on [Railway](https://railway.app) for 24/7 mobile and PC access:

1. **Create a GitHub Repository** and push your code:
   ```bash
   git init
   git add .
   git commit -m "feat: streamlined job application pipeline and railway deployment config"
   git remote add origin https://github.com/your-username/outbound-pipeline.git
   git push -u origin master
   ```
2. **Deploy on Railway**:
   - Go to [railway.app](https://railway.app) $\rightarrow$ **New Project** $\rightarrow$ **Deploy from GitHub Repo**.
   - Select your `outbound-pipeline` repository.
   - Railway will automatically detect the Python environment via `Procfile`, `requirements.txt`, and `railway.json`.

3. **Set Environment Variables in Railway**:
   Navigate to **Variables** in your Railway dashboard and set:
   * `OPENAI_API_KEY`: Your OpenAI API key (`sk-proj-...`).
   * `GOOGLE_SPREADSHEET_ID`: Your Google Spreadsheet ID
   * `GOOGLE_RESUMES_FOLDER_ID`: Your Google Drive resumes folder ID
   * `GOOGLE_APPLICATIONS_ROOT_FOLDER_ID`: Your Google Drive applications root folder ID
   * `GOOGLE_CREDENTIALS_JSON`: Copy and paste the entire JSON content of your `credentials.json` file.
   * `DEMO_MODE`: `false`

4. **Generate Domain**:
   - In Railway Settings, click **Generate Domain** under *Networking*.
   - Open your custom URL on your phone or PC to use your live tracker!

