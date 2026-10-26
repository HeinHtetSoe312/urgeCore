"""initial schema: users, ledger, crowdfunding, outbox and spending-friction tables

Revision ID: 001
Revises:
Create Date: 2026-10-18

Generated from the models with Alembic's autogenerate renderer, then reviewed by hand
(Postgres-specific fixes: JSONB import, boolean server default). Spending-friction and outbox
tables are created now so the schema matches the models; they have no features yet.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('outbox_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('event_type', sa.String(length=50), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('processed', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_outbox_events'))
    )
    op.create_index('ix_outbox_unprocessed', 'outbox_events', ['created_at'], unique=False, postgresql_where=sa.text('processed = false'))
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=80), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('balance', sa.Numeric(precision=12, scale=2), server_default='100.00', nullable=False),
    sa.Column('internal_credit_score', sa.Integer(), server_default='600', nullable=False),
    sa.Column('verification_tier', sa.String(length=20), server_default='Basic', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('balance >= 0', name=op.f('ck_users_balance_non_negative')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_table('crowdfund_campaigns',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('creator_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('target_amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('current_raised', sa.Numeric(precision=12, scale=2), server_default='0.00', nullable=False),
    sa.Column('weighted_yield_sum', sa.Numeric(precision=18, scale=4), server_default='0', nullable=False),
    sa.Column('target_interest_rate', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('final_settled_rate', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('status', sa.String(length=30), server_default='active', nullable=False),
    sa.Column('settlement_deadline', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('active', 'pending_settlement', 'funded', 'expired')", name=op.f('ck_crowdfund_campaigns_status_valid')),
    sa.CheckConstraint('current_raised >= 0 AND current_raised <= target_amount', name=op.f('ck_crowdfund_campaigns_raised_in_range')),
    sa.CheckConstraint('target_amount > 0', name=op.f('ck_crowdfund_campaigns_target_positive')),
    sa.ForeignKeyConstraint(['creator_id'], ['users.id'], name=op.f('fk_crowdfund_campaigns_creator_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_crowdfund_campaigns'))
    )
    op.create_index('ix_campaign_status_deadline', 'crowdfund_campaigns', ['status', 'settlement_deadline'], unique=False)
    op.create_index(op.f('ix_crowdfund_campaigns_id'), 'crowdfund_campaigns', ['id'], unique=False)
    op.create_table('friction_configs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(length=50), nullable=False),
    sa.Column('tier_level', sa.String(length=20), nullable=False),
    sa.Column('consecutive_overrides', sa.Integer(), server_default='0', nullable=False),
    sa.CheckConstraint("tier_level IN ('Relaxed', 'Medium', 'Strict')", name=op.f('ck_friction_configs_tier_level_valid')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_friction_configs_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_friction_configs')),
    sa.UniqueConstraint('user_id', 'category', name=op.f('uq_friction_configs_user_id'))
    )
    op.create_table('ledger_entries',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('entry_type', sa.String(length=30), nullable=False),
    sa.Column('reference_type', sa.String(length=30), nullable=False),
    sa.Column('reference_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("entry_type IN ('SPEND', 'ESCROW_HOLD', 'ESCROW_REFUND', 'PAYOUT')", name=op.f('ck_ledger_entries_entry_type_valid')),
    sa.CheckConstraint('amount <> 0', name=op.f('ck_ledger_entries_amount_non_zero')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_ledger_entries_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ledger_entries'))
    )
    op.create_index(op.f('ix_ledger_entries_user_id'), 'ledger_entries', ['user_id'], unique=False)
    op.create_table('spending_ledger',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('vendor', sa.String(length=100), nullable=False),
    sa.Column('category', sa.String(length=50), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('friction_unlock_time', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('Pending_Friction', 'Approved', 'Cancelled_By_User')", name=op.f('ck_spending_ledger_status_valid')),
    sa.CheckConstraint('amount > 0', name=op.f('ck_spending_ledger_amount_positive')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_spending_ledger_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_spending_ledger'))
    )
    op.create_index(op.f('ix_spending_ledger_user_id'), 'spending_ledger', ['user_id'], unique=False)
    op.create_table('crowdfund_contributions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('lender_yield_bid', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='held', nullable=False),
    sa.CheckConstraint("status IN ('held', 'released', 'refunded')", name=op.f('ck_crowdfund_contributions_status_valid')),
    sa.CheckConstraint('amount > 0', name=op.f('ck_crowdfund_contributions_amount_positive')),
    sa.ForeignKeyConstraint(['campaign_id'], ['crowdfund_campaigns.id'], name=op.f('fk_crowdfund_contributions_campaign_id_crowdfund_campaigns')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_crowdfund_contributions_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_crowdfund_contributions'))
    )
    op.create_index(op.f('ix_crowdfund_contributions_campaign_id'), 'crowdfund_contributions', ['campaign_id'], unique=False)
    


def downgrade() -> None:
    op.drop_index(op.f('ix_crowdfund_contributions_campaign_id'), table_name='crowdfund_contributions')
    op.drop_table('crowdfund_contributions')
    op.drop_index(op.f('ix_spending_ledger_user_id'), table_name='spending_ledger')
    op.drop_table('spending_ledger')
    op.drop_index(op.f('ix_ledger_entries_user_id'), table_name='ledger_entries')
    op.drop_table('ledger_entries')
    op.drop_table('friction_configs')
    op.drop_index(op.f('ix_crowdfund_campaigns_id'), table_name='crowdfund_campaigns')
    op.drop_index('ix_campaign_status_deadline', table_name='crowdfund_campaigns')
    op.drop_table('crowdfund_campaigns')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_table('users')
    op.drop_index('ix_outbox_unprocessed', table_name='outbox_events', postgresql_where=sa.text('processed = false'))
    op.drop_table('outbox_events')
    
