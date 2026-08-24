"""Read-only SQLite connection helper for the structured data layer.

This is a trusted/internal connection point for Milestone 1: it has no
notion of who is calling it or what they are allowed to see. Milestone 2
adds a Principal-scoped wrapper around `backend/db/queries.py`'s functions
rather than modifying this module, so this stays a small, stable
foundation the authorization layer can build on top of.

The connection is opened read-only at the SQLite level (`mode=ro`), not
just "read-only by convention" — a bug in a future query function that
tried to write would fail loudly here rather than silently succeeding.
Writable access (state-changing actions, Milestone 4) is a deliberately
separate store, never this connection.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from backend.config import settings


def _default_db_path() -> Path:
    return settings.var_dir / "app.db"


def open_readonly_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a read-only connection to the ingested SQLite database.

    Raises `sqlite3.OperationalError` if the database file doesn't exist —
    deliberately not caught here, since "the database is missing" should
    fail loudly (run the Milestone 0 ingestion scripts first) rather than
    be mistaken for "the data legitimately has zero rows".
    """
    path = db_path if db_path is not None else _default_db_path()
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Context-manager form of `open_readonly_connection`."""
    conn = open_readonly_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()
