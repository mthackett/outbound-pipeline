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
    telemetry_flags: List[str] = Field(default_factory=list, description="Configured flag findings only. Each string MUST be '[rule-id]: rationale', using the exact configured ID and short JD evidence. Never a bare ID or display name. Empty if none match.")
    telemetry_warnings: List[str] = Field(
        default_factory=list, description="Configured warning findings only. Each string MUST be '[rule-id]: rationale', using the exact configured ID and short JD evidence. Never a bare ID or display name. Empty if none match."
    )
    telemetry_benefits: List[str] = Field(
        default_factory=list, description="Configured benefit findings only. Each string MUST be '[rule-id]: rationale', using the exact configured ID and short JD evidence. Never a bare ID or display name. Empty if none match."
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

    @property
    def client(self):
        return getattr(self._runner, "client", None)

    @property
    def is_connected(self) -> bool:
        return self.client is not None


    def extract_job_telemetry(
        self,
        raw_jd: str,
        warning_rules: Optional[List[Dict[str, Any]]] = None
    ) -> JobExtractionPayload:
        """Parses raw job description text into structured JobExtractionPayload using gpt-4o-mini and user warning rules."""
        from job_pipeline.domain.telemetry_service import TelemetryService
        if warning_rules is None:
            try:
                from job_pipeline.domain.services import PipelineConfigService
                warning_rules = PipelineConfigService.get_active_telemetry_rules()
            except Exception:
                warning_rules = []

        normalized_rules = [TelemetryService.normalize_rule(r) for r in (warning_rules or []) if (r.get("enabled", True) if isinstance(r, dict) else r.enabled)]

        # 1. Deterministic evaluation (instant, 0 tokens, boundary-aware)
        deterministic_findings = TelemetryService.evaluate_deterministic_rules(normalized_rules, raw_jd)
        det_flags, det_warns, det_benefits = TelemetryService.split_findings(deterministic_findings)

        # 2. Check cache to avoid repeated LLM work on unchanged JD & rules
        cache_key = TelemetryService.compute_cache_key(
            raw_jd,
            [r if isinstance(r, dict) else r.model_dump() for r in (warning_rules or [])]
        )
        cache_key = ("online:semantic-v2:" if self.api_key else "offline:") + cache_key
        cached_payload = TelemetryService.get_cached_extraction(cache_key)
        if cached_payload:
            self.last_telemetry_tokens = 0
            return cached_payload

        # 3. Offline fallback if no API key
        if not self.api_key:
            self.last_telemetry_tokens = 0
            offline_warnings = [f.to_display_string() for f in det_warns]
            offline_benefits = [f.to_display_string() for f in det_benefits]

            payload = JobExtractionPayload(
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
                    telemetry_warnings=offline_warnings,
                    telemetry_flags=[f.to_display_string() for f in det_flags],
                    telemetry_benefits=offline_benefits
                )
            )
            TelemetryService.set_cached_extraction(cache_key, payload)
            return payload

        # 4. Online LLM extraction with semantic rules only
        client = self._runner.client
        semantic_rules = [r for r in normalized_rules if r.match_mode == "concept"]
        warning_section = TelemetryService.build_semantic_prompt_section(semantic_rules)

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
            "9. Never fill missing contract values using industry assumptions; preserve them as null.\n"
            "Job signals must correspond ONLY to the configured rules below. With no configured semantic rules, return empty telemetry arrays."
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

        # 5. Parse returned semantic infractions & combine with deterministic findings
        llm_warn_raw = list(parsed.requirements.telemetry_warnings or [])
        llm_ben_raw = list(parsed.requirements.telemetry_benefits or [])
        semantic_findings = TelemetryService.parse_semantic_infractions(list(parsed.requirements.telemetry_flags or []) + llm_warn_raw + llm_ben_raw, semantic_rules)

        all_findings = list(deterministic_findings)
        for sf in semantic_findings:
            if not any(af.rule_id == sf.rule_id for af in all_findings):
                all_findings.append(sf)

        flags, warns, benefits = TelemetryService.split_findings(all_findings)
        parsed.requirements.telemetry_flags = [f.to_display_string() for f in flags]
        parsed.requirements.telemetry_warnings = [f.to_display_string() for f in warns]
        parsed.requirements.telemetry_benefits = [f.to_display_string() for f in benefits]

        TelemetryService.set_cached_extraction(cache_key, parsed)
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
