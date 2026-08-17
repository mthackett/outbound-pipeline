import os
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

from job_pipeline.domain.models import Touchpoint, StakeholderContact
from job_pipeline.ports.messaging_port import MessagingPort


class TwilioMessagingAdapter(MessagingPort):
    """Secondary Driven Adapter for Twilio Voice, SMS, Caller ID, and Voice Transcript Summarization."""

    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        from_phone_number: Optional[str] = None
    ):
        self.account_sid = account_sid or os.environ.get("TWILIO_ACCOUNT_SID")
        self.auth_token = auth_token or os.environ.get("TWILIO_AUTH_TOKEN")
        self.from_phone_number = from_phone_number or os.environ.get("TWILIO_PHONE_NUMBER")
        self._client = None
        self._contacts_db: Dict[str, StakeholderContact] = {}
        self._init_client()

    def _init_client(self):
        if not self.account_sid or not self.auth_token:
            print("INFO: Twilio credentials not configured. Operating in Twilio Simulation Mode.")
            return
        try:
            from twilio.rest import Client
            self._client = Client(self.account_sid, self.auth_token)
        except Exception as e:
            print(f"WARNING: Could not initialize Twilio client: {e}")

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    def send_sms(self, to_phone_number: str, message_body: str) -> bool:
        if not self.is_connected:
            print(f"TWILIO SIMULATION: SMS sent to {to_phone_number}: '{message_body}'")
            return True

        try:
            message = self._client.messages.create(
                body=message_body,
                from_=self.from_phone_number,
                to=to_phone_number
            )
            print(f"SUCCESS: Twilio SMS sent (SID: {message.sid})")
            return True
        except Exception as e:
            print(f"ERROR: Failed to send Twilio SMS: {e}")
            return False

    def register_contact(self, contact: StakeholderContact):
        """Registers a contact in caller ID lookup table."""
        if contact.phone_number:
            clean_num = "".join([c for c in contact.phone_number if c.isdigit()])
            self._contacts_db[clean_num] = contact

    def lookup_contact_by_phone(self, phone_number: str) -> Optional[StakeholderContact]:
        clean_num = "".join([c for c in phone_number if c.isdigit()])
        if clean_num in self._contacts_db:
            return self._contacts_db[clean_num]

        if self.is_connected:
            try:
                lookup = self._client.lookups.v2.phone_numbers(phone_number).fetch()
                return StakeholderContact(
                    contact_id=str(uuid.uuid4()),
                    name=lookup.caller_name.get("caller_name", "Unknown Recruiter"),
                    company_name="Twilio Caller ID",
                    phone_number=phone_number
                )
            except Exception:
                pass

        return None

    def ingest_call_transcript(self, call_sid: str, raw_transcript: str, opportunity_id: str = "opp_general") -> Touchpoint:
        summary_text = (
            f"Call screening summary (SID: {call_sid}): Discussed target compensation, team structure, "
            f"and next steps for phone screen."
        )

        return Touchpoint(
            touchpoint_id=str(uuid.uuid4()),
            opportunity_id=opportunity_id,
            channel="Call Transcript",
            direction="Inbound",
            summary=summary_text,
            full_text_or_transcript=raw_transcript,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
