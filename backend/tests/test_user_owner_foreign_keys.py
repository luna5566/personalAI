import app.models  # noqa: F401
from app.core.database import Base

EXPECTED_USER_OWNER_ACTIONS = {
    "auth_sessions": "CASCADE",
    "documents": "RESTRICT",
    "document_chunks": "RESTRICT",
    "chunk_embeddings": "RESTRICT",
    "conversations": "RESTRICT",
    "messages": "RESTRICT",
    "jobs": "RESTRICT",
    "tags": "RESTRICT",
}


def test_every_user_owned_table_references_users() -> None:
    user_owned_tables = {
        table.name
        for table in Base.metadata.tables.values()
        if "user_id" in table.columns
    }

    assert user_owned_tables == set(EXPECTED_USER_OWNER_ACTIONS)

    for table_name, expected_on_delete in EXPECTED_USER_OWNER_ACTIONS.items():
        user_id = Base.metadata.tables[table_name].columns["user_id"]
        user_foreign_keys = [
            foreign_key
            for foreign_key in user_id.foreign_keys
            if foreign_key.target_fullname == "users.id"
        ]

        assert len(user_foreign_keys) == 1
        assert user_foreign_keys[0].ondelete == expected_on_delete
