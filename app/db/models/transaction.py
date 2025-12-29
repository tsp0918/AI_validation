"""
Transaction model
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base


if TYPE_CHECKING:
    from app.db.models.ai_run import AiRun, PatentRetrieval, MatrixMatch


class TransactionStatus(str, enum.Enum):
    draft = "draft"
    in_review = "in_review"
    approved = "approved"
    rejected = "rejected"


class UsageSource(str, enum.Enum):
    core = "core"
    expanded = "expanded"
    analyst_added = "analyst_added"


class CreatedBy(str, enum.Enum):
    user = "user"
    ai = "ai"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Transaction(Base, TimestampMixin):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_no: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default=TransactionStatus.draft.value, nullable=False)

    created_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    items: Mapped[List["TransactionItem"]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    usage_requirements: Mapped[List["UsageRequirement"]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    ai_runs: Mapped[List["AiRun"]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TransactionItem(Base, TimestampMixin):
    __tablename__ = "transaction_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"), index=True)

    item_name: Mapped[Optional[str]] = mapped_column(String(255))
    item_model: Mapped[Optional[str]] = mapped_column(String(255))
    spec_text: Mapped[Optional[str]] = mapped_column(Text)

    attachments_meta: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    transaction: Mapped["Transaction"] = relationship(back_populates="items")
    usage_requirements: Mapped[List["UsageRequirement"]] = relationship(
        back_populates="transaction_item",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class UsageRequirement(Base, TimestampMixin):
    __tablename__ = "usage_requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"), index=True)
    transaction_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("transaction_items.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )

    source: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[Optional[str]] = mapped_column(Text)

    risk_tags: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Integer, nullable=True)  # floatにしたい場合はFloatへ

    created_by: Mapped[str] = mapped_column(String(16), default=CreatedBy.user.value, nullable=False)

    transaction: Mapped["Transaction"] = relationship(back_populates="usage_requirements")
    transaction_item: Mapped[Optional["TransactionItem"]] = relationship(back_populates="usage_requirements")

    patent_retrievals: Mapped[List["PatentRetrieval"]] = relationship(
        back_populates="usage_requirement",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    matrix_matches: Mapped[List["MatrixMatch"]] = relationship(
        back_populates="usage_requirement",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_usage_requirements_tx_source", "transaction_id", "source"),
    )
