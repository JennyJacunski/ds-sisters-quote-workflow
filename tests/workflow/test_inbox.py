"""The inbox path through the workflow: raw RFQ -> intake -> case, with dedup
and intake failures turned into FAILED cases. Uses the mock mailbox; temp
catalog and case store, no LLM."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from quote_workflow import demo_inbox
from quote_workflow.contracts.enums import CaseStatus
from quote_workflow.contracts.source import RfqSource
from quote_workflow.storage.sqlite_store import SqliteCaseStore
from quote_workflow.workflow import create_case_from_source, ingest_sources


@pytest.fixture
def store(tmp_path: Path):
    s = SqliteCaseStore(tmp_path / "cases.db")
    try:
        yield s
    finally:
        s.close()


def _source(source_id: str = "msg-1") -> RfqSource:
    return RfqSource(source_id=source_id, received_at=datetime(2026, 9, 30, tzinfo=UTC), body_text="Need 10 mugs")


def test_demo_inbox_becomes_cases_with_the_email_attached(store, built_db):
    created = ingest_sources(store, built_db, demo_inbox.fetch_new_rfqs(), demo_inbox.run_intake, use_llm=False)

    by_source = {case.source.source_id: case for case in created}
    assert by_source["demo-jayanta-hoodies"].status == CaseStatus.READY_FOR_REVIEW
    assert by_source["demo-krishnam-rc-cars"].status == CaseStatus.READY_FOR_REVIEW
    assert by_source["demo-wingtip-rc-cars"].status == CaseStatus.NEEDS_INFO
    # Jayanta's contract deal #10 fixes the XL hoodie at $28: 15 x $28 = $420.
    assert by_source["demo-jayanta-hoodies"].pricing.total_quoted_value == pytest.approx(420.0)
    assert all(case.request.source_text == case.source.body_text for case in created)
    assert store.count() == 3


def test_checking_the_inbox_twice_creates_no_duplicates(store, built_db):
    ingest_sources(store, built_db, demo_inbox.fetch_new_rfqs(), demo_inbox.run_intake, use_llm=False)
    again = ingest_sources(store, built_db, demo_inbox.fetch_new_rfqs(), demo_inbox.run_intake, use_llm=False)

    assert again == []
    assert store.count() == 3


def test_an_intake_error_is_a_failed_case_not_a_crash(store, built_db):
    def broken_intake(source, conn):
        raise RuntimeError("model timed out")

    case = create_case_from_source(store, built_db, _source(), broken_intake)

    assert case.status == CaseStatus.FAILED
    assert case.source.source_id == "msg-1"
    assert any(e.stage == "intake" and e.level == "error" and "model timed out" in e.message for e in case.events)


def test_intake_returning_the_wrong_type_is_a_failed_case(store, built_db):
    case = create_case_from_source(store, built_db, _source(), lambda source, conn: {"customer_name": "x"})

    assert case.status == CaseStatus.FAILED
    assert any(e.stage == "intake" and "expected QuoteRequest" in e.message for e in case.events)
