from typing import Dict, Any, Optional

from sqlalchemy.orm import Session

from app.db.models.ai_run import RunType
from app.services.pipeline.runner import execute_step

from app.services.pipeline.steps.usage_extract import step_usage_extract
from app.services.pipeline.steps.patent_retrieve import step_patent_retrieve
from app.services.pipeline.steps.usage_expand import step_usage_expand
from app.services.pipeline.steps.matrix_match import step_matrix_match


def run_until_matrix_match(db: Session, transaction_id: int, threshold: float = 0.75) -> Dict[str, Any]:
    """
    ① core抽出 → ② 特許検索 → ③ 用途拡張 → ④ マトリクス照合
    最終的に matrix_match の run_id を返す（2リスト集計に使う）
    """

    r1 = execute_step(
        db=db,
        transaction_id=transaction_id,
        run_type=RunType.usage_extract,
        step_fn=step_usage_extract,
        params={"max_requirements": 10},
        model_name="local",
        prompt_version="usage_extract_v1",
    )

    r2 = execute_step(
        db=db,
        transaction_id=transaction_id,
        run_type=RunType.patent_retrieve,
        step_fn=step_patent_retrieve,
        params={"top_k": 10},
        model_name="local",
        prompt_version="patent_retrieve_v1",
    )

    r3 = execute_step(
        db=db,
        transaction_id=transaction_id,
        run_type=RunType.usage_expand,
        step_fn=step_usage_expand,
        params={},
        model_name="local",
        prompt_version="usage_expand_v1",
    )

    r4 = execute_step(
        db=db,
        transaction_id=transaction_id,
        run_type=RunType.matrix_match,
        step_fn=step_matrix_match,
        params={"threshold": threshold},
        model_name="local",
        prompt_version="matrix_match_v1",
    )

    # execute_step はステップ結果 dict を返す設計なので、run_id を返せるように runner 側で含めるのが理想
    # ここでは "latest matrix_match run を two_list が拾える" 前提で返す
    return {
        "usage_extract": r1,
        "patent_retrieve": r2,
        "usage_expand": r3,
        "matrix_match": r4,
        "note": "two_list側は省略時に最新matrix_match runを拾います",
    }
