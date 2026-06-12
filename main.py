import os
import uuid
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from openai import OpenAI
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
import dotenv

# Load environment variables from .env file
dotenv.load_dotenv()

# =====================================================================
# 1. PYDANTIC SCHEMAS FOR STRUCTURED EXTRACTION
# =====================================================================

class JobRequirementsSchema(BaseModel):
    years_experience_required: Optional[int] = Field(
        None, 
        description="The minimum years of experience required for the role, if specified. Extract as an integer."
    )
    required_tech_stack: List[str] = Field(
        default_factory=list,
        description="List of technologies, programming languages, databases, or frameworks explicitly required."
    )
    preferred_tech_stack: List[str] = Field(
        default_factory=list,
        description="List of preferred or nice-to-have technologies, frameworks, databases, or tools."
    )
    core_pain_points: Optional[str] = Field(
        None,
        description="The main problem(s) the company is trying to solve by hiring this role, as inferred from the responsibilities and requirements."
    )
    is_remote: bool = Field(
        False,
        description="Whether the job is remote (WFH / Work From Home). Set to True if remote or hybrid with remote option, False otherwise."
    )
    salary_min: Optional[float] = Field(
        None,
        description="The minimum base salary mentioned in the text (numeric, e.g. 70000 for $70k). Set to null if not specified."
    )
    salary_max: Optional[float] = Field(
        None,
        description="The maximum base salary mentioned in the text (numeric, e.g. 110000 for $110k). Set to null if not specified."
    )
    extraction_confidence: float = Field(
        ...,
        description="Your self-assessed confidence score for this extraction on a scale from 0.0 (lowest) to 1.0 (highest)."
    )

class JobExtractionPayload(BaseModel):
    company_name: str = Field(
        ..., 
        description="The canonical/cleaned name of the company hiring for the position."
    )
    job_title: str = Field(
        ..., 
        description="The exact title of the job position."
    )
    title_family: Literal["data_analytics", "business_systems", "gtm_engineering", "revenue_operations", "solutions_implementation"] = Field(
        ..., 
        description="Select the closest matching job family based on the job responsibilities and technical stack."
    )
    source_url: Optional[str] = Field(
        None, 
        description="An optional URL representing the job posting source found within the job description text, if any."
    )
    requirements: JobRequirementsSchema = Field(
        ...,
        description="Details about the role's requirements, tech stack, pain points, and salary metrics."
    )

# =====================================================================
# 2. HELPER FUNCTIONS
# =====================================================================

def to_postgres_array(lst: List[str]) -> str:
    """Formats a Python list of strings as a Postgres text array literal, e.g. {'Python', 'Postgres'}."""
    if not lst:
        return "{}"
    # Escape single quotes by doubling them
    escaped_items = []
    for item in lst:
        clean_item = item.replace("'", "''")
        escaped_items.append(f"'{clean_item}'")
    return "{" + ", ".join(escaped_items) + "}"

# =====================================================================
# 3. MAIN RUN ROUTINE
# =====================================================================

def run_pipeline():
    # Initialize OpenAI Client
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("❌ Error: OPENAI_API_KEY environment variable is not set.")
        return
    openai_client = OpenAI(api_key=api_key)

    # Initialize Google Sheets client
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    
    SPREADSHEET_ID = "your-google-spreadsheet-id-here"
    sheet = client.open_by_key(SPREADSHEET_ID)
    
    # Setup Main Sheet
    print("🔄 Connecting to 'Raw Ingestion' worksheet...")
    ingest_worksheet = sheet.worksheet("Raw Ingestion")
    
    # Read headers
    headers = ingest_worksheet.row_values(1)
    headers = [h.strip() for h in headers]
    
    # Check and add Opportunity ID column if missing (Option A)
    if "Opportunity ID" not in headers:
        print("➕ 'Opportunity ID' column not found in headers. Appending it...")
        ingest_worksheet.update_cell(1, len(headers) + 1, "Opportunity ID")
        headers.append("Opportunity ID")
        
    # Check and add Tokens column if missing
    if "Tokens" not in headers:
        print("➕ 'Tokens' column not found in headers. Appending it...")
        ingest_worksheet.update_cell(1, len(headers) + 1, "Tokens")
        headers.append("Tokens")
        
    header_indices = {header: idx + 1 for idx, header in enumerate(headers)}
    
    # Setup Requirements Sheet
    requirements_sheet_name = "Requirements Extraction"
    try:
        extraction_worksheet = sheet.worksheet(requirements_sheet_name)
        print(f"✅ Found existing '{requirements_sheet_name}' worksheet.")
    except gspread.exceptions.WorksheetNotFound:
        print(f"➕ '{requirements_sheet_name}' worksheet not found. Creating it...")
        extraction_worksheet = sheet.add_worksheet(title=requirements_sheet_name, rows=1000, cols=11)
        req_headers = [
            "requirement_id", "opportunity_id", "years_experience_required",
            "required_tech_stack", "preferred_tech_stack", "core_pain_points",
            "is_remote", "salary_min", "salary_max", "extraction_confidence", "updated_at"
        ]
        extraction_worksheet.append_row(req_headers)
        print(f"✅ Created worksheet '{requirements_sheet_name}' with headers.")

    # Fetch all records
    records = ingest_worksheet.get_all_records()
    print(f"📊 Total rows found in 'Raw Ingestion': {len(records)}")

    # Containers for batch updates to avoid Google Sheets API rate limiting
    cell_updates = []
    req_cell_updates = []
    
    system_instruction = (
        "You are a precise B2B GTM intelligence engine. Your task is to analyze raw text "
        "to extract high-fidelity structured data for an outbound pipeline.\n\n"
        "Crucial Instruction on Culture: Do not blindly ignore corporate jargon or idioms. "
        "Instead, systematically isolate specific phrases (e.g., 'write the playbook', 'do the impossible') "
        "and use them to infer the true operational reality of the target environment—such as whether the "
        "culture is frantic and poorly defined, or structured with high personal agency and quiet ownership.\n\n"
        "Additionally, search for any source URL or job application link mentioned inside the job description text, "
        "and extract it if available."
    )

    # Process rows (header is row 1, data starts at row 2)
    for index, record in enumerate(records, start=2):
        status = record.get("Status")
        job_description = record.get("Job Description", "").strip()
        
        # We only process if Status is not "Processed"/"Failed" and Job Description exists
        if status not in ["Processed", "Failed"] and job_description:
            if len(job_description) < 20:
                print(f"⚠️ Row {index}: Job Description is too short ({len(job_description)} chars). Skipping...")
                continue
                
            print(f"🚀 Processing Row {index}: Extracting fields via LLM...")
            
            try:
                # Call OpenAI structured parsing API
                completion = openai_client.beta.chat.completions.parse(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": job_description}
                    ],
                    response_format=JobExtractionPayload,
                )
                
                payload = completion.choices[0].message.parsed
                if not payload:
                    raise ValueError("LLM returned an empty or unparsable payload.")
                
                # Generate unique identifiers
                opp_id = str(uuid.uuid4())
                req_id = str(uuid.uuid4())
                
                # Helper to queue updates only if the cell is currently empty
                def queue_update_if_empty(header_name, val):
                    current_val = record.get(header_name)
                    if current_val is None or str(current_val).strip() == "":
                        col_idx = header_indices[header_name]
                        cell_updates.append(gspread.Cell(row=index, col=col_idx, value=val))
                        record[header_name] = val # Update local record state
                
                # Update main opportunity sheet cells if not already populated
                queue_update_if_empty("Company Name", payload.company_name)
                queue_update_if_empty("Job Title", payload.job_title)
                queue_update_if_empty("Title Family", payload.title_family)
                
                current_date = datetime.date.today().strftime("%Y-%m-%d")
                queue_update_if_empty("Date Created", current_date)
                
                if payload.source_url:
                    queue_update_if_empty("Source URL", payload.source_url)
                
                queue_update_if_empty("Opportunity ID", opp_id)
                
                # Update token usage
                tokens_str = f"{{Output: {completion.usage.completion_tokens}, Input: {completion.usage.prompt_tokens}}}"
                queue_update_if_empty("Tokens", tokens_str)
                
                # Always update Status and Last Modified for processed rows
                current_timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cell_updates.append(gspread.Cell(row=index, col=header_indices["Status"], value="Processed"))
                cell_updates.append(gspread.Cell(row=index, col=header_indices["Last Modified"], value=current_timestamp))
                
                # Prepare row for requirements extraction table
                req = payload.requirements
                req_row = [
                    req_id,
                    record.get("Opportunity ID") or opp_id,
                    req.years_experience_required if req.years_experience_required is not None else "",
                    to_postgres_array(req.required_tech_stack),
                    to_postgres_array(req.preferred_tech_stack),
                    req.core_pain_points if req.core_pain_points else "",
                    "TRUE" if req.is_remote else "FALSE",
                    req.salary_min if req.salary_min is not None else "",
                    req.salary_max if req.salary_max is not None else "",
                    req.extraction_confidence,
                    current_timestamp
                ]
                # Queue cell updates for the requirements extraction worksheet at the matching row index
                for col_idx, value in enumerate(req_row, start=1):
                    req_cell_updates.append(gspread.Cell(row=index, col=col_idx, value=value))
                print(f"✅ Row {index}: Successfully parsed and queued updates.")
                
            except Exception as e:
                print(f"❌ Row {index}: Error during LLM extraction/validation: {e}")
                current_timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cell_updates.append(gspread.Cell(row=index, col=header_indices["Status"], value="Failed"))
                cell_updates.append(gspread.Cell(row=index, col=header_indices["Last Modified"], value=current_timestamp))
                if "Notes" in header_indices:
                    cell_updates.append(gspread.Cell(row=index, col=header_indices["Notes"], value=f"Extraction failed: {str(e)[:100]}"))

    # Apply batch updates to Google Sheets
    if cell_updates:
        print(f"📡 Sending {len(cell_updates)} cell updates to 'Raw Ingestion' worksheet...")
        ingest_worksheet.update_cells(cell_updates)
        print("✅ Opportunity updates saved.")
        try:
            ingest_worksheet.columns_auto_resize(0, len(headers))
            print("✅ Auto-resized 'Raw Ingestion' columns.")
        except Exception as e:
            print(f"⚠️ Warning: Could not auto-resize 'Raw Ingestion' columns: {e}")
        
    if req_cell_updates:
        print(f"📡 Sending {len(req_cell_updates)} cell updates to '{requirements_sheet_name}' worksheet...")
        extraction_worksheet.update_cells(req_cell_updates)
        print("✅ Requirements extraction updates saved.")
        try:
            extraction_worksheet.columns_auto_resize(0, 11)
            print("✅ Auto-resized 'Requirements Extraction' columns.")
        except Exception as e:
            print(f"⚠️ Warning: Could not auto-resize '{requirements_sheet_name}' columns: {e}")

    if not cell_updates and not req_cell_updates:
        print("💤 No new or pending job descriptions found to process.")

if __name__ == "__main__":
    run_pipeline()
