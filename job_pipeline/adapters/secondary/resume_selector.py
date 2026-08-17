import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from job_pipeline.ports.resume_port import ResumeFileRef


class ResumeMatchResult(BaseModel):
    selected_resume: Optional[ResumeFileRef] = None
    match_score: float = 0.0
    match_reason: str = ""


class TitleBasedResumeSelector:
    """
    Title-based resume router.
    Scans candidate resume filenames in Google Drive matching convention: '<Name> <Role> Resume'.
    Matches role keywords against job title / title_family.
    """

    ROLE_MAPPINGS = {
        "revenue_operations": ["revops", "revenue operations", "rev ops", "revenue op"],
        "revenue_systems": ["revenue systems", "revsys", "rev sys", "salesforce", "systems analyst"],
        "business_analytics": ["business analyst", "business analytics", "data analyst", "analytics"],
        "gtm_engineering": ["gtm engineer", "gtm engineering", "revenue engineer", "solutions engineer"],
        "solutions_implementation": ["implementation", "solutions analyst", "integration"]
    }

    def select_resume(
        self,
        job_title: str,
        title_family: str,
        available_resumes: List[Dict[str, str]]
    ) -> ResumeMatchResult:
        if not available_resumes:
            return ResumeMatchResult(
                selected_resume=None,
                match_score=0.0,
                match_reason="No resume files available in Google Drive folder."
            )

        parsed_resumes: List[ResumeFileRef] = []
        for file in available_resumes:
            file_id = file.get("id") or file.get("doc_id", "")
            file_name = file.get("name") or file.get("filename", "")

            clean_name = re.sub(r'(?i)\b(resume|cv|doc)\b', '', file_name).strip()
            parsed_resumes.append(ResumeFileRef(
                doc_id=file_id,
                filename=file_name,
                role_label=clean_name
            ))

        job_title_lower = job_title.lower()
        title_family_lower = title_family.lower()

        best_resume = None
        best_score = -1.0
        best_reason = ""

        for resume in parsed_resumes:
            res_name_lower = resume.filename.lower()
            score = 0.0
            reasons = []

            family_keywords = self.ROLE_MAPPINGS.get(title_family_lower, [title_family_lower.replace("_", " ")])
            for kw in family_keywords:
                if kw in res_name_lower:
                    score += 0.5
                    reasons.append(f"Matched role family keyword '{kw}'")
                    break

            job_words = set(re.findall(r'\w+', job_title_lower)) - {"analyst", "senior", "lead", "junior", "manager", "specialist"}
            res_words = set(re.findall(r'\w+', res_name_lower))
            overlap = job_words.intersection(res_words)
            if overlap:
                score += len(overlap) * 0.2
                reasons.append(f"Matched title words: {', '.join(overlap)}")

            if score > best_score:
                best_score = score
                best_resume = resume
                best_reason = "; ".join(reasons) if reasons else "Default fallback match"

        if best_resume is None or best_score <= 0.0:
            best_resume = parsed_resumes[0]
            best_score = 0.1
            best_reason = f"Default fallback resume selection ('{best_resume.filename}')"

        return ResumeMatchResult(
            selected_resume=best_resume,
            match_score=round(min(best_score, 1.0), 2),
            match_reason=best_reason
        )
