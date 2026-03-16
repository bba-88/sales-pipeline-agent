"""
Meeting Booking Agent
Handles scheduling from interested reply → confirmed calendar invite.
Integrates with Calendly (real) or mock mode for demo.
"""
import logging
from dataclasses import dataclass
from agents.base import BaseAgent
from config import settings

logger = logging.getLogger(__name__)


@dataclass
class BookingResult:
    booking_link: str
    reply_draft: str
    event_id: str = ""
    mock: bool = False


SYSTEM_PROMPT = """You are a helpful sales assistant scheduling a discovery call.
Write a warm, brief reply (under 80 words) that:
1. Acknowledges their interest enthusiastically but not over-the-top
2. Embeds the booking link naturally (use {BOOKING_LINK} placeholder)
3. Mentions a specific benefit or agenda item to get them excited
4. Signs off with the sender's name

Return ONLY the email body text, no subject line, no JSON."""


class MeetingBookingAgent(BaseAgent):
    """Generates booking links and drafts meeting scheduling replies."""

    async def run(
        self,
        prospect_name: str,
        company: str,
        interest_signal: str = "",
        sender_name: str | None = None,
    ) -> BookingResult:
        name = sender_name or settings.sender_name

        if settings.calendly_api_key:
            return await self._book_via_calendly(prospect_name, company, interest_signal, name)
        return await self._mock_booking(prospect_name, company, interest_signal, name)

    async def _book_via_calendly(
        self,
        prospect_name: str,
        company: str,
        interest_signal: str,
        sender_name: str,
    ) -> BookingResult:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.calendly.com/event_types",
                    headers={"Authorization": f"Bearer {settings.calendly_api_key}"},
                    timeout=10,
                )
                resp.raise_for_status()
                event_types = resp.json().get("collection", [])
                booking_link = (
                    event_types[0]["scheduling_url"]
                    if event_types
                    else settings.calendly_link
                )

            reply = await self._draft_reply(prospect_name, company, interest_signal, sender_name, booking_link)
            return BookingResult(booking_link=booking_link, reply_draft=reply, mock=False)
        except Exception as exc:
            logger.error("Calendly API error: %s", exc)
            return await self._mock_booking(prospect_name, company, interest_signal, sender_name)

    async def _mock_booking(
        self,
        prospect_name: str,
        company: str,
        interest_signal: str,
        sender_name: str,
    ) -> BookingResult:
        booking_link = settings.calendly_link
        reply = await self._draft_reply(prospect_name, company, interest_signal, sender_name, booking_link)
        return BookingResult(booking_link=booking_link, reply_draft=reply, mock=True)

    async def _draft_reply(
        self,
        prospect_name: str,
        company: str,
        interest_signal: str,
        sender_name: str,
        booking_link: str,
    ) -> str:
        first_name = prospect_name.split()[0]
        user_msg = (
            f"Prospect: {first_name} at {company}\n"
            f"Their signal: {interest_signal or 'Expressed interest in learning more'}\n"
            f"My name: {sender_name}\n"
            f"Booking link: {booking_link}"
        )
        text, _, _ = self.call_claude(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            model=self.MODEL_FAST,
            max_tokens=300,
        )
        return text.replace("{BOOKING_LINK}", booking_link)
