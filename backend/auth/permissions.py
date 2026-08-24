"""Role -> permission matrix.

This is the single source of truth for what each role may do. The
authorization chokepoint (`backend/auth/authorize.py`) consults it for
data-scoping decisions now; the action layer (Milestone 4) and tool layer
(Milestone 5) will consult the same module for action-type permissions
later, rather than hard-coding their own role checks.
"""

from __future__ import annotations

from backend.auth.principal import Role

# ---------------------------------------------------------------------------
# Read scoping
# ---------------------------------------------------------------------------

# Roles that may read structured data and documents across accounts. A
# customer principal only ever sees their own account's rows; both
# internal roles may read across accounts. See backend/auth/authorize.py.
_CROSS_ACCOUNT_READ_ROLES: frozenset[Role] = frozenset({Role.INTERNAL_AGENT, Role.INTERNAL_ADMIN})


def can_read_cross_account(role: Role) -> bool:
    return role in _CROSS_ACCOUNT_READ_ROLES


# ---------------------------------------------------------------------------
# Sensitive-field redaction
# ---------------------------------------------------------------------------

# Fields stripped from a customer-role response, even for their own
# account's rows. Internal roles see these fields unredacted.
SENSITIVE_ACCOUNT_FIELDS_FOR_CUSTOMER: frozenset[str] = frozenset({"csm"})
SENSITIVE_TICKET_FIELDS_FOR_CUSTOMER: frozenset[str] = frozenset(
    {"assigned_to", "historical_resolution"}
)

# ---------------------------------------------------------------------------
# State-changing action permissions (consumed by Milestone 4 onward; this
# module's shape does not need to change for that milestone to add concrete
# action handlers, only to extend the sets below if a new action type is
# introduced).
# ---------------------------------------------------------------------------

# A customer may only ask for things that require staff judgment or
# approval; only internal roles may propose the actions that actually
# resolve those requests, and only an admin may propose an adjustment that
# falls outside what the deterministic rule engine itself computed (e.g. an
# ad hoc fee waiver the rule engine did not calculate).
_ACTION_TYPES_BY_ROLE: dict[Role, frozenset[str]] = {
    Role.CUSTOMER: frozenset({"request_escalation", "request_credit_review"}),
    Role.INTERNAL_AGENT: frozenset(
        {
            "request_escalation",
            "request_credit_review",
            "create_escalation",
            "update_ticket",
            "create_follow_up_task",
            "issue_service_credit",
        }
    ),
    Role.INTERNAL_ADMIN: frozenset(
        {
            "request_escalation",
            "request_credit_review",
            "create_escalation",
            "update_ticket",
            "create_follow_up_task",
            "issue_service_credit",
            "waive_fee_manually",
        }
    ),
}


def can_propose_action(role: Role, action_type: str) -> bool:
    return action_type in _ACTION_TYPES_BY_ROLE.get(role, frozenset())


def allowed_action_types(role: Role) -> frozenset[str]:
    return _ACTION_TYPES_BY_ROLE.get(role, frozenset())
