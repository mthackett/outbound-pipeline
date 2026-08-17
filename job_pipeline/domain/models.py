from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class TargetPayBounds(BaseModel):
    posted_min: Optional[float] = None
    posted_max: Optional[float] = None
    target_min: Optional[float] = None
    target_max: Optional[float] = None
    currency: str = "USD"
    display_range: str = "Not specified"


class FitEvaluation(BaseModel):
    status: str = Field(
        ...,
        description="PASS, FLAGGED_DEALBREAKER, FLAGGED_SKILL_MISMATCH, FLAGGED_LOW_PAY, FLAGGED_DUPLICATE"
    )
    is_qualified: bool = True
    dealbreakers_found: List[str] = Field(default_factory=list)
    matching_skills: List[str] = Field(default_factory=list)
    fit_score: float = 0.0
    pay_bounds: TargetPayBounds = Field(default_factory=TargetPayBounds)
    warnings: List[str] = Field(default_factory=list)
    reasoning: str = ""


class JobPosting(BaseModel):
    opportunity_id: str
    company_name: str
    job_title: str
    title_family: str
    raw_description: str
    source_url: Optional[str] = None
    date_created: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    status: str = "Pending"
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    fit_evaluation: Optional[FitEvaluation] = None
    selected_resume_name: Optional[str] = None
    drive_folder_link: Optional[str] = None
    drive_jd_link: Optional[str] = None
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
