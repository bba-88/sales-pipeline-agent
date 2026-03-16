"""
Prospect Research Agent
Enriches raw contact data into a rich prospect profile with personalization hooks.
In prototype mode: uses Claude to synthesize a realistic profile from available data.
Production mode: calls LinkedIn, Crunchbase, Hunter.io, News APIs.
"""
import json
from dataclasses import dataclass
from agents.base import BaseAgent
from config import settings


@dataclass
class ProspectInput:
    email: str
    first_name: str
    last_name: str
    company: str
    title: str = ""
    domain: str = ""
    linkedin_url: str = ""


@dataclass
class ProspectProfile:
    funding_stage: str
    employee_count: str
    tech_stack: list[str]
    recent_hires: list[str]
    pain_signals: list[str]
    recent_news: list[str]
    open_roles: list[str]
    personalization_hooks: list[str]
    fit_score: int  # 0-100
    research_summary: str


SYSTEM_PROMPT = """You are an expert B2B sales researcher. Given basic prospect info,
synthesize a realistic and detailed prospect profile as if you had researched their
LinkedIn, company website, Crunchbase, and recent news.

Return ONLY valid JSON matching this exact schema:
{
  "funding_stage": "Series B",
  "employee_count": "150-200",
  "tech_stack": ["Salesforce", "Slack", "AWS"],
  "recent_hires": ["VP of Sales hired 3 months ago", "Expanding AE team"],
  "pain_signals": ["Switching from legacy CRM", "Rapid headcount growth"],
  "recent_news": ["Raised $20M Series B in Jan 2026", "Expanding to EMEA"],
  "open_roles": ["Account Executive x5", "Sales Operations Manager"],
  "personalization_hooks": [
    "Just raised Series B — likely scaling sales team aggressively",
    "Hiring 5 AEs suggests they need pipeline infrastructure",
    "Using legacy CRM = pain around data hygiene",
    "EMEA expansion = new market entry challenges"
  ],
  "fit_score": 87,
  "research_summary": "2-3 sentence summary of why this is a strong prospect"
}"""


class ProspectResearchAgent(BaseAgent):
    """Enriches a prospect with deep research and personalization hooks."""

    async def run(self, prospect: ProspectInput) -> ProspectProfile:
        # In production: hit LinkedIn, Crunchbase, Hunter, News APIs in parallel
        # In prototype: Claude synthesizes a realistic profile
        if self._has_real_apis():
            return await self._research_with_apis(prospect)
        return await self._research_with_claude(prospect)

    def _has_real_apis(self) -> bool:
        return bool(settings.crunchbase_api_key or settings.hunter_api_key)

    async def _research_with_claude(self, prospect: ProspectInput) -> ProspectProfile:
        """Use Claude to synthesize a realistic prospect profile (prototype mode)."""
        user_msg = f"""Research this prospect and return their profile:

Name: {prospect.first_name} {prospect.last_name}
Title: {prospect.title}
Company: {prospect.company}
Domain: {prospect.domain or prospect.email.split('@')[-1]}
Email: {prospect.email}
LinkedIn: {prospect.linkedin_url or 'unknown'}

Synthesize a realistic profile based on what you'd find if you researched this person."""

        text, cost, latency_ms = self.call_claude(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            model=self.MODEL_PRIMARY,
            max_tokens=1024,
        )

        data = self.parse_json(text)
        return ProspectProfile(
            funding_stage=data.get("funding_stage", "Unknown"),
            employee_count=data.get("employee_count", "Unknown"),
            tech_stack=data.get("tech_stack", []),
            recent_hires=data.get("recent_hires", []),
            pain_signals=data.get("pain_signals", []),
            recent_news=data.get("recent_news", []),
            open_roles=data.get("open_roles", []),
            personalization_hooks=data.get("personalization_hooks", []),
            fit_score=data.get("fit_score", 50),
            research_summary=data.get("research_summary", ""),
        )

    async def _research_with_apis(self, prospect: ProspectInput) -> ProspectProfile:
        """Production: parallel API calls to enrich prospect data."""
        # TODO: implement LinkedIn, Crunchbase, Hunter, News API calls
        raise NotImplementedError("Real API enrichment not yet implemented")
