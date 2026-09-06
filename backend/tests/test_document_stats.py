from app.models.document import DocumentStatus
from app.services.document_service import _document_stats_from_counts


def test_document_stats_cover_all_processing_states() -> None:
    stats = _document_stats_from_counts(
        {
            DocumentStatus.INDEXED.value: 12,
            DocumentStatus.FAILED.value: 2,
            DocumentStatus.PARSING.value: 3,
            DocumentStatus.EMBEDDING.value: 1,
        },
        storage_bytes=12 * 1024 * 1024,
    )

    assert stats.total == 18
    assert stats.indexed == 12
    assert stats.processing == 4
    assert stats.failed == 2
    assert stats.cancelled == 0
    assert stats.storage_bytes == 12 * 1024 * 1024
