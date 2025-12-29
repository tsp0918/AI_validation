"""
Transaction model
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Index, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base


if TYPE_CHECKING:
    from app.db.models.transaction import Transaction, UsageRequirement
    from app.db.models.patent import Patent
    from app.db.models.matrix import MatrixRule

class RunStatus(str, enum.Enum):
    success = "success"
    failed = "failed"
    running = "running"


class RunType(str, enum.Enum):
    usage_extract = "usage_extract"
    patent_retrieve = "patent_retrieve"
    usage_expand = "usage_expand"
    matrix_match = "matrix_match"
    explanation = "explanation"


class MatchType(str, enum.Enum):
    core_hit = "core_hit"
    expanded_hit = "expanded_hit"


class MatchDecision(str, enum.Enum):
    hit = "hit"
    maybe = "maybe"
    no_hit = "no_hit"


class EvidenceType(str, enum.Enum):
    transaction_text = "transaction_text"
    expanded_usage = "expanded_usage"
    patent_usecase = "patent_usecase"
    law_text = "law_text"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class AiRun(Base, TimestampMixin):
    __tablename__ = "ai_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"), index=True)

    run_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=RunStatus.running.value, nullable=False)

    model_name: Mapped[Optional[str]] = mapped_column(String(128))
    prompt_version: Mapped[Optional[str]] = mapped_column(String(64))

    params: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    error: Mapped[Optional[str]] = mapped_column(Text)

    transaction: Mapped["Transaction"] = relationship(back_populates="ai_runs")

    patent_retrievals: Mapped[List["PatentRetrieval"]] = relationship(
        back_populates="ai_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    matrix_matches: Mapped[List["MatrixMatch"]] = relationship(
        back_populates="ai_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PatentRetrieval(Base, TimestampMixin):
    __tablename__ = "patent_retrievals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ai_run_id: Mapped[int] = mapped_column(ForeignKey("ai_runs.id", ondelete="CASCADE"), index=True)

    usage_requirement_id: Mapped[int] = mapped_column(ForeignKey("usage_requirements.id", ondelete="CASCADE"), index=True)
    patent_id: Mapped[int] = mapped_column(ForeignKey("patents.id", ondelete="CASCADE"), index=True)

    score: Mapped[float] = mapped_column(Float, nullable=False)
    why: Mapped[Optional[str]] = mapped_column(Text)

    ai_run: Mapped["AiRun"] = relationship(back_populates="patent_retrievals")
    usage_requirement: Mapped["UsageRequirement"] = relationship(back_populates="patent_retrievals")
    patent: Mapped["Patent"] = relationship(back_populates="retrievals")

    __table_args__ = (Index("ix_patent_retrievals_run_usage", "ai_run_id", "usage_requirement_id"),)


class MatrixMatch(Base, TimestampMixin):
    __tablename__ = "matrix_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ai_run_id: Mapped[int] = mapped_column(ForeignKey("ai_runs.id", ondelete="CASCADE"), index=True)

    usage_requirement_id: Mapped[int] = mapped_column(ForeignKey("usage_requirements.id", ondelete="CASCADE"), index=True)
    matrix_rule_id: Mapped[int] = mapped_column(ForeignKey("matrix_rules.id", ondelete="CASCADE"), index=True)

    match_score: Mapped[Optional[float]] = mapped_column(Float)
    match_type: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), default=MatchDecision.hit.value, nullable=False)

    ai_run: Mapped["AiRun"] = relationship(back_populates="matrix_matches")
    usage_requirement: Mapped["UsageRequirement"] = relationship(back_populates="matrix_matches")
    matrix_rule: Mapped["MatrixRule"] = relationship(back_populates="matches")

    evidences: Mapped[List["MatchEvidence"]] = relationship(
        back_populates="matrix_match",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (Index("ix_matrix_matches_run_rule", "ai_run_id", "matrix_rule_id"),)


class MatchEvidence(Base, TimestampMixin):
    __tablename__ = "match_evidences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    matrix_match_id: Mapped[int] = mapped_column(ForeignKey("matrix_matches.id", ondelete="CASCADE"), index=True)

    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[Optional[int]] = mapped_column(Integer)
    quote: Mapped[Optional[str]] = mapped_column(Text)
    explanation: Mapped[Optional[str]] = mapped_column(Text)

    matrix_match: Mapped["MatrixMatch"] = relationship(back_populates="evidences")
