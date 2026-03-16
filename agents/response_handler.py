"""
Response Handling Agent
Classifies inbound replies and generates appropriate next actions / draft responses.
"""
from dataclasses import dataclass
from agents.base import BaseAgent


@dataclass
class ReplyAnalysis:
    classification: str  # interested | not_now | wrong_person | out_of_office | unsubscribe | objection | other
    sentiment: str       # positive | neutral | negative
    key_signals: list[str]
    draft_response: str
    next_action: str     # pause_sequence | reschedule | route_referral | flag_for_human | unsubscribe | continue
    reschedule_hint: str  # e.g. "Q2 2026" if they said "reach out in a few months"
    referral_name: str   # if wrong_person gave a referral
    objection_type: str  # pricing | timing | competitor | no_need | other


SYSTEM_PROMPT = """You are an expert sales AI that classifies and responds to prospect replies.

Classifications:
- interested: Positive engagement, wants to learn more or schedule
- not_now: Acknowledges value but wrong timing
- wrong_person: Not the right contact, may or may not give referral
- out_of_office: Auto-reply or manual OOO
- unsubscribe: Wants to be removed
- objection: Has a specific concern (pricing, competitor, timing, no need)
- other: Unclear or unrelated

Return ONLY valid JSON:
{
  "classification": "interested",
  "sentiment": "positive",
  "key_signals": ["asked about pricing", "mentioned specific use case"],
  "draft_response": "Full suggested reply email here...",
  "next_action": "flag_for_human",
  "reschedule_hint": "",
  "referral_name": "",
  "objection_type": ""
}

For 'interested': draft a warm reply that books a meeting.
For 'not_now': acknowledge timing, offer to reconnect at their specified date.
For 'wrong_person': ask for the right person's name/email.
For 'objection': address the objection directly and reframe value.
For 'unsubscribe': draft a polite confirmation of removal."""


class ResponseHandlerAgent(BaseAgent):
    """Classifies prospect replies and generates appropriate responses."""

    async def run(
        self,
        reply_content: str,
        prospect_name: str,
        company: str,
        sequence_context: str = "",
        sender_name: str = "Alex",
    ) -> ReplyAnalysis:

        user_msg = f"""Classify and respond to this reply:

FROM: {prospect_name} at {company}
REPLY:
{reply_content}

CONTEXT:
{sequence_context or "Cold outreach sequence, step 2"}

Sender name: {sender_name}"""

        text, cost, latency_ms = self.call_claude(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            model=self.MODEL_FAST,  # Classification uses Haiku for speed/cost
            max_tokens=1024,
        )

        data = self.parse_json(text)
        return ReplyAnalysis(
            classification=data.get("classification", "other"),
            sentiment=data.get("sentiment", "neutral"),
            key_signals=data.get("key_signals", []),
            draft_response=data.get("draft_response", ""),
            next_action=data.get("next_action", "continue"),
            reschedule_hint=data.get("reschedule_hint", ""),
            referral_name=data.get("referral_name", ""),
            objection_type=data.get("objection_type", ""),
        )
