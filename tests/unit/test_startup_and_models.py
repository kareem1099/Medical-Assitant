import logging
from datetime import datetime

import mongomock
import pytest

from config.logging_config import get_logger, setup_logging
from db import mongo_client as mc
from src.models import ChatMessage, ChatTurn, SearchResult, User, Workspace


def test_init_mongo_creates_indexes_and_returns_db(monkeypatch):
    monkeypatch.setattr(mc, "MongoClient", lambda *a, **k: mongomock.MongoClient())
    monkeypatch.setattr(mc, "_db", None)
    db = mc.init_mongo()
    assert mc.get_db() is db
    assert "project_id_1" in db.chunks.index_information() and "file_id_1" in db.chunks.index_information()


def test_init_mongo_failure_message_hides_the_password(monkeypatch, test_settings):
    monkeypatch.setattr(test_settings, "mongo_uri", "mongodb://admin:TopSecret@db.example.net:27017")

    class Boom:
        def __init__(self, *a, **k):
            raise ConnectionError("cannot connect")

    monkeypatch.setattr(mc, "MongoClient", Boom)
    with pytest.raises(RuntimeError) as err:
        mc.init_mongo()
    assert "TopSecret" not in str(err.value) and "db.example.net" in str(err.value)


def test_setup_logging_writes_file_and_is_idempotent(tmp_path):
    log = tmp_path / "nested" / "app.log"
    setup_logging(str(log), logging.INFO)
    setup_logging(str(log), logging.INFO)
    get_logger("tests.demo").info("hello from the test")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert "hello from the test" in log.read_text(encoding="utf-8")
    assert len(logging.getLogger().handlers) == 2          # not duplicated by the second call


def test_setup_logging_survives_unwritable_path(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    setup_logging(str(blocker / "app.log"))               # parent is a file -> cannot create dir
    assert logging.getLogger().handlers


def test_models_are_immutable_value_objects():
    now = datetime.utcnow()
    user = User("1", "a@b.co", "A", now)
    assert user.is_active and user.last_login_at is None
    with pytest.raises(Exception):
        user.email = "x"
    assert Workspace("1", "u", "n", "d", now).name == "n"
    assert ChatTurn("q").citations == [] and ChatMessage("1", "s", "u", "user", "hi", now).role == "user"
    assert SearchResult(text="t", source="s").page is None
