from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from job_pipeline.domain.models import Touchpoint, StakeholderContact


class MessagingPort(ABC):
    """Abstract Port for Twilio SMS messaging, Smart Caller ID, and Voice Transcript ingestion."""

    @abstractmethod
    def send_sms(self, to_phone_number: str, message_body: str) -> bool:
        pass

    @abstractmethod
    def lookup_contact_by_phone(self, phone_number: str) -> Optional[StakeholderContact]:
        pass

    @abstractmethod
    def ingest_call_transcript(self, call_sid: str, raw_transcript: str) -> Touchpoint:
        pass
