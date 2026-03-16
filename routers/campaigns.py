from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import models
from database import get_db

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    name: str
    icp_definition: str = ""
    value_prop: str = ""
    tone: str = "professional"
    daily_send_limit: int = 50
    sequence_steps: int = 5


class CampaignResponse(BaseModel):
    id: int
    name: str
    status: str
    icp_definition: str | None
    value_prop: str | None
    tone: str
    daily_send_limit: int
    sequence_steps: int
    prospect_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/", response_model=list[CampaignResponse])
async def list_campaigns(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.Campaign).order_by(models.Campaign.created_at.desc()))
    campaigns = result.scalars().all()

    output = []
    for c in campaigns:
        count_result = await db.execute(
            select(func.count()).where(models.Prospect.campaign_id == c.id)
        )
        count = count_result.scalar() or 0
        output.append(CampaignResponse(
            id=c.id, name=c.name, status=c.status,
            icp_definition=c.icp_definition, value_prop=c.value_prop,
            tone=c.tone, daily_send_limit=c.daily_send_limit,
            sequence_steps=c.sequence_steps, prospect_count=count,
            created_at=c.created_at,
        ))
    return output


@router.post("/", response_model=CampaignResponse)
async def create_campaign(data: CampaignCreate, db: AsyncSession = Depends(get_db)):
    campaign = models.Campaign(**data.model_dump())
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return CampaignResponse(**{**campaign.__dict__, "prospect_count": 0})


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(campaign_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.Campaign).where(models.Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    count_result = await db.execute(
        select(func.count()).where(models.Prospect.campaign_id == campaign_id)
    )
    count = count_result.scalar() or 0
    return CampaignResponse(**{**campaign.__dict__, "prospect_count": count})
