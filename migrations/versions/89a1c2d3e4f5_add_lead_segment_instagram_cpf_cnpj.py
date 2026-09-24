"""add lead segment instagram and expand cpf for cnpj

Revision ID: 89a1c2d3e4f5
Revises: 1687461931eb
Create Date: 2026-09-23 14:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '89a1c2d3e4f5'
down_revision = '1687461931eb'
branch_labels = None
depends_on = None


def upgrade():
    # Adiciona colunas se não existirem
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('client')]

    if 'segment' not in columns:
        op.add_column('client', sa.Column('segment', sa.String(length=256), nullable=True))
    if 'instagram' not in columns:
        op.add_column('client', sa.Column('instagram', sa.String(length=256), nullable=True))
    if 'website' not in columns:
        op.add_column('client', sa.Column('website', sa.Text(), nullable=True))
    if 'category' not in columns:
        op.add_column('client', sa.Column('category', sa.String(length=256), nullable=True))

    # Expande cpf para VARCHAR(32) para comportar CNPJ formatado
    try:
        op.alter_column('client', 'cpf',
            existing_type=sa.String(length=14),
            type_=sa.String(length=32),
            existing_nullable=True
        )
    except Exception:
        pass


def downgrade():
    op.drop_column('client', 'instagram')
    op.drop_column('client', 'segment')
