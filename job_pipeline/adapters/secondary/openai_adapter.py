import os
import re
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
        None, description="Minimum base salary or hourly rate mentioned in numeric form."
    )
    salary_max: Optional[float] = Field(
        None, description="Maximum base salary or hourly rate mentioned in numeric form."
    )
    extraction_confidence: float = Field(
        1.0, description="Self-assessed extraction confidence score from 0.0 to 1.0."
    )
    employment_arrangement: Optional[Literal["Employee", "Contract"]] = Field(
        None, description="Employee or Contract if mentioned in posting; null if unspecified."
    )
    worker_classification: Optional[Literal["W2", "1099", "C2C"]] = Field(
        None, description="Worker tax classification (W2, 1099, C2C) only if explicitly mentioned; null if unspecified."
    )
    pay_basis: Optional[Literal["Annual", "Hourly"]] = Field(
        None, description="Annual or Hourly pay basis; null if ambiguous or unspecified."
    )
    expected_hours_per_week: Optional[float] = Field(
        None, description="Expected weekly work hours if explicitly specified (e.g. 40, 20)."
    )
    contract_length_months: Optional[float] = Field(
        None, description="Contract duration normalized in months (e.g. 6.0 for '6 months')."
    )
    contract_length_weeks: Optional[float] = Field(
        None, description="Contract duration normalized in weeks (e.g. 26.0 for '26 weeks')."
    )
    contract_length_raw: Optional[str] = Field(
        None, description="Original contract duration text as stated (e.g. '6-month contract', 'through December 2026')."
    )
    extension_possible: Optional[bool] = Field(
        None, description="True if contract extension is mentioned as possible, False if explicitly no extension, null if not mentioned."
    )
    fte_conversion_possible: Optional[bool] = Field(
        None, description="True if contract-to-hire or full-time FTE conversion is mentioned, False if explicitly no, null if not mentioned."
    )
    staffing_agency: Optional[str] = Field(
        None, description="Staffing firm or recruiting agency name if this role is through an agency (e.g. 'Acme Staffing')."
    )
    client_company: Optional[str] = Field(
        None, description="End client or host company name if distinct from the staffing agency (e.g. 'Contoso')."
    )
    benefits_offered: Optional[bool] = Field(
        None, description="True if benefits are explicitly offered, null if unspecified."
    )
    guaranteed_hours: Optional[bool] = Field(
        None, description="True if guaranteed hours are explicitly mentioned, null if unspecified."
    )
    telemetry_warnings: List[str] = Field(
        default_factory=list, description="List of warning labels or infractions detected based on the configured warning criteria or job post conditions."
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

    def extract_job_telemetry(
        self,
        raw_jd: str,
        warning_rules: Optional[List[Dict[str, Any]]] = None
    ) -> JobExtractionPayload:
        """Parses raw job description text into structured JobExtractionPayload using gpt-4o-mini and user warning rules."""
        if warning_rules is None:
            try:
                from job_pipeline.domain.services import PipelineConfigService
                warning_rules = PipelineConfigService.get_active_warning_rules()
            except Exception:
                warning_rules = []

        if not self.api_key:
            self.last_telemetry_tokens = 0
            offline_warnings: List[str] = []
            if warning_rules:
                for rule in warning_rules:
                    r_name = rule.get("name", "Warning")
                    for kw in rule.get("keywords", []):
                        if kw and kw.strip():
                            pattern = r'(?:\b|_)' + re.escape(kw.strip()) + r'(?:\b|_)'
                            if re.search(pattern, raw_jd, re.IGNORECASE):
                                offline_warnings.append(f"[{r_name}]: Keyword match detected ('{kw.strip()}').")
                                break

            return JobExtractionPayload(
                company_name="Target Company",
                job_title="Revenue Operations Analyst",
                title_family="revenue_operations",
                requirements=JobRequirementsSchema(
                    required_tech_stack=["Salesforce", "SQL", "Tableau", "dbt"],
                    preferred_tech_stack=["HubSpot", "Clari", "Power BI"],
                    core_pain_points="Unifying funnel analytics and pipeline velocity across CRM tools.",
                    is_remote=True,
                    employment_arrangement="Employee",
                    pay_basis="Annual",
                    telemetry_warnings=offline_warnings
                )
            )

        client = self._runner.client
        warning_section = ""
        if warning_rules:
            rule_lines = []
            for idx, r in enumerate(warning_rules, start=1):
                name = r.get("name", f"Rule {idx}")
                category = r.get("category", "General")
                severity = r.get("severity", "Warning")
                keywords = ", ".join(r.get("keywords", []))
                concept = r.get("concept_description", "")
                rule_lines.append(
                    f"{idx}. {name} (Category: {category}, Severity: {severity})\n"
                    f"   - Trigger Keywords: {keywords or 'None specified'}\n"
                    f"   - Target Concept/Condition: {concept}"
                )
            warning_section = (
                "\n\nCONFIGURABLE TELEMETRY WARNING RULES:\n"
                "Evaluate the job post against each rule below. If any keyword, concept, or condition is present or implied,\n"
                "add a distinct infraction to the 'telemetry_warnings' list in the format '[<Rule Name>]: <Brief reason/quote>'.\n"
                "Do NOT combine multiple violations into one string; record every matching rule infraction as a separate item:\n"
                + "\n".join(rule_lines)
            )

        system_instruction = (
            "You are a precise B2B GTM intelligence engine. Analyze the job description "
            "to extract high-fidelity structured data, required tech stack, preferred tools, pain points, compensation, and contract terms.\n\n"
            "CONTRACT & COMPENSATION EXTRACTION RULES:\n"
            "1. Pay Basis: Identify 'Hourly' vs 'Annual' pay when clear. For hourly roles (e.g. $60-$70/hr), set pay_basis='Hourly' and record numeric hourly rates in salary_min / salary_max. Do NOT convert hourly to annual here.\n"
            "2. Employment Arrangement: Identify 'Contract' vs 'Employee' separately from pay basis.\n"
            "3. Worker Classification: Extract 'W2', '1099', or 'C2C' ONLY when explicitly stated or strongly unambiguous. If the post simply says 'contract position', leave worker_classification as null.\n"
            "4. Unknown Values: Distinguish unknown (null) from explicitly false. If the post says nothing about extension, store null, not false.\n"
            "5. Contract Duration: Extract contract duration when specified, providing normalized months/weeks and preserving the raw phrase.\n"
            "6. Extension & FTE Conversion: Extract extension_possible and fte_conversion_possible independently (e.g. 'contract-to-hire' -> fte_conversion_possible=True).\n"
            "7. Staffing Agency & Client: Extract staffing_agency and client_company only when identifiable from the text.\n"
            "8. Expected Hours: Extract expected_hours_per_week only when explicitly stated. Do NOT invent hours.\n"
            "9. Never fill missing contract values using industry assumptions; preserve them as null."
            + warning_section
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
        parsed = completion.choices[0].message.parsed

        # Hybrid scanning: Ensure deterministic keyword matches are guaranteed to be flagged
        detected_warnings = list(parsed.requirements.telemetry_warnings or [])
        if warning_rules:
            for rule in warning_rules:
                r_name = rule.get("name", "Warning")
                keywords = rule.get("keywords", [])
                matched_kws = []
                for kw in keywords:
                    if not kw or not kw.strip():
                        continue
                    pattern = r'(?:\b|_)' + re.escape(kw.strip()) + r'(?:\b|_)'
                    if re.search(pattern, raw_jd, re.IGNORECASE):
                        matched_kws.append(kw.strip())
                if matched_kws:
                    already_flagged = any(r_name.lower() in w.lower() for w in detected_warnings)
                    if not already_flagged:
                        kws_str = ", ".join(f"'{k}'" for k in set(matched_kws))
                        detected_warnings.append(f"[{r_name}]: Keyword match detected ({kws_str}).")
        parsed.requirements.telemetry_warnings = detected_warnings
        return parsed

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
