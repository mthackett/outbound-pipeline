import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field, field_validator



EMPLOYMENT_ARRANGEMENTS: List[str] = [
    "Employee",
    "Contract"
]

PAY_BASES: List[str] = [
    "Annual",
    "Hourly"
]

WORKER_CLASSIFICATIONS: List[str] = [
    "W2",
    "1099",
    "C2C"
]

TELEMETRY_RULE_CATEGORIES: List[str] = [
    "warning",
    "flag",
    "benefit"
]

TELEMETRY_MATCH_MODES: List[str] = [
    "token",
    "phrase",
    "regex",
    "concept"
]

TELEMETRY_DOMAIN_CATEGORIES: List[str] = [
    "Scope",
    "Skills",
    "Experience",
    "Benefits",
    "Culture",
    "Compensation",
    "Other"
]

TELEMETRY_WARNING_CATEGORIES: List[str] = TELEMETRY_DOMAIN_CATEGORIES

DEFAULT_TELEMETRY_RULES: List[Dict[str, Any]] = [
    {
        "id": "warn-on-call",
        "name": "On-Call / Weekend Support Required",
        "category": "warning",
        "match_mode": "concept",
        "patterns": ["on-call", "24/7", "pagerduty", "weekend coverage", "after-hours", "night shift"],
        "keywords": ["on-call", "24/7", "pagerduty", "weekend coverage", "after-hours", "night shift"],
        "concept_description": "Role requires regular on-call rotation, 24/7 availability, off-hours incident response, or mandatory night/weekend work. Exclude optional support and descriptions of the product or other teams.",
        "explanation": "Role requires regular on-call rotation, off-hours response, or mandatory weekend work.",
        "domain_category": "Scope",
        "severity": "Warning",
        "enabled": True,
        "case_sensitive": False
    },
    {
        "id": "warn-excessive-travel",
        "name": "Excessive Travel (>25%)",
        "category": "warning",
        "match_mode": "concept",
        "patterns": ["travel 50%", "travel 75%", "frequent travel", "extensive travel", "road warrior"],
        "keywords": ["travel 50%", "travel 75%", "frequent travel", "extensive travel", "road warrior"],
        "concept_description": "Role requires more than 25% travel. Require explicit percentage or equivalent recurring commitment; vague mentions of travel alone are insufficient.",
        "explanation": "Role requires heavy or frequent travel exceeding 25%.",
        "domain_category": "Scope",
        "severity": "Warning",
        "enabled": True,
        "case_sensitive": False
    },
    {
        "id": "warn-no-benefits",
        "name": "No Benefits / Commission Only",
        "category": "warning",
        "match_mode": "concept",
        "patterns": ["commission only", "no benefits", "unpaid", "equity only", "stipend only"],
        "keywords": ["commission only", "no benefits", "unpaid", "equity only", "stipend only"],
        "concept_description": "Role explicitly offers no standard benefits or no guaranteed base compensation (commission-only, entirely performance-based, equity-only, or unpaid). Do not flag normal salary plus commission or merely unspecified benefits.",
        "explanation": "Role offers no standard benefits or no guaranteed base compensation.",
        "domain_category": "Benefits",
        "severity": "Warning",
        "enabled": True,
        "case_sensitive": False
    },
    {
        "id": "warn-legacy-stack",
        "name": "Outdated / Legacy Tech Stack",
        "category": "warning",
        "match_mode": "concept",
        "patterns": ["COBOL", "Visual Basic", "VB6", "Fortran", "Lotus Notes", "Access database", "legacy monolithic"],
        "keywords": ["COBOL", "Visual Basic", "VB6", "Fortran", "Lotus Notes", "Access database", "legacy monolithic"],
        "concept_description": "Role heavily relies on legacy, deprecated, or obsolete technology. Exclude incidental mentions, optional experience, and work primarily replacing legacy systems with modern tools.",
        "explanation": "Role heavily relies on legacy or deprecated programming languages and architectures.",
        "domain_category": "Skills",
        "severity": "Warning",
        "enabled": True,
        "case_sensitive": False
    },
    {
        "id": "warn-overbroad-scope",
        "name": "Overbroad Scope / Multi-Department Trap",
        "category": "warning",
        "match_mode": "concept",
        "patterns": ["wear many hats", "handle IT and sales and marketing", "one-person department", "do-it-all"],
        "keywords": ["wear many hats", "handle IT and sales and marketing", "one-person department", "do-it-all"],
        "concept_description": "Role assigns one person substantial responsibilities across unrelated departments, such as IT helpdesk, office management, sales, and engineering, without dedicated team support. Exclude ordinary cross-functional collaboration and vague wear-many-hats language alone.",
        "explanation": "Job description expects a single person to handle IT, office management, sales, and engineering simultaneously.",
        "domain_category": "Scope",
        "severity": "Warning",
        "enabled": True,
        "case_sensitive": False
    }
]

DEFAULT_TELEMETRY_WARNING_RULES: List[Dict[str, Any]] = DEFAULT_TELEMETRY_RULES


class TelemetryFinding(BaseModel):
    rule_id: str
    rule_name: str
    category: str = "warning"  # "warning", "flag", "benefit"
    match_mode: str = "token"  # "token", "phrase", "regex", "concept"
    matched_text: Optional[str] = None
    reason: str = ""
    domain_category: Optional[str] = None

    def to_display_string(self) -> str:
        """Formatted explainable string representation."""
        cat_lower = (self.category or "warning").lower()
        if cat_lower == "flag":
            prefix = f"FLAG: [{self.rule_name}]"
        elif cat_lower == "benefit":
            prefix = f"BENEFIT: [{self.rule_name}]"
        else:
            prefix = f"[{self.rule_name}]"

        details = []
        if self.matched_text:
            details.append(f"Matched: '{self.matched_text}'")
        if self.reason:
            details.append(self.reason)

        detail_str = " - ".join(details) if details else "Condition detected."
        return f"{prefix}: {detail_str}"


class TelemetryRule(BaseModel):
    id: str = Field(default_factory=lambda: f"rule-{uuid.uuid4().hex[:6]}")
    name: str = Field(..., description="Short descriptive title for this rule.")
    category: str = Field(default="warning", description="Classification: 'warning', 'flag', or 'benefit'.")
    match_mode: str = Field(default="token", description="Evaluation mode: 'token', 'phrase', 'regex', or 'concept'.")
    patterns: List[str] = Field(default_factory=list, description="Keywords, phrases, or regex patterns to match.")
    concept_description: str = Field(default="", description="Semantic condition or concept for LLM evaluation.")
    explanation: str = Field(default="", description="Optional explanation or reason displayed when this rule triggers.")
    domain_category: str = Field(default="Scope", description="Domain classification: Scope, Skills, Experience, Benefits, Culture, Compensation, Other.")
    enabled: bool = Field(default=True, description="Whether this rule is active.")
    case_sensitive: bool = Field(default=False, description="Whether token/phrase/regex matching is case-sensitive.")

    def __init__(self, **data: Any):
        # Backward compatibility transformations
        if "keywords" in data and "patterns" not in data:
            data["patterns"] = data["keywords"]
        if "patterns" in data and "keywords" not in data:
            data["keywords"] = data["patterns"]

        raw_cat = str(data.get("category", "")).strip().lower()
        raw_sev = str(data.get("severity", "")).strip().lower()
        if raw_cat not in ("warning", "flag", "benefit"):
            if "category" in data and data["category"] and not data.get("domain_category"):
                data["domain_category"] = data["category"]
            if raw_sev in ("warning", "flag", "benefit"):
                data["category"] = raw_sev
            else:
                data["category"] = "warning"
        super().__init__(**data)

    @property
    def keywords(self) -> List[str]:
        return self.patterns

    @keywords.setter
    def keywords(self, val: List[str]) -> None:
        self.patterns = val

    @property
    def severity(self) -> str:
        cat = (self.category or "warning").lower()
        if cat == "flag":
            return "Flag"
        elif cat == "benefit":
            return "Benefit"
        return "Warning"

    @severity.setter
    def severity(self, val: str) -> None:
        v = str(val).strip().lower()
        if v in ("warning", "flag", "benefit"):
            self.category = v


# Backwards compatibility alias
TelemetryWarningRule = TelemetryRule



class TargetPayBounds(BaseModel):
    posted_min: Optional[float] = None
    posted_max: Optional[float] = None
    target_min: Optional[float] = None
    target_max: Optional[float] = None
    currency: str = "USD"
    display_range: str = "Not specified"
    pay_basis: str = "Annual"  # "Annual" or "Hourly"
    hourly_min: Optional[float] = None
    hourly_max: Optional[float] = None
    annualized_min: Optional[float] = None
    annualized_max: Optional[float] = None
    expected_hours_per_week: float = 40.0
    expected_hours_per_week_is_assumed: bool = True
    contract_value_min: Optional[float] = None
    contract_value_max: Optional[float] = None
    contract_value_is_estimated: bool = True
    contract_value_display: Optional[str] = None


SCREENING_CATEGORIES: List[str] = [
    "General",
    "Technical",
    "Salary",
    "Experience",
    "Culture",
    "Questions for Company"
]


APPLICATION_CATEGORIES: Dict[str, str] = {
    "Target": "Strong fit and genuinely desirable. This is the type of role your search is primarily designed to produce.",
    "Stretch": "Desirable, but you have a meaningful experience, seniority, domain, or tooling gap.",
    "Opportunistic": "Not part of the normal search profile, but something about the role makes it a compelling fit. This is particularly useful for the unexpected-title searches you're doing.",
    "Practice": "Plausible enough to apply to, but primarily useful for gaining application/interview reps or testing positioning.",
    "Fallback": "Acceptable and worth taking under the right circumstances, but below your preferred role/compensation/trajectory.",
}

CATEGORY_ICONS: Dict[str, str] = {
    "Target": "🎯",
    "Stretch": "🚀",
    "Opportunistic": "💡",
    "Practice": "🥊",
    "Fallback": "🛡️",
    "Unassigned": "⚪"
}

APPLICATION_STAGES: List[str] = [
    "Pending", "Processed", "Applied", "Application Rejected",
    "Recruiter Screen", "Hiring Manager",
    "Technical Screen", "Final Round", "Offer",
    "Archived / Rejected"
]

DEFAULT_APPLICATION_SOURCES: List[str] = [
    "LinkedIn",
    "Indeed",
    "ZipRecruiter",
    "Company Website"
]

DEFAULT_PRIORITIES: List[str] = [
    "High",
    "Medium",
    "Low"
]

PRIORITY_ICONS: Dict[str, str] = {
    "High": "🔥",
    "Medium": "⚡",
    "Low": "🌱",
    "Critical": "🚨",
    "Urgent": "⚡",
    "Normal": "🔹"
}

SOURCE_ICONS: Dict[str, str] = {
    "LinkedIn": "🔗",
    "Indeed": "🔎",
    "ZipRecruiter": "💼",
    "Company Website": "🌐"
}


SCREENING_ARCHETYPES: Dict[str, str] = {
    "COMPENSATION": "Compensation & Salary",
    "WORK_AUTHORIZATION": "Work Authorization & Sponsorship",
    "TECHNICAL_STACK": "Technical Stack & Tools",
    "EXPERIENCE_DOMAIN": "Domain & Functional Experience",
    "BEHAVIORAL_MOTIVATION": "Motivation & Culture Fit",
    "REMOTE_LOCATION": "Location, Remote & Travel",
    "LEADERSHIP_CONFLICT": "Leadership & Stakeholder Conflict",
    "PROCESS_GOVERNANCE": "Process & Governance",
    "QUESTIONS_FOR_COMPANY": "Questions for the Company",
    "GENERAL": "General Inquiries"
}


class ScreeningQA(BaseModel):
    qa_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    question: str
    answer: str
    category: Optional[str] = None  # Salary, Technical, Experience, Culture, General, Questions for Company
    archetype: Optional[str] = None
    competency_signals: List[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    @field_validator("answer", mode="before")
    @classmethod
    def coerce_answer(cls, v: Any) -> str:
        from job_pipeline.domain.services import normalize_screening_answer
        return normalize_screening_answer(v)



class ScreeningMatchResult(BaseModel):
    query: str
    matched_question: str
    matched_answer: str
    similarity_score: float
    archetype: str = "GENERAL"
    company_name: Optional[str] = None
    created_at: Optional[str] = None
    competency_signals: List[str] = Field(default_factory=list)


class StoryBreadcrumb(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    label: str
    content: str
    kind: str = "milestone"  # "context", "milestone", "pivot", "metric", "learning"


class CanonicalStory(BaseModel):
    story_id: str
    story_number: int
    title: str
    archetype_tags: List[str] = Field(default_factory=list)
    competencies: List[str] = Field(default_factory=list)
    industries: List[str] = Field(default_factory=list)
    is_locked: bool = False
    is_canonical: bool = True
    hook: str
    problem: str
    turning_point: str
    result: str
    learning: str
    breadcrumbs: List[StoryBreadcrumb] = Field(default_factory=list)
    trigger_keywords: List[str] = Field(default_factory=list)
    target_question_types: List[str] = Field(default_factory=list)
    transitions: Dict[str, str] = Field(default_factory=dict)


class StoryCueCard(BaseModel):
    story_id: str
    story_number: int
    title: str
    keywords: List[str] = Field(default_factory=list)
    turning_point: str
    result: str
    target_question_types: List[str] = Field(default_factory=list)
    recommended_angle: str = "Core Impact"
    relevance_reason: str = ""
    active_breadcrumbs: List[StoryBreadcrumb] = Field(default_factory=list)



class FitEvaluation(BaseModel):
    status: str = Field(
        ...,
        description="PASS, FLAGGED_DEALBREAKER, FLAGGED_SKILL_MISMATCH, FLAGGED_LOW_PAY, FLAGGED_DUPLICATE, FLAGGED_COMPANY_VELOCITY"
    )
    is_qualified: bool = True
    dealbreakers_found: List[str] = Field(default_factory=list)
    matching_skills: List[str] = Field(default_factory=list)
    fit_score: float = 0.0
    pay_bounds: TargetPayBounds = Field(default_factory=TargetPayBounds)
    warnings: List[str] = Field(default_factory=list)
    reasoning: str = ""
    telemetry_findings: List[TelemetryFinding] = Field(default_factory=list)
    telemetry_status: str = "green"  # "green", "yellow", "red"
    telemetry_flags: List[str] = Field(default_factory=list)
    telemetry_warnings: List[str] = Field(default_factory=list)
    telemetry_benefits: List[Union[TelemetryFinding, str]] = Field(default_factory=list)
    duplicate_detected: bool = False
    is_repost: bool = False
    prior_application_date: Optional[str] = None
    company_velocity_exceeded: bool = False
    active_company_applications_count: int = 0
    active_company_applications: List[Dict[str, Any]] = Field(default_factory=list)


class JobPosting(BaseModel):
    opportunity_id: str
    company_name: str
    job_title: str
    title_family: str
    raw_description: str
    source_url: Optional[str] = None
    date_created: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    status: str = "Pending"
    category: Optional[str] = None
    applied_via: Optional[str] = None
    priority: Optional[str] = None
    employment_arrangement: Optional[str] = None  # "Employee", "Contract", or None
    worker_classification: Optional[str] = None  # "W2", "1099", "C2C", or None
    pay_basis: Optional[str] = "Annual"  # "Annual", "Hourly", or None
    expected_hours_per_week: Optional[float] = 40.0
    expected_hours_per_week_is_assumed: bool = True
    contract_length_months: Optional[float] = None
    contract_length_weeks: Optional[float] = None
    contract_length_raw: Optional[str] = None
    contract_value_min: Optional[float] = None
    contract_value_max: Optional[float] = None
    contract_value_display: Optional[str] = None
    extension_possible: Optional[bool] = None  # True, False, None
    fte_conversion_possible: Optional[bool] = None  # True, False, None
    staffing_agency: Optional[str] = None
    client_company: Optional[str] = None
    benefits_offered: Optional[bool] = None
    guaranteed_hours: Optional[bool] = None
    stage_history: List[Dict[str, str]] = Field(default_factory=list)
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    fit_evaluation: Optional[FitEvaluation] = None
    selected_resume_name: Optional[str] = None
    drive_folder_link: Optional[str] = None
    drive_jd_link: Optional[str] = None
    drive_screening_doc_link: Optional[str] = None
    screening_qa: List[ScreeningQA] = Field(default_factory=list)
    telemetry_warnings: List[str] = Field(default_factory=list)
    telemetry_flags: List[str] = Field(default_factory=list)
    telemetry_findings: List[Dict[str, Any]] = Field(default_factory=list)
    telemetry_benefits: List[Union[Dict[str, Any], str]] = Field(default_factory=list)
    row_index: Optional[int] = None
    tokens_used: int = 0


class CandidateProfile(BaseModel):
    candidate_name: str = "GTM Professional"
    resumes_folder_id: str = ""
    dealbreaker_skills: List[str] = Field(default_factory=lambda: ["Epic", "HL7", "Cerner", "Meditech"])
    core_strengths: List[str] = Field(default_factory=lambda: [
        "Salesforce", "dbt", "HubSpot", "SQL", "Python", "Tableau", "RevOps", "GTM Engineering"
    ])
    minimum_compensation_floor: float = 90000
    target_pay_percentiles: List[float] = Field(default_factory=lambda: [0.60, 0.80])
    max_company_applications_limit: int = 2
    company_application_window_days: int = 60
    repost_detection_threshold_days: int = 60


class StakeholderContact(BaseModel):
    contact_id: str
    name: str
    company_name: str
    role_type: str = "Recruiter"  # Recruiter, Hiring Manager, Peer, VP
    email: Optional[str] = None
    phone_number: Optional[str] = None
    linkedin_url: Optional[str] = None
    notes: Optional[str] = None


class Company(BaseModel):
    company_name: str
    domain: Optional[str] = None
    industry: Optional[str] = None
    active_opportunities: List[str] = Field(default_factory=list)
    contacts: List[StakeholderContact] = Field(default_factory=list)


class Touchpoint(BaseModel):
    touchpoint_id: str
    opportunity_id: str
    channel: str  # SMS, Call, Email, Recruiter Screen, Interview
    direction: str = "Inbound"  # Inbound, Outbound
    summary: str
    full_text_or_transcript: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class RoleIntelligenceReport(BaseModel):
    document_title: str
    company: str
    job_title: str
    output_docx_path: str
    drive_file_id: Optional[str] = None
    manifest_path: Optional[str] = None


class QuickLink(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str
    url: str
    category: str = "Profile"  # Profile, Portfolio, Calendar, Other
    icon: str = "🔗"
