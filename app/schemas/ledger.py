"""Read-only view of a user's own ledger rows."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class LedgerEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: Decimal
    entry_type: str
    reference_type: str
    reference_id: int
    created_at: datetime
