import csv
import io
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import models
from database import get_db
from agents.orchestrator import (
    Orchestrator,
    run_enrollment_background,
    run_sequence_step_background,
)

router = APIRouter(prefix="/prospects", tags=["prospects"])


class ProspectCreate(BaseModel):
    email: str
    first_name: str
    last_name: str
    title: str = ""
    company: str = ""
    domain: str = ""
    linkedin_url: str = ""
    campaign_id: int | None = None

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v:
            raise ValueError("Invalid email address")
        return v


class ProspectResponse(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    title: str | None
    company: str | None
    status: str
    score: int | None
    personalization_hooks: list[str]
    research_profile: dict | None
    created_at: datetime

    class Config:
        from_attributes = True


class ReplySubmit(BaseModel):
    content: str
    channel: str = "email"


class ApprovalDecision(BaseModel):
    approved: bool
    note: str = ""


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[ProspectResponse])
async def list_prospects(
    campaign_id: int | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(models.Prospect).order_by(models.Prospect.created_at.desc())
    if campaign_id:
        query = query.where(models.Prospect.campaign_id == campaign_id)
    if status:
        query = query.where(models.Prospect.status == status)
    result = await db.execute(query)
    return [_to_response(p) for p in result.scalars().all()]


@router.get("/{prospect_id}", response_model=ProspectResponse)
async def get_prospect(prospect_id: int, db: AsyncSession = Depends(get_db)):
    prospect = await _get_or_404(db, prospect_id)
    return _to_response(prospect)


@router.post("/", response_model=ProspectResponse)
async def create_prospect(data: ProspectCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(models.Prospect).where(models.Prospect.email == data.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Prospect with this email already exists")
    prospect = models.Prospect(**data.model_dump())
    db.add(prospect)
    await db.commit()
    await db.refresh(prospect)
    return _to_response(prospect)


# ── CSV bulk import ───────────────────────────────────────────────────────────

@router.post("/bulk")
async def bulk_import(
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Import prospects from CSV text.
    Payload: { "csv_text": "...", "campaign_id": 1 }
    CSV columns (header required): email, first_name, last_name, title, company, linkedin_url
    """
    csv_text: str = payload.get("csv_text", "")
    campaign_id: int | None = payload.get("campaign_id")

    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    created, skipped, errors = 0, 0, []

    for row in reader:
        email = row.get("email", "").strip().lower()
        if not email or "@" not in email:
            errors.append(f"Invalid email: {row}")
            continue
        existing = await db.execute(
            select(models.Prospect).where(models.Prospect.email == email)
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue
        prospect = models.Prospect(
            email=email,
            first_name=row.get("first_name", "").strip(),
            last_name=row.get("last_name", "").strip(),
            title=row.get("title", "").strip(),
            company=row.get("company", "").strip(),
            linkedin_url=row.get("linkedin_url", "").strip(),
            campaign_id=campaign_id,
        )
        db.add(prospect)
        created += 1

    await db.commit()
    return {"created": created, "skipped": skipped, "errors": errors}


# ── Enroll ────────────────────────────────────────────────────────────────────

@router.post("/{prospect_id}/enroll")
async def enroll_prospect(
    prospect_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Kick off full AI pipeline in background (uses its own DB session — no session leak)."""
    prospect = await _get_or_404(db, prospect_id)
    if not prospect.campaign_id:
        raise HTTPException(status_code=400, detail="Prospect must be assigned to a campaign first")

    # Validate campaign exists
    c_result = await db.execute(
        select(models.Campaign).where(models.Campaign.id == prospect.campaign_id)
    )
    if not c_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Mark as researching immediately (visual feedback)
    prospect.status = models.ProspectStatus.RESEARCHING
    await db.commit()

    # Background task uses its OWN session — fixes the critical DB session bug
    background_tasks.add_task(run_enrollment_background, prospect_id, prospect.campaign_id)
    return {"message": "Enrollment started", "prospect_id": prospect_id}


@router.post("/{prospect_id}/send-next-step")
async def send_next_step(
    prospect_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger sending the next sequence step."""
    seq_result = await db.execute(
        select(models.Sequence).where(
            models.Sequence.prospect_id == prospect_id,
            models.Sequence.status == models.SequenceStatus.ACTIVE,
        ).order_by(models.Sequence.created_at.desc()).limit(1)
    )
    sequence = seq_result.scalar_one_or_none()
    if not sequence:
        raise HTTPException(status_code=404, detail="No active sequence found for this prospect")

    background_tasks.add_task(run_sequence_step_background, sequence.id)
    return {"message": "Sending next step", "sequence_id": sequence.id}


# ── Reply handling ────────────────────────────────────────────────────────────

@router.post("/{prospect_id}/reply")
async def submit_reply(
    prospect_id: int,
    data: ReplySubmit,
    db: AsyncSession = Depends(get_db),
):
    """Submit an inbound reply for immediate AI classification."""
    prospect = await _get_or_404(db, prospect_id)

    reply = models.Reply(
        prospect_id=prospect_id,
        channel=models.Channel(data.channel),
        raw_content=data.content,
    )
    db.add(reply)
    await db.commit()
    await db.refresh(reply)

    orch = Orchestrator(db)
    reply = await orch.handle_reply(reply, prospect)

    return {
        "id": reply.id,
        "classification": reply.classification,
        "sentiment": reply.sentiment,
        "draft_response": reply.draft_response,
        "prospect_status": prospect.status,
    }


# ── Sequence viewer ───────────────────────────────────────────────────────────

@router.get("/{prospect_id}/sequence")
async def get_sequence(prospect_id: int, db: AsyncSession = Depends(get_db)):
    seq_result = await db.execute(
        select(models.Sequence)
        .where(models.Sequence.prospect_id == prospect_id)
        .order_by(models.Sequence.created_at.desc())
    )
    sequence = seq_result.scalar_one_or_none()
    if not sequence:
        return {"sequence": None}

    steps_result = await db.execute(
        select(models.SequenceStep)
        .where(models.SequenceStep.sequence_id == sequence.id)
        .order_by(models.SequenceStep.step_number)
    )
    steps = steps_result.scalars().all()

    # Count pending approvals
    pending_approval = [
        s for s in steps
        if s.sent_at is None and getattr(s, "approved", True) is False
    ]

    return {
        "sequence_id": sequence.id,
        "status": sequence.status,
        "current_step": sequence.current_step,
        "next_action_at": sequence.next_action_at.isoformat() if sequence.next_action_at else None,
        "pending_approvals": len(pending_approval),
        "steps": [
            {
                "step": s.step_number,
                "channel": s.channel.value if hasattr(s.channel, "value") else s.channel,
                "subject": s.subject,
                "body": s.body,
                "sent_at": s.sent_at.isoformat() if s.sent_at else None,
                "opened_at": s.opened_at.isoformat() if s.opened_at else None,
                "replied_at": s.replied_at.isoformat() if s.replied_at else None,
            }
            for s in steps
        ],
    }


# ── Replies list ──────────────────────────────────────────────────────────────

@router.get("/{prospect_id}/replies")
async def get_replies(prospect_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Reply)
        .where(models.Reply.prospect_id == prospect_id)
        .order_by(models.Reply.created_at.desc())
    )
    replies = result.scalars().all()
    return [
        {
            "id": r.id,
            "channel": r.channel.value if hasattr(r.channel, "value") else r.channel,
            "classification": r.classification,
            "sentiment": r.sentiment,
            "raw_content": r.raw_content,
            "draft_response": r.draft_response,
            "human_reviewed": r.human_reviewed,
            "created_at": r.created_at.isoformat(),
        }
        for r in replies
    ]


# ── Meetings ──────────────────────────────────────────────────────────────────

@router.get("/{prospect_id}/meetings")
async def get_meetings(prospect_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Meeting).where(models.Meeting.prospect_id == prospect_id)
    )
    meetings = result.scalars().all()
    return [
        {
            "id": m.id,
            "scheduled_at": m.scheduled_at.isoformat() if m.scheduled_at else None,
            "calendly_event_id": m.calendly_event_id,
            "agenda_sent": m.agenda_sent,
            "outcome": m.outcome,
        }
        for m in meetings
    ]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_or_404(db: AsyncSession, prospect_id: int) -> models.Prospect:
    result = await db.execute(
        select(models.Prospect).where(models.Prospect.id == prospect_id)
    )
    prospect = result.scalar_one_or_none()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")
    return prospect


def _to_response(p: models.Prospect) -> ProspectResponse:
    hooks: list[str] = []
    if p.personalization_hooks:
        try:
            hooks = json.loads(p.personalization_hooks)
        except Exception:
            pass
    profile: dict | None = None
    if p.research_profile:
        try:
            profile = json.loads(p.research_profile)
        except Exception:
            pass
    return ProspectResponse(
        id=p.id,
        email=p.email,
        first_name=p.first_name,
        last_name=p.last_name,
        title=p.title,
        company=p.company,
        status=p.status.value if hasattr(p.status, "value") else p.status,
        score=p.score,
        personalization_hooks=hooks,
        research_profile=profile,
        created_at=p.created_at,
    )
