import os
from dotenv import load_dotenv
load_dotenv()
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Literal

from job_pipeline.domain.models import RoleIntelligenceReport
from job_pipeline.ports.llm_port import LLMStrategyPort
from job_pipeline.role_intelligence_runner import RoleIntelligenceRunner


class JobRequirementsSchema(BaseModel):
    years_experience_required: Optional[int] = Field(
        None, description="Minimum years of experience required for the role, if specified."
    )
    required_tech_stack: List[str] = Field(
        default_factory=list, description="Technologies, programming languages, databases, or tools explicitly required."
    )
    preferred_tech_stack: List[str] = Field(
        default_factory=list, description="Preferred or nice-to-have technologies, tools, or frameworks."
    )
    core_pain_points: Optional[str] = Field(
        None, description="Main business problem(s) the company is hiring to solve."
    )
    is_remote: bool = Field(
        False, description="Whether the role is remote or hybrid."
    )
    salary_min: Optional[float] = Field(
        None, description="Minimum base salary mentioned in numeric form."
    )
    salary_max: Optional[float] = Field(
        None, description="Maximum base salary mentioned in numeric form."
    )
    extraction_confidence: float = Field(
        1.0, description="Self-assessed extraction confidence score from 0.0 to 1.0."
    )


class JobExtractionPayload(BaseModel):
    company_name: str = Field(..., description="Canonical name of the hiring company.")
    job_title: str = Field(..., description="Exact job title.")
    title_family: Literal["data_analytics", "business_systems", "gtm_engineering", "revenue_operations", "solutions_implementation"] = Field(
        ..., description="Closest matching job family."
    )
    source_url: Optional[str] = Field(None, description="Job URL if mentioned in text.")
    requirements: JobRequirementsSchema


class OpenAIEngineAdapter(LLMStrategyPort):
    """Secondary Driven Adapter for OpenAI Strategy Generation, Telemetry Extraction, and DOCX Rendering."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._runner = RoleIntelligenceRunner(api_key=self.api_key)
        self.last_telemetry_tokens: int = 0
        self.last_report_tokens: int = 0

    def extract_job_telemetry(self, raw_jd: str) -> JobExtractionPayload:
        """Parses raw job description text into structured JobExtractionPayload using gpt-4o-mini."""
        if not self.api_key:
            self.last_telemetry_tokens = 0
            return JobExtractionPayload(
                company_name="Target Company",
                job_title="Revenue Operations Analyst",
                title_family="revenue_operations",
                requirements=JobRequirementsSchema(
                    required_tech_stack=["Salesforce", "SQL", "Tableau", "dbt"],
                    preferred_tech_stack=["HubSpot", "Clari", "Power BI"],
                    core_pain_points="Unifying funnel analytics and pipeline velocity across CRM tools.",
                    is_remote=True
                )
            )

        client = self._runner.client
        system_instruction = (
            "You are a precise B2B GTM intelligence engine. Analyze the job description "
            "to extract high-fidelity structured data, required tech stack, preferred tools, pain points, and compensation."
        )

        completion = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": raw_jd}
            ],
            response_format=JobExtractionPayload
        )
        self.last_telemetry_tokens = getattr(completion.usage, "total_tokens", 0) if hasattr(completion, "usage") else 0
        return completion.choices[0].message.parsed

    def generate_role_intelligence_report(
        self,
        job_data: Dict[str, Any],
        resume_data: Dict[str, Any],
        output_docx_path: str,
        target_pay_bounds: Optional[Dict[str, Any]] = None,
        demo_mode: bool = False
    ) -> RoleIntelligenceReport:
        company = job_data.get("company", "Target Company")
        title = job_data.get("title", "Target Role")

        result = self._runner.run_pipeline(
            job_data=job_data,
            resume_data=resume_data,
            output_docx_path=output_docx_path,
            target_pay_bounds=target_pay_bounds,
            demo_mode=demo_mode
        )
        self.last_report_tokens = result.get("tokens_used", 0)

        return RoleIntelligenceReport(
            document_title=f"Role Intelligence Report - {company}",
            company=company,
            job_title=title,
            output_docx_path=output_docx_path,
            manifest_path=result.get("manifest_path")
        )
