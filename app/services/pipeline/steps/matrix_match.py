from __future__ import annotations

from typing import Dict, Any, List
from sqlalchemy.orm import Session

from app.db.models.transaction import UsageRequirement, UsageSource
from app.db.models.matrix import MatrixRule
from app.db.models.ai_run import MatrixMatch, MatchType, MatchDecision, MatchEvidence, EvidenceType


def _match_stub(usage_text: str, rule_text: str) -> float:
    if not usage_text or not rule_text:
        return 0.0

    u = usage_text.lower()
    r = rule_text.lower()

    keywords = ["露光", "litho", "リソグラフィ", "フォトレジスト", "photoresist", "krf"]
    if any(k in u for k in keywords) and any(k in r for k in keywords):
        return 0.95

    return 0.2


def step_matrix_match(db: Session, transaction_id: int, run_id: int, params: Dict[str, Any]) -> Dict[str, Any]:
    threshold = float(params.get("threshold", 0.75))

    core = (
        db.query(UsageRequirement)
        .filter(
            UsageRequirement.transaction_id == transaction_id,
            UsageRequirement.source == UsageSource.core.value,
        )
        .all()
    )
    expanded = (
        db.query(UsageRequirement)
        .filter(
            UsageRequirement.transaction_id == transaction_id,
            UsageRequirement.source == UsageSource.expanded.value,
        )
        .all()
    )

    if not core:
        raise ValueError("No core usage requirements. usage_extract を先に実行してください。")
    if not expanded:
        raise ValueError("No expanded usage requirements. usage_expand を先に実行してください。")

    rules = db.query(MatrixRule).all()
    if not rules:
        raise ValueError("No matrix_rules in DB. seed_data を確認してください。")

    # この run_id の結果を作り直す（再実行に強い）
    db.query(MatrixMatch).filter(MatrixMatch.ai_run_id == run_id).delete(synchronize_session=False)

    def process(urs: List[UsageRequirement], mtype: MatchType) -> int:
        saved = 0
        for ur in urs:
            for rule in rules:
                score = _match_stub(ur.text, rule.requirement_text)
                if score < threshold:
                    continue

                mm = MatrixMatch(
                    ai_run_id=run_id,
                    usage_requirement_id=ur.id,
                    matrix_rule_id=rule.id,
                    match_score=score,
                    match_type=mtype.value,
                    decision=MatchDecision.hit.value,
                )
                db.add(mm)
                db.flush()  # mm.id 確定

                # Evidence（最小構成）
                db.add(
                    MatchEvidence(
                        matrix_match_id=mm.id,
                        evidence_type=EvidenceType.transaction_text.value
                        if mtype == MatchType.core_hit
                        else EvidenceType.expanded_usage.value,
                        source_id=ur.id,
                        quote=(ur.text or "")[:240],
                        explanation="用途要件が該当項番の要件文言と一致/近似すると判断",
                    )
                )
                db.add(
                    MatchEvidence(
                        matrix_match_id=mm.id,
                        evidence_type=EvidenceType.law_text.value,
                        source_id=rule.id,
                        quote=(rule.requirement_text or "")[:240],
                        explanation="該当項番の用途/技術要件（抜粋）",
                    )
                )
                saved += 1
        return saved

    core_hits = process(core, MatchType.core_hit)
    expanded_hits = process(expanded, MatchType.expanded_hit)

    db.flush()
    return {"threshold": threshold, "core_hits": core_hits, "expanded_hits": expanded_hits}
