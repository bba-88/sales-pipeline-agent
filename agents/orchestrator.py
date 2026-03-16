"""
Orchestrator
Coordinates the full prospect lifecycle through the state machine.
New → Researching → Sequencing → Responded → Meeting Booked → Disqualified
"""
import json
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import models
from agents.prospect_research import ProspectResearchAgent, ProspectInput
from agents.message_generation import MessageGenerationAgent
from agents.response_handler import ResponseHandlerAgent


class Orchestrator:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.research_agent = ProspectResearchAgent()
        self.message_agent = MessageGenerationAgent()
        self.response_agent = ResponseHandlerAgent()

    async def enroll_prospect(
        self,
        prospect: models.Prospect,
        campaign: models.Campaign,
    ) -> models.Sequence:
        """Full pipeline: research → generate sequence → enroll."""
        await self._update_prospect_status(prospect, models.ProspectStatus.RESEARCHING)
        await self._log("Orchestrator", "enroll_prospect", {"prospect_id": prospect.id})

        # Step 1: Research
        profile = await self.research_agent.run(
            ProspectInput(
                email=prospect.email,
                first_name=prospect.first_name,
                last_name=prospect.last_name,
                company=prospect.company or "",
                title=prospect.title or "",
                domain=prospect.domain or "",
                linkedin_url=prospect.linkedin_url or "",
            )
        )

        # Persist research
        prospect.research_profile = json.dumps({
            "funding_stage": profile.funding_stage,
            "employee_count": profile.employee_count,
            "tech_stack": profile.tech_stack,
            "recent_hires": profile.recent_hires,
            "pain_signals": profile.pain_signals,
            "recent_news": profile.recent_news,
            "open_roles": profile.open_roles,
            "research_summary": profile.research_summary,
        })
        prospect.personalization_hooks = json.dumps(profile.personalization_hooks)
        prospect.score = profile.fit_score
        await self.db.commit()

        # Step 2: Generate sequence
        sequence_data = await self.message_agent.run(
            prospect_name=f"{prospect.first_name} {prospect.last_name}",
            prospect_title=prospect.title or "Executive",
            company=prospect.company or "their company",
            profile=profile,
            value_prop=campaign.value_prop or "help you scale revenue with AI",
            tone=campaign.tone,
        )

        # Step 3: Persist sequence + steps
        sequence = models.Sequence(
            prospect_id=prospect.id,
            campaign_id=campaign.id,
            current_step=0,
            status=models.SequenceStatus.ACTIVE,
        )
        self.db.add(sequence)
        await self.db.flush()

        for msg in sequence_data.messages:
            step = models.SequenceStep(
                sequence_id=sequence.id,
                step_number=msg.step,
                channel=models.Channel(msg.channel),
                subject=msg.subject,
                body=msg.body,
            )
            self.db.add(step)

        await self._update_prospect_status(prospect, models.ProspectStatus.SEQUENCING)
        await self.db.commit()
        await self.db.refresh(sequence)
        return sequence

    async def handle_reply(
        self,
        reply: models.Reply,
        prospect: models.Prospect,
    ) -> models.Reply:
        """Classify a reply and take the appropriate automated action."""
        analysis = await self.response_agent.run(
            reply_content=reply.raw_content,
            prospect_name=f"{prospect.first_name} {prospect.last_name}",
            company=prospect.company or "",
        )

        reply.classification = models.ReplyClassification(analysis.classification)
        reply.sentiment = analysis.sentiment
        reply.draft_response = analysis.draft_response

        # State transitions based on classification
        action_map = {
            "interested": models.ProspectStatus.RESPONDED,
            "not_now": models.ProspectStatus.SEQUENCING,
            "wrong_person": models.ProspectStatus.NEW,
            "unsubscribe": models.ProspectStatus.DISQUALIFIED,
            "objection": models.ProspectStatus.RESPONDED,
            "other": models.ProspectStatus.RESPONDED,
        }
        new_status = action_map.get(analysis.classification, models.ProspectStatus.RESPONDED)
        await self._update_prospect_status(prospect, new_status)

        # Pause active sequences for interested/objection replies
        if analysis.classification in ("interested", "objection"):
            await self._pause_sequences(prospect.id)

        await self.db.commit()
        return reply

    async def _update_prospect_status(
        self,
        prospect: models.Prospect,
        status: models.ProspectStatus,
    ) -> None:
        prospect.status = status
        prospect.updated_at = datetime.utcnow()
        await self.db.commit()

    async def _pause_sequences(self, prospect_id: int) -> None:
        result = await self.db.execute(
            select(models.Sequence).where(
                models.Sequence.prospect_id == prospect_id,
                models.Sequence.status == models.SequenceStatus.ACTIVE,
            )
        )
        for seq in result.scalars().all():
            seq.status = models.SequenceStatus.PAUSED
        await self.db.commit()

    async def _log(self, agent: str, action: str, data: dict) -> None:
        log = models.AuditLog(
            agent_name=agent,
            action=action,
            input_data=json.dumps(data),
            created_at=datetime.utcnow(),
        )
        self.db.add(log)
        await self.db.commit()
