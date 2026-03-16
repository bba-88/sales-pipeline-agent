import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import models
from database import get_db
from agents.orchestrator import Orchestrator

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
    prospects = result.scalars().all()
    return [_to_response(p) for p in prospects]


@router.post("/", response_model=ProspectResponse)
async def create_prospect(data: ProspectCreate, db: AsyncSession = Depends(get_db)):
    # Check for duplicate
    existing = await db.execute(select(models.Prospect).where(models.Prospect.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Prospect with this email already exists")
    prospect = models.Prospect(**data.model_dump())
    db.add(prospect)
    await db.commit()
    await db.refresh(prospect)
    return _to_response(prospect)


@router.post("/{prospect_id}/enroll")
async def enroll_prospect(
    prospect_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Kick off full research + sequence generation pipeline."""
    p_result = await db.execute(select(models.Prospect).where(models.Prospect.id == prospect_id))
    prospect = p_result.scalar_one_or_none()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")
    if not prospect.campaign_id:
        raise HTTPException(status_code=400, detail="Prospect must be assigned to a campaign first")

    c_result = await db.execute(select(models.Campaign).where(models.Campaign.id == prospect.campaign_id))
    campaign = c_result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Run in background so we don't block the HTTP response
    async def run_pipeline():
        orch = Orchestrator(db)
        await orch.enroll_prospect(prospect, campaign)

    background_tasks.add_task(run_pipeline)
    return {"message": "Enrollment started", "prospect_id": prospect_id}


@router.post("/{prospect_id}/reply")
async def submit_reply(
    prospect_id: int,
    data: ReplySubmit,
    db: AsyncSession = Depends(get_db),
):
    """Submit an inbound reply for AI classification and response drafting."""
    p_result = await db.execute(select(models.Prospect).where(models.Prospect.id == prospect_id))
    prospect = p_result.scalar_one_or_none()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    reply = models.Reply(
        prospect_id=prospect_id,
        channel=models.Channel(data.channel),
        raw_content=data.content,
    )
    db.add(reply)
    await db.commit()
    await db.refresh(reply)

    # Classify immediately (fast with Haiku)
    orch = Orchestrator(db)
    reply = await orch.handle_reply(reply, prospect)

    return {
        "id": reply.id,
        "classification": reply.classification,
        "sentiment": reply.sentiment,
        "draft_response": reply.draft_response,
    }


@router.get("/{prospect_id}", response_model=ProspectResponse)
async def get_prospect(prospect_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.Prospect).where(models.Prospect.id == prospect_id))
    prospect = result.scalar_one_or_none()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")
    return _to_response(prospect)


@router.get("/{prospect_id}/sequence")
async def get_sequence(prospect_id: int, db: AsyncSession = Depends(get_db)):
    """Get the generated outreach sequence for a prospect."""
    seq_result = await db.execute(
        select(models.Sequence).where(models.Sequence.prospect_id == prospect_id)
        .order_by(models.Sequence.created_at.desc())
    )
    sequence = seq_result.scalar_one_or_none()
    if not sequence:
        return {"sequence": None}

    steps_result = await db.execute(
        select(models.SequenceStep).where(models.SequenceStep.sequence_id == sequence.id)
        .order_by(models.SequenceStep.step_number)
    )
    steps = steps_result.scalars().all()
    return {
        "sequence_id": sequence.id,
        "status": sequence.status,
        "current_step": sequence.current_step,
        "steps": [
            {
                "step": s.step_number,
                "channel": s.channel,
                "subject": s.subject,
                "body": s.body,
                "sent_at": s.sent_at,
            }
            for s in steps
        ],
    }


def _to_response(p: models.Prospect) -> ProspectResponse:
    hooks = []
    if p.personalization_hooks:
        try:
            hooks = json.loads(p.personalization_hooks)
        except Exception:
            pass
    profile = None
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
