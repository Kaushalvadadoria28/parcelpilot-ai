"""Idempotent ingestion of the ParcelPilot document corpus into SQLite.

Reads `config/doc_manifest.yaml` (structural metadata: filename -> document
type, version, status, effective date, customer scope, authority tier) and
the matching files under the documents directory, splits each into
section-level chunks, and rebuilds the `doc_chunks` table. Safe to re-run at
any time.

Supports both real PDFs (via `pypdf`) and plain-text fixtures (read
directly), so the same chunking/metadata logic is exercised by tests
without ever needing the proprietary pack (see `tests/fixtures/`).

A document referenced by the manifest but not present locally is skipped
rather than treated as fatal, so ingestion still works against a partial or
substituted data pack.

Section splitting: PDF text extraction does not reliably preserve the
original line layout (bold/emphasized text in this corpus can extract as
one word per line). Section boundaries are therefore detected on
whitespace-normalized text using a boundary-anchored "N. " marker
(1-2 digits, so it can't match inside a larger number like "2026." or
"5,000."), which was validated against the real documents before being
adopted here. The derived `section` label is a best-effort heading
snippet for citation display; the full, exact section text is always
preserved verbatim in `content` regardless of label quality.

Usage:
    python -m backend.ingestion.build_doc_index [--documents-dir PATH] \
        [--manifest PATH] [--db-path PATH]
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml
from pypdf import PdfReader

from backend.config import settings

_HEADING = re.compile(r"\b\d{1,2}\.\s+(?=[A-Z])")
_BULLET = "●"  # '●', used as a body-content delimiter in this corpus
_HEADING_LABEL_MAX_WORDS = 6

_SCHEMA = """
DROP TABLE IF EXISTS doc_chunks;

CREATE TABLE doc_chunks (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    document_type TEXT NOT NULL,
    version TEXT,
    status TEXT NOT NULL,
    effective_date TEXT,
    customer_account_id TEXT,
    authority_tier TEXT NOT NULL,
    superseded_by TEXT,
    section TEXT NOT NULL,
    page INTEGER NOT NULL DEFAULT 1,
    content TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class DocMeta:
    filename: str
    document_type: str
    version: str | None
    status: str
    effective_date: str | None
    customer_account_id: str | None
    authority_tier: str
    superseded_by: str | None = None


def load_manifest(manifest_path: Path) -> list[DocMeta]:
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    return [
        DocMeta(
            filename=doc["filename"],
            document_type=doc["document_type"],
            version=doc.get("version"),
            status=doc["status"],
            effective_date=doc.get("effective_date"),
            customer_account_id=doc.get("customer_account_id"),
            authority_tier=str(doc["authority_tier"]),
            superseded_by=doc.get("superseded_by"),
        )
        for doc in raw["documents"]
    ]


def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(encoding="utf-8")


def _heading_label(chunk_text: str, max_words: int = _HEADING_LABEL_MAX_WORDS) -> str:
    marker, _, rest = chunk_text.partition(" ")
    bullet_idx = rest.find(_BULLET)
    if bullet_idx != -1:
        rest = rest[:bullet_idx]
    words = rest.split()[:max_words]
    label = " ".join(words).rstrip(" .")
    return f"{marker} {label}".strip()


def split_sections(text: str) -> list[tuple[str, str]]:
    """Split document text into (section_label, section_content) chunks.

    Text before the first numbered heading becomes a "Header" chunk (the
    title/status/effective-date block every document in this corpus starts
    with). Documents with no numbered headings at all (e.g. the deprecated
    policy, which uses only a table) become a single "Header" chunk.
    """
    flattened = re.sub(r"\s+", " ", text).strip()
    if not flattened:
        return []

    matches = list(_HEADING.finditer(flattened))
    if not matches:
        return [("Header", flattened)]

    sections: list[tuple[str, str]] = []
    header = flattened[: matches[0].start()].strip()
    if header:
        sections.append(("Header", header))

    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(flattened)
        chunk_text = flattened[start:end].strip()
        sections.append((_heading_label(chunk_text), chunk_text))

    return sections


def build_document_index(documents_dir: Path, manifest_path: Path, db_path: Path) -> int:
    """Rebuild `db_path`'s `doc_chunks` table. Returns the number of chunks written."""
    manifest = load_manifest(manifest_path)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    chunk_count = 0
    try:
        conn.executescript(_SCHEMA)

        for doc in manifest:
            doc_path = documents_dir / doc.filename
            if not doc_path.exists():
                continue

            text = extract_text(doc_path)
            rows = [
                (
                    doc.filename,
                    doc.document_type,
                    doc.version,
                    doc.status,
                    doc.effective_date,
                    doc.customer_account_id,
                    doc.authority_tier,
                    doc.superseded_by,
                    section,
                    1,
                    content,
                )
                for section, content in split_sections(text)
            ]
            conn.executemany(
                """INSERT INTO doc_chunks
                   (source_file, document_type, version, status, effective_date,
                    customer_account_id, authority_tier, superseded_by, section, page, content)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            chunk_count += len(rows)

        conn.commit()
    finally:
        conn.close()

    return chunk_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--documents-dir",
        type=Path,
        default=settings.data_dir / "documents",
        help="Directory containing the source documents.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("config/doc_manifest.yaml"),
        help="Path to the document metadata manifest.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=settings.var_dir / "app.db",
        help="Path to the SQLite database to (re)build.",
    )
    args = parser.parse_args()

    count = build_document_index(args.documents_dir, args.manifest, args.db_path)
    print(f"Ingested {count} chunks from {args.documents_dir} -> {args.db_path}")


if __name__ == "__main__":
    main()
