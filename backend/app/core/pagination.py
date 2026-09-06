import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID


MAX_PAGE_SIZE = 100
MAX_OFFSET_ROWS = 100_000
MAX_PAGE_NUMBER = MAX_OFFSET_ROWS + 1
CURSOR_MAX_LENGTH = 512

PAGINATION_LIMIT_MESSAGE = "分页位置超出允许范围，请使用游标分页"
INVALID_CURSOR_MESSAGE = "分页游标无效"


class PaginationError(ValueError):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class TimestampIdCursor:
    timestamp: datetime
    id: UUID


def offset_for_page(page: int, page_size: int) -> int:
    _validate_page_size(page_size)
    if type(page) is not int or page < 1:
        raise PaginationError(PAGINATION_LIMIT_MESSAGE)
    offset = (page - 1) * page_size
    if offset > MAX_OFFSET_ROWS:
        raise PaginationError(PAGINATION_LIMIT_MESSAGE)
    return offset


def validate_cursor_page_size(page_size: int) -> None:
    _validate_page_size(page_size)


def encode_timestamp_id_cursor(kind: str, cursor: TimestampIdCursor) -> str:
    timestamp = cursor.timestamp
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Cursor timestamps must include a timezone")
    return _encode_cursor(
        kind,
        [
            timestamp.astimezone(timezone.utc).isoformat(timespec="microseconds"),
            str(cursor.id),
        ],
    )


def decode_timestamp_id_cursor(
    value: str,
    *,
    expected_kind: str,
) -> TimestampIdCursor:
    parts = _decode_cursor(value, expected_kind=expected_kind, part_count=2)
    try:
        timestamp = datetime.fromisoformat(parts[0])
        cursor_id = UUID(parts[1])
    except (TypeError, ValueError) as exc:
        raise PaginationError(INVALID_CURSOR_MESSAGE) from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise PaginationError(INVALID_CURSOR_MESSAGE)
    return TimestampIdCursor(
        timestamp=timestamp.astimezone(timezone.utc),
        id=cursor_id,
    )


def encode_text_cursor(kind: str, value: str) -> str:
    if not value:
        raise ValueError("Cursor text must not be empty")
    return _encode_cursor(kind, [value])


def decode_text_cursor(
    value: str,
    *,
    expected_kind: str,
    max_value_length: int,
) -> str:
    parts = _decode_cursor(value, expected_kind=expected_kind, part_count=1)
    decoded = parts[0]
    if not decoded or len(decoded) > max_value_length:
        raise PaginationError(INVALID_CURSOR_MESSAGE)
    return decoded


def _validate_page_size(page_size: int) -> None:
    if (
        type(page_size) is not int
        or page_size < 1
        or page_size > MAX_PAGE_SIZE
    ):
        raise PaginationError(PAGINATION_LIMIT_MESSAGE)


def _encode_cursor(kind: str, parts: list[str]) -> str:
    payload = json.dumps(
        {"v": 1, "kind": kind, "parts": parts},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(
    value: str,
    *,
    expected_kind: str,
    part_count: int,
) -> list[str]:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > CURSOR_MAX_LENGTH
    ):
        raise PaginationError(INVALID_CURSOR_MESSAGE)
    try:
        encoded = value.encode("ascii")
        padding = b"=" * (-len(encoded) % 4)
        raw = base64.b64decode(
            encoded + padding,
            altchars=b"-_",
            validate=True,
        )
        payload: Any = json.loads(raw.decode("utf-8"))
    except (
        UnicodeEncodeError,
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
    ) as exc:
        raise PaginationError(INVALID_CURSOR_MESSAGE) from exc

    if (
        type(payload) is not dict
        or set(payload) != {"v", "kind", "parts"}
        or type(payload["v"]) is not int
        or payload["v"] != 1
        or payload["kind"] != expected_kind
        or type(payload["parts"]) is not list
        or len(payload["parts"]) != part_count
        or any(type(part) is not str for part in payload["parts"])
    ):
        raise PaginationError(INVALID_CURSOR_MESSAGE)
    return payload["parts"]
