import re
from typing import List, Optional, Dict, Any
from job_pipeline.domain.models import TargetPayBounds, FitEvaluation, CandidateProfile


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


class JobQualificationService:
    """Pure domain service for evaluating job fit, dealbreakers, and skill scores."""

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
        existing_company_titles: Optional[List[Dict[str, str]]] = None
    ) -> FitEvaluation:
        if profile is None:
            profile = CandidateProfile()

        warnings = []
        dealbreakers_found = []

        # 1. Duplicate Detection
        if existing_company_titles:
            norm_comp = company_name.lower().strip()
            norm_title = job_title.lower().strip()
            for item in existing_company_titles:
                if item.get("company", "").lower().strip() == norm_comp and item.get("title", "").lower().strip() == norm_title:
                    return FitEvaluation(
                        status="FLAGGED_DUPLICATE",
                        is_qualified=False,
                        warnings=["Duplicate application detected for this company and title."],
                        reasoning=f"Duplicate entry found: '{company_name} - {job_title}' was previously ingested."
                    )

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

        # 5. Determine Final Status
        if dealbreakers_found:
            status = "FLAGGED_DEALBREAKER"
            is_qualified = False
            reasoning = f"Flagged: Contains dealbreaker skills ({', '.join(dealbreakers_found)})."
        elif warnings and "below minimum floor" in " ".join(warnings):
            status = "FLAGGED_LOW_PAY"
            is_qualified = False
            reasoning = f"Flagged: Salary below candidate floor (${profile.minimum_compensation_floor:,.0f})."
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
            reasoning=reasoning
        )
