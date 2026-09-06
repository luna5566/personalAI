from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.services.document_service import attach_tags
from app.services.tag_service import document_ids_for_tags


def test_attach_tags_loads_a_document_page_in_one_query() -> None:
    first_id = uuid4()
    second_id = uuid4()
    documents = [SimpleNamespace(id=first_id), SimpleNamespace(id=second_id)]
    db = MagicMock()
    db.execute.return_value = [
        (first_id, "学习"),
        (first_id, "重点"),
        (second_id, "工作"),
    ]

    result = attach_tags(db, documents)

    db.execute.assert_called_once()
    assert result[0].tags == ["学习", "重点"]
    assert result[1].tags == ["工作"]


def test_attach_tags_skips_the_database_for_an_empty_page() -> None:
    db = MagicMock()

    assert attach_tags(db, []) == []
    db.execute.assert_not_called()


def test_tag_document_lookup_can_stop_after_the_collection_limit() -> None:
    db = MagicMock()
    db.scalars.return_value = []

    document_ids_for_tags(db, uuid4(), ["学习"], limit=21)

    statement = db.scalars.call_args.args[0]
    assert statement._limit_clause.value == 21
