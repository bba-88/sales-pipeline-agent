"""
Message Generation Agent
Writes a hyper-personalized multi-touch outreach sequence for a prospect.
"""
from dataclasses import dataclass
from agents.base import BaseAgent
from agents.prospect_research import ProspectProfile


@dataclass
class SequenceMessage:
    step: int
    channel: str  # "email" | "linkedin"
    subject: str
    body: str
    delay_days: int  # days after previous step


@dataclass
class OutreachSequence:
    messages: list[SequenceMessage]
    primary_hook: str
    value_angle: str


SYSTEM_PROMPT = """You are an expert B2B sales copywriter who writes cold outreach that gets replies.

Your sequences:
- Lead with a specific, researched observation (not a generic opener)
- Connect their situation to a concrete pain/opportunity
- Make a low-friction CTA (not "let's jump on a call" on step 1)
- Are conversational and brief (under 150 words per email)
- Escalate urgency/value across the sequence

Return ONLY valid JSON:
{
  "primary_hook": "The single strongest personalization angle",
  "value_angle": "Core value prop most relevant to this prospect",
  "messages": [
    {
      "step": 1,
      "channel": "email",
      "subject": "Subject line here",
      "body": "Full email body here",
      "delay_days": 0
    },
    {
      "step": 2,
      "channel": "linkedin",
      "subject": "",
      "body": "LinkedIn connection message (under 300 chars)",
      "delay_days": 2
    },
    ...
  ]
}

Generate a 5-step sequence: email, linkedin, email, email, linkedin."""


class MessageGenerationAgent(BaseAgent):
    """Generates a personalized multi-touch outreach sequence."""

    async def run(
        self,
        prospect_name: str,
        prospect_title: str,
        company: str,
        profile: ProspectProfile,
        value_prop: str,
        sender_name: str = "Alex",
        sender_company: str = "your company",
        tone: str = "professional",
    ) -> OutreachSequence:

        hooks_text = "\n".join(f"- {h}" for h in profile.personalization_hooks)
        pain_text = "\n".join(f"- {p}" for p in profile.pain_signals)

        user_msg = f"""Write a 5-step outreach sequence for this prospect:

PROSPECT:
- Name: {prospect_name}
- Title: {prospect_title}
- Company: {company}
- Funding stage: {profile.funding_stage}
- Employee count: {profile.employee_count}
- Tech stack: {', '.join(profile.tech_stack)}

RESEARCH INSIGHTS:
Personalization hooks:
{hooks_text}

Pain signals:
{pain_text}

Recent news: {', '.join(profile.recent_news)}

SENDER:
- Name: {sender_name}
- Company: {sender_company}
- Value prop: {value_prop}
- Tone: {tone}

Use the strongest hook as the opening. Make each step distinct in angle."""

        text, cost, latency_ms = self.call_claude(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            model=self.MODEL_PRIMARY,
            max_tokens=2048,
        )

        data = self.parse_json(text)
        messages = [
            SequenceMessage(
                step=m["step"],
                channel=m["channel"],
                subject=m.get("subject", ""),
                body=m["body"],
                delay_days=m.get("delay_days", 3),
            )
            for m in data["messages"]
        ]

        return OutreachSequence(
            messages=messages,
            primary_hook=data.get("primary_hook", ""),
            value_angle=data.get("value_angle", ""),
        )
