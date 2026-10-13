import json
import os
import re
import uuid
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Optional, Dict, Any, Union, Tuple
from job_pipeline.domain.models import (
    TargetPayBounds, FitEvaluation, CandidateProfile, ScreeningQA, QuickLink,
    ScreeningMatchResult, DEFAULT_APPLICATION_SOURCES, DEFAULT_PRIORITIES,
    DEFAULT_TELEMETRY_WARNING_RULES, DEFAULT_TELEMETRY_RULES,
    TelemetryWarningRule, TelemetryRule, TelemetryFinding,
    PipelineInstanceConfig, INTERVIEW_STAGES, AUTHORITATIVE_PIPELINE_STAGES,
    ACTIVE_OPPORTUNITY_STAGES, POSITIVE_INTEREST_STAGES, KPI_INTERVIEW_STAGES, TERMINAL_STAGES, SUBMITTED_STAGES
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
        telemetry_benefits: Optional[List[Union[TelemetryFinding, Dict[str, Any], str]]] = None,
        telemetry_flags: Optional[List[str]] = None
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

        resolved_benefits: List[Union[TelemetryFinding, str]] = []
        if telemetry_benefits:
            for item in telemetry_benefits:
                if isinstance(item, TelemetryFinding):
                    resolved_benefits.append(item)
                elif isinstance(item, dict):
                    resolved_benefits.append(TelemetryFinding(**item))
                elif isinstance(item, str):
                    resolved_benefits.append(item)

        t_flags, t_warnings, t_benefits = TelemetryService.split_findings(resolved_findings)
        for b in t_benefits:
            if not any(getattr(rb, "rule_id", None) == b.rule_id for rb in resolved_benefits):
                resolved_benefits.append(b)

        # Build explainable telemetry warning strings
        telemetry_warning_strings = list(telemetry_flags or []) + list(telemetry_warnings or [])
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
        if telemetry_flags or t_flags or any(tw.startswith("FLAG:") or "[FLAG]" in tw.upper() for tw in telemetry_warning_strings):
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
            reasoning = f"Job Signals — Flags: {'; '.join(telemetry_warning_strings)}"
        elif fit_score < 0.2:
            status = "FLAGGED_SKILL_MISMATCH"
            is_qualified = True
            reasoning = "Warning: Low skill overlap detected with candidate core strengths."
        elif telemetry_warning_strings:
            status = "PASS"
            is_qualified = True
            reasoning = f"Job Signals — Warnings: {'; '.join(telemetry_warning_strings)}"
        else:
            status = "PASS"
            is_qualified = True
            reasoning = f"Passed fit evaluation. Skill score: {int(fit_score * 100)}% ({len(matching_skills)} matching core strengths)."

        # Append telemetry warnings to reasoning if other flags took priority, so every infraction is preserved
        if telemetry_warning_strings and not reasoning.startswith("Job Signals"):
            reasoning += f" | Job Signals: {'; '.join(telemetry_warning_strings)}"

        flag_strings, warning_strings, _ = TelemetryService.split_display_findings(
            telemetry_flags or [], telemetry_warning_strings, []
        )

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
            telemetry_flags=flag_strings,
            telemetry_warnings=warning_strings,
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
    DEFAULT_CATEGORIES: List[str] = ["Links", "Scheduling", "Contact / Info"]

    ICON_OPTIONS: List[Tuple[str, str]] = [
        ("", "🚫 (None / Text Only)"),
        # Links & Web
        ("🔗", "🔗 Generic Link"),
        ("🌐", "🌐 Globe / Web"),
        ("🌍", "🌍 World"),
        # Work & Dev
        ("💼", "💼 Briefcase / Work"),
        ("👔", "👔 Tie / Professional"),
        ("💻", "💻 Laptop / Dev"),
        ("🖥️", "🖥️ Desktop / Tech"),
        ("🧑‍💻", "🧑‍💻 Developer"),
        ("⌨️", "⌨️ Keyboard"),
        ("🎨", "🎨 Portfolio / Design"),
        ("📂", "📂 Projects Folder"),
        # Scheduling & Time
        ("📅", "📅 Calendar"),
        ("🗓️", "🗓️ Spiral Calendar"),
        ("⏰", "⏰ Clock"),
        ("⏱️", "⏱️ Stopwatch"),
        # Communication
        ("✉️", "✉️ Envelope / Email"),
        ("📧", "📧 Electronic Mail"),
        ("📨", "📨 Incoming Message"),
        ("📞", "📞 Telephone"),
        ("📱", "📱 Mobile Phone"),
        ("💬", "💬 Chat / Message"),
        ("🎥", "🎥 Video / Meeting"),
        # Personal & Contact
        ("👤", "👤 Person / User"),
        ("🧑", "🧑 Personal"),
        ("🪪", "🪪 ID Card"),
        ("🏷️", "🏷️ Name Tag"),
        ("📍", "📍 Map Pin / Location"),
        ("🏠", "🏠 Home Address"),
        ("🏢", "🏢 Office / Building"),
        ("🏙️", "🏙️ Cityscape"),
        ("🌆", "🌆 Skyline"),
        ("📮", "📮 Postal Box / Zip"),
        ("📬", "📬 Mailbox"),
        # Education & Credentials
        ("🎓", "🎓 Graduation Cap / College"),
        ("🏫", "🏫 School / University"),
        ("📚", "📚 Books / Academia"),
        # Documents & Highlights
        ("📄", "📄 Document / Resume"),
        ("📑", "📑 Bookmarks / Tabs"),
        ("📝", "📝 Memo / Note"),
        ("📋", "📋 Clipboard"),
        ("⭐", "⭐ Star / Highlight"),
        ("🚀", "🚀 Rocket / Startup"),
        ("💡", "💡 Idea / Innovation"),
        ("🏆", "🏆 Trophy / Award"),
        ("🔒", "🔒 Security / Credential"),
        ("💲", "💲 Salary / Pay"),
    ]

    @classmethod
    def get_default_quicklinks(cls) -> List[QuickLink]:
        """Provides default common links required on job applications."""
        return [
            QuickLink(
                id="link-linkedin",
                title="LinkedIn",
                url="https://linkedin.com/in/your-profile",
                category="Links",
                icon="💼"
            ),
            QuickLink(
                id="link-github",
                title="GitHub",
                url="https://github.com/your-username",
                category="Links",
                icon="💻"
            ),
            QuickLink(
                id="link-website",
                title="Portfolio",
                url="https://your-portfolio.com",
                category="Links",
                icon="🌐"
            ),
            QuickLink(
                id="link-calendly",
                title="Scheduling",
                url="https://calendly.com/your-calendar",
                category="Scheduling",
                icon="📅"
            ),
            QuickLink(
                id="link-email",
                title="Email",
                url="candidate@example.com",
                category="Contact / Info",
                icon="✉️"
            ),
            QuickLink(
                id="link-phone",
                title="Phone",
                url="555-123-4567",
                category="Contact / Info",
                icon="📞"
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
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False

    @classmethod
    def format_clipboard_bundle(cls, links: List[QuickLink]) -> str:
        """Formats all links into a clean plain-text block grouped by category for fast copying into applications/emails."""
        if not links:
            return ""
        categories: List[str] = []
        grouped: Dict[str, List[QuickLink]] = {}
        for l in links:
            cat = l.category or "Links"
            if cat not in grouped:
                categories.append(cat)
                grouped[cat] = []
            grouped[cat].append(l)

        sections: List[str] = []
        for cat in categories:
            section_lines = [f"[{cat}]"]
            for l in grouped[cat]:
                section_lines.append(f"{l.title}: {l.url}")
            sections.append("\n".join(section_lines))
        return "\n\n".join(sections)



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
            "telemetry_warnings": [TelemetryService.normalize_rule_dict(r) for r in DEFAULT_TELEMETRY_RULES],
            "instance_config": PipelineInstanceConfig().model_dump()
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

                raw_inst = data.get("instance_config")
                if isinstance(raw_inst, dict):
                    try:
                        inst_cfg = PipelineInstanceConfig(**raw_inst).model_dump()
                    except Exception:
                        inst_cfg = PipelineInstanceConfig().model_dump()
                else:
                    inst_cfg = PipelineInstanceConfig().model_dump()

                res = {
                    **data,
                    "enable_cli_logging": bool(enable_logging),
                    "sources": sources if isinstance(sources, list) and sources else list(DEFAULT_APPLICATION_SOURCES),
                    "priorities": priorities if isinstance(priorities, list) and priorities else list(DEFAULT_PRIORITIES),
                    "telemetry_rules": normalized_rules,
                    "telemetry_warnings": normalized_rules,
                    "instance_config": inst_cfg
                }
                return res
            return defaults
        except Exception:
            return defaults

    @classmethod
    def get_instance_config(cls, filepath: Optional[str] = None) -> PipelineInstanceConfig:
        cfg = cls.load_config(filepath)
        raw = cfg.get("instance_config")
        if isinstance(raw, dict):
            try:
                return PipelineInstanceConfig(**raw)
            except Exception:
                pass
        return PipelineInstanceConfig()

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
        norm_rule = TelemetryService.normalize_rule_dict({**rule, "id": rule.get("id") or f"warn-{uuid.uuid4().hex[:12]}"})
        valid, error = TelemetryService.validate_rule(TelemetryRule(**norm_rule))
        if not valid:
            raise ValueError(error)
        rules = cfg.setdefault("telemetry_rules", [])
        if any(r["id"] == norm_rule["id"] for r in rules):
            raise ValueError("A Job Signal rule with this ID already exists; edit it instead.")
        rules.append(norm_rule)
        cfg["telemetry_warnings"] = list(rules)
        if not cls.save_config(cfg, filepath):
            raise OSError("Could not save Job Signal rules.")
        return rules

    @classmethod
    def update_telemetry_rule(cls, rule_id: str, updated_fields: Dict[str, Any], filepath: Optional[str] = None) -> List[Dict[str, Any]]:
        cfg = cls.load_config(filepath)
        rules = cfg.setdefault("telemetry_rules", [])
        for r in rules:
            if r.get("id") == rule_id:
                norm = TelemetryService.normalize_rule_dict({**r, **updated_fields, "id": rule_id})
                valid, error = TelemetryService.validate_rule(TelemetryRule(**norm))
                if not valid:
                    raise ValueError(error)
                r.clear()
                r.update(norm)
                break
        else:
            raise ValueError("The Job Signal rule no longer exists. Reload the rule list.")
        cfg["telemetry_warnings"] = list(rules)
        if not cls.save_config(cfg, filepath):
            raise OSError("Could not save Job Signal rules.")
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
    def find_workspace_record(records: List[Dict[str, Any]], folder_id: str,
                              opportunity_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        matches = []
        for record in records:
            link = str(record.get("Drive Folder Link") or "")
            match = re.search(r"(?:folders/|[?&]id=)([\w-]+)", link)
            linked_id = match.group(1) if match else link
            identity = str(record.get("Opportunity ID") or "").strip()
            if linked_id == folder_id or (opportunity_id and identity == opportunity_id):
                if opportunity_id and identity and identity != opportunity_id:
                    raise ValueError("Workspace and canonical opportunity IDs conflict; manual review is required.")
                if opportunity_id and identity == opportunity_id and linked_id and linked_id != folder_id:
                    raise ValueError("Opportunity is linked to a different workspace; manual review is required.")
                matches.append(record)
        if len(matches) > 1:
            raise ValueError("Multiple canonical records reference this workspace; manual review is required.")
        return matches[0] if matches else None

    @staticmethod
    def require_completion(*, workspace_id: str, raw_jd_saved: bool,
                           canonical_saved: bool, report_saved: Optional[bool] = None,
                           require_report: bool = False) -> None:
        """Required durable outputs; resume copies, shortcuts and Q&A docs are optional.

        Canonical persistence includes submitted screening answers and requirements.
        The caller may mark Drive complete only after this check succeeds.
        Role Intelligence is decoupled from ingestion and optional unless require_report=True.
        """
        checks = [
            ("application workspace", bool(workspace_id)),
            ("raw job description", raw_jd_saved),
            ("canonical opportunity, requirements and screening answers", canonical_saved),
        ]
        if require_report:
            checks.append(("Role Intelligence report", bool(report_saved)))
        missing = [name for name, ok in checks if not ok]
        if missing:
            raise RuntimeError("Ingestion is incomplete; persistence failed for: " + ", ".join(missing) + ". Resume processing to retry.")

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


class PipelineSearchPaginationService:
    """Pure domain service for Pipeline Tracker search filtering, sorting, and pagination state."""

    PAGE_SIZE_OPTIONS = [5, 10, 15, 25, 50]
    DEFAULT_PAGE_SIZE = 5

    @staticmethod
    def filter_opportunities(
        opportunities: List[Dict[str, Any]],
        search_query: str = "",
        arrangement_filter: str = "All Types",
        category_filter: str = "All Categories",
        priority_filter: str = "All Priorities",
        source_filter: str = "All Sources",
        freshness_filter: str = "All Freshness",
        stale_threshold_days: int = 7,
        reference_date: Optional[datetime] = None,
        application_categories: Optional[List[str]] = None,
        opportunity_source_filter: str = "All"
    ) -> List[Dict[str, Any]]:
        app_cats = application_categories or ["Target", "Stretch", "Opportunistic", "Practice", "Fallback"]
        filtered = list(opportunities)

        if opportunity_source_filter and opportunity_source_filter not in ("All", "All Sources"):
            filtered = [
                o for o in filtered
                if str(o.get("Opportunity Source") or o.get("opportunity_source") or "Outbound").strip().lower() == opportunity_source_filter.strip().lower()
            ]

        if arrangement_filter and arrangement_filter != "All Types":
            filtered = [
                o for o in filtered
                if str(o.get("Employment Arrangement") or o.get("employment_arrangement") or "").strip() == arrangement_filter
            ]

        if category_filter and category_filter != "All Categories":
            if category_filter == "Unassigned":
                filtered = [
                    o for o in filtered
                    if str(o.get("Category", "")).strip() not in app_cats
                ]
            else:
                filtered = [
                    o for o in filtered
                    if str(o.get("Category", "")).strip() == category_filter
                ]

        if priority_filter and priority_filter != "All Priorities":
            if priority_filter == "Unspecified":
                filtered = [
                    o for o in filtered
                    if not o.get("Priority") or o.get("Priority") == "Not Specified"
                ]
            else:
                filtered = [
                    o for o in filtered
                    if str(o.get("Priority", "")).strip() == priority_filter
                ]

        if source_filter and source_filter != "All Sources":
            if source_filter == "Unspecified":
                filtered = [
                    o for o in filtered
                    if not o.get("Applied Via") or o.get("Applied Via") == "Not Specified"
                ]
            else:
                filtered = [
                    o for o in filtered
                    if str(o.get("Applied Via", "")).strip() == source_filter
                ]

        if freshness_filter and freshness_filter not in ("All Freshness", "All"):
            eff_threshold = stale_threshold_days
            m_thresh = re.search(r'(\d+)\s*d', str(freshness_filter))
            if m_thresh and stale_threshold_days == 7:
                eff_threshold = int(m_thresh.group(1))

            if "Stale" in freshness_filter:
                filtered = [
                    o for o in filtered
                    if PipelineKPIService.is_stale(o, threshold_days=eff_threshold, reference_date=reference_date)
                ]
            elif "Fresh" in freshness_filter:
                filtered = [
                    o for o in filtered
                    if not PipelineKPIService.is_stale(o, threshold_days=eff_threshold, reference_date=reference_date)
                ]

        if search_query and search_query.strip():
            sq = search_query.strip().lower()
            filtered = [
                o for o in filtered
                if sq in str(o.get("Company Name", "")).lower()
                or sq in str(o.get("Job Title", "")).lower()
                or sq in str(o.get("Contact Name", "")).lower()
                or sq in str(o.get("contact_name", "")).lower()
                or sq in str(o.get("Status", "")).lower()
                or sq in str(o.get("Notes", "")).lower()
                or sq in str(o.get("Category", "")).lower()
                or sq in str(o.get("Priority", "")).lower()
                or sq in str(o.get("Applied Via", "")).lower()
                or sq in str(o.get("Employment Arrangement", "")).lower()
                or sq in str(o.get("Worker Classification", "")).lower()
                or sq in str(o.get("Staffing Agency", "")).lower()
                or sq in str(o.get("Client Company", "")).lower()
            ]

        return filtered

    @staticmethod
    def calculate_pagination(
        total_items: int,
        items_per_page: int = 5,
        current_page: int = 1
    ) -> Dict[str, Any]:
        """
        Calculates total pages, safe clamped page, start offset, and end offset.
        Deterministic, 1-indexed page, 0-indexed offsets.
        """
        items_per_page = max(1, items_per_page)
        if total_items <= 0:
            return {
                "total_items": 0,
                "total_pages": 1,
                "current_page": 1,
                "start_offset": 0,
                "end_offset": 0
            }

        import math
        total_pages = max(1, math.ceil(total_items / items_per_page))
        safe_page = min(max(1, current_page), total_pages)
        start_offset = (safe_page - 1) * items_per_page
        end_offset = min(start_offset + items_per_page, total_items)
        return {
            "total_items": total_items,
            "total_pages": total_pages,
            "current_page": safe_page,
            "start_offset": start_offset,
            "end_offset": end_offset
        }

    @staticmethod
    def paginate_records(
        records: List[Dict[str, Any]],
        items_per_page: int = 5,
        current_page: int = 1,
        reverse: bool = True
    ) -> Dict[str, Any]:
        """
        Orders records (newest first by default) and returns paginated slice with metadata.
        """
        ordered = list(reversed(records)) if reverse else list(records)
        pagination = PipelineSearchPaginationService.calculate_pagination(
            total_items=len(ordered),
            items_per_page=items_per_page,
            current_page=current_page
        )
        paginated_items = ordered[pagination["start_offset"]:pagination["end_offset"]]
        return {
            **pagination,
            "items": paginated_items,
            "ordered_records": ordered
        }

    @staticmethod
    def resolve_page_on_filter_change(
        previous_filter_tuple: Optional[tuple],
        current_filter_tuple: tuple,
        current_page: int
    ) -> int:
        """
        Resets page to 1 if search query or any filter has changed.
        """
        if previous_filter_tuple is not None and previous_filter_tuple != current_filter_tuple:
            return 1
        return current_page

    @staticmethod
    def find_card_page(
        card_id: str,
        ordered_records: List[Dict[str, Any]],
        items_per_page: int = 5
    ) -> Optional[int]:
        """
        Finds the 1-indexed page of a specific opportunity card in ordered records.
        """
        if not card_id or items_per_page <= 0:
            return None
        target = str(card_id).strip()
        for idx, item in enumerate(ordered_records):
            oid = str(item.get("Opportunity ID") or item.get("opportunity_id") or "").strip()
            if oid == target:
                return (idx // items_per_page) + 1
        return None


class PipelineKPIService:
    """Domain service for calculating pipeline performance KPIs, staleness indicators, and resume variant breakdowns."""

    ACTIVE_STAGES = ACTIVE_OPPORTUNITY_STAGES
    INTERVIEW_STAGES = KPI_INTERVIEW_STAGES
    POSITIVE_INTEREST_STAGES = POSITIVE_INTEREST_STAGES
    TERMINAL_STAGES = TERMINAL_STAGES
    SUBMITTED_STAGES = SUBMITTED_STAGES

    @classmethod
    def parse_stage_history(cls, opp: Dict[str, Any]) -> List[str]:
        """Extracts list of stage names from an opportunity dictionary."""
        raw = opp.get("stage_history") or opp.get("Stage History") or []
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = []
        stages = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    stg = item.get("stage")
                    if stg:
                        stages.append(str(stg).strip())
                elif isinstance(item, str):
                    stages.append(item.strip())
        return stages

    @classmethod
    def parse_stage_history_entries(cls, opp: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extracts structured stage history entries with stage and entered_at."""
        raw = opp.get("stage_history") or opp.get("Stage History") or []
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = []
        entries = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    entries.append(item)
                elif isinstance(item, str):
                    entries.append({"stage": item.strip()})
        return entries

    @classmethod
    def parse_timestamp(cls, val: Any) -> Optional[datetime]:
        """Safely parses ISO timestamp or YYYY-MM-DD date."""
        if not val:
            return None
        s = str(val).strip()
        if not s:
            return None
        try:
            if "T" in s:
                return datetime.fromisoformat(s[:19])
            if len(s) >= 10:
                return datetime.strptime(s[:10], "%Y-%m-%d")
        except Exception:
            pass
        return None

    @classmethod
    def is_submitted(cls, opp: Dict[str, Any]) -> bool:
        """
        Counts applications that were actually submitted, including those subsequently
        progressed, rejected, or withdrawn. Checks stage history first, then current status.
        Does not assume unverified terminal records outside submission stages were submitted.
        For Inbound opportunities: only counted as submitted if explicitly marked with an 'Applied' stage.
        """
        source = str(opp.get("Opportunity Source") or opp.get("opportunity_source") or "Outbound").strip().capitalize()
        curr = str(opp.get("Status") or opp.get("status") or "").strip()
        hist = cls.parse_stage_history(opp)
        if source == "Inbound":
            return curr == "Applied" or "Applied" in hist
        if any(s in cls.SUBMITTED_STAGES for s in hist):
            return True
        if curr in cls.SUBMITTED_STAGES:
            return True
        return False

    @classmethod
    def has_positive_interest(cls, opp: Dict[str, Any]) -> bool:
        """
        Determines whether a submitted application reached positive employer interest
        (Employer Interest, Recruiter Screen, Hiring Manager, Technical Screen, Final Round, Offer).
        Counted once per application regardless of number of qualifying stages.
        For Outbound: requires submission evidence.
        For Inbound: qualifies directly without requiring submission.
        """
        source = str(opp.get("Opportunity Source") or opp.get("opportunity_source") or "Outbound").strip().capitalize()
        curr = str(opp.get("Status") or opp.get("status") or "").strip()
        hist = cls.parse_stage_history(opp)
        if source == "Inbound":
            if curr in cls.POSITIVE_INTEREST_STAGES:
                return True
            return any(s in cls.POSITIVE_INTEREST_STAGES for s in hist)
        if not cls.is_submitted(opp):
            return False
        if curr in cls.POSITIVE_INTEREST_STAGES:
            return True
        return any(s in cls.POSITIVE_INTEREST_STAGES for s in hist)

    @classmethod
    def has_inbound_interviewed(cls, opp: Dict[str, Any]) -> bool:
        """
        Determines whether an inbound lead reached an interview stage
        (Recruiter Screen, Hiring Manager, Technical Screen, or Final Round)
        without requiring an application submission step.
        """
        curr = str(opp.get("Status") or opp.get("status") or "").strip()
        if curr in cls.INTERVIEW_STAGES:
            return True
        hist = cls.parse_stage_history(opp)
        return any(s in cls.INTERVIEW_STAGES for s in hist)

    @classmethod
    def has_interviewed(cls, opp: Dict[str, Any]) -> bool:
        """
        Determines whether an application reached an interview stage
        (Recruiter Screen, Hiring Manager, Technical Screen, or Final Round).
        Counted once per application regardless of number of interview rounds.
        Employer Interest explicitly does NOT qualify as an interview.
        Offer alone does NOT qualify unless historical evidence establishes that
        the application reached an interview stage.
        For Outbound: requires is_submitted(opp).
        For Inbound: delegates to has_inbound_interviewed(opp).
        """
        source = str(opp.get("Opportunity Source") or opp.get("opportunity_source") or "Outbound").strip().capitalize()
        if source == "Inbound":
            return cls.has_inbound_interviewed(opp)
        if not cls.is_submitted(opp):
            return False
        curr = str(opp.get("Status") or opp.get("status") or "").strip()
        if curr in cls.INTERVIEW_STAGES:
            return True
        hist = cls.parse_stage_history(opp)
        return any(s in cls.INTERVIEW_STAGES for s in hist)

    @classmethod
    def is_active(cls, opp: Dict[str, Any]) -> bool:
        """
        Active Opportunities: Counts ONLY records whose CURRENT stage is in the explicit allowlist:
        Employer Interest, Recruiter Screen, Hiring Manager, Technical Screen, Final Round, Offer.
        """
        curr = str(opp.get("Status") or opp.get("status") or "").strip()
        return curr in cls.ACTIVE_STAGES

    @classmethod
    def get_last_meaningful_activity_date(cls, opp: Dict[str, Any]) -> Tuple[Optional[datetime], str]:
        """
        Determines the datetime of the last reliably recorded meaningful activity.
        Meaningful activity includes:
        - Pipeline stage transitions (entered_at in stage_history)
        - Substantive interactions or touchpoints (timestamped interaction records)
        - User-initiated creation or modification of application notes (notes_updated_at or dated note entries)

        Role Intelligence generation, routine refreshes, non-stage edits without note updates,
        and untimestamped historical notes do NOT reset freshness.
        Documented fallback: Date Created / date_created.
        Returns: (datetime, source_name)
        """
        candidates: List[Tuple[datetime, str]] = []

        # 1. Stage transitions from stage_history
        entries = cls.parse_stage_history_entries(opp)
        for item in entries:
            ea = item.get("entered_at")
            parsed = cls.parse_timestamp(ea)
            if parsed:
                candidates.append((parsed, "stage_history"))

        # 2. Structured interactions / touchpoints
        for key in ("interactions", "touchpoints", "activities", "activity_history"):
            acts = opp.get(key)
            if isinstance(acts, str):
                try:
                    acts = json.loads(acts)
                except Exception:
                    acts = []
            if isinstance(acts, list):
                for act in acts:
                    if isinstance(act, dict):
                        ts = act.get("timestamp") or act.get("date") or act.get("created_at") or act.get("entered_at")
                        parsed = cls.parse_timestamp(ts)
                        if parsed:
                            candidates.append((parsed, "interaction"))

        # 3. User-initiated note modifications (via reliable note-edit timestamps)
        for key in ("notes_updated_at", "notes_modified_at", "last_note_edit_at", "Notes Updated At"):
            note_ts = opp.get(key)
            if note_ts:
                parsed_note_ts = cls.parse_timestamp(note_ts)
                if parsed_note_ts:
                    candidates.append((parsed_note_ts, "note_edit"))

        # 4. Reliably timestamped notes entries (e.g. [2026-10-15] or 2026-10-15:)
        notes = opp.get("Notes") or opp.get("notes") or ""
        if isinstance(notes, str) and notes.strip():
            date_matches = re.findall(r'(?:\[|\b)(\d{4}-\d{2}-\d{2})(?:\]|:|\s)', notes)
            for dm in date_matches:
                parsed_note_dt = cls.parse_timestamp(dm)
                if parsed_note_dt:
                    candidates.append((parsed_note_dt, "timestamped_note"))

        if candidates:
            # Sort descending to find the most recent meaningful activity
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0]

        # 5. Documented fallback: Date Created
        dc = opp.get("Date Created") or opp.get("date_created")
        parsed_dc = cls.parse_timestamp(dc)
        if parsed_dc:
            return parsed_dc, "date_created"

        return None, "missing"

    @classmethod
    def get_last_stage_transition_date(cls, opp: Dict[str, Any]) -> Tuple[Optional[datetime], str]:
        """Backward-compatible alias delegating to get_last_meaningful_activity_date."""
        return cls.get_last_meaningful_activity_date(opp)

    @classmethod
    def is_stale(
        cls,
        opp: Dict[str, Any],
        threshold_days: int = 7,
        reference_date: Optional[datetime] = None
    ) -> bool:
        """
        Derived freshness indicator for active, nonterminal applications and leads.
        Marked Stale when threshold_days or more have elapsed since its last meaningful activity.
        Stale does NOT replace current stage, and does NOT remove an application from Active Opportunities.
        Terminal records (Declined to Apply, Application Rejected, Rejected, Withdrawn, Archived) are excluded.
        Non-substantive edits (refreshes, un-timestamped notes) do not reset freshness.
        Outbound requires application submission; Inbound requires nonterminal status.
        Default threshold: 7 days (configurable).
        """
        curr = str(opp.get("Status") or opp.get("status") or "").strip()
        if curr in cls.TERMINAL_STAGES:
            return False

        source = str(opp.get("Opportunity Source") or opp.get("opportunity_source") or "Outbound").strip().capitalize()
        if source != "Inbound":
            if not cls.is_submitted(opp):
                return False

        last_dt, _ = cls.get_last_meaningful_activity_date(opp)
        if not last_dt:
            return False

        ref = reference_date or datetime.now()
        days_elapsed = (ref - last_dt).total_seconds() / 86400.0
        return days_elapsed >= threshold_days

    @classmethod
    def get_staleness_info(
        cls,
        opp: Dict[str, Any],
        threshold_days: int = 7,
        reference_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Returns structured staleness information:
        - is_eligible: nonterminal (and submitted if outbound)
        - is_stale: bool
        - days_elapsed: float or None
        - last_transition_date: datetime or None
        - last_activity_date: datetime or None
        - source: source identifier string
        """
        curr = str(opp.get("Status") or opp.get("status") or "").strip()
        if curr in cls.TERMINAL_STAGES:
            return {
                "is_eligible": False,
                "is_stale": False,
                "days_elapsed": None,
                "last_transition_date": None,
                "last_activity_date": None,
                "source": "terminal"
            }

        source = str(opp.get("Opportunity Source") or opp.get("opportunity_source") or "Outbound").strip().capitalize()
        if source != "Inbound":
            if not cls.is_submitted(opp):
                return {
                    "is_eligible": False,
                    "is_stale": False,
                    "days_elapsed": None,
                    "last_transition_date": None,
                    "last_activity_date": None,
                    "source": "not_submitted"
                }

        last_dt, src = cls.get_last_meaningful_activity_date(opp)
        if not last_dt:
            return {
                "is_eligible": True,
                "is_stale": False,
                "days_elapsed": None,
                "last_transition_date": None,
                "last_activity_date": None,
                "source": "missing"
            }

        ref = reference_date or datetime.now()
        days_elapsed = (ref - last_dt).total_seconds() / 86400.0
        return {
            "is_eligible": True,
            "is_stale": days_elapsed >= threshold_days,
            "days_elapsed": days_elapsed,
            "last_transition_date": last_dt,
            "last_activity_date": last_dt,
            "source": src
        }

    @classmethod
    def get_canonical_resume_variant(cls, opp: Union[Dict[str, Any], str]) -> str:
        """Extracts and normalizes the resume variant name from opp dict or string."""
        if isinstance(opp, str):
            raw = opp
        elif isinstance(opp, dict):
            raw = opp.get("Selected Resume") or opp.get("selected_resume_name") or opp.get("selected_resume") or ""
        else:
            raw = ""
        if not raw or not str(raw).strip():
            return "Unassigned"
        val = str(raw).strip()
        # Remove file extensions
        val = re.sub(r'(?i)\.(docx?|pdf|txt|gdoc)$', '', val).strip()
        # Remove candidate prefixes (e.g. 'Candidate ', 'Matt Hackett - ')
        val = re.sub(r'(?i)^(candidate\s+|(?:[a-z]+\s+){1,3}-\s*)', '', val).strip()
        # Remove trailing 'Resume' or 'CV'
        val = re.sub(r'(?i)\s+(resume|cv)$', '', val).strip()
        # Normalize canonical role families
        low = val.lower()
        if "revops" in low or "revenue operations" in low:
            return "RevOps Analyst"
        if "gtm" in low or "go to market" in low:
            return "GTM Engineer"
        if "business analyst" in low or "business analytics" in low or "data analytics" in low:
            return "Business Analyst"
        if "solutions" in low:
            return "Solutions Engineer"
        if val:
            return val
        return "Unassigned"

    @classmethod
    def format_ratio(cls, numerator: int, denominator: int) -> str:
        if denominator <= 0:
            return "—"
        ratio = numerator / denominator
        return f"1:{int(round(ratio))}"

    @classmethod
    def calculate_kpis(
        cls,
        opportunities: List[Dict[str, Any]],
        stale_threshold_days: int = 7,
        reference_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        total_tracked = len(opportunities)
        submitted_opps = [o for o in opportunities if cls.is_submitted(o)]
        submitted_count = len(submitted_opps)
        interviewed_count = sum(1 for o in opportunities if cls.has_interviewed(o))
        positive_interest_count = sum(1 for o in opportunities if cls.has_positive_interest(o))
        active_count = sum(1 for o in opportunities if cls.is_active(o))
        stale_count = sum(
            1 for o in opportunities
            if cls.is_stale(o, threshold_days=stale_threshold_days, reference_date=reference_date)
        )

        # Outbound-specific conversions to preserve metric integrity
        outbound_opps = [
            o for o in opportunities
            if str(o.get("Opportunity Source") or o.get("opportunity_source") or "Outbound").strip().capitalize() != "Inbound"
        ]
        outbound_submitted = len([o for o in outbound_opps if cls.is_submitted(o)])
        outbound_interviewed = sum(1 for o in outbound_opps if cls.has_interviewed(o))
        outbound_interest = sum(1 for o in outbound_opps if cls.has_positive_interest(o))
        apps_per_interview = cls.format_ratio(outbound_submitted, outbound_interviewed)
        apps_per_interest = cls.format_ratio(outbound_submitted, outbound_interest)

        # Submitted applications breakdown by strategy (sum equals submitted_count)
        submitted_categories = {
            "Target": 0,
            "Stretch": 0,
            "Opportunistic": 0,
            "Practice": 0,
            "Fallback": 0,
            "Unassigned": 0
        }
        for o in submitted_opps:
            c = str(o.get("Category") or o.get("category") or "").strip()
            if c in submitted_categories and c != "Unassigned":
                submitted_categories[c] += 1
            else:
                submitted_categories["Unassigned"] += 1

        # Group by canonical resume variant
        variants_data: Dict[str, Dict[str, int]] = {}
        for o in opportunities:
            variant = cls.get_canonical_resume_variant(o)
            if variant not in variants_data:
                variants_data[variant] = {
                    "tracked": 0,
                    "applied": 0,
                    "active": 0,
                    "interest": 0,
                    "interviewed": 0,
                    "stale": 0
                }
            variants_data[variant]["tracked"] += 1
            if cls.is_submitted(o):
                variants_data[variant]["applied"] += 1
            if cls.is_active(o):
                variants_data[variant]["active"] += 1
            if cls.has_positive_interest(o):
                variants_data[variant]["interest"] += 1
            if cls.has_interviewed(o):
                variants_data[variant]["interviewed"] += 1
            if cls.is_stale(o, threshold_days=stale_threshold_days, reference_date=reference_date):
                variants_data[variant]["stale"] += 1

        variant_rows = []
        for v_name, stats in sorted(variants_data.items(), key=lambda x: (-x[1]["tracked"], x[0])):
            variant_rows.append({
                "variant": v_name,
                "tracked": stats["tracked"],
                "applied": stats["applied"],
                "active": stats["active"],
                "interest": stats["interest"],
                "interviewed": stats["interviewed"],
                "stale": stats["stale"],
                "apps_per_interest": cls.format_ratio(stats["applied"], stats["interest"]),
                "apps_per_interview": cls.format_ratio(stats["applied"], stats["interviewed"])
            })

        totals_row = {
            "variant": "Total",
            "tracked": total_tracked,
            "applied": submitted_count,
            "active": active_count,
            "interest": positive_interest_count,
            "interviewed": interviewed_count,
            "stale": stale_count,
            "apps_per_interest": apps_per_interest,
            "apps_per_interview": apps_per_interview
        }

        return {
            "total_tracked": total_tracked,
            "total_applied": submitted_count,
            "total_active": active_count,
            "total_active_opportunities": active_count,
            "total_positive_interest": positive_interest_count,
            "total_interviewed": interviewed_count,
            "total_stale": stale_count,
            "apps_per_interest": apps_per_interest,
            "apps_per_interview": apps_per_interview,
            "submitted_categories": submitted_categories,
            "variant_rows": variant_rows,
            "totals_row": totals_row
        }

    @classmethod
    def calculate_analytics_dashboard_metrics(
        cls,
        opportunities: List[Dict[str, Any]],
        stale_threshold_days: int = 7,
        source_filter: str = "All",
        date_range_filter: str = "All Time",
        reference_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Calculates comprehensive metrics for the dedicated Analytics Dashboard:
        - Overview: Tracked, Outbound, Inbound, Submitted, Interviews, Active, Stale
        - Source Performance: Separate denominators for Outbound vs Inbound
        - Funnel: Conversion stages
        - Opportunity Health: Staleness analysis with configurable threshold
        - Application Strategy: Strategy performance
        - Resume Performance: Variants breakdown
        - Activity Trends: Monthly activity progression
        """
        ref = reference_date or datetime.now()

        # 1. Date-range filter
        filtered_by_date = list(opportunities)
        if date_range_filter and date_range_filter != "All Time":
            cutoff = None
            if date_range_filter == "Last 7 Days":
                cutoff = ref - timedelta(days=7)
            elif date_range_filter == "Last 30 Days":
                cutoff = ref - timedelta(days=30)
            elif date_range_filter == "Last 90 Days":
                cutoff = ref - timedelta(days=90)

            if cutoff:
                date_filtered = []
                for o in filtered_by_date:
                    act_dt, _ = cls.get_last_meaningful_activity_date(o)
                    if act_dt and act_dt >= cutoff:
                        date_filtered.append(o)
                filtered_by_date = date_filtered

        # 2. Source filter
        filtered_opps = list(filtered_by_date)
        if source_filter and source_filter not in ("All", "All Sources"):
            norm_sf = source_filter.strip().capitalize()
            filtered_opps = [
                o for o in filtered_opps
                if str(o.get("Opportunity Source") or o.get("opportunity_source") or "Outbound").strip().capitalize() == norm_sf
            ]

        # 3. Overall numbers on filtered dataset
        total_tracked = len(filtered_opps)
        outbound_opps = [
            o for o in filtered_opps
            if str(o.get("Opportunity Source") or o.get("opportunity_source") or "Outbound").strip().capitalize() != "Inbound"
        ]
        inbound_opps = [
            o for o in filtered_opps
            if str(o.get("Opportunity Source") or o.get("opportunity_source") or "Outbound").strip().capitalize() == "Inbound"
        ]

        total_outbound = len(outbound_opps)
        total_inbound = len(inbound_opps)
        submitted_outbound = sum(1 for o in outbound_opps if cls.is_submitted(o))
        interviews_outbound = sum(1 for o in outbound_opps if cls.has_interviewed(o))
        interest_outbound = sum(1 for o in outbound_opps if cls.has_positive_interest(o))
        active_outbound = sum(1 for o in outbound_opps if cls.is_active(o))
        stale_outbound = sum(1 for o in outbound_opps if cls.is_stale(o, threshold_days=stale_threshold_days, reference_date=ref))

        interviews_inbound = sum(1 for o in inbound_opps if cls.has_interviewed(o))
        interest_inbound = sum(1 for o in inbound_opps if cls.has_positive_interest(o))
        active_inbound = sum(1 for o in inbound_opps if cls.is_active(o))
        stale_inbound = sum(1 for o in inbound_opps if cls.is_stale(o, threshold_days=stale_threshold_days, reference_date=ref))

        interviews_total = interviews_outbound + interviews_inbound
        active_total = active_outbound + active_inbound
        stale_total = stale_outbound + stale_inbound

        # 4. Source performance calculations
        outbound_conv_pct = round((interviews_outbound / submitted_outbound * 100.0), 1) if submitted_outbound > 0 else 0.0
        outbound_ratio_str = cls.format_ratio(submitted_outbound, interviews_outbound)

        inbound_conv_pct = round((interviews_inbound / total_inbound * 100.0), 1) if total_inbound > 0 else 0.0
        inbound_ratio_str = cls.format_ratio(total_inbound, interviews_inbound)

        # 5. Opportunity health details
        stale_records = []
        days_since_activity_list = []
        stale_by_stage_source: Dict[str, Dict[str, int]] = {}

        for o in filtered_opps:
            curr_stg = str(o.get("Status") or o.get("status") or "").strip()
            src = str(o.get("Opportunity Source") or o.get("opportunity_source") or "Outbound").strip().capitalize()
            stale_info = cls.get_staleness_info(o, threshold_days=stale_threshold_days, reference_date=ref)

            if stale_info.get("days_elapsed") is not None and curr_stg not in cls.TERMINAL_STAGES:
                days_since_activity_list.append(stale_info["days_elapsed"])

            if stale_info.get("is_stale"):
                if curr_stg not in stale_by_stage_source:
                    stale_by_stage_source[curr_stg] = {"Outbound": 0, "Inbound": 0, "Total": 0}
                if src == "Inbound":
                    stale_by_stage_source[curr_stg]["Inbound"] += 1
                else:
                    stale_by_stage_source[curr_stg]["Outbound"] += 1
                stale_by_stage_source[curr_stg]["Total"] += 1

                c_name = str(o.get("Company Name") or o.get("company_name") or "").strip()
                t_name = str(o.get("Job Title") or o.get("job_title") or "").strip()
                ct_name = str(o.get("Contact Name") or o.get("contact_name") or "").strip()
                if c_name and t_name:
                    disp = f"{c_name} — {t_name}"
                elif c_name:
                    disp = f"{c_name}" + (f" ({ct_name})" if ct_name else "")
                elif ct_name:
                    disp = f"{ct_name} (Inbound Lead)"
                else:
                    disp = "Untitled Opportunity"

                stale_records.append({
                    "opportunity_id": o.get("Opportunity ID") or o.get("opportunity_id") or "",
                    "display_name": disp,
                    "company_name": c_name,
                    "contact_name": ct_name,
                    "job_title": t_name,
                    "status": curr_stg,
                    "source": src,
                    "days_elapsed": round(stale_info.get("days_elapsed") or 0.0, 1),
                    "last_activity_date": stale_info.get("last_activity_date"),
                    "last_activity_source": stale_info.get("source") or ""
                })

        avg_days_since_activity = (
            round(sum(days_since_activity_list) / len(days_since_activity_list), 1)
            if days_since_activity_list else None
        )

        # 6. Strategy breakdown (for submitted outbound)
        strategy_stats = {
            "Target": {"submitted": 0, "interviewed": 0, "active": 0},
            "Stretch": {"submitted": 0, "interviewed": 0, "active": 0},
            "Opportunistic": {"submitted": 0, "interviewed": 0, "active": 0},
            "Practice": {"submitted": 0, "interviewed": 0, "active": 0},
            "Fallback": {"submitted": 0, "interviewed": 0, "active": 0},
            "Unassigned": {"submitted": 0, "interviewed": 0, "active": 0}
        }
        for o in outbound_opps:
            if cls.is_submitted(o):
                cat = str(o.get("Category") or o.get("category") or "").strip()
                key = cat if cat in strategy_stats and cat != "Unassigned" else "Unassigned"
                strategy_stats[key]["submitted"] += 1
                if cls.has_interviewed(o):
                    strategy_stats[key]["interviewed"] += 1
                if cls.is_active(o):
                    strategy_stats[key]["active"] += 1

        strategy_rows = []
        for cat, s_data in strategy_stats.items():
            sub = s_data["submitted"]
            intv = s_data["interviewed"]
            act = s_data["active"]
            ratio = cls.format_ratio(sub, intv)
            strategy_rows.append({
                "category": cat,
                "submitted": sub,
                "interviewed": intv,
                "active": act,
                "conversion_ratio": ratio
            })

        # 7. Resume variant breakdown
        kpi_res = cls.calculate_kpis(filtered_opps, stale_threshold_days=stale_threshold_days, reference_date=ref)
        variant_rows = kpi_res.get("variant_rows", [])

        # 8. Activity trends by month
        monthly_trends: Dict[str, Dict[str, int]] = {}
        for o in filtered_opps:
            act_dt, _ = cls.get_last_meaningful_activity_date(o)
            if act_dt:
                m_key = act_dt.strftime("%Y-%m")
                if m_key not in monthly_trends:
                    monthly_trends[m_key] = {"outbound_applied": 0, "interviews": 0, "inbound_leads": 0}
                src = str(o.get("Opportunity Source") or o.get("opportunity_source") or "Outbound").strip().capitalize()
                if src == "Inbound":
                    monthly_trends[m_key]["inbound_leads"] += 1
                else:
                    if cls.is_submitted(o):
                        monthly_trends[m_key]["outbound_applied"] += 1
                if cls.has_interviewed(o):
                    monthly_trends[m_key]["interviews"] += 1

        trend_rows = [
            {"month": m, **data}
            for m, data in sorted(monthly_trends.items())
        ]

        return {
            "overview": {
                "total_tracked": total_tracked,
                "total_outbound": total_outbound,
                "total_inbound": total_inbound,
                "applications_submitted": submitted_outbound,
                "interviews_total": interviews_total,
                "active_total": active_total,
                "stale_total": stale_total,
            },
            "source_performance": {
                "outbound": {
                    "tracked": total_outbound,
                    "submitted": submitted_outbound,
                    "interviewed": interviews_outbound,
                    "active": active_outbound,
                    "stale": stale_outbound,
                    "conversion_pct": outbound_conv_pct,
                    "ratio": outbound_ratio_str,
                },
                "inbound": {
                    "tracked": total_inbound,
                    "interviewed": interviews_inbound,
                    "active": active_inbound,
                    "stale": stale_inbound,
                    "conversion_pct": inbound_conv_pct,
                    "ratio": inbound_ratio_str,
                },
                "combined": {
                    "tracked": total_tracked,
                    "interviews": interviews_total,
                }
            },
            "funnel": {
                "outbound": {
                    "tracked": total_outbound,
                    "submitted": submitted_outbound,
                    "interest": interest_outbound,
                    "interviewed": interviews_outbound,
                    "app_to_interest_ratio": cls.format_ratio(submitted_outbound, interest_outbound),
                    "app_to_interview_ratio": outbound_ratio_str,
                },
                "inbound": {
                    "tracked": total_inbound,
                    "interviewed": interviews_inbound,
                    "active": active_inbound,
                    "opp_to_interview_ratio": inbound_ratio_str,
                }
            },
            "opportunity_health": {
                "stale_threshold_days": stale_threshold_days,
                "stale_total": stale_total,
                "avg_days_since_activity": avg_days_since_activity,
                "stale_by_stage_source": stale_by_stage_source,
                "stale_records": stale_records,
            },
            "strategy": {
                "rows": strategy_rows
            },
            "resume_performance": {
                "variant_rows": variant_rows,
                "totals_row": kpi_res.get("totals_row", {})
            },
            "trends": {
                "rows": trend_rows
            }
        }

    @staticmethod
    def format_compensation_display(salary_submitted: Optional[str] = None, target_pay: Optional[str] = None) -> str:
        r"""
        Standardizes compensation display for pipeline opportunity records.
        Display precedence:
        1. Salary Submitted: When an actual salary response was recorded ($X) -> 'Salary Submitted: :green[\$135,000]'
        2. Suggested Range: Otherwise when a valid calculated range exists ($X–$Y) -> 'Suggested Range: :green[\$115,000–\$125,000]'
        3. Salary Unspecified: When neither value exists -> ':color[Salary Unspecified]{foreground="#FCD34D"}'
        """
        def format_currency_amount(val_str: str) -> str:
            val_str = str(val_str).strip()
            m_k = re.match(r"^\$?([0-9]+(?:\.[0-9]+)?)\s*[kK]$", val_str)
            if m_k:
                amt = float(m_k.group(1)) * 1000
                return f"\\${amt:,.0f}"
            clean = re.sub(r"[\$,]", "", val_str)
            try:
                amt = float(clean)
                return f"\\${amt:,.0f}"
            except ValueError:
                val_clean = val_str.lstrip("$")
                return f"\\${val_clean}"

        # 1. Salary Submitted: When an actual salary response was recorded
        if salary_submitted:
            s_val = str(salary_submitted).strip()
            if s_val and s_val.lower() not in ("none", "n/a", "not specified", "unspecified", "undisclosed", "null", "0"):
                m_range = re.match(r"^\$?([0-9kK,\.]+)\s*[-–—]\s*\$?([0-9kK,\.]+)$", s_val)
                if m_range:
                    low = format_currency_amount(m_range.group(1))
                    high = format_currency_amount(m_range.group(2))
                    return f"Salary Submitted: :green[{low}–{high}]"
                formatted = format_currency_amount(s_val)
                return f"Salary Submitted: :green[{formatted}]"

        # 2. Suggested Range: When a valid calculated range exists
        if target_pay:
            t_val = str(target_pay).strip()
            placeholder_patterns = [
                r"undisclosed", r"set per role", r"not specified", r"not calculated",
                r"unspecified", r"^n/?a$", r"^none$", r"^null$", r"rate undisclosed"
            ]
            is_placeholder = any(re.search(pat, t_val, re.IGNORECASE) for pat in placeholder_patterns)
            if not is_placeholder and t_val:
                m_target = re.match(r"^(.*?)\s*\((?:Target:.*?)\)$", t_val, re.IGNORECASE)
                base_range = m_target.group(1).strip() if m_target else t_val

                m_rng = re.match(r"^\$?([0-9kK,\.]+)\s*[-–—]\s*\$?([0-9kK,\.]+)$", base_range)
                if m_rng:
                    low = format_currency_amount(m_rng.group(1))
                    high = format_currency_amount(m_rng.group(2))
                    return f"Suggested Range: :green[{low}–{high}]"

                m_plus = re.match(r"^\$?([0-9kK,\.]+)\s*\+$", base_range)
                if m_plus:
                    amt = format_currency_amount(m_plus.group(1))
                    return f"Suggested Range: :green[{amt}+]"

                m_upto = re.match(r"^up to\s+\$?([0-9kK,\.]+)$", base_range, re.IGNORECASE)
                if m_upto:
                    amt = format_currency_amount(m_upto.group(1))
                    return f"Suggested Range: :green[Up to {amt}]"

                m_hr = re.match(r"^\$?([0-9\.]+)\s*[-–—]\s*\$?([0-9\.]+)\s*/\s*hr", base_range, re.IGNORECASE)
                if m_hr:
                    low = format_currency_amount(m_hr.group(1))
                    high = format_currency_amount(m_hr.group(2))
                    return f"Suggested Range: :green[{low}–{high}/hr]"

                if re.search(r"\d", base_range):
                    escaped_base = re.sub(r"(?<!\\)\$", r"\$", base_range)
                    return f"Suggested Range: :green[{escaped_base}]"

        # 3. Salary Unspecified: When neither value exists
        return ':color[Salary Unspecified]{foreground="#FCD34D"}'

    @classmethod
    def refresh_pipeline_data(cls, storage_adapter) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Authoritative shared refresh operation for Google Sheets pipeline data.
        Fetches fresh opportunities, screening Q&A, and requirements extractions.
        Returns: (success: bool, message: str, data: dict)
        """
        if not storage_adapter or not getattr(storage_adapter, "is_connected", False):
            return False, "Google Sheets adapter is offline or not connected.", {}
        try:
            opps = storage_adapter.fetch_all_opportunities(force_refresh=True)
            qa = storage_adapter.fetch_screening_qa(force_refresh=True)
            reqs = storage_adapter.fetch_all_requirements_extractions(force_refresh=True)
            return True, "Pipeline data successfully refreshed from Google Sheets.", {
                "opportunities": opps,
                "qa": qa,
                "requirements": reqs
            }
        except Exception as err:
            return False, f"Could not refresh pipeline data from Google Sheets: {err}", {}

    @classmethod
    def has_job_signal_flags(cls, opp: Any) -> bool:
        """
        Determines whether an opportunity has one or more Job Signal flags.
        Reads from persisted 'Job Signals' JSON, gracefully handling missing,
        empty, or malformed data. Does not trigger on warnings or benefits.
        """
        if not opp:
            return False
        if isinstance(opp, dict):
            raw_signals = opp.get("Job Signals") or opp.get("job_signals")
            legacy_note = opp.get("Fit Warning") or opp.get("fit_warning") or ""
            telemetry_flags = opp.get("telemetry_flags")
        else:
            raw_signals = getattr(opp, "job_signals", None)
            legacy_note = getattr(opp, "fit_warning", "")
            telemetry_flags = getattr(opp, "telemetry_flags", None)

        try:
            flags, _, _ = TelemetryService.load_display_findings(raw_signals, legacy_note)
            if flags and len(flags) > 0:
                return True
        except Exception:
            pass

        if telemetry_flags and isinstance(telemetry_flags, list) and len(telemetry_flags) > 0:
            return True

        return False


