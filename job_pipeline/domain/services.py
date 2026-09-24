import json
import os
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Optional, Dict, Any
from job_pipeline.domain.models import (
    TargetPayBounds, FitEvaluation, CandidateProfile, ScreeningQA, QuickLink,
    ScreeningMatchResult
)
from job_pipeline.domain.screening_intelligence import ScreeningIntelligenceService
from job_pipeline.domain.story_bank import StoryBankService



class PayCalculatorService:
    """Pure domain service for calculating 60%-80% target pay range."""

    @staticmethod
    def calculate_target_pay(
        salary_min: Optional[float],
        salary_max: Optional[float],
        percentiles: List[float] = [0.60, 0.80]
    ) -> TargetPayBounds:
        if salary_min is None and salary_max is None:
            return TargetPayBounds(display_range="Undisclosed / Set per role")

        if salary_min is not None and salary_max is None:
            return TargetPayBounds(
                posted_min=salary_min,
                target_min=salary_min,
                display_range=f"${salary_min:,.0f}+"
            )

        if salary_min is None and salary_max is not None:
            return TargetPayBounds(
                posted_max=salary_max,
                target_max=salary_max,
                display_range=f"Up to ${salary_max:,.0f}"
            )

        if salary_max < salary_min:
            salary_min, salary_max = salary_max, salary_min

        spread = salary_max - salary_min
        t_min = round(salary_min + (percentiles[0] * spread))
        t_max = round(salary_min + (percentiles[1] * spread))

        display_str = f"${salary_min:,.0f} - ${salary_max:,.0f} (Target: ${t_min:,.0f} - ${t_max:,.0f})"

        return TargetPayBounds(
            posted_min=salary_min,
            posted_max=salary_max,
            target_min=t_min,
            target_max=t_max,
            display_range=display_str
        )


class ApplicationGuardrailService:
    """Domain service for detecting duplicate job applications and enforcing company application velocity limits."""

    @staticmethod
    def normalize_string(text: str) -> str:
        if not text:
            return ""
        # Lowercase and strip non-alphanumeric except spaces
        cleaned = re.sub(r'[^a-zA-Z0-9\s]', ' ', text.lower())
        return ' '.join(cleaned.split())

    @staticmethod
    def calculate_similarity(s1: str, s2: str) -> float:
        norm1 = ApplicationGuardrailService.normalize_string(s1)
        norm2 = ApplicationGuardrailService.normalize_string(s2)
        if not norm1 or not norm2:
            return 0.0
        if norm1 == norm2:
            return 1.0
        return SequenceMatcher(None, norm1, norm2).ratio()

    @staticmethod
    def parse_date(date_str: Any) -> Optional[datetime]:
        if not date_str:
            return None
        date_str = str(date_str).strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(date_str[:19], fmt)
            except ValueError:
                continue
        return None

    @classmethod
    def check_duplicate(
        cls,
        company_name: str,
        job_title: str,
        existing_records: List[Dict[str, Any]],
        repost_threshold_days: int = 60
    ) -> Dict[str, Any]:
        """
        Checks if the job has been applied to before.
        Returns:
            {
                "is_duplicate": bool,
                "is_repost": bool,
                "prior_date": Optional[str],
                "prior_status": Optional[str],
                "days_elapsed": Optional[int],
                "matched_record": Optional[Dict[str, Any]],
                "warning": Optional[str]
            }
        """
        norm_company = cls.normalize_string(company_name)
        norm_title = cls.normalize_string(job_title)
        today = datetime.now()

        for rec in existing_records:
            rec_company = cls.normalize_string(rec.get("Company Name") or rec.get("company", ""))
            rec_title = cls.normalize_string(rec.get("Job Title") or rec.get("title", ""))

            # Company must match closely (or exact normalized)
            comp_sim = cls.calculate_similarity(norm_company, rec_company)
            if comp_sim < 0.80 and norm_company not in rec_company and rec_company not in norm_company:
                continue

            title_sim = cls.calculate_similarity(norm_title, rec_title)
            # High title match or exact match
            if title_sim >= 0.80 or norm_title == rec_title:
                raw_date = rec.get("Date Created") or rec.get("date_created") or rec.get("Created At")
                parsed_dt = cls.parse_date(raw_date)
                days_elapsed = (today - parsed_dt).days if parsed_dt else None
                status = str(rec.get("Status") or rec.get("status") or "Processed")

                is_repost = bool(days_elapsed is not None and days_elapsed >= repost_threshold_days)
                if is_repost:
                    warning = (
                        f"Potential Repost / Reopened Requisition: You previously applied to '{rec.get('Job Title', job_title)}' "
                        f"at {company_name} {days_elapsed} days ago ({raw_date}). Status: {status}."
                    )
                else:
                    days_str = f"{days_elapsed} days ago" if days_elapsed is not None else "previously"
                    warning = (
                        f"Duplicate Application Detected: You already applied to '{rec.get('Job Title', job_title)}' "
                        f"at {company_name} {days_str} ({raw_date}). Current Status: {status}."
                    )

                return {
                    "is_duplicate": True,
                    "is_repost": is_repost,
                    "prior_date": str(raw_date),
                    "prior_status": status,
                    "days_elapsed": days_elapsed,
                    "matched_record": rec,
                    "warning": warning
                }

        return {
            "is_duplicate": False,
            "is_repost": False,
            "prior_date": None,
            "prior_status": None,
            "days_elapsed": None,
            "matched_record": None,
            "warning": None
        }

    @classmethod
    def check_company_velocity(
        cls,
        company_name: str,
        existing_records: List[Dict[str, Any]],
        max_limit: int = 2,
        window_days: int = 60
    ) -> Dict[str, Any]:
        """
        Enforces company application concurrency cap (e.g. max 2 active/recent applications in 60 days).
        """
        norm_company = cls.normalize_string(company_name)
        today = datetime.now()
        active_apps = []

        for rec in existing_records:
            rec_company = cls.normalize_string(rec.get("Company Name") or rec.get("company", ""))
            comp_sim = cls.calculate_similarity(norm_company, rec_company)
            if comp_sim >= 0.80 or norm_company in rec_company or rec_company in norm_company:
                raw_date = rec.get("Date Created") or rec.get("date_created") or rec.get("Created At")
                parsed_dt = cls.parse_date(raw_date)
                days_elapsed = (today - parsed_dt).days if parsed_dt else 0

                # Count applications within the rolling window
                if days_elapsed <= window_days:
                    title = rec.get("Job Title") or rec.get("title") or "Unknown Title"
                    status = str(rec.get("Status") or rec.get("status") or "Processed")
                    active_apps.append({
                        "company": rec.get("Company Name", company_name),
                        "title": title,
                        "date": str(raw_date),
                        "status": status,
                        "days_ago": days_elapsed
                    })

        exceeded = len(active_apps) >= max_limit
        warning = None
        if exceeded:
            warning = (
                f"Company Application Cap Warning: You currently have {len(active_apps)} recent application(s) "
                f"at {company_name} in the past {window_days} days (Limit: {max_limit})."
            )

        return {
            "velocity_exceeded": exceeded,
            "active_count": len(active_apps),
            "max_limit": max_limit,
            "window_days": window_days,
            "active_applications": active_apps,
            "warning": warning
        }


class ScreeningQAService:
    """Service for formatting, serializing, and structuring Application Screening Questions & Answers."""

    @staticmethod
    def format_screening_gdoc_text(
        company_name: str,
        job_title: str,
        qa_items: List[ScreeningQA],
        opportunity_id: Optional[str] = None
    ) -> str:
        """Formats screening questions and answers into a professional Google Doc text payload."""
        lines = []
        lines.append("=" * 70)
        lines.append(f"APPLICATION SCREENING QUESTIONS & ANSWERS")
        lines.append(f"Company:        {company_name}")
        lines.append(f"Role:           {job_title}")
        lines.append(f"Recorded Date:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if opportunity_id:
            lines.append(f"Opportunity ID: {opportunity_id}")
        lines.append("=" * 70)
        lines.append("")

        if not qa_items:
            lines.append("No screening questions were recorded for this application.")
            return "\n".join(lines)

        lines.append(f"Total Screening Questions Answered: {len(qa_items)}")
        lines.append("")

        for idx, item in enumerate(qa_items, start=1):
            category_tag = f" [{item.category}]" if item.category else ""
            lines.append(f"QUESTION {idx}{category_tag}:")
            lines.append(f"{item.question.strip()}")
            lines.append("")
            lines.append("YOUR SUBMITTED ANSWER:")
            lines.append(f"{item.answer.strip()}")
            lines.append("-" * 70)
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def format_qa_clipboard_summary(qa_items: List[ScreeningQA]) -> str:
        """Compact format for quick 1-click clipboard copying into ATS application portals."""
        if not qa_items:
            return ""
        blocks = []
        for idx, item in enumerate(qa_items, start=1):
            blocks.append(f"Q{idx}: {item.question}\nA{idx}: {item.answer}")
        return "\n\n".join(blocks)


class JobQualificationService:
    """Pure domain service for evaluating job fit, dealbreakers, skill scores, and application guardrails."""

    @staticmethod
    def evaluate(
        company_name: str,
        job_title: str,
        raw_description: str,
        required_skills: List[str] = [],
        preferred_skills: List[str] = [],
        salary_min: Optional[float] = None,
        salary_max: Optional[float] = None,
        profile: Optional[CandidateProfile] = None,
        existing_company_titles: Optional[List[Dict[str, Any]]] = None
    ) -> FitEvaluation:
        if profile is None:
            profile = CandidateProfile()

        warnings = []
        dealbreakers_found = []
        duplicate_detected = False
        is_repost = False
        prior_date = None
        velocity_exceeded = False
        active_company_apps = []

        # 1. Guardrail Checks: Duplicate & Repost Detection
        if existing_company_titles:
            dup_res = ApplicationGuardrailService.check_duplicate(
                company_name=company_name,
                job_title=job_title,
                existing_records=existing_company_titles,
                repost_threshold_days=profile.repost_detection_threshold_days
            )
            duplicate_detected = dup_res["is_duplicate"]
            is_repost = dup_res["is_repost"]
            prior_date = dup_res["prior_date"]
            if dup_res["warning"]:
                warnings.append(dup_res["warning"])

            # Guardrail Checks: Company Application Velocity
            vel_res = ApplicationGuardrailService.check_company_velocity(
                company_name=company_name,
                existing_records=existing_company_titles,
                max_limit=profile.max_company_applications_limit,
                window_days=profile.company_application_window_days
            )
            velocity_exceeded = vel_res["velocity_exceeded"]
            active_company_apps = vel_res["active_applications"]
            if vel_res["warning"]:
                warnings.append(vel_res["warning"])

        # 2. Dealbreaker Check
        combined_text = f"{job_title} {raw_description} {' '.join(required_skills)} {' '.join(preferred_skills)}"
        for db in profile.dealbreaker_skills:
            if re.search(r'\b' + re.escape(db) + r'\b', combined_text, re.IGNORECASE):
                dealbreakers_found.append(db)

        if dealbreakers_found:
            warnings.append(f"Contains dealbreaker skills: {', '.join(dealbreakers_found)}")

        # 3. Skill Overlap Calculation
        matching_skills = []
        combined_skills_lower = [s.lower() for s in required_skills + preferred_skills]
        text_lower = combined_text.lower()

        for strength in profile.core_strengths:
            str_lower = strength.lower()
            if str_lower in combined_skills_lower or re.search(r'\b' + re.escape(str_lower) + r'\b', text_lower):
                matching_skills.append(strength)

        total_strengths = len(profile.core_strengths) if profile.core_strengths else 1
        fit_score = round(min(len(matching_skills) / max(total_strengths * 0.4, 1.0), 1.0), 2)

        # 4. Target Pay Bounds
        pay_bounds = PayCalculatorService.calculate_target_pay(
            salary_min, salary_max, profile.target_pay_percentiles
        )
        if salary_max is not None and salary_max < profile.minimum_compensation_floor:
            warnings.append(f"Max salary (${salary_max:,.0f}) is below minimum floor (${profile.minimum_compensation_floor:,.0f}).")

        # 5. Determine Final Status & Reasoning
        if duplicate_detected and not is_repost:
            status = "FLAGGED_DUPLICATE"
            is_qualified = False
            reasoning = f"Flagged Duplicate: Application submitted previously on {prior_date}."
        elif velocity_exceeded:
            status = "FLAGGED_COMPANY_VELOCITY"
            is_qualified = False
            reasoning = f"Flagged Company Velocity: {len(active_company_apps)} applications already submitted to {company_name} within {profile.company_application_window_days} days."
        elif dealbreakers_found:
            status = "FLAGGED_DEALBREAKER"
            is_qualified = False
            reasoning = f"Flagged Dealbreaker: Contains dealbreaker skills ({', '.join(dealbreakers_found)})."
        elif warnings and any("below minimum floor" in w for w in warnings):
            status = "FLAGGED_LOW_PAY"
            is_qualified = False
            reasoning = f"Flagged Low Pay: Salary below candidate floor (${profile.minimum_compensation_floor:,.0f})."
        elif fit_score < 0.2:
            status = "FLAGGED_SKILL_MISMATCH"
            is_qualified = True
            reasoning = "Warning: Low skill overlap detected with candidate core strengths."
        else:
            status = "PASS"
            is_qualified = True
            reasoning = f"Passed fit evaluation. Skill score: {int(fit_score * 100)}% ({len(matching_skills)} matching core strengths)."

        return FitEvaluation(
            status=status,
            is_qualified=is_qualified,
            dealbreakers_found=dealbreakers_found,
            matching_skills=matching_skills,
            fit_score=fit_score,
            pay_bounds=pay_bounds,
            warnings=warnings,
            reasoning=reasoning,
            duplicate_detected=duplicate_detected,
            is_repost=is_repost,
            prior_application_date=prior_date,
            company_velocity_exceeded=velocity_exceeded,
            active_company_applications_count=len(active_company_apps),
            active_company_applications=active_company_apps
        )


class QuickLinksService:
    """Domain service for managing, persisting, and formatting candidate application quicklinks."""

    DEFAULT_CONFIG_PATH = "quicklinks.json"

    @classmethod
    def get_default_quicklinks(cls) -> List[QuickLink]:
        """Provides default common links required on job applications."""
        return [
            QuickLink(
                id="link-linkedin",
                title="LinkedIn Profile",
                url="https://linkedin.com/in/your-profile",
                category="Profile",
                icon="💼"
            ),
            QuickLink(
                id="link-github",
                title="GitHub Portfolio",
                url="https://github.com/your-username",
                category="Portfolio",
                icon="💻"
            ),
            QuickLink(
                id="link-website",
                title="Personal Website",
                url="https://your-portfolio.com",
                category="Portfolio",
                icon="🌐"
            ),
            QuickLink(
                id="link-calendly",
                title="Scheduling / Calendly",
                url="https://calendly.com/your-calendar",
                category="Calendar",
                icon="📅"
            ),
        ]

    @classmethod
    def load_quicklinks(cls, filepath: Optional[str] = None) -> List[QuickLink]:
        """Loads quicklinks from a JSON file, or falls back to defaults if not found or corrupted."""
        path = Path(filepath or os.environ.get("QUICKLINKS_CONFIG_PATH", cls.DEFAULT_CONFIG_PATH))
        if not path.exists():
            defaults = cls.get_default_quicklinks()
            cls.save_quicklinks(defaults, str(path))
            return defaults

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                links = [QuickLink(**item) for item in data]
                return links if links else cls.get_default_quicklinks()
            return cls.get_default_quicklinks()
        except Exception:
            return cls.get_default_quicklinks()

    @classmethod
    def save_quicklinks(cls, links: List[QuickLink], filepath: Optional[str] = None) -> bool:
        """Saves quicklinks list to a JSON file."""
        path = Path(filepath or os.environ.get("QUICKLINKS_CONFIG_PATH", cls.DEFAULT_CONFIG_PATH))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = [link.model_dump() for link in links]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception:
            return False

    @classmethod
    def format_clipboard_bundle(cls, links: List[QuickLink]) -> str:
        """Formats all links into a clean plain-text block for fast copying into applications/emails."""
        lines = []
        for l in links:
            lines.append(f"{l.title}: {l.url}")
        return "\n".join(lines)

