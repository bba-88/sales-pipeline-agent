"""
Orchestrator
Coordinates the full prospect lifecycle.
New → Researching → Sequencing → Responded → Meeting Booked → Disqualified

IMPORTANT: Always instantiate with a fresh session (not the request-scoped one):
    async with AsyncSessionLocal() as db:
        orch = Orchestrator(db)
"""
import json
import logging
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import models
from database import AsyncSessionLocal
from agents.prospect_research import ProspectResearchAgent, ProspectInput
from agents.message_generation import MessageGenerationAgent
from agents.sequence_execution import SequenceExecutionAgent
from agents.response_handler import ResponseHandlerAgent
from agents.meeting_booking import MeetingBookingAgent
from agents.crm_sync import CRMSyncAgent
from config import settings

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.research_agent = ProspectResearchAgent()
        self.message_agent = MessageGenerationAgent()
        self.execution_agent = SequenceExecutionAgent()
        self.response_agent = ResponseHandlerAgent()
        self.booking_agent = MeetingBookingAgent()
        self.crm_agent = CRMSyncAgent()

    # ── Enroll ─────────────────────────────────────────────────────────────

    async def enroll_prospect(
        self,
        prospect: models.Prospect,
        campaign: models.Campaign,
    ) -> models.Sequence:
        """Full pipeline: research → generate sequence → persist."""
        await self._update_prospect_status(prospect, models.ProspectStatus.RESEARCHING)
        await self._log("Orchestrator", "enroll_start", {"prospect_id": prospect.id})

        # Step 1: Research
        try:
            profile = await self.research_agent.run(
                ProspectInput(
                    email=prospect.email,
                    first_name=prospect.first_name,
                    last_name=prospect.last_name,
                    company=prospect.company or "",
                    title=prospect.title or "",
                    domain=prospect.domain or prospect.email.split("@")[-1],
                    linkedin_url=prospect.linkedin_url or "",
                )
            )
        except Exception as exc:
            logger.error("Research failed for prospect %d: %s", prospect.id, exc)
            await self._log("ProspectResearchAgent", "error", {"error": str(exc), "prospect_id": prospect.id})
            raise

        # Persist research profile
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
        await self._log("ProspectResearchAgent", "research_complete", {"prospect_id": prospect.id, "score": profile.fit_score})

        # Step 2: Generate sequence
        try:
            sequence_data = await self.message_agent.run(
                prospect_name=f"{prospect.first_name} {prospect.last_name}",
                prospect_title=prospect.title or "Executive",
                company=prospect.company or "their company",
                profile=profile,
                value_prop=campaign.value_prop or "help you scale revenue with AI",
                sender_name=settings.sender_name,
                sender_company=settings.sender_company,
                tone=campaign.tone,
            )
        except Exception as exc:
            logger.error("Message generation failed for prospect %d: %s", prospect.id, exc)
            raise

        # Step 3: Persist sequence + steps
        sequence = models.Sequence(
            prospect_id=prospect.id,
            campaign_id=campaign.id,
            current_step=0,
            status=models.SequenceStatus.ACTIVE,
            next_action_at=datetime.utcnow(),  # Ready to send immediately
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
        await self._log("MessageGenerationAgent", "sequence_created", {"prospect_id": prospect.id, "steps": len(sequence_data.messages)})

        # Step 4: Sync to CRM
        await self.crm_agent.run("upsert_contact", {
            "email": prospect.email,
            "first_name": prospect.first_name,
            "last_name": prospect.last_name,
            "title": prospect.title,
            "company": prospect.company,
            "status": "SEQUENCING",
        })

        await self.db.refresh(sequence)
        return sequence

    # ── Execute next step ──────────────────────────────────────────────────

    async def execute_next_step(self, sequence: models.Sequence) -> bool:
        """Send the next pending step in a sequence. Returns True if sent."""
        if sequence.status != models.SequenceStatus.ACTIVE:
            return False

        # Load prospect
        p_result = await self.db.execute(
            select(models.Prospect).where(models.Prospect.id == sequence.prospect_id)
        )
        prospect = p_result.scalar_one_or_none()
        if not prospect:
            return False

        # Find next unsent step
        steps_result = await self.db.execute(
            select(models.SequenceStep)
            .where(
                models.SequenceStep.sequence_id == sequence.id,
                models.SequenceStep.sent_at.is_(None),
            )
            .order_by(models.SequenceStep.step_number)
            .limit(1)
        )
        step = steps_result.scalar_one_or_none()
        if not step:
            # All steps sent → complete
            sequence.status = models.SequenceStatus.COMPLETED
            sequence.completed_at = datetime.utcnow()
            await self.db.commit()
            return False

        # Send the step
        result = await self.execution_agent.run(
            to_email=prospect.email,
            to_name=f"{prospect.first_name} {prospect.last_name}",
            subject=step.subject or "",
            body=step.body or "",
            channel=step.channel.value if hasattr(step.channel, "value") else step.channel,
            step_number=step.step_number,
        )

        if result.success:
            step.sent_at = datetime.utcnow()
            sequence.current_step = step.step_number

            # Schedule next step (3-day default gap with some randomisation)
            sequence.next_action_at = datetime.utcnow() + timedelta(days=3)
            await self.db.commit()
            await self._log(
                "SequenceExecutionAgent",
                "step_sent",
                {
                    "prospect_id": prospect.id,
                    "step": step.step_number,
                    "channel": step.channel,
                    "mock": result.mock,
                },
            )
            # Sync activity to CRM
            await self.crm_agent.run("log_activity", {
                "type": "EMAIL" if step.channel == models.Channel.EMAIL else "LINKEDIN",
                "body": step.body,
                "timestamp": datetime.utcnow().isoformat(),
                "prospect_email": prospect.email,
            })
        else:
            logger.error("Step send failed: %s", result.error)
            await self._log("SequenceExecutionAgent", "step_failed", {"error": result.error})

        return result.success

    # ── Reply handling ─────────────────────────────────────────────────────

    async def handle_reply(
        self,
        reply: models.Reply,
        prospect: models.Prospect,
    ) -> models.Reply:
        """Classify a reply and take the appropriate automated action."""
        # Load sequence context
        seq_result = await self.db.execute(
            select(models.Sequence).where(
                models.Sequence.prospect_id == prospect.id,
                models.Sequence.status.in_([
                    models.SequenceStatus.ACTIVE,
                    models.SequenceStatus.PAUSED,
                ]),
            ).order_by(models.Sequence.created_at.desc()).limit(1)
        )
        sequence = seq_result.scalar_one_or_none()
        context = f"Step {sequence.current_step} of outreach sequence" if sequence else "Cold outreach"

        analysis = await self.response_agent.run(
            reply_content=reply.raw_content,
            prospect_name=f"{prospect.first_name} {prospect.last_name}",
            company=prospect.company or "",
            sequence_context=context,
            sender_name=settings.sender_name,
        )

        reply.classification = models.ReplyClassification(analysis.classification)
        reply.sentiment = analysis.sentiment
        reply.draft_response = analysis.draft_response

        # State transitions
        action_map = {
            "interested": models.ProspectStatus.RESPONDED,
            "not_now": models.ProspectStatus.SEQUENCING,
            "wrong_person": models.ProspectStatus.NEW,
            "unsubscribe": models.ProspectStatus.DISQUALIFIED,
            "objection": models.ProspectStatus.RESPONDED,
            "out_of_office": models.ProspectStatus.SEQUENCING,
            "other": models.ProspectStatus.RESPONDED,
        }
        new_status = action_map.get(analysis.classification, models.ProspectStatus.RESPONDED)
        await self._update_prospect_status(prospect, new_status)

        # Pause sequences for interested/objection
        if analysis.classification in ("interested", "objection"):
            await self._pause_sequences(prospect.id)

        # Schedule re-engage for "not_now"
        if analysis.classification == "not_now" and sequence:
            sequence.next_action_at = datetime.utcnow() + timedelta(days=60)
            sequence.status = models.SequenceStatus.PAUSED

        # Handle interested → trigger meeting booking
        if analysis.classification == "interested":
            await self._trigger_meeting_booking(prospect, reply.raw_content)

        # Unsubscribe: suppress from all future outreach
        if analysis.classification == "unsubscribe":
            await self._cancel_all_sequences(prospect.id)

        await self.db.commit()
        await self._log("ResponseHandlerAgent", "reply_classified", {
            "prospect_id": prospect.id,
            "classification": analysis.classification,
            "sentiment": analysis.sentiment,
        })

        # Sync reply to CRM
        await self.crm_agent.run("log_activity", {
            "type": "REPLY",
            "body": reply.raw_content,
            "classification": analysis.classification,
            "timestamp": datetime.utcnow().isoformat(),
        })

        return reply

    # ── Meeting booking ────────────────────────────────────────────────────

    async def _trigger_meeting_booking(
        self,
        prospect: models.Prospect,
        interest_signal: str,
    ) -> None:
        booking = await self.booking_agent.run(
            prospect_name=f"{prospect.first_name} {prospect.last_name}",
            company=prospect.company or "",
            interest_signal=interest_signal,
        )

        # Store booking as a meeting record
        meeting = models.Meeting(
            prospect_id=prospect.id,
            calendly_event_id=booking.event_id or "pending",
        )
        self.db.add(meeting)

        # Update prospect status
        prospect.status = models.ProspectStatus.MEETING_BOOKED
        await self.db.commit()

        # Enrich the draft_response on the latest reply with the booking link
        reply_result = await self.db.execute(
            select(models.Reply)
            .where(models.Reply.prospect_id == prospect.id)
            .order_by(models.Reply.created_at.desc())
            .limit(1)
        )
        latest_reply = reply_result.scalar_one_or_none()
        if latest_reply:
            latest_reply.draft_response = booking.reply_draft
            await self.db.commit()

        await self._log("MeetingBookingAgent", "booking_triggered", {
            "prospect_id": prospect.id,
            "booking_link": booking.booking_link,
            "mock": booking.mock,
        })

        # Create deal in CRM
        await self.crm_agent.run("create_deal", {
            "company": prospect.company,
            "email": prospect.email,
        })

    # ── Helpers ────────────────────────────────────────────────────────────

    async def _update_prospect_status(
        self, prospect: models.Prospect, status: models.ProspectStatus
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

    async def _cancel_all_sequences(self, prospect_id: int) -> None:
        result = await self.db.execute(
            select(models.Sequence).where(
                models.Sequence.prospect_id == prospect_id,
                models.Sequence.status.in_([
                    models.SequenceStatus.ACTIVE,
                    models.SequenceStatus.PAUSED,
                ]),
            )
        )
        for seq in result.scalars().all():
            seq.status = models.SequenceStatus.CANCELLED
        await self.db.commit()

    async def _log(self, agent: str, action: str, data: dict) -> None:
        log = models.AuditLog(
            agent_name=agent,
            action=action,
            input_data=json.dumps(data, default=str),
            prospect_id=data.get("prospect_id"),
            created_at=datetime.utcnow(),
        )
        self.db.add(log)
        await self.db.commit()


# ── Standalone factory: creates its own session (safe for background tasks) ──

async def run_enrollment_background(prospect_id: int, campaign_id: int) -> None:
    """Entry point for background tasks — creates its own DB session."""
    async with AsyncSessionLocal() as db:
        p_result = await db.execute(
            select(models.Prospect).where(models.Prospect.id == prospect_id)
        )
        prospect = p_result.scalar_one_or_none()
        c_result = await db.execute(
            select(models.Campaign).where(models.Campaign.id == campaign_id)
        )
        campaign = c_result.scalar_one_or_none()
        if not prospect or not campaign:
            logger.error("Enrollment: prospect %d or campaign %d not found", prospect_id, campaign_id)
            return
        orch = Orchestrator(db)
        await orch.enroll_prospect(prospect, campaign)
        logger.info("Enrollment complete for prospect %d", prospect_id)


async def run_sequence_step_background(sequence_id: int) -> None:
    """Execute next step for a sequence — creates its own DB session."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(models.Sequence).where(models.Sequence.id == sequence_id)
        )
        sequence = result.scalar_one_or_none()
        if not sequence:
            return
        orch = Orchestrator(db)
        await orch.execute_next_step(sequence)
