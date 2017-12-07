"""change last_updated_columns_type

Revision ID: e10a938e5801
Revises: 4e4814bebf31
Create Date: 2017-10-03 05:56:59.307155

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e10a938e5801'
down_revision = '4e4814bebf31'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('fort_sightings', sa.Column('updated', sa.Integer, nullable=True))
    op.add_column('pokestops', sa.Column('updated', sa.Integer, nullable=True))
    op.add_column('sightings', sa.Column('updated', sa.Integer, nullable=True))

def downgrade():
    op.drop_column('fort_sightings', 'updated')
    op.drop_column('pokestops', 'updated')
    op.drop_column('sightings', 'updated')


