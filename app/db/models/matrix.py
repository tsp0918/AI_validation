"""
Transaction model
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base


if TYPE_CHECKING:
    from app.db.models.ai_run import MatrixMatch


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class MatrixRule(Base, TimestampMixin):
    __tablename__ = "matrix_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    regime: Mapped[str] = mapped_column(String(64), nullable=False)
    list_name: Mapped[Optional[str]] = mapped_column(String(255))
    item_no: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(512))

    requirement_text: Mapped[str] = mapped_column(Text, nullable=False)
    usage_criteria_text: Mapped[Optional[str]] = mapped_column(Text)
    tech_criteria_text: Mapped[Optional[str]] = mapped_column(Text)

    notes: Mapped[Optional[str]] = mapped_column(Text)
    version: Mapped[Optional[str]] = mapped_column(String(64))
    effective_date: Mapped[Optional[datetime]] = mapped_column(DateTime)

    matches: Mapped[List["MatrixMatch"]] = relationship(
        back_populates="matrix_rule",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_matrix_rules_regime_itemno", "regime", "item_no"),
        UniqueConstraint("regime", "item_no", "version", name="uq_matrix_rules_regime_itemno_version"),
    )
