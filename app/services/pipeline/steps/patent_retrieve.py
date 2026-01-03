# app/services/pipeline/steps/patent_retrieve.py
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import inspect, or_

from app.db.models.patent import Patent
from app.db.models.transaction import UsageRequirement
from app.db.models.ai_run import PatentRetrieval


def _project_root() -> str:
    # app/services/pipeline/steps/ からルートへ
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", "..", ".."))


def _read_patents_json(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict) and isinstance(doc.get("items"), list):
        return doc["items"]
    raise ValueError("patents.json must be a list or {items:[...]} JSON")


def _to_ipc_raw(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s or None
    if isinstance(v, list):
        s = ";".join([str(x).strip() for x in v if str(x).strip()])
        return s or None
    s = str(v).strip()
    return s or None


def _first_non_empty_str(*vals: Any) -> str:
    for v in vals:
        if v is None:
            continue
        if isinstance(v, str):
            s = v.strip()
            if s:
                return s
        else:
            s = str(v).strip()
            if s:
                return s
    return ""


def _table_has_column(db: Session, table_name: str, col_name: str) -> bool:
    try:
        cols = inspect(db.get_bind()).get_columns(table_name)
        return any(c["name"] == col_name for c in cols)
    except Exception:
        return False


def _get_usage_text(u: UsageRequirement) -> str:
    """
    UsageRequirement の本文フィールド名の揺れに耐えるための吸収層。
    あなたの指摘の 'usage_details' 問題はここで解消する。
    """
    return _first_non_empty_str(
        getattr(u, "text", None),
        getattr(u, "usage_details", None),
        getattr(u, "usage_detail", None),
        getattr(u, "details", None),
        getattr(u, "description", None),
        getattr(u, "requirement_text", None),
    )


def _upsert_patents_from_json(db: Session, json_path: str) -> Dict[str, int]:
    items = _read_patents_json(json_path)

    inserted = 0
    updated = 0
    now = datetime.utcnow()

    for it in items:
        pub = _first_non_empty_str(it.get("publication_number"), it.get("pub_number"))
        if not pub:
            continue

        title = _first_non_empty_str(it.get("title"))
        applicant = _first_non_empty_str(it.get("applicant"), it.get("assignee"))

        # JSON 側のキー揺れ吸収（usage_detail / usage_details など）
        usage_detail = _first_non_empty_str(
            it.get("usage_detail"),
            it.get("usage_details"),
            it.get("usage_details_text"),
            it.get("usage"),
            it.get("abstract"),
            it.get("description"),
            it.get("summary"),
        )

        ipc_raw = _to_ipc_raw(it.get("ipc_codes") or it.get("ipc") or it.get("ipc_codes_raw"))

        obj = db.query(Patent).filter(Patent.publication_number == pub).first()
        if obj:
            if hasattr(obj, "title"):
                obj.title = title
            if hasattr(obj, "applicant"):
                obj.applicant = applicant
            if hasattr(obj, "usage_detail"):
                obj.usage_detail = usage_detail
            if hasattr(obj, "ipc_codes_raw"):
                obj.ipc_codes_raw = ipc_raw
            if hasattr(obj, "updated_at"):
                obj.updated_at = now
            updated += 1
        else:
            obj = Patent(publication_number=pub)
            if hasattr(obj, "title"):
                obj.title = title
            if hasattr(obj, "applicant"):
                obj.applicant = applicant
            if hasattr(obj, "usage_detail"):
                obj.usage_detail = usage_detail
            if hasattr(obj, "ipc_codes_raw"):
                obj.ipc_codes_raw = ipc_raw
            if hasattr(obj, "created_at"):
                obj.created_at = now
            if hasattr(obj, "updated_at"):
                obj.updated_at = now
            db.add(obj)
            inserted += 1

    return {"inserted": inserted, "updated": updated, "total_in_json": len(items)}


def step_patent_retrieve(
    db: Session,
    transaction_id: int,
    run_id: int,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    - patents テーブルを参照して retrieval を作る
    - ただし patents が空なら data/patents.json を upsert して埋める
    """
    # --- ensure patents are loaded ---
    patents_json_path = str(params.get("patents_json_path") or "").strip()
    if not patents_json_path:
        patents_json_path = os.path.join(_project_root(), "data", "patents.json")

    ingest_result = None
    patent_count = db.query(Patent).count()

    if patent_count == 0 and os.path.exists(patents_json_path):
        ingest_result = _upsert_patents_from_json(db, patents_json_path)
        db.commit()
        patent_count = db.query(Patent).count()

    # --- cleanup old rows for this run ---
    db.query(PatentRetrieval).filter(PatentRetrieval.ai_run_id == run_id).delete(synchronize_session=False)
    db.flush()

    usages = (
        db.query(UsageRequirement)
        .filter(UsageRequirement.transaction_id == transaction_id)
        .all()
    )
    if not usages:
        db.commit()
        return {"step": "patent_retrieve", "inserted": 0, "note": "usage_requirements が0件"}

    top_k = int(params.get("top_k_patents_per_usage", 5))
    like_len = int(params.get("like_prefix_len", 16))  # 既存の q[:10] を少し緩和（任意）

    inserted = 0
    for u in usages:
        q = _get_usage_text(u)
        if not q:
            continue

        q_like = q[:like_len]

        # Patent 側のカラム存在チェック（事故防止）
        filters = []
        if hasattr(Patent, "title"):
            filters.append(Patent.title.like(f"%{q_like}%"))
        if hasattr(Patent, "usage_detail"):
            filters.append(Patent.usage_detail.like(f"%{q_like}%"))

        candidates: List[Patent] = []
        if filters:
            candidates = (
                db.query(Patent)
                .filter(or_(*filters))
                .limit(top_k)
                .all()
            )

        # 0件なら fallback で先頭から
        if not candidates:
            candidates = db.query(Patent).limit(top_k).all()

        for p in candidates:
            pr = PatentRetrieval(
                ai_run_id=run_id,
                usage_requirement_id=u.id,
                patent_id=p.id,
                score=0.5,   # ここは既存ロジックのスコアに置換してください
                why="json_dataset_lookup",
            )
            db.add(pr)
            inserted += 1

    db.commit()

    return {
        "step": "patent_retrieve",
        "transaction_id": transaction_id,
        "run_id": run_id,
        "patent_count": patent_count,
        "ingest": ingest_result,
        "inserted": inserted,
        "patents_json_path": patents_json_path,
        "note": "patents.json -> DB(upsert if empty) -> retrieve from DB",
    }
