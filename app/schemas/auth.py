"""Request/response contracts for auth and account. Clients can never set balance etc."""

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Username = Annotated[
    str,
    StringConstraints(
        min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$", strip_whitespace=True
    ),
]
Password = Annotated[str, StringConstraints(min_length=12, max_length=128)]


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown fields are rejected

    username: Username
    password: Password


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type label, not a secret


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    balance: Decimal
    verification_tier: str
