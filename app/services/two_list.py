# app/services/two_list.py
from __future__ import annotations

import json
from typing import Optional, Dict, Any, List, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db.models.ai_run import AiRun, RunType, MatrixMatch
from app.db.models.matrix import MatrixRule
from app.db.models.transaction import UsageRequirement, UsageSource


def _pick_latest_matrix_match_run_id(db: Session, transaction_id: int) -> int:
    run = (
        db.query(AiRun)
        .filter(
            AiRun.transaction_id == transaction_id,
            AiRun.run_type == RunType.matrix_match.value,
        )
        .order_by(desc(AiRun.id))
        .first()
    )
    if not run:
        raise ValueError(
            "matrix_match の実行履歴（ai_runs）が見つかりません。先に pipeline の matrix_match を実行してください。"
        )
    return run.id


def _get_item_key(rule: MatrixRule) -> str:
    v = getattr(rule, "version", None) or ""
    return f"{rule.regime}::{rule.item_no}::{v}"


def _safe_json_loads(s: Optional[str]) -> Optional[Dict[str, Any]]:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def _load_matches(db: Session, run_id: int) -> List[Tuple[MatrixMatch, MatrixRule]]:
    return (
        db.query(MatrixMatch, MatrixRule)
        .join(MatrixRule, MatrixRule.id == MatrixMatch.matrix_rule_id)
        .filter(MatrixMatch.ai_run_id == run_id)
        .all()
    )


def _load_usage_map(db: Session, transaction_id: int) -> Dict[int, UsageRequirement]:
    urs = (
        db.query(UsageRequirement)
        .filter(UsageRequirement.transaction_id == transaction_id)
        .all()
    )
    return {u.id: u for u in urs}


def compute_two_lists(db: Session, transaction_id: int, run_id: Optional[int] = None) -> Dict[str, Any]:
    """
    2リスト集計（DB互換・堅牢版）:
      - core_hit と expanded_hit を item_no 単位で集約
      - A: 両方に出る item（intersection）
      - B: expanded のみに出る item（expanded_only）

    重要:
      - 指定 run_id に matrix_matches が 0 件でも "エラーにしない"（UIで0件表示できる）
    """
    rid = run_id or _pick_latest_matrix_match_run_id(db, transaction_id)

    rows = _load_matches(db, rid)
    usage_map = _load_usage_map(db, transaction_id)

    # ★ 0件なら例外を投げずに空で返す（ここが今回のポイント）
    if not rows:
        return {
            "transaction_id": transaction_id,
            "run_id": rid,
            "counts": {
                "intersection": 0,
                "expanded_only": 0,
                "total_unique_items": 0,
            },
            "intersection": [],
            "expanded_only": [],
            "note": "このrun_idでは matrix_matches が0件でした（用途要件とマトリクスの語彙が一致しない等）。",
        }

    grouped: Dict[str, Dict[str, Any]] = {}

    for mm, rule in rows:
        key = _get_item_key(rule)
        g = grouped.setdefault(
            key,
            {
                "key": key,
                "regime": rule.regime,
                "item_no": rule.item_no,
                "version": getattr(rule, "version", None),
                "title": rule.title,
                "rule_id": rule.id,
                "hits": {"core": [], "expanded": []},
                "max_score": None,
            },
        )

        ur = usage_map.get(mm.usage_requirement_id) if getattr(mm, "usage_requirement_id", None) else None
        ur_source = ur.source if ur else None
        ur_text = ur.text if ur else None

        evidence = _safe_json_loads(getattr(mm, "evidence_json", None))

        hit_record = {
            "matrix_match_id": mm.id,
            "usage_requirement_id": getattr(mm, "usage_requirement_id", None),
            "usage_source": ur_source,
            "usage_text": ur_text,
            "match_score": getattr(mm, "match_score", None),
            "match_type": getattr(mm, "match_type", None),
            "evidence": evidence,
        }

        score = getattr(mm, "match_score", None)
        if score is not None:
            if g["max_score"] is None or score > g["max_score"]:
                g["max_score"] = score

        mt = (getattr(mm, "match_type", None) or "").lower()
        if mt == "core_hit" or (ur and ur.source == UsageSource.core.value):
            g["hits"]["core"].append(hit_record)
        elif mt == "expanded_hit" or (ur and ur.source in (UsageSource.expanded.value, UsageSource.analyst_added.value)):
            g["hits"]["expanded"].append(hit_record)
        else:
            g["hits"]["expanded"].append(hit_record)

    intersection: List[Dict[str, Any]] = []
    expanded_only: List[Dict[str, Any]] = []

    for item in grouped.values():
        has_core = len(item["hits"]["core"]) > 0
        has_exp = len(item["hits"]["expanded"]) > 0
        if has_core and has_exp:
            intersection.append(item)
        elif (not has_core) and has_exp:
            expanded_only.append(item)

    def sort_key(x: Dict[str, Any]):
        score = x["max_score"]
        score_sort = -score if score is not None else 10**9
        return (score_sort, str(x["item_no"]))

    intersection.sort(key=sort_key)
    expanded_only.sort(key=sort_key)

    return {
        "transaction_id": transaction_id,
        "run_id": rid,
        "counts": {
            "intersection": len(intersection),
            "expanded_only": len(expanded_only),
            "total_unique_items": len(grouped),
        },
        "intersection": intersection,
        "expanded_only": expanded_only,
    }
