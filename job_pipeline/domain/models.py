import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
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

TELEMETRY_WARNING_CATEGORIES: List[str] = [
    "Scope",
    "Skills",
    "Experience",
    "Benefits",
    "Culture",
    "Compensation",
    "Other"
]

DEFAULT_TELEMETRY_WARNING_RULES: List[Dict[str, Any]] = [
    {
        "id": "warn-on-call",
        "name": "On-Call / Weekend Support Required",
        "category": "Scope",
        "keywords": ["on-call", "24/7", "pagerduty", "weekend coverage", "after-hours", "night shift"],
        "concept_description": "Role requires regular on-call rotation, 24/7 availability, off-hours incident response, or mandatory weekend work.",
        "severity": "Warning",
        "enabled": True
    },
    {
        "id": "warn-excessive-travel",
        "name": "Excessive Travel (>25%)",
        "category": "Scope",
        "keywords": ["travel 50%", "travel 75%", "frequent travel", "extensive travel", "road warrior"],
        "concept_description": "Role requires heavy or frequent travel (more than 25% travel commitment).",
        "severity": "Warning",
        "enabled": True
    },
    {
        "id": "warn-no-benefits",
        "name": "No Benefits / Commission Only",
        "category": "Benefits",
        "keywords": ["commission only", "no benefits", "unpaid", "equity only", "stipend only"],
        "concept_description": "Role does not offer standard benefits, is commission-only, equity-only, or unpaid.",
        "severity": "Warning",
        "enabled": True
    },
    {
        "id": "warn-legacy-stack",
        "name": "Outdated / Legacy Tech Stack",
        "category": "Skills",
        "keywords": ["COBOL", "Visual Basic", "VB6", "Fortran", "Lotus Notes", "Access database", "legacy monolithic"],
        "concept_description": "Role heavily relies on legacy, deprecated, or obsolete programming languages and architectures.",
        "severity": "Warning",
        "enabled": True
    },
    {
        "id": "warn-overbroad-scope",
        "name": "Overbroad Scope / Multi-Department Trap",
        "category": "Scope",
        "keywords": ["wear many hats", "handle IT and sales and marketing", "one-person department", "do-it-all"],
        "concept_description": "Job description expects a single person to handle IT helpdesk, office management, sales, and engineering simultaneously without dedicated team support.",
        "severity": "Warning",
        "enabled": True
    }
]


class TelemetryWarningRule(BaseModel):
    id: str = Field(default_factory=lambda: f"warn-{uuid.uuid4().hex[:6]}")
    name: str = Field(..., description="Short descriptive title for this warning criterion.")
    category: str = Field(default="Scope", description="Category: Scope, Skills, Experience, Benefits, Culture, Compensation, Other.")
    keywords: List[str] = Field(default_factory=list, description="Specific keywords or phrases that trigger this warning.")
    concept_description: str = Field(default="", description="Semantic concept or condition for the LLM to watch for.")
    severity: str = Field(default="Warning", description="'Warning' or 'Flag'.")
    enabled: bool = Field(default=True, description="Whether this warning rule is active.")


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

