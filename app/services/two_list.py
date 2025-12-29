from __future__ import annotations

from typing import Optional, Dict, Any, List, Tuple, Set
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db.models.ai_run import AiRun, RunType
from app.db.models.ai_run import MatrixMatch, MatchEvidence, EvidenceType
from app.db.models.matrix import MatrixRule
from app.db.models.transaction import UsageRequirement, UsageSource


def _pick_latest_matrix_match_run_id(db: Session, transaction_id: int) -> int:
    run = (
        db.query(AiRun)
        .filter(AiRun.transaction_id == transaction_id, AiRun.run_type == RunType.matrix_match.value)
        .order_by(desc(AiRun.id))
        .first()
    )
    if not run:
        raise ValueError("matrix_match の実行履歴（ai_runs）が見つかりません。先に pipeline の matrix_match を実行してください。")
    return run.id


def _get_item_key(rule: MatrixRule) -> str:
    """
    集約キー。基本は regime + item_no (+ version)。
    version運用していなければ version は空でOK。
    """
    v = rule.version or ""
    return f"{rule.regime}::{rule.item_no}::{v}"


def _load_matches(db: Session, run_id: int) -> List[Tuple[MatrixMatch, MatrixRule]]:
    rows = (
        db.query(MatrixMatch, MatrixRule)
        .join(MatrixRule, MatrixRule.id == MatrixMatch.matrix_rule_id)
        .filter(MatrixMatch.ai_run_id == run_id)
        .filter(MatrixMatch.decision.in_(["hit", "maybe"]))
        .all()
    )
    return rows



def _load_usage_map(db: Session, transaction_id: int) -> Dict[int, UsageRequirement]:
    urs = (
        db.query(UsageRequirement)
        .filter(UsageRequirement.transaction_id == transaction_id)
        .all()
    )
    return {u.id: u for u in urs}


def _load_evidences_for_matches(db: Session, match_ids: List[int]) -> Dict[int, List[MatchEvidence]]:
    if not match_ids:
        return {}
    evs = (
        db.query(MatchEvidence)
        .filter(MatchEvidence.matrix_match_id.in_(match_ids))
        .all()
    )
    out: Dict[int, List[MatchEvidence]] = {}
    for e in evs:
        out.setdefault(e.matrix_match_id, []).append(e)
    return out


def compute_two_lists(db: Session, transaction_id: int, run_id: Optional[int] = None) -> Dict[str, Any]:
    """
    2リスト集計ロジック（B案）:
      - core_hit と expanded_hit を item_no 単位で集約
      - A: 両方に出る item（intersection）
      - B: expanded のみに出る item（expanded_only）
    """
    # 1) run_id決定
    rid = run_id or _pick_latest_matrix_match_run_id(db, transaction_id)

    # 2) マッチ読み込み（MatrixMatch + MatrixRule）
    rows = _load_matches(db, rid)
    if not rows:
        raise ValueError("指定run_idに matrix_matches がありません。thresholdやseed状況を確認してください。")

    usage_map = _load_usage_map(db, transaction_id)

    # 3) item_keyごとに core/expanded を集約
    #    返却用に「どのusage要件に紐づいたか」「スコア」「根拠」をまとめる
    grouped: Dict[str, Dict[str, Any]] = {}
    match_ids: List[int] = []

    for mm, rule in rows:
        match_ids.append(mm.id)

        key = _get_item_key(rule)
        g = grouped.setdefault(
            key,
            {
                "key": key,
                "regime": rule.regime,
                "item_no": rule.item_no,
                "version": rule.version,
                "title": rule.title,
                "rule_id": rule.id,
                "hits": {
                    "core": [],
                    "expanded": [],
                },
                "max_score": None,
            },
        )

        ur = usage_map.get(mm.usage_requirement_id)
        ur_source = None
        ur_text = None
        if ur:
            ur_source = ur.source
            ur_text = ur.text

        hit_record = {
            "matrix_match_id": mm.id,
            "usage_requirement_id": mm.usage_requirement_id,
            "usage_source": ur_source,
            "usage_text": ur_text,
            "match_score": mm.match_score,
            "match_type": mm.match_type,
            "decision": mm.decision,
        }

        # max_score 更新
        if mm.match_score is not None:
            if g["max_score"] is None or mm.match_score > g["max_score"]:
                g["max_score"] = mm.match_score

        # core_hit / expanded_hit を mm.match_type で判定（UsageRequirement.source でも二重チェック可）
        if mm.match_type == "core_hit" or (ur and ur.source == UsageSource.core.value):
            g["hits"]["core"].append(hit_record)
        elif mm.match_type == "expanded_hit":
            g["hits"]["expanded"].append(hit_record)
        else:
            # 予期しない値でも落とさない
            pass

    # 4) evidenceを付与（必要な分だけ）
    ev_map = _load_evidences_for_matches(db, match_ids)

    def attach_evidences(item: Dict[str, Any]) -> None:
        # 各hitに evidences を付ける
        for side in ("core", "expanded"):
            for h in item["hits"][side]:
                evs = ev_map.get(h["matrix_match_id"], [])
                h["evidences"] = [
                    {
                        "evidence_type": e.evidence_type,
                        "source_id": e.source_id,
                        "quote": e.quote,
                        "explanation": e.explanation,
                    }
                    for e in evs
                ]

    # 5) A/B を作る
    intersection: List[Dict[str, Any]] = []
    expanded_only: List[Dict[str, Any]] = []

    for item in grouped.values():
        has_core = len(item["hits"]["core"]) > 0
        has_exp = len(item["hits"]["expanded"]) > 0

        if has_core and has_exp:
            attach_evidences(item)
            intersection.append(item)
        elif (not has_core) and has_exp:
            attach_evidences(item)
            expanded_only.append(item)

    # 6) 並び順（見やすさ：max_score desc → item_no）
    def sort_key(x: Dict[str, Any]):
        score = x["max_score"]
        # Noneは末尾に
        score_sort = -score if score is not None else 10**9
        return (score_sort, x["item_no"])

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
