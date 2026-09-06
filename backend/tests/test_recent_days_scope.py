from datetime import datetime, timedelta, timezone

from app.schemas.chat import ChatScope, normalize_legacy_chat_scope
from app.services.retrieval_service import created_after_from_recent_days


def test_chat_scope_accepts_recent_days() -> None:
    scope = ChatScope.model_validate(
        {
            "document_ids": [],
            "tags": [],
            "source_types": [],
            "recent_days": 7,
        }
    )
    assert scope.recent_days == 7


def test_normalize_legacy_chat_scope_keeps_recent_days() -> None:
    normalized = normalize_legacy_chat_scope(
        {
            "document_ids": [],
            "tags": ["英语"],
            "source_types": ["note"],
            "recent_days": 30,
            "extra": "ignored",
        }
    )
    assert normalized["recent_days"] == 30
    assert normalized["tags"] == ["英语"]
    assert "extra" not in normalized


def test_normalize_legacy_chat_scope_rejects_invalid_recent_days() -> None:
    assert normalize_legacy_chat_scope({"recent_days": 0})["recent_days"] is None
    assert normalize_legacy_chat_scope({"recent_days": 999})["recent_days"] is None
    assert normalize_legacy_chat_scope({"recent_days": True})["recent_days"] is None


def test_created_after_from_recent_days() -> None:
    assert created_after_from_recent_days(None) is None
    cutoff = created_after_from_recent_days(7)
    assert cutoff is not None
    now = datetime.now(timezone.utc)
    assert now - timedelta(days=8) < cutoff < now - timedelta(days=6)
