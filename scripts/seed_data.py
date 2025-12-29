# scripts/seed_data.py
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db.models import (
    Transaction, TransactionItem, UsageRequirement,
    Patent, PatentUsecase, MatrixRule,
)

# もし Enum を使っているなら、source値は "core"/"expanded" を合わせる
CORE = "core"
EXPANDED = "expanded"


def upsert_min_seed(db: Session) -> None:
    """
    目的:
      - パイプライン（usage_extract/patent_retrieve/usage_expand/matrix_match）の動作確認
      - 画面/APIの疎通確認
    方針:
      - 既に同一 case_no / publication_number / item_no があれば作らない
    """

    # -------------------------
    # 1) Transaction + Item
    # -------------------------
    case_no = "TX-0001"
    tx = db.query(Transaction).filter(Transaction.case_no == case_no).first()
    if not tx:
        tx = Transaction(case_no=case_no, title="Seed: Lithography material export review", status="draft")
        db.add(tx)
        db.flush()

    # Item 1件
    item_name = "Photoresist (KrF)"
    item = (
        db.query(TransactionItem)
        .filter(TransactionItem.transaction_id == tx.id, TransactionItem.item_name == item_name)
        .first()
    )
    if not item:
        item = TransactionItem(
            transaction_id=tx.id,
            item_name=item_name,
            item_model="KR-PR-100",
            spec_text=(
                "用途: 半導体製造のフォトリソグラフィ工程（KrF露光）に使用。\n"
                "想定工程: 露光→現像→エッチング。用途要件: 微細加工。\n"
                "最終用途: ロジック/メモリ製造ライン。\n"
            ),
            attachments_meta={"files": []},
        )
        db.add(item)
        db.flush()

    # -------------------------
    # 2) Usage Requirements（core/expandedのサンプル）
    # -------------------------
    # 既にある場合は足さない（重複回避）
    def ensure_usage(source: str, text: str, risk_tags=None, confidence=None):
        risk_tags = risk_tags or []
        exists = (
            db.query(UsageRequirement)
            .filter(
                UsageRequirement.transaction_id == tx.id,
                UsageRequirement.source == source,
                UsageRequirement.text == text,
            )
            .first()
        )
        if not exists:
            db.add(
                UsageRequirement(
                    transaction_id=tx.id,
                    transaction_item_id=item.id,
                    source=source,
                    text=text,
                    normalized_text=None,
                    risk_tags=risk_tags,
                    confidence=confidence,
                    created_by="user",
                )
            )

    ensure_usage(
        CORE,
        "半導体製造工程におけるフォトリソグラフィ（KrF露光）用の感光材料として使用",
        risk_tags=["semiconductor_mfg"],
    )
    ensure_usage(
        EXPANDED,
        "微細加工向けリソグラフィ工程に用いる感光性樹脂用途（露光・現像工程）",
        risk_tags=["semiconductor_mfg"],
        confidence=0.72,
    )

    # -------------------------
    # 3) Patents + Usecases（特許用途の知識源）
    # -------------------------
    pub = "JP-2025-000001-A"
    p = db.query(Patent).filter(Patent.publication_number == pub).first()
    if not p:
        p = Patent(
            publication_number=pub,
            title="Chemically amplified photoresist composition for KrF lithography",
            assignee="Example Chemical Co., Ltd.",
            abstract="A photoresist composition suitable for KrF excimer laser lithography.",
            fulltext=None,
            ipc_codes_raw="G03F; C08F",
            source_url="https://example.com/patent/JP-2025-000001-A",
        )
        db.add(p)
        db.flush()

    # PatentUsecase
    usecase_text = "KrFエキシマレーザー露光を用いた半導体微細加工のレジスト材料として利用"
    pu = (
        db.query(PatentUsecase)
        .filter(PatentUsecase.patent_id == p.id, PatentUsecase.usecase_text == usecase_text)
        .first()
    )
    if not pu:
        db.add(
            PatentUsecase(
                patent_id=p.id,
                usecase_text=usecase_text,
                normalized_usecase_text=None,
                extraction_method="manual",
                quality_score=0.9,
            )
        )

    # -------------------------
    # 4) MatrixRule（該非判定マトリクスの最小サンプル）
    # -------------------------
    # ※ item_no はあなたの体系に合わせて置換してください（例: "3A001" など）
    def ensure_rule(regime: str, item_no: str, title: str, requirement_text: str):
        r = (
            db.query(MatrixRule)
            .filter(MatrixRule.regime == regime, MatrixRule.item_no == item_no, MatrixRule.version.is_(None))
            .first()
        )
        if not r:
            db.add(
                MatrixRule(
                    regime=regime,
                    list_name="SeedList",
                    item_no=item_no,
                    title=title,
                    requirement_text=requirement_text,
                    usage_criteria_text=None,
                    tech_criteria_text=None,
                    notes="seed rule",
                    version=None,
                )
            )

    ensure_rule(
        regime="JP_FX",
        item_no="3A-Seed-001",
        title="フォトリソグラフィ関連（用途要件サンプル）",
        requirement_text="半導体製造のフォトリソグラフィ工程に用いる材料・装置・プロセス（用途要件を含む）",
    )
    ensure_rule(
        regime="JP_FX",
        item_no="3A-Seed-002",
        title="微細加工向け感光材料（用途要件サンプル）",
        requirement_text="微細加工を目的とする露光・現像工程に用いる感光性材料（用途要件を含む）",
    )

    db.flush()


def main() -> None:
    db = SessionLocal()
    try:
        upsert_min_seed(db)
        db.commit()
        print("Seed data inserted/updated successfully.")
    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
