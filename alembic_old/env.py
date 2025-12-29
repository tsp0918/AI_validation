import os
from alembic import context
from sqlalchemy import engine_from_config, pool

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # .../AI_validation
sys.path.insert(0, str(PROJECT_ROOT))

from app.db.models import Base  # ← これだけでOK

target_metadata = Base.metadata

def get_url():
    return os.getenv("DATABASE_URL", "sqlite:///./app.db")

def run_migrations_online():
    config = context.config
    config.set_main_option("sqlalchemy.url", get_url())

    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()

run_migrations_online()
