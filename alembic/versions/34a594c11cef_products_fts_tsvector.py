"""products fts tsvector

Revision ID: 34a594c11cef
Revises: c7ba320979d3
Create Date: 2026-05-20 14:39:57.246780

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '34a594c11cef'
down_revision: Union[str, Sequence[str], None] = 'c7ba320979d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Generated tsvector column kept in sync by Postgres itself — no trigger needed.
    # `english` config is fine even for KE products (we mostly index English text);
    # if you start carrying Swahili copy at scale, switch to a custom config.
    op.execute(
        """
        ALTER TABLE products
        ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
          setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
          setweight(to_tsvector('english', coalesce(brand, '')), 'B') ||
          setweight(to_tsvector('english', coalesce(description, '')), 'C')
        ) STORED;
        """
    )
    op.execute(
        "CREATE INDEX ix_products_search_vector ON products USING GIN (search_vector);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_search_vector;")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS search_vector;")
