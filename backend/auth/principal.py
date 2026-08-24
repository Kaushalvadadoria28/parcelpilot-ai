"""Caller identity for authorization decisions.

A `Principal` is the one piece of caller identity that flows into every
authorization decision in this system (see `backend/auth/authorize.py`).
It is intentionally minimal: role and account scope, nothing else. Real
session/token issuance over HTTP is Milestone 6's job; this milestone only
needs the type and an in-process way to construct one (see
`backend/auth/mock_sessions.py`).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


class Role(StrEnum):
    CUSTOMER = "customer"
    INTERNAL_AGENT = "internal_agent"
    INTERNAL_ADMIN = "internal_admin"


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    display_name: str
    role: Role
    # None for internal roles, which are not bound to a single account.
    # Required for a customer principal — enforced below, since a
    # customer with no account scope would be a bug in whoever
    # constructed it, not a valid state to silently allow through.
    account_id: str | None = None

    @model_validator(mode="after")
    def _customer_must_have_an_account(self) -> Principal:
        if self.role is Role.CUSTOMER and self.account_id is None:
            raise ValueError("A customer Principal must have an account_id.")
        return self

    @property
    def is_internal(self) -> bool:
        return self.role is not Role.CUSTOMER
