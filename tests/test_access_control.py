"""Tests for the Milestone 2 authorization layer (backend/auth/).

Runs entirely against the synthetic fixture database (tests/conftest.py's
`synthetic_db_connection`, built from tests/fixtures/synthetic_dataset.py)
— never the real proprietary pack. The authorization function itself is
tested directly here; adversarial "trick the agent into asking for this"
variants are deferred to Milestone 9, once an agent exists to try tricking
(see docs/git-development-plan.md, Milestone 2).
"""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from backend.auth import mock_sessions
from backend.auth.authorize import AuthorizationError, NotFoundError, ScopedRepository
from backend.auth.permissions import can_propose_action, can_read_cross_account
from backend.auth.principal import Principal, Role
from backend.db import queries as db_queries

# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------


class TestPrincipal:
    def test_customer_without_account_id_is_rejected(self):
        with pytest.raises(ValidationError):
            Principal(user_id="x", display_name="x", role=Role.CUSTOMER, account_id=None)

    def test_internal_roles_do_not_require_an_account_id(self):
        principal = Principal(user_id="x", display_name="x", role=Role.INTERNAL_AGENT)
        assert principal.account_id is None

    def test_principal_is_immutable(self):
        principal = mock_sessions.customer_principal("FIX-ACCT-001")
        with pytest.raises(ValidationError):
            principal.account_id = "FIX-ACCT-002"  # type: ignore[misc]

    def test_is_internal_property(self):
        assert mock_sessions.customer_principal("FIX-ACCT-001").is_internal is False
        assert mock_sessions.INTERNAL_AGENT.is_internal is True
        assert mock_sessions.INTERNAL_ADMIN.is_internal is True


# ---------------------------------------------------------------------------
# mock_sessions
# ---------------------------------------------------------------------------


class TestMockSessions:
    def test_customer_principal_scopes_to_the_given_account(self):
        principal = mock_sessions.customer_principal("FIX-ACCT-003")
        assert principal.role == Role.CUSTOMER
        assert principal.account_id == "FIX-ACCT-003"

    def test_static_personas_have_no_account_scope(self):
        assert mock_sessions.INTERNAL_AGENT.account_id is None
        assert mock_sessions.INTERNAL_ADMIN.account_id is None

    def test_get_static_persona_lookup(self):
        found = mock_sessions.get_static_persona(mock_sessions.INTERNAL_AGENT.user_id)
        assert found == mock_sessions.INTERNAL_AGENT
        assert mock_sessions.get_static_persona("not-a-real-user") is None

    def test_list_static_personas_contains_both_internal_roles(self):
        roles = {p.role for p in mock_sessions.list_static_personas()}
        assert roles == {Role.INTERNAL_AGENT, Role.INTERNAL_ADMIN}


# ---------------------------------------------------------------------------
# permissions
# ---------------------------------------------------------------------------


class TestPermissions:
    @pytest.mark.parametrize(
        ("role", "expected"),
        [
            (Role.CUSTOMER, False),
            (Role.INTERNAL_AGENT, True),
            (Role.INTERNAL_ADMIN, True),
        ],
    )
    def test_can_read_cross_account(self, role, expected):
        assert can_read_cross_account(role) is expected

    def test_customer_cannot_propose_internal_only_action_types(self):
        assert can_propose_action(Role.CUSTOMER, "waive_fee_manually") is False
        assert can_propose_action(Role.CUSTOMER, "update_ticket") is False

    def test_customer_can_propose_its_own_action_types(self):
        assert can_propose_action(Role.CUSTOMER, "request_escalation") is True
        assert can_propose_action(Role.CUSTOMER, "request_credit_review") is True

    def test_only_admin_may_waive_a_fee_manually(self):
        assert can_propose_action(Role.INTERNAL_AGENT, "waive_fee_manually") is False
        assert can_propose_action(Role.INTERNAL_ADMIN, "waive_fee_manually") is True

    def test_unknown_action_type_is_denied_for_every_role(self):
        for role in Role:
            assert can_propose_action(role, "not_a_real_action_type") is False


# ---------------------------------------------------------------------------
# Account access control
# ---------------------------------------------------------------------------


class TestAccountAccessControl:
    def test_customer_can_access_their_own_account(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-001"), conn=synthetic_db_connection
        )
        account = repo.get_account("FIX-ACCT-001")
        assert account.account_id == "FIX-ACCT-001"

    def test_customer_cannot_access_another_accounts_account(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-001"), conn=synthetic_db_connection
        )
        with pytest.raises(AuthorizationError):
            repo.get_account("FIX-ACCT-002")

    def test_customer_account_response_has_csm_redacted(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-001"), conn=synthetic_db_connection
        )
        account = repo.get_account("FIX-ACCT-001")
        assert account.csm is None
        # Non-sensitive fields are still present.
        assert account.account_name == "Fixture Freight Co"
        assert account.plan == "Enterprise"

    def test_internal_role_can_access_any_account_with_csm_visible(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(mock_sessions.INTERNAL_AGENT, conn=synthetic_db_connection)
        account = repo.get_account("FIX-ACCT-002")
        assert account.csm == "Fixture CSM B"

    def test_customer_list_accounts_returns_only_their_own(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-003"), conn=synthetic_db_connection
        )
        accounts = repo.list_accounts()
        assert [a.account_id for a in accounts] == ["FIX-ACCT-003"]
        assert accounts[0].csm is None

    def test_internal_list_accounts_returns_every_account_unredacted(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(mock_sessions.INTERNAL_ADMIN, conn=synthetic_db_connection)
        accounts = repo.list_accounts()
        assert {a.account_id for a in accounts} == {"FIX-ACCT-001", "FIX-ACCT-002", "FIX-ACCT-003"}
        assert all(a.csm is not None for a in accounts)

    def test_get_account_not_found_for_internal_role(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(mock_sessions.INTERNAL_AGENT, conn=synthetic_db_connection)
        with pytest.raises(NotFoundError):
            repo.get_account("NOT-A-REAL-ACCOUNT")


# ---------------------------------------------------------------------------
# Order access control
# ---------------------------------------------------------------------------


class TestOrderAccessControl:
    def test_customer_can_access_their_own_order(self, synthetic_db_connection: sqlite3.Connection):
        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-001"), conn=synthetic_db_connection
        )
        order = repo.get_order("FIX-ORD-001")
        assert order.order_id == "FIX-ORD-001"

    def test_customer_cannot_access_another_accounts_order(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-001"), conn=synthetic_db_connection
        )
        with pytest.raises(AuthorizationError):
            repo.get_order("FIX-ORD-002")  # belongs to FIX-ACCT-002

    def test_customer_list_orders_never_includes_other_accounts(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-001"), conn=synthetic_db_connection
        )
        orders = repo.list_orders()
        assert [o.order_id for o in orders] == ["FIX-ORD-001"]

    def test_customer_cannot_widen_scope_via_account_id_argument(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-001"), conn=synthetic_db_connection
        )
        orders = repo.list_orders(account_id="FIX-ACCT-002")  # attempted override
        assert [o.order_id for o in orders] == ["FIX-ORD-001"]

    def test_internal_role_can_access_any_order(self, synthetic_db_connection: sqlite3.Connection):
        repo = ScopedRepository(mock_sessions.INTERNAL_AGENT, conn=synthetic_db_connection)
        order = repo.get_order("FIX-ORD-002")
        assert order.order_id == "FIX-ORD-002"

    def test_internal_list_orders_with_no_filter_spans_every_account(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(mock_sessions.INTERNAL_ADMIN, conn=synthetic_db_connection)
        orders = repo.list_orders()
        assert {o.account_id for o in orders} == {"FIX-ACCT-001", "FIX-ACCT-002", "FIX-ACCT-003"}

    def test_get_order_not_found_for_internal_role(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(mock_sessions.INTERNAL_AGENT, conn=synthetic_db_connection)
        with pytest.raises(NotFoundError):
            repo.get_order("NOT-A-REAL-ORDER")


# ---------------------------------------------------------------------------
# Ticket access control + sensitive-field redaction
# ---------------------------------------------------------------------------


class TestTicketAccessControl:
    def test_customer_can_access_their_own_ticket(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-001"), conn=synthetic_db_connection
        )
        ticket = repo.get_ticket("FIX-TKT-001")
        assert ticket.ticket_id == "FIX-TKT-001"

    def test_customer_cannot_access_another_accounts_ticket(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-001"), conn=synthetic_db_connection
        )
        with pytest.raises(AuthorizationError):
            repo.get_ticket("FIX-TKT-002")  # belongs to FIX-ACCT-002

    def test_customer_ticket_response_has_sensitive_fields_redacted(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-002"), conn=synthetic_db_connection
        )
        ticket = repo.get_ticket("FIX-TKT-002")
        assert ticket.assigned_to is None
        assert ticket.historical_resolution is None
        # Non-sensitive fields are still present.
        assert ticket.subject == "Cancellation fee question"
        assert ticket.status == "closed"

    def test_customer_list_tickets_redacts_every_row(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-001"), conn=synthetic_db_connection
        )
        tickets = repo.list_tickets()
        assert tickets  # sanity: fixture actually has a ticket for this account
        assert all(t.assigned_to is None for t in tickets)
        assert all(t.historical_resolution is None for t in tickets)

    def test_internal_role_sees_unredacted_ticket_fields(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(mock_sessions.INTERNAL_AGENT, conn=synthetic_db_connection)
        ticket = repo.get_ticket("FIX-TKT-002")
        assert ticket.assigned_to == "Fixture Agent B"
        assert ticket.historical_resolution is not None

    def test_internal_list_tickets_spans_every_account_unredacted(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(mock_sessions.INTERNAL_ADMIN, conn=synthetic_db_connection)
        tickets = repo.list_tickets()
        assert {t.account_id for t in tickets} == {"FIX-ACCT-001", "FIX-ACCT-002"}
        assert any(t.historical_resolution is not None for t in tickets)

    def test_get_ticket_not_found_for_internal_role(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(mock_sessions.INTERNAL_AGENT, conn=synthetic_db_connection)
        with pytest.raises(NotFoundError):
            repo.get_ticket("NOT-A-REAL-TICKET")


# ---------------------------------------------------------------------------
# Document / contract access control
# ---------------------------------------------------------------------------


class TestDocumentAccessControl:
    def test_customer_sees_general_documents_and_their_own_contract(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-001"), conn=synthetic_db_connection
        )
        sources = {chunk.source_file for chunk in repo.list_doc_chunks()}
        assert "fixture_contract_a.txt" in sources  # their own contract
        assert "fixture_sop.txt" in sources  # general document
        assert "fixture_policy_v2_current.txt" in sources  # general document
        assert "fixture_contract_b.txt" not in sources  # another customer's contract

    def test_get_doc_chunk_denies_another_customers_contract(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        internal_repo = ScopedRepository(mock_sessions.INTERNAL_AGENT, conn=synthetic_db_connection)
        contract_b_chunk = next(
            c for c in internal_repo.list_doc_chunks() if c.source_file == "fixture_contract_b.txt"
        )

        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-001"), conn=synthetic_db_connection
        )
        with pytest.raises(AuthorizationError):
            repo.get_doc_chunk(contract_b_chunk.chunk_id)

    def test_get_doc_chunk_allows_a_general_document_for_any_customer(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        internal_repo = ScopedRepository(mock_sessions.INTERNAL_AGENT, conn=synthetic_db_connection)
        sop_chunk = next(
            c for c in internal_repo.list_doc_chunks() if c.source_file == "fixture_sop.txt"
        )

        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-003"), conn=synthetic_db_connection
        )
        result = repo.get_doc_chunk(sop_chunk.chunk_id)
        assert result.chunk_id == sop_chunk.chunk_id

    def test_internal_role_sees_every_document(self, synthetic_db_connection: sqlite3.Connection):
        repo = ScopedRepository(mock_sessions.INTERNAL_ADMIN, conn=synthetic_db_connection)
        sources = {chunk.source_file for chunk in repo.list_doc_chunks()}
        assert sources == {
            "fixture_policy_v2_current.txt",
            "fixture_policy_v1_deprecated.txt",
            "fixture_sop.txt",
            "fixture_contract_a.txt",
            "fixture_contract_b.txt",
        }

    def test_get_doc_chunk_not_found_for_internal_role(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        repo = ScopedRepository(mock_sessions.INTERNAL_AGENT, conn=synthetic_db_connection)
        with pytest.raises(NotFoundError):
            repo.get_doc_chunk(999_999)


# ---------------------------------------------------------------------------
# Authorization happens before protected data is exposed
# ---------------------------------------------------------------------------


class TestAuthorizationHappensBeforeDataIsExposed:
    def test_cross_account_order_lookup_is_scoped_at_the_query_layer(
        self, synthetic_db_connection: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ):
        """Proves the denial isn't "fetch the row, then decide": the
        underlying Milestone 1 query is itself called with the caller's
        own account_id, so a different account's order is excluded by the
        SQL WHERE clause and never fetched from storage at all — verified
        on the query layer's call arguments, not just the final result.
        """
        original_list_orders = db_queries.list_orders
        recorded_calls: list[dict[str, object]] = []

        def spy(*, account_id=None, status=None, conn=None):
            recorded_calls.append({"account_id": account_id, "status": status})
            return original_list_orders(account_id=account_id, status=status, conn=conn)

        monkeypatch.setattr(db_queries, "list_orders", spy)

        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-001"), conn=synthetic_db_connection
        )
        with pytest.raises(AuthorizationError):
            repo.get_order("FIX-ORD-002")  # belongs to FIX-ACCT-002

        assert recorded_calls, "expected the query layer to have been called"
        assert all(call["account_id"] == "FIX-ACCT-001" for call in recorded_calls)

    def test_cross_account_ticket_lookup_is_scoped_at_the_query_layer(
        self, synthetic_db_connection: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ):
        original_list_tickets = db_queries.list_tickets
        recorded_calls: list[dict[str, object]] = []

        def spy(*, account_id=None, status=None, conn=None):
            recorded_calls.append({"account_id": account_id, "status": status})
            return original_list_tickets(account_id=account_id, status=status, conn=conn)

        monkeypatch.setattr(db_queries, "list_tickets", spy)

        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-001"), conn=synthetic_db_connection
        )
        with pytest.raises(AuthorizationError):
            repo.get_ticket("FIX-TKT-002")  # belongs to FIX-ACCT-002

        assert recorded_calls, "expected the query layer to have been called"
        assert all(call["account_id"] == "FIX-ACCT-001" for call in recorded_calls)

    def test_cross_account_account_lookup_never_queries_storage_at_all(
        self, synthetic_db_connection: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ):
        """get_account needs no query to decide authorization: the
        requested id either matches the principal's own scope or it
        doesn't, so a mismatch is rejected before any query runs at all."""
        recorded_calls: list[str] = []
        original_get_account = db_queries.get_account

        def spy(account_id, *, conn=None):
            recorded_calls.append(account_id)
            return original_get_account(account_id, conn=conn)

        monkeypatch.setattr(db_queries, "get_account", spy)

        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-001"), conn=synthetic_db_connection
        )
        with pytest.raises(AuthorizationError):
            repo.get_account("FIX-ACCT-002")

        assert recorded_calls == [], "expected no query at all for a scope mismatch"

    def test_denial_raises_rather_than_returning_a_partial_object(
        self, synthetic_db_connection: sqlite3.Connection
    ):
        """A denial is always a hard denial: the call either returns the
        authorized object or raises — there is no third "partial/None"
        outcome to accidentally treat as safe."""
        repo = ScopedRepository(
            mock_sessions.customer_principal("FIX-ACCT-001"), conn=synthetic_db_connection
        )
        with pytest.raises(AuthorizationError):
            result = repo.get_ticket("FIX-TKT-002")
            pytest.fail(f"expected AuthorizationError, got a return value instead: {result!r}")
