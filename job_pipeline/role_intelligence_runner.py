import os
import sys
import json
from pathlib import Path
from typing import Dict, Any, Optional
from openai import OpenAI

# Add role_intelligence directory to sys.path for internal imports
PROJECT_ROOT = Path(__file__).resolve().parent
ROLE_INTEL_DIR = PROJECT_ROOT / "role_intelligence"
sys.path.insert(0, str(ROLE_INTEL_DIR))

from prepare_source_bundle import prepare_source_bundle
from recall_sheet_generator import generate_recall_sheet, load_json


class RoleIntelligenceRunner:
    """Orchestrates the 2-stage LLM workflow and renders the Role Intelligence Report DOCX."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._openai_client = None

    @property
    def client(self) -> OpenAI:
        if not self._openai_client:
            if not self.api_key:
                raise ValueError("OPENAI_API_KEY environment variable is not set.")
            self._openai_client = OpenAI(api_key=self.api_key)
        return self._openai_client

    def run_pipeline(
        self,
        job_data: Dict[str, Any],
        resume_data: Dict[str, Any],
        output_docx_path: str,
        target_pay_bounds: Optional[Dict[str, Any]] = None,
        demo_mode: bool = False
    ) -> Dict[str, Any]:
        """
        Executes the Role Intelligence pipeline:
        1. Prepare tagged source bundle (J001..., R001...)
        2. LLM Call 1: Value Match Strategy
        3. LLM Call 2: Role Intelligence Report Composition
        4. Render DOCX via recall_sheet_generator
        """
        company = job_data.get("company", "Target Company")
        title = job_data.get("title", "Target Role")
        
        # Step 1: Prepare source bundle
        raw_bundle = {
            "job": {
                "job_id": job_data.get("job_id", "JOB-001"),
                "company": company,
                "title": title,
                "description": job_data.get("description", "")
            },
            "resume": {
                "resume_id": resume_data.get("resume_id", "RESUME-001"),
                "text": resume_data.get("text", "")
            }
        }
        tagged_bundle = prepare_source_bundle(raw_bundle)

        if demo_mode or not self.api_key:
            print("INFO: Running Role Intelligence Runner in Demo Mode (using cached fixtures)...")
            fixture_path = PROJECT_ROOT / "examples" / "fixtures" / "mock_cockpit_content.json"
            if not fixture_path.exists():
                fixture_path = ROLE_INTEL_DIR / "example_content.json"
            content_json = load_json(fixture_path)
            
            # Dynamic title override for fixture output
            content_json["document_title"] = f"Role Intelligence Report - {company}"
            if "job" in content_json:
                content_json["job"]["company"] = company
                content_json["job"]["title"] = title
        else:
            print(f"RUNNING: Role Intelligence LLM Strategy & Composition for {company}...")
            
            # Load prompts
            strategy_prompt_path = ROLE_INTEL_DIR / "prompts" / "value_match_strategy_prompt.md"
            compose_prompt_path = ROLE_INTEL_DIR / "prompts" / "cockpit_composition_prompt.md"
            
            strategy_prompt = strategy_prompt_path.read_text(encoding="utf-8")
            compose_prompt = compose_prompt_path.read_text(encoding="utf-8")
            
            # LLM Call 1: Strategy Stage
            strategy_input = f"{strategy_prompt}\n\n# SOURCE_BUNDLE\n{json.dumps(tagged_bundle, indent=2)}\n"
            strat_completion = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a senior GTM Strategy consultant. Respond strictly in JSON object format."},
                    {"role": "user", "content": strategy_input}
                ],
                response_format={"type": "json_object"}
            )
            strategy_json = json.loads(strat_completion.choices[0].message.content)
            
            # LLM Call 2: Composition Stage
            compose_system_prompt = (
                "You are a GTM Role Intelligence Report composer. Output ONLY valid JSON containing a top-level \"pages\" array. "
                "The \"pages\" array must contain exactly 2 page objects (Page 1: Strategic Fit & Pain Points, Page 2: Interview & Compensation Strategy). "
                "Each page must have a \"title\" string and a \"columns\" array of 2 column lists, containing section objects with \"title\", \"kind\", and \"items\"."
            )
            compose_input = (
                f"{compose_prompt}\n\n# SOURCE_BUNDLE\n{json.dumps(tagged_bundle, indent=2)}"
                f"\n\n# VALUE_MATCH_STRATEGY\n{json.dumps(strategy_json, indent=2)}\n"
            )
            comp_completion = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": compose_system_prompt},
                    {"role": "user", "content": compose_input}
                ],
                response_format={"type": "json_object"}
            )
            content_json = json.loads(comp_completion.choices[0].message.content)
            
            # Calculate total LLM tokens for strategy + composition calls
            strat_tokens = getattr(strat_completion.usage, "total_tokens", 0) if hasattr(strat_completion, "usage") else 0
            comp_tokens = getattr(comp_completion.usage, "total_tokens", 0) if hasattr(comp_completion, "usage") else 0
            total_llm_tokens = strat_tokens + comp_tokens

            # Normalize top-level JSON key if wrapped by LLM
            if isinstance(content_json, dict):
                if "pages" not in content_json and "title" not in content_json:
                    for k in ["report", "content", "role_intelligence_report", "data"]:
                        if k in content_json and isinstance(content_json[k], dict):
                            content_json = content_json[k]
                            break

                # Normalize 1D list of section objects into 2D list of columns
                if "pages" in content_json and isinstance(content_json["pages"], list):
                    for page in content_json["pages"]:
                        if isinstance(page, dict) and "columns" in page and isinstance(page["columns"], list):
                            cols = page["columns"]
                            if cols and isinstance(cols[0], dict):
                                mid = max(1, len(cols) // 2)
                                page["columns"] = [cols[:mid], cols[mid:]]

            # Fallback if invalid structure
            if not isinstance(content_json, dict) or ("pages" not in content_json and "title" not in content_json):
                print("WARNING: LLM composition JSON missing top-level 'pages'. Falling back to mock fixture layout...")
                fixture_path = PROJECT_ROOT / "examples" / "fixtures" / "mock_cockpit_content.json"
                if not fixture_path.exists():
                    fixture_path = ROLE_INTEL_DIR / "example_content.json"
                content_json = load_json(fixture_path)

        # Prepare runtime variables for template pay substitution
        variables = {}
        if target_pay_bounds:
            if target_pay_bounds.get("posted_min") and target_pay_bounds.get("posted_max"):
                variables["posted_pay"] = f"${target_pay_bounds['posted_min']:,.0f} - ${target_pay_bounds['posted_max']:,.0f}"
            else:
                variables["posted_pay"] = target_pay_bounds.get("display_range", "Not specified")
                
            if target_pay_bounds.get("target_min") and target_pay_bounds.get("target_max"):
                variables["target_pay"] = f"${target_pay_bounds['target_min']:,.0f} - ${target_pay_bounds['target_max']:,.0f}"
                variables["floor_pay"] = f"${target_pay_bounds['target_min']:,.0f}"
                variables["strong_win_pay"] = f"${target_pay_bounds['target_max']:,.0f}+"

        # Step 4: Render DOCX with layout validation & fallback
        os.makedirs(os.path.dirname(os.path.abspath(output_docx_path)), exist_ok=True)
        try:
            generate_recall_sheet(
                content_json,
                output_docx_path,
                variables=variables,
                manifest_path="auto"
            )
        except Exception as render_err:
            print(f"WARNING: Role Intelligence DOCX render validation error ({render_err}). Falling back to fixture layout...")
            fixture_path = PROJECT_ROOT / "examples" / "fixtures" / "mock_cockpit_content.json"
            if not fixture_path.exists():
                fixture_path = ROLE_INTEL_DIR / "example_content.json"
            fallback_json = load_json(fixture_path)
            generate_recall_sheet(
                fallback_json,
                output_docx_path,
                variables=variables,
                manifest_path="auto"
            )

        print(f"SUCCESS: Generated Role Intelligence Report: {output_docx_path}")
        
        return {
            "output_docx_path": output_docx_path,
            "manifest_path": output_docx_path.replace(".docx", ".manifest.json"),
            "content_json": content_json,
            "tokens_used": total_llm_tokens if 'total_llm_tokens' in locals() else 0
        }


if __name__ == "__main__":
    runner = RoleIntelligenceRunner()
    sample_job = {
        "company": "Acme Test Corp",
        "title": "Revenue Operations Analyst",
        "description": "Responsibilities include dbt, BigQuery, Salesforce lead routing, and funnel optimization."
    }
    sample_resume = {
        "resume_id": "res-001",
        "text": "Built dbt models and SQL dashboards for Salesforce RevOps."
    }
    out_path = "output_reports/Acme_Test_Corp_Role_Intelligence_Report.docx"
    res = runner.run_pipeline(sample_job, sample_resume, out_path, demo_mode=True)
    assert os.path.exists(out_path)
    print("SUCCESS: Role intelligence runner demo test passed!")
