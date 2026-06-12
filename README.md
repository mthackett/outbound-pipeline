# Outbound Target Pipeline

A Python-based automation pipeline that processes raw job descriptions from Google Sheets, extracts structured GTM telemetry (company name, title, target tech stacks, remote status, pain points, and base compensation bounds) using OpenAI's `gpt-4o-mini` structured parsing model, and updates the sheets in place.

## 📁 Key Components

*   **[main.py](file:///c:/Users/mthac/Projects/outbound-pipeline/main.py)**: The core pipeline script. Identifies unprocessed rows, queries the OpenAI API with Pydantic schema validation, updates the main sheet, and appends raw extraction logs to the requirements sheet.
*   **[project.md](file:///c:/Users/mthac/Projects/outbound-pipeline/project.md)**: Product backlog, architecture roadmap, and future state machine integration instructions.
*   **[sheets.py](file:///c:/Users/mthac/Projects/outbound-pipeline/sheets.py)** & **[smoketest.py](file:///c:/Users/mthac/Projects/outbound-pipeline/smoketest.py)**: Initial exploration scripts for Google Sheets API connectivity.

---

## 🚀 Getting Started

### 1. Installation
Ensure your virtual environment is active, then install the dependencies:
```bash
pip install gspread oauth2client openai pydantic python-dotenv
```

### 2. Configuration
Create a `.env` file in the root directory:
```env
OPENAI_API_KEY=your-openai-api-key-here
```
Ensure you place your Google Cloud Service Account credentials in `credentials.json` in the root directory.

---

## 🛠️ How to Run the Pipeline

1. **Add Job Descriptions**: Paste a raw job description into the `Job Description` column of a new row in the **Raw Ingestion** worksheet.
2. **Execute the Pipeline**:
   ```bash
   python main.py
   ```
3. **Verify Output**:
   *   The **Raw Ingestion** columns (Company Name, Job Title, Title Family, Source URL, Status, Opportunity ID, etc.) will populate.
   *   Detailed requirements will be appended as a new row to the **Requirements Extraction** worksheet, automatically linked by `opportunity_id` with Postgres-formatted array notation (`{'Python', 'SQL'}`).
   *   Sheet columns will auto-resize dynamically to prevent text overflow.
