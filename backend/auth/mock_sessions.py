"""Mocked persona/session registry.

Provides `Principal`s for local development and testing without any real
authentication — appropriate for this stage of the project per
`docs/system-design.md` Part I. Real HTTP session/token issuance is
Milestone 6's job (an `/auth` route); this module is only consumed
in-process for now, by tests and, once it exists, the agent tool layer.

Internal-role personas are static, since they are not bound to any
account. A customer persona is built for a specific `account_id` at call
time rather than hard-coded here — this module does not assume which
accounts exist, so it works unchanged against the synthetic fixtures, the
real locally-supplied pack, or a substituted one with entirely different
account ids (see `docs/git-development-plan.md` §2 on not hard-coding real
assessment identifiers into application code).
"""

from __future__ import annotations

from backend.auth.principal import Principal, Role

INTERNAL_AGENT: Principal = Principal(
    user_id="demo-internal-agent",
    display_name="Internal Support Agent (demo)",
    role=Role.INTERNAL_AGENT,
)

INTERNAL_ADMIN: Principal = Principal(
    user_id="demo-internal-admin",
    display_name="Internal Admin (demo)",
    role=Role.INTERNAL_ADMIN,
)

_STATIC_PERSONAS: dict[str, Principal] = {
    INTERNAL_AGENT.user_id: INTERNAL_AGENT,
    INTERNAL_ADMIN.user_id: INTERNAL_ADMIN,
}


def customer_principal(account_id: str, *, display_name: str | None = None) -> Principal:
    """Build a customer-role Principal scoped to `account_id`.

    Takes the account id as a parameter rather than assuming a fixed set
    of demo accounts, so callers (tests now; the API layer from Milestone
    6 onward) can look up real accounts via `backend.db.queries.
    list_accounts()` and construct a persona for any of them.
    """
    return Principal(
        user_id=f"demo-customer-{account_id}",
        display_name=display_name or f"Customer contact ({account_id})",
        role=Role.CUSTOMER,
        account_id=account_id,
    )


def get_static_persona(user_id: str) -> Principal | None:
    """Look up one of the fixed (non-account-specific) demo personas."""
    return _STATIC_PERSONAS.get(user_id)


def list_static_personas() -> list[Principal]:
    return list(_STATIC_PERSONAS.values())
