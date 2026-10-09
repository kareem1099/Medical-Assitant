import time

import mongomock
import pytest
from bson import ObjectId

from src.stores.metadata.MongoMetadataProvider import MongoMetadataProvider


def test_user_email_is_normalised_and_unique(metadata):
    uid = metadata.create_user("  Kareem@Example.COM ", "password-123", " Kareem ")
    user = metadata.find_user_by_email("kareem@example.com")
    assert str(user["_id"]) == uid
    assert user["display_name"] == "Kareem"
    assert metadata.find_user_by_email("KAREEM@example.com  ")["email"] == "kareem@example.com"
    with pytest.raises(mongomock.DuplicateKeyError):
        metadata.create_user("kareem@example.com", "password-123", "Dup")


def test_inactive_users_cannot_be_found(metadata):
    uid = metadata.create_user("a@b.co", "password-123", "A")
    metadata.users.update_one({"_id": ObjectId(uid)}, {"$set": {"is_active": False}})
    assert metadata.find_user_by_email("a@b.co") is None


def test_password_is_stored_hashed(metadata):
    metadata.create_user("a@b.co", "password-123", "A")
    assert "password-123" not in metadata.find_user_by_email("a@b.co")["password_hash"]


def test_workspaces_are_listed_per_user_newest_first(metadata):
    metadata.create_workspace("u1", "first")
    metadata.create_workspace("u1", " second ", " desc ")
    metadata.create_workspace("u2", "other")
    names = [w["name"] for w in metadata.list_workspaces("u1")]
    assert names == ["second", "first"]


def test_conversation_lifecycle_and_ordering(metadata):
    a = metadata.create_conversation("u1", "w1", "A")
    b = metadata.create_conversation("u1", "w1", "B")
    assert [str(c["_id"]) for c in metadata.list_conversations("u1")] == [b, a]
    time.sleep(0.01)   # MongoDB stores datetimes with millisecond precision
    metadata.append_message("u1", a, "user", "hello")
    # the conversation with the newest activity floats to the top
    assert [str(c["_id"]) for c in metadata.list_conversations("u1")][0] == a


def test_blank_title_falls_back_to_default(metadata):
    cid = metadata.create_conversation("u1", None, "   ")
    assert metadata.get_conversation("u1", cid)["title"] == "New conversation"


def test_messages_are_ordered_and_preview_truncated(metadata):
    cid = metadata.create_conversation("u1", "w1", "T")
    metadata.append_message("u1", cid, "user", "q1")
    metadata.append_message("u1", cid, "assistant", "x" * 500, ["c"], ["local"])
    msgs = metadata.get_messages("u1", cid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["citations"] == ["c"] and msgs[1]["source_types"] == ["local"]
    assert len(metadata.get_conversation("u1", cid)["last_message_preview"]) == 160


def test_other_users_cannot_read_or_write_a_conversation(metadata):
    cid = metadata.create_conversation("owner", "w", "Private")
    metadata.append_message("owner", cid, "user", "secret")
    with pytest.raises(PermissionError):
        metadata.get_messages("intruder", cid)
    with pytest.raises(PermissionError):
        metadata.append_message("intruder", cid, "user", "hack")
    assert metadata.get_conversation("intruder", cid) is None


def test_other_users_cannot_delete(metadata):
    cid = metadata.create_conversation("owner", "w", "Private")
    metadata.append_message("owner", cid, "user", "keep me")
    metadata.delete_conversation("intruder", cid)
    assert metadata.get_conversation("owner", cid) is not None
    assert len(metadata.get_messages("owner", cid)) == 1


def test_delete_removes_messages_too(metadata):
    cid = metadata.create_conversation("u", "w", "T")
    metadata.append_message("u", cid, "user", "hi")
    metadata.delete_conversation("u", cid)
    assert metadata.get_conversation("u", cid) is None
    assert metadata.chat_messages.count_documents({"session_id": cid}) == 0


@pytest.mark.parametrize("raw", [None, "", "not-an-oid", 123, [], {}])
def test_invalid_ids_raise_value_error(metadata, raw):
    with pytest.raises(ValueError):
        metadata.get_conversation("u", raw)


def test_id_normalisation_accepts_gradio_shapes(metadata):
    cid = metadata.create_conversation("u", "w", "T")
    assert metadata.get_conversation("u", {"id": cid})["title"] == "T"
    assert metadata.get_conversation("u", ("label", cid))["title"] == "T"
    assert metadata.get_conversation("u", ObjectId(cid))["title"] == "T"


def test_rename_conversation(metadata):
    cid = metadata.create_conversation("u", "w", "New conversation")
    metadata.rename_conversation("u", cid, "  What is metformin?  ")
    assert metadata.get_conversation("u", cid)["title"] == "What is metformin?"
    metadata.rename_conversation("someone-else", cid, "hijack")
    assert metadata.get_conversation("u", cid)["title"] == "What is metformin?"


def test_clear_messages_keeps_the_conversation(metadata):
    cid = metadata.create_conversation("u", "w", "T")
    metadata.append_message("u", cid, "user", "hi")
    metadata.append_message("u", cid, "assistant", "hello")
    metadata.clear_messages("u", cid)
    assert metadata.get_messages("u", cid) == []
    assert metadata.get_conversation("u", cid)["last_message_preview"] == ""
    # not allowed for someone else
    metadata.append_message("u", cid, "user", "again")
    metadata.clear_messages("intruder", cid)
    assert len(metadata.get_messages("u", cid)) == 1


def test_indexes_are_created(mongo_db):
    MongoMetadataProvider(mongo_db)
    assert any(i.get("unique") for i in mongo_db.users.index_information().values())
