"""A mock RFQ mailbox and intake, for the portal's "Check inbox" button until
the real intake (``quote_workflow.intake``) lands.

Exposes the same two functions intake will: ``fetch_new_rfqs()`` and
``run_intake(source, conn)``, so swapping is a one-line import change in
``app/resources.py``. Only the mailbox read and the extraction are faked:
each email in ``data/samples/demo_inbox.json`` is paired with the
``QuoteRequest`` a correct extraction would produce (names, not ids), and that
request is resolved against the catalog. Everything after this - completeness,
pricing, summary, status - is the real workflow.

Must not price, persist, or decide a status; ``workflow.ingest_sources`` does that.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from quote_workflow.catalog.resolution import resolve
from quote_workflow.config import DEMO_INBOX_PATH
from quote_workflow.contracts.quote_request import QuoteRequest
from quote_workflow.contracts.source import RfqSource

_PREFIX = "demo-"


def _emails(path: Path = DEMO_INBOX_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_new_rfqs(path: Path = DEMO_INBOX_PATH) -> list[RfqSource]:
    """Every email in the mock mailbox. Which ones are new is the workflow's
    call (by ``source_id``), so ids must be stable across calls."""
    return [
        RfqSource(
            source_id=_PREFIX + email["id"],
            received_at=datetime.fromisoformat(email["received_at"]),
            sender=email["sender"],
            subject=email["subject"],
            body_text=email["body"],
        )
        for email in _emails(path)
    ]


def run_intake(source: RfqSource, conn: sqlite3.Connection, path: Path = DEMO_INBOX_PATH) -> QuoteRequest:
    """The canned extraction for this email, resolved against the catalog."""
    email_id = source.source_id.removeprefix(_PREFIX)
    email = next((e for e in _emails(path) if e["id"] == email_id), None)
    if email is None:
        raise KeyError(f"no canned extraction for {source.source_id}")
    request = QuoteRequest.model_validate({**email["request"], "source_text": source.body_text})
    return resolve(conn, request)
