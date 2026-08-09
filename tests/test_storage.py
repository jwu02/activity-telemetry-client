import mongomock
from datetime import datetime, timezone
from unittest.mock import MagicMock
from telemetry.config import Config
from telemetry.storage import Storage


def make_config():
    return Config(
        mongo_uri="",
        db_name="test",
        collection_name="telemetry",
        flush_interval_seconds=300,
        mouse_dpi=72,
        app_whitelist=set(),
    )


def test_flush_builds_document_and_inserts():
    client = mongomock.MongoClient()
    config = make_config()
    storage = Storage(config, _client=client)
    snapshot = {
        "mouse": {"leftClicks": 1, "rightClicks": 2, "movementMeters": 0.5},
        "keys": {"A": 3},
        "apps": {"Visual Studio Code": 5.0},
    }
    doc_id = storage.flush(snapshot)
    assert doc_id is not None
    docs = list(client["test"]["telemetry"].find())
    assert len(docs) == 1
    doc = docs[0]
    assert "createdAt" in doc
    assert isinstance(doc["createdAt"], datetime)
    assert doc["mouse"] == snapshot["mouse"]
    assert doc["keys"] == snapshot["keys"]
    assert doc["apps"] == snapshot["apps"]


def test_close_calls_client_close():
    client = MagicMock()
    storage = Storage(make_config(), _client=client)
    storage.close()
    client.close.assert_called_once()
