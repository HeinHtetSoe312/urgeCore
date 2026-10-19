"""ORM models for Tier 1 (PRD section 3). Money is Numeric(12, 2) / Decimal, never float.

Friendship and SocialLoanMemo are deferred to Tier 3 and intentionally absent.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

MONEY = Numeric(12, 2)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# --------------------------------------------------------------------------- core
class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("balance >= 0", name="balance_non_negative"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    balance: Mapped[Decimal] = mapped_column(
        MONEY, default=Decimal("100.00"), server_default="100.00"
    )
    # Unused in Tier 1; only the Tier 3 repayment feature may change it.
    internal_credit_score: Mapped[int] = mapped_column(Integer, default=600, server_default="600")
    verification_tier: Mapped[str] = mapped_column(
        String(20), default="Basic", server_default="Basic"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LedgerEntry(Base):
    """Every balance change is one signed row here (PRD principle P2)."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint("amount <> 0", name="amount_non_zero"),
        CheckConstraint(
            "entry_type IN ('SPEND', 'ESCROW_HOLD', 'ESCROW_REFUND', 'PAYOUT')",
            name="entry_type_valid",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)  # signed: debits are negative
    entry_type: Mapped[str] = mapped_column(String(30))
    reference_type: Mapped[str] = mapped_column(String(30))
    reference_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ------------------------------------------------------------------------ domain A
class FrictionConfig(Base):
    __tablename__ = "friction_configs"
    __table_args__ = (
        UniqueConstraint("user_id", "category"),
        CheckConstraint("tier_level IN ('Relaxed', 'Medium', 'Strict')", name="tier_level_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    category: Mapped[str] = mapped_column(String(50))
    tier_level: Mapped[str] = mapped_column(String(20))
    consecutive_overrides: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class SpendingLedger(Base):
    __tablename__ = "spending_ledger"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "status IN ('Pending_Friction', 'Approved', 'Cancelled_By_User')",
            name="status_valid",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    vendor: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(50))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(30))
    friction_unlock_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ------------------------------------------------------------------------ domain B
class CrowdfundCampaign(Base):
    __tablename__ = "crowdfund_campaigns"
    __table_args__ = (
        CheckConstraint("target_amount > 0", name="target_positive"),
        CheckConstraint(
            "current_raised >= 0 AND current_raised <= target_amount", name="raised_in_range"
        ),
        CheckConstraint(
            "status IN ('active', 'pending_settlement', 'funded', 'expired')",
            name="status_valid",
        ),
        # Lets the reconciler find overdue settlements quickly.
        Index("ix_campaign_status_deadline", "status", "settlement_deadline"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(120))
    target_amount: Mapped[Decimal] = mapped_column(MONEY)
    current_raised: Mapped[Decimal] = mapped_column(
        MONEY, default=Decimal("0.00"), server_default="0.00"
    )
    # Running SUM(amount * bid) so VWAR = weighted_yield_sum / current_raised is O(1).
    weighted_yield_sum: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("0"), server_default="0"
    )
    target_interest_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))  # borrower's maximum
    final_settled_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active", server_default="active")
    settlement_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CrowdfundContribution(Base):
    __tablename__ = "crowdfund_contributions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("status IN ('held', 'released', 'refunded')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("crowdfund_campaigns.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    lender_yield_bid: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(20), default="held", server_default="held")


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "ix_outbox_unprocessed",
            "created_at",
            postgresql_where=text("processed = false"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSONB)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
