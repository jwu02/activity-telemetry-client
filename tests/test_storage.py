import mongomock
from datetime import datetime
from unittest.mock import MagicMock, patch

from telemetry.config import Config
from telemetry.storage import Storage


def make_config():
    return Config(
        mongo_uri="",
        db_name="test",
        collection_name="telemetry",
        heatmap_collection_name="keyboard_heatmap",
        flush_interval_seconds=300,
        mouse_dpi=72,
        app_whitelist=set(),
    )


def test_flush_writes_telemetry_and_heatmap_documents():
    client = mongomock.MongoClient()
    storage = Storage(make_config(), _client=client)
    snapshot = {
        "leftClicks": 1,
        "rightClicks": 2,
        "movementMeters": 0.5,
        "keysPressed": 3,
        "keyboard_heatmap": {"A": 2, "Return": 1},
        "apps": {"Visual Studio Code": 5.0},
    }
    result = storage.flush(snapshot)
    assert result is not None
    assert len(result) == 2

    telemetry_docs = list(client["test"]["telemetry"].find())
    heatmap_docs = list(client["test"]["keyboard_heatmap"].find())
    assert len(telemetry_docs) == 1
    assert len(heatmap_docs) == 1

    telemetry = telemetry_docs[0]
    heatmap = heatmap_docs[0]
    assert isinstance(telemetry["createdAt"], datetime)
    assert isinstance(heatmap["createdAt"], datetime)
    assert telemetry["createdAt"] == heatmap["createdAt"]
    assert telemetry["leftClicks"] == 1
    assert telemetry["rightClicks"] == 2
    assert telemetry["movementMeters"] == 0.5
    assert telemetry["keysPressed"] == 3
    assert "apps" not in telemetry
    assert heatmap["A"] == 2
    assert heatmap["Return"] == 1


def test_flush_skips_heatmap_document_when_no_keys():
    client = mongomock.MongoClient()
    storage = Storage(make_config(), _client=client)
    snapshot = {
        "leftClicks": 1,
        "rightClicks": 0,
        "movementMeters": 0.0,
        "keysPressed": 0,
        "keyboard_heatmap": {},
        "apps": {},
    }
    result = storage.flush(snapshot)
    assert result is not None
    assert len(result) == 1
    assert len(list(client["test"]["telemetry"].find())) == 1
    assert len(list(client["test"]["keyboard_heatmap"].find())) == 0


def test_flush_returns_none_when_heatmap_insert_fails():
    client = mongomock.MongoClient()
    storage = Storage(make_config(), _client=client)
    snapshot = {
        "leftClicks": 1,
        "rightClicks": 0,
        "movementMeters": 0.0,
        "keysPressed": 1,
        "keyboard_heatmap": {"A": 1},
        "apps": {},
    }
    with patch.object(
        storage._heatmap_collection, "insert_one", side_effect=RuntimeError("boom")
    ):
        assert storage.flush(snapshot) is None
    # The telemetry document was inserted before the heatmap insert failed, so a
    # retry on the next flush would re-insert a duplicate telemetry document.
    assert len(list(client["test"]["telemetry"].find())) == 1


def test_close_calls_client_close():
    client = MagicMock()
    storage = Storage(make_config(), _client=client)
    storage.close()
    client.close.assert_called_once()
