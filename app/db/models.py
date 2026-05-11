"""
Silent Whale — Full SQLAlchemy 2.0 ORM.

Tables: Project, TvlSnapshot, FundingRound, GithubSignal,
GithubOverride, SourceHealth, AlertQueue, ScoreHistory, ProjectOutcome.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


# ──────────────────────────────────────────────
# Core entity
# ──────────────────────────────────────────────
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    chain: Mapped[str | None] = mapped_column(String(100))
    has_token: Mapped[bool] = mapped_column(Boolean, default=False)
    current_tvl: Mapped[float | None] = mapped_column(Float)
    tvl_growth_30d_pct: Mapped[float | None] = mapped_column(Float)
    latest_score: Mapped[float | None] = mapped_column(Float)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    tvl_snapshots: Mapped[list["TvlSnapshot"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    funding_rounds: Mapped[list["FundingRound"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    github_signals: Mapped[list["GithubSignal"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    github_overrides: Mapped[list["GithubOverride"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["AlertQueue"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    score_history: Mapped[list["ScoreHistory"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    outcomes: Mapped[list["ProjectOutcome"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


# ──────────────────────────────────────────────
# TVL history
# ──────────────────────────────────────────────
class TvlSnapshot(Base):
    __tablename__ = "tvl_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    tvl_usd: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="tvl_snapshots")

    __table_args__ = (
        Index("ix_tvl_snapshots_project_recorded", "project_id", "recorded_at"),
    )


# ──────────────────────────────────────────────
# VC funding
# ──────────────────────────────────────────────
class FundingRound(Base):
    __tablename__ = "funding_rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    round_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    amount_usd: Mapped[float | None] = mapped_column(Float)
    round_type: Mapped[str | None] = mapped_column(String(100))
    lead_investor: Mapped[str | None] = mapped_column(String(255))
    investors: Mapped[str | None] = mapped_column(Text)  # JSON array of names
    source_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="funding_rounds")


# ──────────────────────────────────────────────
# GitHub signals + overrides
# ──────────────────────────────────────────────
class GithubSignal(Base):
    __tablename__ = "github_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    repo_url: Mapped[str] = mapped_column(Text, nullable=False)
    keyword: Mapped[str] = mapped_column(String(100), nullable=False)
    commit_hash: Mapped[str] = mapped_column(String(40), nullable=False)
    commit_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    commit_message: Mapped[str | None] = mapped_column(Text)
    is_false_positive: Mapped[bool] = mapped_column(Boolean, default=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="github_signals")

    __table_args__ = (
        UniqueConstraint(
            "project_id", "commit_hash", "keyword", name="uq_github_signal"
        ),
    )


class GithubOverride(Base):
    __tablename__ = "github_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    commit_hash: Mapped[str] = mapped_column(String(40), nullable=False)
    keyword: Mapped[str] = mapped_column(String(100), nullable=False)
    is_false_positive: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="github_overrides")


# ──────────────────────────────────────────────
# Operational
# ──────────────────────────────────────────────
class SourceHealth(Base):
    __tablename__ = "source_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    is_healthy: Mapped[bool] = mapped_column(Boolean, default=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AlertQueue(Base):
    __tablename__ = "alert_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    score_at_alert: Mapped[float] = mapped_column(Float, nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    sent: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="alerts")

    __table_args__ = (Index("ix_alert_queue_unsent", "sent", "created_at"),)


class ScoreHistory(Base):
    __tablename__ = "score_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    tvl_points: Mapped[float] = mapped_column(Float, default=0)
    growth_points: Mapped[float] = mapped_column(Float, default=0)
    funding_points: Mapped[float] = mapped_column(Float, default=0)
    github_points: Mapped[float] = mapped_column(Float, default=0)
    breakdown_json: Mapped[str | None] = mapped_column(Text)
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="score_history")

    __table_args__ = (
        Index("ix_score_history_project_scored", "project_id", "scored_at"),
    )


class ProjectOutcome(Base):
    __tablename__ = "project_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    outcome_type: Mapped[str] = mapped_column(String(50), nullable=False)
    outcome_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    score_at_outcome: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="outcomes")
