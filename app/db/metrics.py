"""Ingestion metrics model — referenced by MetricsCollector."""
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.models import Base


class IngestionMetric(Base):
    __tablename__ = "ingestion_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    projects_upserted: Mapped[int] = mapped_column(Integer, default=0)
    records_inserted: Mapped[int] = mapped_column(Integer, default=0)
    api_calls_made: Mapped[int] = mapped_column(Integer, default=0)
    api_errors: Mapped[int] = mapped_column(Integer, default=0)
    error_details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
