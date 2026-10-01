import json
import os
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Optional, Dict, Any, Union, Tuple
from job_pipeline.domain.models import (
    TargetPayBounds, FitEvaluation, CandidateProfile, ScreeningQA, QuickLink,
    ScreeningMatchResult, DEFAULT_APPLICATION_SOURCES, DEFAULT_PRIORITIES,
    DEFAULT_TELEMETRY_WARNING_RULES, DEFAULT_TELEMETRY_RULES,
    TelemetryWarningRule, TelemetryRule, TelemetryFinding
)
from job_pipeline.domain.screening_intelligence import ScreeningIntelligenceService
from job_pipeline.domain.story_bank import StoryBankService
from job_pipeline.domain.telemetry_service import TelemetryService




class PayCalculatorService:
    """Pure domain service for calculating pay bounds for annual and hourly roles."""

    @staticmethod
    def calculate_target_pay(
        salary_min: Optional[float],
        salary_max: Optional[float],
        percentiles: List[float] = [0.60, 0.80],
        pay_basis: Optional[str] = "Annual",
        expected_hours_per_week: Optional[float] = None,
        expected_hours_per_week_is_assumed: Optional[bool] = None,
        contract_length_months: Optional[float] = None,
        contract_length_weeks: Optional[float] = None
    ) -> TargetPayBounds:
        norm_basis = (pay_basis or "Annual").strip().capitalize()
        if norm_basis not in ["Annual", "Hourly"]:
            norm_basis = "Annual"

        # Handle Hourly roles
        if norm_basis == "Hourly":
            hours = expected_hours_per_week if (expected_hours_per_week and expected_hours_per_week > 0) else 40.0
            is_assumed = True if expected_hours_per_week is None else (
                expected_hours_per_week_is_assumed if expected_hours_per_week_is_assumed is not None else False
            )

            if salary_min is None and salary_max is None:
                return TargetPayBounds(
                    pay_basis="Hourly",
                    expected_hours_per_week=hours,
                    expected_hours_per_week_is_assumed=is_assumed,
                    display_range="Hourly (Rate undisclosed)"
                )

            if salary_min is not None and salary_max is not None and salary_max < salary_min:
                salary_min, salary_max = salary_max, salary_min

            ann_min = round(salary_min * hours * 52) if salary_min is not None else None
            ann_max = round(salary_max * hours * 52) if salary_max is not None else None

            # Calculate contract duration in weeks
            c_weeks = None
            if contract_length_weeks is not None and contract_length_weeks > 0:
                c_weeks = float(contract_length_weeks)
            elif contract_length_months is not None and contract_length_months > 0:
                c_weeks = float(contract_length_months) * (50.0 / 12.0)

            c_val_min = round(salary_min * hours * c_weeks) if (salary_min is not None and c_weeks is not None) else None
            c_val_max = round(salary_max * hours * c_weeks) if (salary_max is not None and c_weeks is not None) else None

            c_val_disp = None
            if c_val_min is not None and c_val_max is not None:
                if c_val_min == c_val_max:
                    c_val_disp = f"Estimated contract value: ~${c_val_min:,.0f}"
                else:
                    c_val_disp = f"Estimated contract value: ~${c_val_min:,.0f} - ${c_val_max:,.0f}"
            elif c_val_min is not None:
                c_val_disp = f"Estimated contract value: ~${c_val_min:,.0f}+"
            elif c_val_max is not None:
                c_val_disp = f"Estimated contract value: ~Up to ${c_val_max:,.0f}"

            if salary_min is not None and salary_max is not None:
                disp_str = f"${salary_min:,.0f} - ${salary_max:,.0f}/hr (~${ann_min:,.0f} - ${ann_max:,.0f} annualized)"
            elif salary_min is not None:
                disp_str = f"${salary_min:,.0f}+/hr (~${ann_min:,.0f}+ annualized)"
            else:
                disp_str = f"Up to ${salary_max:,.0f}/hr (~Up to ${ann_max:,.0f} annualized)"

            return TargetPayBounds(
                posted_min=ann_min,
                posted_max=ann_max,
                target_min=ann_min,
                target_max=ann_max,
                currency="USD",
                display_range=disp_str,
                pay_basis="Hourly",
                hourly_min=salary_min,
                hourly_max=salary_max,
                annualized_min=ann_min,
                annualized_max=ann_max,
                expected_hours_per_week=hours,
                expected_hours_per_week_is_assumed=is_assumed,
                contract_value_min=c_val_min,
                contract_value_max=c_val_max,
                contract_value_is_estimated=True,
                contract_value_display=c_val_disp
            )

        # Standard Annual role
        if salary_min is None and salary_max is None:
            return TargetPayBounds(
                pay_basis="Annual",
                display_range="Undisclosed / Set per role"
            )

        if salary_min is not None and salary_max is None:
            return TargetPayBounds(
                posted_min=salary_min,
                target_min=salary_min,
                annualized_min=salary_min,
                annualized_max=None,
                pay_basis="Annual",
                display_range=f"${salary_min:,.0f}+"
            )

        if salary_min is None and salary_max is not None:
            return TargetPayBounds(
                posted_max=salary_max,
                target_max=salary_max,
                annualized_min=None,
                annualized_max=salary_max,
                pay_basis="Annual",
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
            annualized_min=salary_min,
            annualized_max=salary_max,
            pay_basis="Annual",
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


def normalize_screening_answer(val: Any) -> str:
    """Safely normalizes user-entered screening answers into valid strings.
    
    Handles primitive values (int, float, bool) and gracefully normalizes None to empty string
    to prevent persisting the literal string 'None'.
    """
    if val is None:
        return ""
    if isinstance(val, bool):
        return "True" if val else "False"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        return val
    return str(val)


class ScreeningQAService:
    """Service for formatting, serializing, and structuring Application Screening Questions & Answers."""

    @staticmethod
    def normalize_answer(val: Any) -> str:
        return normalize_screening_answer(val)

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
        existing_company_titles: Optional[List[Dict[str, Any]]] = None,
        pay_basis: Optional[str] = "Annual",
        expected_hours_per_week: Optional[float] = None,
        expected_hours_per_week_is_assumed: Optional[bool] = None,
        contract_length_months: Optional[float] = None,
        contract_length_weeks: Optional[float] = None,
        telemetry_warnings: Optional[List[str]] = None,
        telemetry_findings: Optional[List[Union[TelemetryFinding, Dict[str, Any]]]] = None,
        telemetry_benefits: Optional[List[Union[TelemetryFinding, Dict[str, Any]]]] = None
    ) -> FitEvaluation:
        if profile is None:
            profile = CandidateProfile()

        # Process and normalize structured telemetry findings
        resolved_findings: List[TelemetryFinding] = []
        if telemetry_findings:
            for item in telemetry_findings:
                if isinstance(item, TelemetryFinding):
                    resolved_findings.append(item)
                elif isinstance(item, dict):
                    resolved_findings.append(TelemetryFinding(**item))

        resolved_benefits: List[TelemetryFinding] = []
        if telemetry_benefits:
            for item in telemetry_benefits:
                if isinstance(item, TelemetryFinding):
                    resolved_benefits.append(item)
                elif isinstance(item, dict):
                    resolved_benefits.append(TelemetryFinding(**item))

        t_flags, t_warnings, t_benefits = TelemetryService.split_findings(resolved_findings)
        for b in t_benefits:
            if not any(rb.rule_id == b.rule_id for rb in resolved_benefits):
                resolved_benefits.append(b)

        # Build explainable telemetry warning strings
        telemetry_warning_strings = list(telemetry_warnings or [])
        for f in t_flags:
            display_str = f.to_display_string()
            if display_str not in telemetry_warning_strings:
                telemetry_warning_strings.append(display_str)
        for w in t_warnings:
            display_str = w.to_display_string()
            if display_str not in telemetry_warning_strings:
                telemetry_warning_strings.append(display_str)

        warnings = []
        if telemetry_warning_strings:
            for tw in telemetry_warning_strings:
                if tw and tw not in warnings:
                    warnings.append(tw)

        # Compute telemetry status (red / yellow / green)
        if t_flags or any(tw.startswith("FLAG:") or "[FLAG]" in tw.upper() for tw in telemetry_warning_strings):
            telemetry_status = "red"
            has_critical_telemetry_flag = True
        elif t_warnings or telemetry_warning_strings:
            telemetry_status = "yellow"
            has_critical_telemetry_flag = False
        else:
            telemetry_status = "green"
            has_critical_telemetry_flag = False


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
            salary_min=salary_min,
            salary_max=salary_max,
            percentiles=profile.target_pay_percentiles,
            pay_basis=pay_basis,
            expected_hours_per_week=expected_hours_per_week,
            expected_hours_per_week_is_assumed=expected_hours_per_week_is_assumed,
            contract_length_months=contract_length_months,
            contract_length_weeks=contract_length_weeks
        )
        comp_check_val = pay_bounds.annualized_max if pay_bounds.pay_basis == "Hourly" else salary_max
        if comp_check_val is not None and comp_check_val < profile.minimum_compensation_floor:
            warnings.append(f"Max compensation (${comp_check_val:,.0f} annualized) is below minimum floor (${profile.minimum_compensation_floor:,.0f}).")

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
        elif any("below minimum floor" in w for w in warnings):
            status = "FLAGGED_LOW_PAY"
            is_qualified = False
            reasoning = f"Flagged Low Pay: Salary below candidate floor (${profile.minimum_compensation_floor:,.0f})."
        elif has_critical_telemetry_flag:
            status = "FLAGGED_TELEMETRY"
            is_qualified = False
            reasoning = f"Flagged Telemetry: Critical warning condition triggered ({'; '.join(telemetry_warning_strings)})."
        elif fit_score < 0.2:
            status = "FLAGGED_SKILL_MISMATCH"
            is_qualified = True
            reasoning = "Warning: Low skill overlap detected with candidate core strengths."
        elif telemetry_warning_strings:
            status = "PASS"
            is_qualified = True
            reasoning = f"Passed with telemetry warning(s): {'; '.join(telemetry_warning_strings)}"
        else:
            status = "PASS"
            is_qualified = True
            reasoning = f"Passed fit evaluation. Skill score: {int(fit_score * 100)}% ({len(matching_skills)} matching core strengths)."

        # Append telemetry warnings to reasoning if other flags took priority, so every infraction is preserved
        if telemetry_warning_strings and not reasoning.startswith("Passed with telemetry warning") and not reasoning.startswith("Flagged Telemetry"):
            reasoning += f" | Telemetry Warnings: {'; '.join(telemetry_warning_strings)}"

        return FitEvaluation(
            status=status,
            is_qualified=is_qualified,
            dealbreakers_found=dealbreakers_found,
            matching_skills=matching_skills,
            fit_score=fit_score,
            pay_bounds=pay_bounds,
            warnings=warnings,
            reasoning=reasoning,
            telemetry_findings=resolved_findings,
            telemetry_status=telemetry_status,
            telemetry_benefits=resolved_benefits,
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


class PipelineConfigService:
    """Domain service for managing configurable application sources and priority levels."""

    DEFAULT_CONFIG_PATH = "pipeline_config.json"

    @classmethod
    def load_config(cls, filepath: Optional[str] = None) -> Dict[str, Any]:
        path = Path(filepath or os.environ.get("PIPELINE_CONFIG_PATH", cls.DEFAULT_CONFIG_PATH))
        defaults = {
            "enable_cli_logging": True,
            "sources": list(DEFAULT_APPLICATION_SOURCES),
            "priorities": list(DEFAULT_PRIORITIES),
            "telemetry_rules": [TelemetryService.normalize_rule_dict(r) for r in DEFAULT_TELEMETRY_RULES],
            "telemetry_warnings": [TelemetryService.normalize_rule_dict(r) for r in DEFAULT_TELEMETRY_RULES]
        }
        if not path.exists():
            example_path = Path(str(path) + ".example")
            if not example_path.exists() and str(path) == cls.DEFAULT_CONFIG_PATH:
                example_path = Path("pipeline_config.json.example")
            if example_path.exists():
                try:
                    with open(example_path, "r", encoding="utf-8") as f:
                        ex_data = json.load(f)
                    cls.save_config(ex_data, str(path))
                    return cls.load_config(str(path))
                except Exception:
                    pass
            cls.save_config(defaults, str(path))
            return defaults
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                sources = data.get("sources")
                priorities = data.get("priorities")
                enable_logging = data.get("enable_cli_logging", data.get("cli_logging", True))
                raw_rules = data.get("telemetry_rules", data.get("telemetry_warnings"))

                if isinstance(raw_rules, list):
                    normalized_rules = [TelemetryService.normalize_rule_dict(r) for r in raw_rules]
                else:
                    normalized_rules = [TelemetryService.normalize_rule_dict(r) for r in DEFAULT_TELEMETRY_RULES]

                res = {
                    "enable_cli_logging": bool(enable_logging),
                    "sources": sources if isinstance(sources, list) and sources else list(DEFAULT_APPLICATION_SOURCES),
                    "priorities": priorities if isinstance(priorities, list) and priorities else list(DEFAULT_PRIORITIES),
                    "telemetry_rules": normalized_rules,
                    "telemetry_warnings": normalized_rules
                }
                return res
            return defaults
        except Exception:
            return defaults

    @classmethod
    def is_cli_logging_enabled(cls, filepath: Optional[str] = None) -> bool:
        env_val = os.environ.get("ENABLE_CLI_LOGGING", os.environ.get("CLI_LOGGING"))
        if env_val is not None:
            return env_val.strip().lower() in ("1", "true", "yes", "on", "enabled")
        cfg = cls.load_config(filepath)
        return bool(cfg.get("enable_cli_logging", True))

    @classmethod
    def set_cli_logging(cls, enabled: bool, filepath: Optional[str] = None) -> bool:
        cfg = cls.load_config(filepath)
        cfg["enable_cli_logging"] = bool(enabled)
        return cls.save_config(cfg, filepath)

    @classmethod
    def save_config(cls, config: Dict[str, Any], filepath: Optional[str] = None) -> bool:
        path = Path(filepath or os.environ.get("PIPELINE_CONFIG_PATH", cls.DEFAULT_CONFIG_PATH))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            return True
        except Exception:
            return False

    @classmethod
    def add_source(cls, new_source: str, filepath: Optional[str] = None) -> List[str]:
        cfg = cls.load_config(filepath)
        s = new_source.strip()
        if s and s not in cfg["sources"]:
            cfg["sources"].append(s)
            cls.save_config(cfg, filepath)
        return cfg["sources"]

    @classmethod
    def remove_source(cls, source_to_remove: str, filepath: Optional[str] = None) -> List[str]:
        cfg = cls.load_config(filepath)
        if source_to_remove in cfg["sources"]:
            cfg["sources"].remove(source_to_remove)
            cls.save_config(cfg, filepath)
        return cfg["sources"]

    @classmethod
    def add_priority(cls, new_priority: str, filepath: Optional[str] = None) -> List[str]:
        cfg = cls.load_config(filepath)
        p = new_priority.strip()
        if p and p not in cfg["priorities"]:
            cfg["priorities"].append(p)
            cls.save_config(cfg, filepath)
        return cfg["priorities"]

    @classmethod
    def remove_priority(cls, priority_to_remove: str, filepath: Optional[str] = None) -> List[str]:
        cfg = cls.load_config(filepath)
        if priority_to_remove in cfg["priorities"]:
            cfg["priorities"].remove(priority_to_remove)
            cls.save_config(cfg, filepath)
        return cfg["priorities"]

    @classmethod
    def get_telemetry_rules(cls, filepath: Optional[str] = None) -> List[Dict[str, Any]]:
        cfg = cls.load_config(filepath)
        return cfg.get("telemetry_rules", cfg.get("telemetry_warnings", []))

    @classmethod
    def get_active_telemetry_rules(cls, filepath: Optional[str] = None) -> List[Dict[str, Any]]:
        rules = cls.get_telemetry_rules(filepath)
        return [r for r in rules if r.get("enabled", True)]

    @classmethod
    def add_telemetry_rule(cls, rule: Dict[str, Any], filepath: Optional[str] = None) -> List[Dict[str, Any]]:
        cfg = cls.load_config(filepath)
        norm_rule = TelemetryService.normalize_rule_dict(rule)
        rules = cfg.setdefault("telemetry_rules", [])
        rules.append(norm_rule)
        cfg["telemetry_warnings"] = list(rules)
        cls.save_config(cfg, filepath)
        return rules

    @classmethod
    def update_telemetry_rule(cls, rule_id: str, updated_fields: Dict[str, Any], filepath: Optional[str] = None) -> List[Dict[str, Any]]:
        cfg = cls.load_config(filepath)
        rules = cfg.setdefault("telemetry_rules", [])
        for r in rules:
            if r.get("id") == rule_id:
                r.update(updated_fields)
                norm = TelemetryService.normalize_rule_dict(r)
                r.clear()
                r.update(norm)
                break
        cfg["telemetry_warnings"] = list(rules)
        cls.save_config(cfg, filepath)
        return rules

    @classmethod
    def toggle_telemetry_rule(cls, rule_id: str, filepath: Optional[str] = None) -> List[Dict[str, Any]]:
        cfg = cls.load_config(filepath)
        rules = cfg.setdefault("telemetry_rules", [])
        for r in rules:
            if r.get("id") == rule_id:
                r["enabled"] = not r.get("enabled", True)
                break
        cfg["telemetry_warnings"] = list(rules)
        cls.save_config(cfg, filepath)
        return rules

    @classmethod
    def remove_telemetry_rule(cls, rule_id: str, filepath: Optional[str] = None) -> List[Dict[str, Any]]:
        cfg = cls.load_config(filepath)
        rules = cfg.get("telemetry_rules", cfg.get("telemetry_warnings", []))
        cfg["telemetry_rules"] = [r for r in rules if r.get("id") != rule_id]
        cfg["telemetry_warnings"] = cfg["telemetry_rules"]
        cls.save_config(cfg, filepath)
        return cfg["telemetry_rules"]

    @classmethod
    def reset_default_telemetry_rules(cls, filepath: Optional[str] = None) -> List[Dict[str, Any]]:
        cfg = cls.load_config(filepath)
        defaults = [TelemetryService.normalize_rule_dict(r) for r in DEFAULT_TELEMETRY_RULES]
        cfg["telemetry_rules"] = defaults
        cfg["telemetry_warnings"] = defaults
        cls.save_config(cfg, filepath)
        return defaults

    # Backward compatibility aliases
    get_warning_rules = get_telemetry_rules
    get_active_warning_rules = get_active_telemetry_rules
    add_warning_rule = add_telemetry_rule
    update_warning_rule = update_telemetry_rule
    toggle_warning_rule = toggle_telemetry_rule
    remove_warning_rule = remove_telemetry_rule
    reset_default_warning_rules = reset_default_telemetry_rules


class IngestionRecoveryService:
    """Service for managing incomplete workspace detection, job description preview extraction, and recovery."""

    @staticmethod
    def extract_jd_preview(raw_text: str, max_chars: int = 140) -> str:
        """
        Reads from raw job description, normalizes whitespace and newlines,
        and extracts roughly the first 100-150 meaningful characters, adding … when truncated.
        """
        if not raw_text:
            return ""
        text = raw_text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
        lines = [l.strip() for l in text.split("\n") if l.strip()]

        resp_idx = None
        for idx, line in enumerate(lines):
            if re.search(r'^(responsibilities|what you(\'ll| will) do|the role|about the role|role overview)\b', line.lower()):
                resp_idx = idx + 1
                break

        if resp_idx is not None and resp_idx < len(lines):
            chosen_lines = lines[resp_idx:resp_idx + 2]
        else:
            chosen_lines = []
            for line in lines:
                lower = line.lower()
                if any(re.search(pat, lower) for pat in [
                    r'^(apply|job details|full job description|pay|benefits|pulled from|here\'?s how)\b',
                    r'^\$?\d+[\d,]*(\.\d+)?\s*(-\s*\$?\d+[\d,]*(\.\d+)?)?\s*(a year|an hour|\/hr|\/yr)?$',
                    r'^\d+(\.\d+)?(\s*★|\s*stars)?$',
                    r'^(remote|hybrid|on-site|full-time|part-time|contract)$'
                ]):
                    continue
                if len(line) < 30 and not line.endswith(('.', '!', '?', ':')):
                    continue
                chosen_lines.append(line)
                if len(" ".join(chosen_lines)) > max_chars * 2:
                    break

        chosen_text = " ".join(chosen_lines) if chosen_lines else text
        cleaned = re.sub(r'\s*\([^)]*\)', '', chosen_text)
        normalized = re.sub(r'\s+', ' ', cleaned).strip()

        if len(normalized) <= max_chars:
            return normalized

        truncated = normalized[:max_chars]
        last_space = truncated.rfind(' ')
        if last_space > 80:
            truncated = truncated[:last_space]
        return truncated.rstrip(".,;:- ") + "…"

    @staticmethod
    def format_created_date(created_time: Any) -> str:
        """
        Formats created time as e.g. 'Sep 30, 2026'.
        """
        if not created_time:
            return datetime.now().strftime("%b %d, %Y")
        if isinstance(created_time, datetime):
            dt = created_time
        else:
            iso_str = str(created_time).strip()
            try:
                dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone()
            except Exception:
                try:
                    dt = datetime.strptime(iso_str[:10], "%Y-%m-%d")
                except Exception:
                    return str(created_time)[:12]
        return dt.strftime("%b %d, %Y")

    @staticmethod
    def parse_job_identity(raw_text: str, folder_name: str = "") -> Tuple[str, str]:
        """
        Infers company name and job title from raw JD text or folder name if not already stored.
        """
        if folder_name and "Target_Company_Target_Role" not in folder_name:
            parts = folder_name.split("_")
            if len(parts) >= 3 and re.match(r'^\d{4}-\d{2}-\d{2}$', parts[-1]):
                company = parts[0]
                title = " ".join(parts[1:-1])
                return company, title

        if raw_text:
            text = raw_text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            if len(lines) >= 2:
                line0, line1 = lines[0], lines[1]
                title_keywords = [
                    "analyst", "engineer", "manager", "lead", "specialist", "director", "developer", "architect", "consultant"
                ]
                if any(k in line0.lower() for k in title_keywords) and len(line1) < 40 and not any(k in line1.lower() for k in title_keywords):
                    return line1, line0
                if any(k in line1.lower() for k in title_keywords) and len(line0) < 40 and not any(k in line0.lower() for k in title_keywords):
                    return line0, line1

        return "Target Company", "Target Role"




