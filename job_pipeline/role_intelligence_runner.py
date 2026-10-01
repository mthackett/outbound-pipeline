import os
import sys
import json
from pathlib import Path
from typing import Dict, Any, Optional
from dotenv import load_dotenv
load_dotenv()
from openai import OpenAI
from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PROJECT_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PROMPTS_DIR = PROJECT_ROOT / "resources" / "prompts"
FIXTURES_DIR = PROJECT_ROOT / "examples" / "fixtures"

from job_pipeline.domain.role_intelligence import prepare_source_bundle
from job_pipeline.adapters.secondary.docx_report_generator import generate_recall_sheet, load_json, load_config


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

        if not demo_mode and not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for live report generation; enable demo mode explicitly for sample reports.")

        if demo_mode:
            print("INFO: Running Role Intelligence Runner in Demo Mode (using cached fixtures)...")
            fixture_path = FIXTURES_DIR / "mock_cockpit_content.json"
            content_json = load_json(fixture_path)
            
            # Dynamic title override for fixture output
            content_json["document_title"] = f"Role Intelligence Report - {company}"
            if "job" in content_json:
                content_json["job"]["company"] = company
                content_json["job"]["title"] = title
        else:
            print(f"RUNNING: Role Intelligence LLM Strategy & Composition for {company}...")
            
            # Load prompts
            strategy_prompt_path = PROMPTS_DIR / "value_match_strategy_prompt.md"
            compose_prompt_path = PROMPTS_DIR / "cockpit_composition_prompt.md"
            
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
                "Each page must have a \"title\" string and a \"columns\" array of exactly 3 column lists, containing section objects with \"title\", \"kind\", and \"items\"."
            )
            content_schema = load_json(PROJECT_ROOT / "resources" / "schemas" / "cockpit_content.schema.json")
            compose_input = (
                f"# REQUIRED CONTENT SCHEMA\n{json.dumps(content_schema)}\n\n{compose_prompt}\n\n# SOURCE_BUNDLE\n{json.dumps(tagged_bundle, indent=2)}"
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

                # Normalize column structure and section kinds
                if "pages" in content_json and isinstance(content_json["pages"], list):
                    for page in content_json["pages"]:
                        if isinstance(page, dict) and "columns" in page and isinstance(page["columns"], list):
                            cols = page["columns"]
                            # If LLM returned 1D list of section objects instead of 2D list of columns:
                            if cols and all(isinstance(c, dict) for c in cols):
                                n_cols = 3
                                chunk_size = max(1, (len(cols) + n_cols - 1) // n_cols)
                                page["columns"] = [cols[i:i + chunk_size] for i in range(0, len(cols), chunk_size)]
                                while len(page["columns"]) < n_cols:
                                    page["columns"].append([])

                            # Normalize section kinds, item formats, and default titles
                            for col in page["columns"]:
                                if isinstance(col, list):
                                    for sec in col:
                                        if isinstance(sec, dict):
                                            if not sec.get("title") or not str(sec["title"]).strip():
                                                sec["title"] = sec.get("header") or sec.get("name") or sec.get("heading") or "Overview"
                                            skind = str(sec.get("kind", "bullets")).lower()
                                            if skind in ("text", "paragraph", "paragraphs", "prose"):
                                                sec["kind"] = "lines"
                                            elif skind in ("list", "bullet"):
                                                sec["kind"] = "bullets"
                                            elif skind in ("skill", "skill_matrix"):
                                                sec["kind"] = "skills"
                                            if isinstance(sec.get("items"), str):
                                                sec["items"] = [sec["items"]]

        # Live content must satisfy the same three-column contract as the renderer.
        # Invalid output is recoverable failure, never permission to invent career facts.
        content_schema = load_json(PROJECT_ROOT / "resources" / "schemas" / "cockpit_content.schema.json")
        errors = sorted(Draft202012Validator(content_schema).iter_errors(content_json), key=lambda e: str(list(e.path)))
        if errors:
            first = errors[0]
            raise ValueError(f"Role Intelligence content violates the report schema at {list(first.path)}: {first.message}")
        if len(load_config()["column_widths_in"]) != 3:
            raise ValueError("Role Intelligence requires the configured three-column report layout.")

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

        # Step 4: rendering errors propagate to ingestion, keeping it recoverable.
        os.makedirs(os.path.dirname(os.path.abspath(output_docx_path)), exist_ok=True)
        try:
            generate_recall_sheet(content_json, output_docx_path, variables=variables, manifest_path="auto")
        except Exception as render_err:
            raise RuntimeError(f"Role Intelligence rendering failed ({render_err}); ingestion remains incomplete. Retry after correcting the report content or renderer error.") from render_err

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
