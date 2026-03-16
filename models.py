import enum
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Float, DateTime, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


class ProspectStatus(str, enum.Enum):
    NEW = "new"
    RESEARCHING = "researching"
    SEQUENCING = "sequencing"
    RESPONDED = "responded"
    MEETING_BOOKED = "meeting_booked"
    DISQUALIFIED = "disqualified"


class SequenceStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ReplyClassification(str, enum.Enum):
    INTERESTED = "interested"
    NOT_NOW = "not_now"
    WRONG_PERSON = "wrong_person"
    OUT_OF_OFFICE = "out_of_office"
    UNSUBSCRIBE = "unsubscribe"
    OBJECTION = "objection"
    OTHER = "other"


class Channel(str, enum.Enum):
    EMAIL = "email"
    LINKEDIN = "linkedin"


class Prospect(Base):
    __tablename__ = "prospects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    title: Mapped[Optional[str]] = mapped_column(String(200))
    company: Mapped[Optional[str]] = mapped_column(String(200))
    domain: Mapped[Optional[str]] = mapped_column(String(200))
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[ProspectStatus] = mapped_column(SAEnum(ProspectStatus), default=ProspectStatus.NEW)
    score: Mapped[Optional[int]] = mapped_column(Integer)  # 0-100 fit score

    # Rich enrichment data (stored as JSON text)
    research_profile: Mapped[Optional[str]] = mapped_column(Text)
    personalization_hooks: Mapped[Optional[str]] = mapped_column(Text)

    campaign_id: Mapped[Optional[int]] = mapped_column(ForeignKey("campaigns.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    campaign: Mapped[Optional["Campaign"]] = relationship(back_populates="prospects")
    sequences: Mapped[list["Sequence"]] = relationship(back_populates="prospect")
    replies: Mapped[list["Reply"]] = relationship(back_populates="prospect")
    meetings: Mapped[list["Meeting"]] = relationship(back_populates="prospect")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[str] = mapped_column(String(100), default="default")
    status: Mapped[str] = mapped_column(String(50), default="active")
    icp_definition: Mapped[Optional[str]] = mapped_column(Text)
    value_prop: Mapped[Optional[str]] = mapped_column(Text)
    tone: Mapped[str] = mapped_column(String(50), default="professional")
    daily_send_limit: Mapped[int] = mapped_column(Integer, default=50)
    sequence_steps: Mapped[int] = mapped_column(Integer, default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    prospects: Mapped[list["Prospect"]] = relationship(back_populates="campaign")


class Sequence(Base):
    __tablename__ = "sequences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prospect_id: Mapped[int] = mapped_column(ForeignKey("prospects.id"))
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"))
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[SequenceStatus] = mapped_column(SAEnum(SequenceStatus), default=SequenceStatus.ACTIVE)
    next_action_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    prospect: Mapped["Prospect"] = relationship(back_populates="sequences")
    steps: Mapped[list["SequenceStep"]] = relationship(back_populates="sequence")


class SequenceStep(Base):
    __tablename__ = "sequence_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sequence_id: Mapped[int] = mapped_column(ForeignKey("sequences.id"))
    step_number: Mapped[int] = mapped_column(Integer)
    channel: Mapped[Channel] = mapped_column(SAEnum(Channel), default=Channel.EMAIL)
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    body: Mapped[Optional[str]] = mapped_column(Text)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    replied_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    sequence: Mapped["Sequence"] = relationship(back_populates="steps")


class Reply(Base):
    __tablename__ = "replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prospect_id: Mapped[int] = mapped_column(ForeignKey("prospects.id"))
    sequence_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sequences.id"))
    channel: Mapped[Channel] = mapped_column(SAEnum(Channel))
    raw_content: Mapped[str] = mapped_column(Text)
    classification: Mapped[Optional[ReplyClassification]] = mapped_column(SAEnum(ReplyClassification))
    sentiment: Mapped[Optional[str]] = mapped_column(String(50))
    draft_response: Mapped[Optional[str]] = mapped_column(Text)
    human_reviewed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    prospect: Mapped["Prospect"] = relationship(back_populates="replies")


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prospect_id: Mapped[int] = mapped_column(ForeignKey("prospects.id"))
    calendly_event_id: Mapped[Optional[str]] = mapped_column(String(200))
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    agenda_sent: Mapped[bool] = mapped_column(default=False)
    outcome: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    prospect: Mapped["Prospect"] = relationship(back_populates="meetings")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(200))
    input_data: Mapped[Optional[str]] = mapped_column(Text)
    output_data: Mapped[Optional[str]] = mapped_column(Text)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float)
    prospect_id: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
