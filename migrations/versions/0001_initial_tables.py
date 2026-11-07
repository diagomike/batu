"""initial tables

Revision ID: 0001
Revises: 
Create Date: 2026-11-07 03:14:13.085745
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ask_log',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('at', sa.String(length=25), nullable=False),
    sa.Column('lang', sa.String(length=5), nullable=True),
    sa.Column('question', sa.Text(), nullable=True),
    sa.Column('mode', sa.String(length=20), nullable=True),
    sa.Column('found', sa.Boolean(), nullable=True),
    sa.Column('sources', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('ms', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('ask_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ask_log_at'), ['at'], unique=False)

    op.create_table('content_docs',
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('updated_at', sa.String(length=26), nullable=False),
    sa.Column('updated_by', sa.String(length=64), nullable=False),
    sa.Column('seed_hash', sa.String(length=40), nullable=True),
    sa.PrimaryKeyConstraint('name')
    )
    op.create_table('content_versions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('saved_at', sa.String(length=26), nullable=False),
    sa.Column('who', sa.String(length=64), nullable=True),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('content_versions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_content_versions_name'), ['name'], unique=False)

    op.create_table('media_files',
    sa.Column('slug', sa.String(length=80), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('content_type', sa.String(length=40), nullable=False),
    sa.Column('data', sa.LargeBinary().with_variant(mysql.LONGBLOB(), 'mysql'), nullable=False),
    sa.Column('updated_at', sa.String(length=26), nullable=False),
    sa.PrimaryKeyConstraint('slug', 'size')
    )
    op.create_table('payments',
    sa.Column('id', sa.String(length=20), nullable=False),
    sa.Column('request_ref', sa.String(length=40), nullable=False),
    sa.Column('amount', sa.Float(), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created', sa.String(length=25), nullable=False),
    sa.Column('receipt', sa.String(length=20), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_payments_request_ref'), ['request_ref'], unique=False)

    op.create_table('requests',
    sa.Column('ref', sa.String(length=40), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('service_id', sa.String(length=80), nullable=True),
    sa.Column('title', sa.String(length=300), nullable=True),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('amount', sa.Float(), nullable=True),
    sa.Column('paid', sa.Boolean(), nullable=False),
    sa.Column('created', sa.String(length=25), nullable=False),
    sa.Column('updated', sa.String(length=25), nullable=False),
    sa.Column('history', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.PrimaryKeyConstraint('ref')
    )
    with op.batch_alter_table('requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_requests_created'), ['created'], unique=False)
        batch_op.create_index(batch_op.f('ix_requests_status'), ['status'], unique=False)

    op.create_table('settings',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Text().with_variant(mysql.LONGTEXT(), 'mysql'), nullable=False),
    sa.Column('updated_at', sa.String(length=26), nullable=True),
    sa.Column('updated_by', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('studio_users',
    sa.Column('name', sa.String(length=32), nullable=False),
    sa.Column('salt', sa.String(length=64), nullable=False),
    sa.Column('hash', sa.String(length=128), nullable=False),
    sa.Column('role', sa.String(length=10), nullable=False),
    sa.Column('created', sa.String(length=25), nullable=False),
    sa.PrimaryKeyConstraint('name')
    )
    op.create_table('subscriptions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('at', sa.String(length=25), nullable=False),
    sa.Column('channel', sa.String(length=20), nullable=False),
    sa.Column('contact', sa.String(length=200), nullable=False),
    sa.Column('topics', sa.String(length=200), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('uploads',
    sa.Column('name', sa.String(length=40), nullable=False),
    sa.Column('content_type', sa.String(length=40), nullable=False),
    sa.Column('data', sa.LargeBinary().with_variant(mysql.LONGBLOB(), 'mysql'), nullable=False),
    sa.Column('created', sa.String(length=25), nullable=False),
    sa.PrimaryKeyConstraint('name')
    )


def downgrade():
    op.drop_table('uploads')
    op.drop_table('subscriptions')
    op.drop_table('studio_users')
    op.drop_table('settings')
    with op.batch_alter_table('requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_requests_status'))
        batch_op.drop_index(batch_op.f('ix_requests_created'))

    op.drop_table('requests')
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_payments_request_ref'))

    op.drop_table('payments')
    op.drop_table('media_files')
    with op.batch_alter_table('content_versions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_content_versions_name'))

    op.drop_table('content_versions')
    op.drop_table('content_docs')
    with op.batch_alter_table('ask_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ask_log_at'))

    op.drop_table('ask_log')
