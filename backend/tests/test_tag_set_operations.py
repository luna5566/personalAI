from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.models.tag import Tag
from app.services import tag_service


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_tag_merge_moves_links_and_deletes_source_with_two_set_statements() -> None:
    db = MagicMock()
    user_id = uuid4()
    source = Tag(id=uuid4(), user_id=user_id, name="source")
    target = Tag(id=uuid4(), user_id=user_id, name="target")

    tag_service._merge_tags(db, source, target)

    assert db.execute.call_count == 2
    insert_statement = db.execute.call_args_list[0].args[0]
    delete_statement = db.execute.call_args_list[1].args[0]
    insert_sql = _sql(insert_statement)
    delete_sql = _sql(delete_statement)

    assert "INSERT INTO document_tags (document_id, tag_id) SELECT" in insert_sql
    assert "FROM document_tags" in insert_sql
    assert "WHERE document_tags.tag_id =" in insert_sql
    assert "ON CONFLICT (document_id, tag_id) DO NOTHING" in insert_sql
    assert "VALUES" not in insert_sql
    assert "DELETE FROM tags" in delete_sql
    assert "tags.id =" in delete_sql
    assert "tags.user_id =" in delete_sql
    assert source.id in insert_statement.compile().params.values()
    assert target.id in insert_statement.compile().params.values()
    assert source.id in delete_statement.compile().params.values()
    assert user_id in delete_statement.compile().params.values()
    db.scalars.assert_not_called()
    db.add.assert_not_called()
    db.add_all.assert_not_called()
    db.delete.assert_not_called()
    db.flush.assert_not_called()


def test_update_tag_locks_at_most_source_and_target_in_stable_order() -> None:
    db = MagicMock()
    user_id = uuid4()
    source = Tag(id=uuid4(), user_id=user_id, name="source", color=None)
    target = Tag(id=uuid4(), user_id=user_id, name="target", color="#old")
    db.scalars.return_value = [source, target]

    updated = tag_service.update_tag(
        db,
        user_id,
        source.id,
        "target",
        color="#new",
    )

    assert updated is target
    assert target.color == "#new"
    candidate_statement = db.scalars.call_args.args[0]
    candidate_sql = _sql(candidate_statement)
    assert "tags.user_id =" in candidate_sql
    assert "tags.id =" in candidate_sql
    assert "tags.name =" in candidate_sql
    assert "ORDER BY tags.id ASC" in candidate_sql
    assert "FOR UPDATE" in candidate_sql
    assert db.execute.call_count == 2
    db.add.assert_called_once_with(target)
    db.commit.assert_called_once_with()
    db.refresh.assert_called_once_with(target)
    db.scalar.assert_not_called()


def test_update_tag_without_existing_target_keeps_single_row_path() -> None:
    db = MagicMock()
    user_id = uuid4()
    source = Tag(id=uuid4(), user_id=user_id, name="source", color=None)
    db.scalars.return_value = [source]

    updated = tag_service.update_tag(
        db,
        user_id,
        source.id,
        "renamed",
        color="#new",
    )

    assert updated is source
    assert source.name == "renamed"
    assert source.color == "#new"
    db.execute.assert_not_called()
    db.add.assert_called_once_with(source)
    db.commit.assert_called_once_with()
    db.refresh.assert_called_once_with(source)


def test_delete_tag_uses_owned_database_cascade_without_loading_links() -> None:
    db = MagicMock()
    db.execute.return_value.rowcount = 1
    user_id = uuid4()
    tag_id = uuid4()

    assert tag_service.delete_tag(db, user_id, tag_id) is True

    statement = db.execute.call_args.args[0]
    sql = _sql(statement)
    assert "DELETE FROM tags" in sql
    assert "tags.id =" in sql
    assert "tags.user_id =" in sql
    assert tag_id in statement.compile().params.values()
    assert user_id in statement.compile().params.values()
    db.scalars.assert_not_called()
    db.scalar.assert_not_called()
    db.delete.assert_not_called()
    db.commit.assert_called_once_with()


def test_delete_unknown_tag_does_not_commit() -> None:
    db = MagicMock()
    db.execute.return_value.rowcount = 0

    assert tag_service.delete_tag(db, uuid4(), uuid4()) is False

    db.commit.assert_not_called()


def test_tag_relationship_trusts_database_on_delete_cascade() -> None:
    assert Tag.documents.property.passive_deletes is True
