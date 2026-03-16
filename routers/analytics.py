from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import models
from database import get_db

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/dashboard")
async def dashboard_stats(db: AsyncSession = Depends(get_db)):
    """Return key pipeline metrics for the dashboard."""

    total_prospects = (await db.execute(select(func.count()).select_from(models.Prospect))).scalar() or 0
    total_campaigns = (await db.execute(select(func.count()).select_from(models.Campaign))).scalar() or 0
    total_meetings = (await db.execute(select(func.count()).select_from(models.Meeting))).scalar() or 0

    # Status breakdown
    status_rows = await db.execute(
        select(models.Prospect.status, func.count()).group_by(models.Prospect.status)
    )
    status_counts = {row[0]: row[1] for row in status_rows}

    # Replies breakdown
    reply_rows = await db.execute(
        select(models.Reply.classification, func.count()).group_by(models.Reply.classification)
    )
    reply_counts = {str(row[0]): row[1] for row in reply_rows}

    # Recent audit log
    log_result = await db.execute(
        select(models.AuditLog).order_by(models.AuditLog.created_at.desc()).limit(20)
    )
    logs = log_result.scalars().all()

    sequencing_count = status_counts.get(models.ProspectStatus.SEQUENCING, 0)
    responded_count = status_counts.get(models.ProspectStatus.RESPONDED, 0)

    reply_rate = round((responded_count / sequencing_count * 100), 1) if sequencing_count else 0.0
    meeting_rate = round((total_meetings / total_prospects * 100), 1) if total_prospects else 0.0

    return {
        "summary": {
            "total_prospects": total_prospects,
            "total_campaigns": total_campaigns,
            "total_meetings": total_meetings,
            "reply_rate_pct": reply_rate,
            "meeting_rate_pct": meeting_rate,
        },
        "pipeline": {
            "new": status_counts.get(models.ProspectStatus.NEW, 0),
            "researching": status_counts.get(models.ProspectStatus.RESEARCHING, 0),
            "sequencing": sequencing_count,
            "responded": responded_count,
            "meeting_booked": status_counts.get(models.ProspectStatus.MEETING_BOOKED, 0),
            "disqualified": status_counts.get(models.ProspectStatus.DISQUALIFIED, 0),
        },
        "replies": reply_counts,
        "recent_activity": [
            {
                "agent": log.agent_name,
                "action": log.action,
                "prospect_id": log.prospect_id,
                "time": log.created_at.isoformat(),
            }
            for log in logs
        ],
    }
