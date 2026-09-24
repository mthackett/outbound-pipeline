import re
import difflib
from typing import List, Dict, Any, Optional
from job_pipeline.domain.models import ScreeningMatchResult, SCREENING_ARCHETYPES


class ScreeningIntelligenceService:
    """
    Intelligence service for application screening questions.
    Provides archetype classification, competency signal extraction,
    lexical/token similarity scoring, and prior-answer recall.
    """

    ARCHETYPE_RULES: Dict[str, List[str]] = {
        "COMPENSATION": [
            "salary", "compensation", "pay", "rate", "hourly", "base", "remuneration", "target cash", "range"
        ],
        "WORK_AUTHORIZATION": [
            "visa", "sponsorship", "citizen", "authorized to work", "authorization", "green card", "us work", "sponsor"
        ],
        "TECHNICAL_STACK": [
            "sql", "salesforce", "dbt", "python", "tableau", "power bi", "hubspot", "bigquery", "postgres", "looker",
            "api", "excel", "sheets", "clari", "gong", "marketo", "workato", "zapier", "etl", "elt", "data stack"
        ],
        "EXPERIENCE_DOMAIN": [
            "years of experience", "years in", "revops", "sales ops", "revenue operations", "gtm", "b2b", "saas",
            "funnel", "lifecycle", "attribution", "pipeline", "forecasting", "territory", "quota"
        ],
        "REMOTE_LOCATION": [
            "remote", "hybrid", "onsite", "relocate", "relocation", "travel", "location", "commute", "timezone", "located"
        ],
        "BEHAVIORAL_MOTIVATION": [
            "why this role", "why do you want", "why our company", "interest in", "motivate", "proudest", "career goals"
        ],
        "LEADERSHIP_CONFLICT": [
            "conflict", "stakeholder", "cross-functional", "pushback", "disagreement", "alignment", "leadership", "influence"
        ],
        "PROCESS_GOVERNANCE": [
            "agile", "scrum", "sprint", "governance", "documentation", "compliance", "methodology", "data hygiene"
        ],
        "QUESTIONS_FOR_COMPANY": [
            "questions for us", "questions do you have", "ask us", "anything you want to ask"
        ]
    }

    COMPETENCY_ONTOLOGY: Dict[str, List[str]] = {
        "SQL": ["sql", "queries", "joins", "subqueries", "window functions", "stored procedures"],
        "dbt": ["dbt", "data build tool", "semantic layer"],
        "Salesforce": ["salesforce", "sfdc", "soql", "cpq", "flow"],
        "HubSpot": ["hubspot", "crm workflow", "marketing hub"],
        "Python": ["python", "pandas", "numpy", "scripts"],
        "Data Modeling": ["data model", "data models", "data modeling", "modeling", "star schema", "dimensional", "normalization", "warehousing"],
        "BI & Visualization": ["tableau", "power bi", "looker", "dashboards", "reporting"],
        "BigQuery / Cloud DW": ["bigquery", "snowflake", "redshift", "cloud warehouse"],
        "Pipeline Diagnostics": ["pipeline", "funnel", "conversion", "leakage", "diagnostics"],
        "Lead Routing & SLAs": ["lead routing", "sla", "round robin", "lead distribution"],
        "Attribution Modeling": ["attribution", "multi-touch", "first touch", "marketing roi"],
        "Stakeholder Management": ["stakeholder", "cross-functional", "alignment", "executive", "influence"],
        "Compensation Realism": ["salary", "compensation", "rate", "hourly", "target pay"]
    }

    STOPWORDS = {
        "what", "is", "your", "are", "the", "a", "an", "for", "with", "in", "of", "to", "and", "or",
        "do", "you", "have", "how", "many", "years", "describe", "please", "tell", "us", "about"
    }

    @classmethod
    def classify_archetype(cls, question_text: str) -> str:
        """Classifies a question prompt into a canonical archetype code."""
        if not question_text:
            return "GENERAL"
        
        q_lower = question_text.lower()

        # Check explicit keywords
        for archetype, keywords in cls.ARCHETYPE_RULES.items():
            for kw in keywords:
                if re.search(r'\b' + re.escape(kw) + r'\b', q_lower):
                    return archetype

        return "GENERAL"

    @classmethod
    def extract_competency_signals(cls, question_text: str) -> List[str]:
        """Extracts candidate competencies tested by the screening question."""
        if not question_text:
            return []

        q_lower = question_text.lower()
        signals: List[str] = []

        for competency, triggers in cls.COMPETENCY_ONTOLOGY.items():
            for trigger in triggers:
                if re.search(r'\b' + re.escape(trigger) + r'\b', q_lower):
                    signals.append(competency)
                    break

        return signals

    @classmethod
    def _tokenize(cls, text: str) -> set:
        """Helper to extract normalized, non-stopword tokens."""
        words = re.findall(r'\b[a-z0-9_]+\b', text.lower())
        return {w for w in words if w not in cls.STOPWORDS and len(w) > 1}

    @classmethod
    def calculate_similarity(cls, query: str, target: str) -> float:
        """
        Computes composite similarity between two question prompts.
        Uses 60% difflib sequence ratio + 40% Jaccard token overlap.
        """
        if not query or not target:
            return 0.0

        q_clean = query.strip().lower()
        t_clean = target.strip().lower()

        # 1. Exact or near-exact string match
        if q_clean == t_clean:
            return 1.0

        # 2. Sequence matcher ratio
        seq_ratio = difflib.SequenceMatcher(None, q_clean, t_clean).ratio()

        # 3. Token Jaccard similarity
        q_tokens = cls._tokenize(q_clean)
        t_tokens = cls._tokenize(t_clean)

        if not q_tokens or not t_tokens:
            jaccard = 0.0
        else:
            intersection = q_tokens.intersection(t_tokens)
            union = q_tokens.union(t_tokens)
            jaccard = len(intersection) / len(union) if union else 0.0

        composite = (0.6 * seq_ratio) + (0.4 * jaccard)
        return round(composite, 3)

    @classmethod
    def find_similar_questions(
        cls,
        query: str,
        history: List[Dict[str, Any]],
        threshold: float = 0.40,
        top_k: int = 3
    ) -> List[ScreeningMatchResult]:
        """
        Scans historical screening questions and returns matches exceeding threshold.
        """
        if not query or not query.strip() or not history:
            return []

        results: List[ScreeningMatchResult] = []

        for item in history:
            target_q = item.get("question") or item.get("Question") or ""
            target_ans = item.get("answer") or item.get("Answer") or ""
            company = item.get("company_name") or item.get("Company Name") or ""
            date_created = item.get("timestamp") or item.get("created_at") or ""

            if not target_q or not target_ans:
                continue

            score = cls.calculate_similarity(query, target_q)
            if score >= threshold:
                arch = cls.classify_archetype(target_q)
                comp_signals = cls.extract_competency_signals(target_q)

                results.append(ScreeningMatchResult(
                    query=query,
                    matched_question=target_q,
                    matched_answer=target_ans,
                    similarity_score=score,
                    archetype=arch,
                    company_name=company,
                    created_at=date_created,
                    competency_signals=comp_signals
                ))

        # Sort by similarity score descending
        results.sort(key=lambda r: r.similarity_score, reverse=True)
        return results[:top_k]

    @classmethod
    def group_by_archetype(cls, qa_list: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Groups a list of screening QA records by canonical archetype."""
        grouped: Dict[str, List[Dict[str, Any]]] = {
            arch_key: [] for arch_key in SCREENING_ARCHETYPES.keys()
        }

        for item in qa_list:
            q_text = item.get("question") or item.get("Question") or ""
            arch = item.get("archetype") or cls.classify_archetype(q_text)
            if arch not in grouped:
                grouped[arch] = []
            
            # Enrich item with archetype and competencies if missing
            enriched = dict(item)
            enriched["archetype"] = arch
            enriched["archetype_name"] = SCREENING_ARCHETYPES.get(arch, "General Inquiries")
            if "competency_signals" not in enriched:
                enriched["competency_signals"] = cls.extract_competency_signals(q_text)

            grouped[arch].append(enriched)

        return grouped
