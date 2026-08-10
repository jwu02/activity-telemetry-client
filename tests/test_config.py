import pytest
from telemetry import config
from telemetry.config import load_config


def test_load_config_reads_env(monkeypatch):
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost/test")
    monkeypatch.setenv("ACTIVITY_DB_NAME", "test-db")
    cfg = load_config()
    assert cfg.mongo_uri == "mongodb://localhost/test"
    assert cfg.db_name == "test-db"
    assert cfg.collection_name == "telemetry"
    assert cfg.heatmap_collection_name == "keyboard_heatmap"
    assert cfg.flush_interval_seconds == 300
    assert cfg.mouse_dpi == 72
    assert cfg.collection_ttl_seconds == 31536000
    assert cfg.heatmap_ttl_seconds == 2592000
    assert "Visual Studio Code" in cfg.app_whitelist


def test_load_config_missing_mongo_uri(monkeypatch):
    monkeypatch.delenv("MONGO_URI", raising=False)
    # Prevent the existing .env file from re-populating MONGO_URI.
    monkeypatch.setattr(config, "load_dotenv", lambda **kwargs: None)
    with pytest.raises(SystemExit):
        load_config()


def test_load_config_accepts_custom_integers(monkeypatch):
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost/test")
    monkeypatch.setenv("FLUSH_INTERVAL_SECONDS", "120")
    monkeypatch.setenv("MOUSE_DPI", "1600")
    cfg = load_config()
    assert cfg.flush_interval_seconds == 120
    assert cfg.mouse_dpi == 1600


@pytest.mark.parametrize("value", ["abc", "1.5", ""])
def test_load_config_rejects_non_integer(monkeypatch, capsys, value):
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost/test")
    monkeypatch.setenv("FLUSH_INTERVAL_SECONDS", value)
    with pytest.raises(SystemExit):
        load_config()
    assert "FLUSH_INTERVAL_SECONDS" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["0", "-1"])
def test_load_config_rejects_non_positive_integer(monkeypatch, capsys, value):
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost/test")
    monkeypatch.setenv("MOUSE_DPI", value)
    with pytest.raises(SystemExit):
        load_config()
    assert "MOUSE_DPI" in capsys.readouterr().err
