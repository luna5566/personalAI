from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import authenticated_user_id, db_session
from app.api.routes import chat as chat_routes
from app.api.routes.documents import router as documents_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.pagination import (
    INVALID_CURSOR_MESSAGE,
    MAX_OFFSET_ROWS,
    PAGINATION_LIMIT_MESSAGE,
    PaginationError,
    TimestampIdCursor,
    decode_text_cursor,
    decode_timestamp_id_cursor,
    encode_text_cursor,
    encode_timestamp_id_cursor,
    offset_for_page,
)
from app.services import (
    chat_service,
    document_service,
    job_service,
    registration_invite_admin_service,
    tag_service,
)


def test_offset_boundary_is_checked_before_database_work() -> None:
    db = MagicMock()
    user_id = uuid4()
    conversation_id = uuid4()
    excessive_page = MAX_OFFSET_ROWS // 100 + 2

    calls = [
        lambda: document_service.list_documents(
            db,
            user_id,
            page=excessive_page,
            page_size=100,
        ),
        lambda: chat_service.list_conversations(
            db,
            user_id,
            page=excessive_page,
            page_size=100,
        ),
        lambda: chat_service.list_messages(
            db,
            user_id,
            conversation_id,
            page=excessive_page,
            page_size=100,
        ),
        lambda: tag_service.list_tags(
            db,
            user_id,
            page=excessive_page,
            page_size=100,
        ),
        lambda: job_service.list_jobs(
            db,
            user_id,
            page=excessive_page,
            page_size=100,
        ),
        lambda: registration_invite_admin_service.list_registration_invites(
            db,
            user_id=settings.runtime_settings_admin_user_id,
            page=excessive_page,
            page_size=100,
        ),
    ]

    for call in calls:
        with pytest.raises(PaginationError, match=PAGINATION_LIMIT_MESSAGE):
            call()

    assert db.method_calls == []


def test_offset_boundary_allows_the_last_bounded_position() -> None:
    assert offset_for_page(MAX_OFFSET_ROWS // 100 + 1, 100) == MAX_OFFSET_ROWS


@pytest.mark.parametrize(
    ("page", "page_size"),
    [
        (0, 20),
        (1, 0),
        (1, 101),
        (True, 20),
        (1, True),
    ],
)
def test_service_pagination_rejects_invalid_scalar_values(
    page,
    page_size,
) -> None:
    with pytest.raises(PaginationError, match=PAGINATION_LIMIT_MESSAGE):
        offset_for_page(page, page_size)


def test_timestamp_and_text_cursors_round_trip() -> None:
    timestamp_cursor = TimestampIdCursor(
        timestamp=datetime(2026, 7, 18, 12, 30, 45, 123456, tzinfo=UTC),
        id=uuid4(),
    )
    encoded_timestamp = encode_timestamp_id_cursor(
        "documents.created-id.desc",
        timestamp_cursor,
    )
    encoded_text = encode_text_cursor("tags.name.asc", "学习")

    assert decode_timestamp_id_cursor(
        encoded_timestamp,
        expected_kind="documents.created-id.desc",
    ) == timestamp_cursor
    assert decode_text_cursor(
        encoded_text,
        expected_kind="tags.name.asc",
        max_value_length=64,
    ) == "学习"


@pytest.mark.parametrize("cursor", ["not-base64!", "e30", "", "A" * 513])
def test_malformed_cursors_are_rejected(cursor: str) -> None:
    with pytest.raises(PaginationError, match=INVALID_CURSOR_MESSAGE):
        decode_text_cursor(
            cursor,
            expected_kind="tags.name.asc",
            max_value_length=64,
        )


def test_cursor_cannot_cross_endpoint_kinds() -> None:
    cursor = encode_text_cursor("tags.name.asc", "学习")

    with pytest.raises(PaginationError, match=INVALID_CURSOR_MESSAGE):
        decode_text_cursor(
            cursor,
            expected_kind="another.endpoint",
            max_value_length=64,
        )


def test_recent_message_cursor_cannot_cross_into_the_ascending_scan(
    monkeypatch,
) -> None:
    next_cursor = TimestampIdCursor(
        timestamp=datetime(2026, 7, 18, tzinfo=UTC),
        id=uuid4(),
    )
    monkeypatch.setattr(
        chat_routes.chat_service,
        "scan_recent_messages",
        lambda *args, **kwargs: ([], next_cursor),
    )

    response = chat_routes.scan_recent_messages(
        uuid4(),
        MagicMock(),
        uuid4(),
        page_size=50,
    )

    assert decode_timestamp_id_cursor(
        response.next_cursor,
        expected_kind=chat_routes.MESSAGE_RECENT_CURSOR_KIND,
    ) == next_cursor
    with pytest.raises(PaginationError, match=INVALID_CURSOR_MESSAGE):
        chat_routes.scan_messages(
            uuid4(),
            MagicMock(),
            uuid4(),
            page_size=50,
            cursor=response.next_cursor,
        )


def test_cursor_scans_use_keyset_order_and_one_row_lookahead() -> None:
    user_id = uuid4()
    conversation_id = uuid4()
    start = datetime(2026, 7, 18, tzinfo=UTC)
    cursor = TimestampIdCursor(timestamp=start, id=uuid4())

    document_rows = [
        SimpleNamespace(
            id=uuid4(),
            created_at=start - timedelta(seconds=index + 1),
        )
        for index in range(101)
    ]
    document_db = MagicMock()
    document_db.scalars.return_value = document_rows
    documents, document_cursor = document_service.scan_documents(
        document_db,
        user_id,
        cursor=cursor,
    )
    document_statement = document_db.scalars.call_args.args[0]

    assert len(documents) == 100
    assert document_cursor == TimestampIdCursor(
        timestamp=document_rows[99].created_at,
        id=document_rows[99].id,
    )
    assert document_statement._offset_clause is None
    assert document_statement._limit_clause.value == 101
    assert "(documents.created_at, documents.id) <" in str(document_statement)

    message_rows = [
        SimpleNamespace(
            id=uuid4(),
            created_at=start + timedelta(seconds=index + 1),
        )
        for index in range(101)
    ]
    message_db = MagicMock()
    message_db.scalar.return_value = SimpleNamespace()
    message_db.scalars.return_value = message_rows
    messages, message_cursor = chat_service.scan_messages(
        message_db,
        user_id,
        conversation_id,
        cursor=cursor,
    )
    message_statement = message_db.scalars.call_args.args[0]

    assert len(messages) == 100
    assert message_cursor == TimestampIdCursor(
        timestamp=message_rows[99].created_at,
        id=message_rows[99].id,
    )
    assert message_statement._offset_clause is None
    assert message_statement._limit_clause.value == 101
    assert "(messages.created_at, messages.id) >" in str(message_statement)

    recent_rows = list(reversed(message_rows))
    recent_db = MagicMock()
    recent_db.scalar.return_value = SimpleNamespace()
    recent_db.scalars.return_value = recent_rows
    recent_messages, recent_cursor = chat_service.scan_recent_messages(
        recent_db,
        user_id,
        conversation_id,
        page_size=100,
        cursor=cursor,
    )
    recent_statement = recent_db.scalars.call_args.args[0]

    assert recent_messages == list(reversed(recent_rows[:100]))
    assert recent_cursor == TimestampIdCursor(
        timestamp=recent_rows[99].created_at,
        id=recent_rows[99].id,
    )
    assert recent_statement._offset_clause is None
    assert recent_statement._limit_clause.value == 101
    assert "ORDER BY messages.created_at DESC, messages.id DESC" in str(
        recent_statement
    )
    assert "(messages.created_at, messages.id) <" in str(recent_statement)

    tag_rows = [
        SimpleNamespace(name=f"tag-{index:03d}")
        for index in range(101)
    ]
    tag_db = MagicMock()
    tag_db.scalars.return_value = tag_rows
    tags, tag_cursor = tag_service.scan_tags(
        tag_db,
        user_id,
        cursor="tag-start",
    )
    tag_statement = tag_db.scalars.call_args.args[0]

    assert len(tags) == 100
    assert tag_cursor == "tag-099"
    assert tag_statement._offset_clause is None
    assert tag_statement._limit_clause.value == 101
    assert "tags.name >" in str(tag_statement)


def test_excessive_page_returns_stable_422_before_database_access() -> None:
    db = MagicMock()
    app = FastAPI(debug=False)
    register_exception_handlers(app)
    app.include_router(documents_router)
    app.dependency_overrides[db_session] = lambda: db
    app.dependency_overrides[authenticated_user_id] = uuid4

    response = TestClient(app).get("/documents?page=1002&page_size=100")

    assert response.status_code == 422
    assert response.json() == {
        "message": PAGINATION_LIMIT_MESSAGE,
        "detail": PAGINATION_LIMIT_MESSAGE,
    }
    assert db.method_calls == []


def test_unbounded_integer_page_is_rejected_by_request_validation() -> None:
    db = MagicMock()
    app = FastAPI(debug=False)
    register_exception_handlers(app)
    app.include_router(documents_router)
    app.dependency_overrides[db_session] = lambda: db
    app.dependency_overrides[authenticated_user_id] = uuid4

    response = TestClient(app).get(
        "/documents?page=999999999999999999999999999999&page_size=100"
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "less_than_equal"
