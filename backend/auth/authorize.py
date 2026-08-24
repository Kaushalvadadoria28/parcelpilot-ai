"""The single authorization chokepoint for structured and document data.

`ScopedRepository` wraps the trusted, unscoped functions in
`backend/db/queries.py` (Milestone 1) with account- and role-based
authorization. It never modifies those functions — Milestone 1's query
layer is untouched and remains directly callable by anything that has
already established it is operating in a trusted context (tests, this
module itself). Everything else — the future agent tool layer, API routes
— must go through here instead.

Enforcement shape:

  * Single-item lookups for orders and tickets (`get_order`, `get_ticket`)
    search within an already-account-scoped list for a customer principal
    (`list_orders`/`list_tickets` with `account_id` forced to the
    principal's own account) rather than fetching the row unscoped and
    checking it afterwards. Because Milestone 1's `list_orders`/
    `list_tickets` apply that filter in the SQL `WHERE` clause, a row
    belonging to a different account is never fetched from storage at
    all — not fetched-then-discarded, genuinely never read.
  * `get_account` needs no query to decide authorization at all: the
    account id being requested either matches the principal's own scope
    or it doesn't, so a mismatched request is rejected before any query
    runs.
  * `get_doc_chunk` reuses `list_doc_chunks` (already scoped) the same
    way.
  * List operations filter to only the rows the principal may see; a
    customer principal never receives another account's row in a list
    result, and a document chunk scoped to a different customer's
    contract is dropped, while general (unscoped) documents remain
    visible to everyone.
  * Every denial raises `AuthorizationError` — a hard denial, never a
    partial or redacted object returned alongside it (see
    `docs/system-design.md` Part I).
  * Sensitive fields are stripped from every object returned to a
    customer principal, including their own account's rows.
"""

from __future__ import annotations

import sqlite3

from backend.auth.permissions import (
    SENSITIVE_ACCOUNT_FIELDS_FOR_CUSTOMER,
    SENSITIVE_TICKET_FIELDS_FOR_CUSTOMER,
    can_read_cross_account,
)
from backend.auth.principal import Principal
from backend.db import queries
from backend.models import Account, DocChunk, Order, Ticket


class AuthorizationError(Exception):
    """The principal is not permitted to access this resource.

    Always a hard denial: callers must not catch this and fall back to
    returning a partial, redacted, or "empty means no" substitute — the
    caller either gets the authorized object or this exception, nothing
    in between.
    """


class NotFoundError(Exception):
    """The requested resource does not exist.

    Distinct from `AuthorizationError`. Only ever raised for a principal
    whose role already grants unscoped read access to the resource type
    in question — a customer's lookup of a resource outside their scope
    raises `AuthorizationError` instead, deliberately not distinguishing
    "not yours" from "doesn't exist" (see module docstring).
    """


def _redact_account_for_customer(account: Account) -> Account:
    updates = {field: None for field in SENSITIVE_ACCOUNT_FIELDS_FOR_CUSTOMER}
    return account.model_copy(update=updates)


def _redact_ticket_for_customer(ticket: Ticket) -> Ticket:
    updates = {field: None for field in SENSITIVE_TICKET_FIELDS_FOR_CUSTOMER}
    return ticket.model_copy(update=updates)


class ScopedRepository:
    """A Principal-scoped view over the structured/document data layer."""

    def __init__(self, principal: Principal, *, conn: sqlite3.Connection | None = None):
        self.principal = principal
        self._conn = conn

    # -- accounts ----------------------------------------------------------

    def get_account(self, account_id: str) -> Account:
        if (
            not can_read_cross_account(self.principal.role)
            and account_id != self.principal.account_id
        ):
            raise AuthorizationError(
                f"Principal {self.principal.user_id!r} may not access account {account_id!r}."
            )
        account = queries.get_account(account_id, conn=self._conn)
        if account is None:
            raise NotFoundError(f"Account {account_id!r} not found.")
        if not can_read_cross_account(self.principal.role):
            return _redact_account_for_customer(account)
        return account

    def list_accounts(self) -> list[Account]:
        if not can_read_cross_account(self.principal.role):
            assert self.principal.account_id is not None  # enforced by Principal itself
            return [self.get_account(self.principal.account_id)]
        return queries.list_accounts(conn=self._conn)

    # -- orders --------------------------------------------------------------

    def get_order(self, order_id: str) -> Order:
        if not can_read_cross_account(self.principal.role):
            for order in self.list_orders():
                if order.order_id == order_id:
                    return order
            raise AuthorizationError(
                f"Principal {self.principal.user_id!r} may not access order {order_id!r}."
            )
        fetched_order = queries.get_order(order_id, conn=self._conn)
        if fetched_order is None:
            raise NotFoundError(f"Order {order_id!r} not found.")
        return fetched_order

    def list_orders(
        self, *, account_id: str | None = None, status: str | None = None
    ) -> list[Order]:
        if not can_read_cross_account(self.principal.role):
            # Force the caller's own scope regardless of what was asked
            # for — a customer cannot widen this by passing another
            # account_id.
            account_id = self.principal.account_id
        return queries.list_orders(account_id=account_id, status=status, conn=self._conn)

    # -- tickets ---------------------------------------------------------------

    def get_ticket(self, ticket_id: str) -> Ticket:
        if not can_read_cross_account(self.principal.role):
            for ticket in self.list_tickets():  # already redacted for this role
                if ticket.ticket_id == ticket_id:
                    return ticket
            raise AuthorizationError(
                f"Principal {self.principal.user_id!r} may not access ticket {ticket_id!r}."
            )
        fetched_ticket = queries.get_ticket(ticket_id, conn=self._conn)
        if fetched_ticket is None:
            raise NotFoundError(f"Ticket {ticket_id!r} not found.")
        return fetched_ticket

    def list_tickets(
        self, *, account_id: str | None = None, status: str | None = None
    ) -> list[Ticket]:
        cross_account = can_read_cross_account(self.principal.role)
        if not cross_account:
            account_id = self.principal.account_id
        tickets = queries.list_tickets(account_id=account_id, status=status, conn=self._conn)
        if not cross_account:
            return [_redact_ticket_for_customer(t) for t in tickets]
        return tickets

    # -- documents ---------------------------------------------------------------

    def get_doc_chunk(self, chunk_id: int) -> DocChunk:
        for chunk in self.list_doc_chunks():
            if chunk.chunk_id == chunk_id:
                return chunk
        # Not visible to this principal. For internal roles (who can see
        # every chunk), that means it genuinely doesn't exist. For a
        # customer it may exist but be scoped to a different account —
        # deliberately not distinguished, so "not found" can't be used as
        # a side channel to probe another account's contract chunk ids.
        if not can_read_cross_account(self.principal.role):
            raise AuthorizationError(
                f"Principal {self.principal.user_id!r} may not access document chunk {chunk_id}."
            )
        raise NotFoundError(f"Document chunk {chunk_id} not found.")

    def list_doc_chunks(self) -> list[DocChunk]:
        all_chunks = queries.list_doc_chunks(conn=self._conn)
        if can_read_cross_account(self.principal.role):
            return all_chunks
        return [
            chunk
            for chunk in all_chunks
            if chunk.customer_account_id is None
            or chunk.customer_account_id == self.principal.account_id
        ]
