from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from job_pipeline.domain.models import RoleIntelligenceReport


class LLMStrategyPort(ABC):
    """Abstract Port for LLM value match strategy and report composition."""

    @abstractmethod
    def generate_role_intelligence_report(
        self,
        job_data: Dict[str, Any],
        resume_data: Dict[str, Any],
        output_docx_path: str,
        target_pay_bounds: Optional[Dict[str, Any]] = None,
        demo_mode: bool = False
    ) -> RoleIntelligenceReport:
        pass
