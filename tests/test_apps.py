import threading
import time
from unittest.mock import MagicMock, call, patch

from telemetry.state import TelemetryState
from telemetry.config import Config
from telemetry.collectors.apps import AppCollector, BUNDLE_ID_TO_APP_NAME


def make_config() -> Config:
    return Config(
        mongo_uri="",
        db_name="test",
        collection_name="telemetry",
        flush_interval_seconds=300,
        mouse_dpi=72,
        app_whitelist={"Visual Studio Code", "Google Chrome"},
    )


def _make_frontmost_app(localized_name: str, bundle_id: str | None) -> MagicMock:
    app = MagicMock()
    app.localizedName.return_value = localized_name
    app.bundleIdentifier.return_value = bundle_id
    return app


def _patch_frontmost_app(app):
    workspace = MagicMock()
    workspace.frontmostApplication.return_value = app
    return patch("telemetry.collectors.apps.NSWorkspace", sharedWorkspace=MagicMock(return_value=workspace))


def test_frontmost_app_name_uses_bundle_id_mapping():
    state = TelemetryState()
    cfg = make_config()
    collector = AppCollector(state, cfg)

    app = _make_frontmost_app("Code", "com.microsoft.VSCode")
    with _patch_frontmost_app(app):
        assert collector._frontmost_app_name() == "Visual Studio Code"


def test_frontmost_app_name_falls_back_to_localized_name():
    state = TelemetryState()
    cfg = make_config()
    collector = AppCollector(state, cfg)

    app = _make_frontmost_app("Spotify", "com.spotify.client")
    with _patch_frontmost_app(app):
        assert collector._frontmost_app_name() == "Spotify"


def test_frontmost_app_name_returns_none_when_no_app():
    state = TelemetryState()
    cfg = make_config()
    collector = AppCollector(state, cfg)

    with _patch_frontmost_app(None):
        assert collector._frontmost_app_name() is None


def test_bundle_id_mapping_targets_are_whitelisted():
    """Every bundle ID mapping must point to an app in the default whitelist."""
    from telemetry.config import APP_WHITELIST

    mapped = set(BUNDLE_ID_TO_APP_NAME.values())
    not_whitelisted = mapped - set(APP_WHITELIST)
    assert not not_whitelisted, f"Bundle ID mapping targets not whitelisted: {not_whitelisted}"


def test_record_whitelisted_app():
    state = TelemetryState()
    cfg = make_config()
    collector = AppCollector(state, cfg)
    collector._record("Visual Studio Code")
    snap = state.snapshot_and_clear()
    assert snap["apps"]["Visual Studio Code"] == 1.0


def test_record_non_whitelisted_app_is_ignored():
    state = TelemetryState()
    cfg = make_config()
    collector = AppCollector(state, cfg)
    collector._record("Spotify")
    snap = state.snapshot_and_clear()
    assert snap["apps"] == {}


def test_record_uses_provided_seconds():
    state = TelemetryState()
    cfg = make_config()
    collector = AppCollector(state, cfg, poll_interval=1.0)
    collector._record("Visual Studio Code", 2.5)
    snap = state.snapshot_and_clear()
    assert snap["apps"]["Visual Studio Code"] == 2.5


def test_start_is_idempotent():
    state = TelemetryState()
    cfg = make_config()
    collector = AppCollector(state, cfg, poll_interval=0.01)
    with patch.object(collector, "_frontmost_app_name", return_value=None), \
         patch.object(collector, "_record"):
        collector.start()
        first_thread = collector._thread
        collector.start()
        assert collector._thread is first_thread
        collector.stop()


def test_stop_is_idempotent():
    state = TelemetryState()
    cfg = make_config()
    collector = AppCollector(state, cfg)
    collector.stop()
    collector.stop()
    assert collector._thread is None


def test_run_records_wall_clock_elapsed():
    state = TelemetryState()
    cfg = make_config()
    collector = AppCollector(state, cfg, poll_interval=0.01)
    stop_event = threading.Event()
    collector._stop_event = stop_event

    def stop_soon():
        time.sleep(0.05)
        stop_event.set()

    threading.Thread(target=stop_soon).start()

    with patch.object(collector, "_frontmost_app_name", return_value="Visual Studio Code") as frontmost, \
         patch.object(collector, "_record") as record, \
         patch("telemetry.collectors.apps.time.monotonic", side_effect=[0.0, 1.5, 3.0, 4.5, 6.0, 7.5, 9.0, 10.5]):
        collector._run()
        # Two iterations before stop_event is set.
        assert record.call_count >= 2
        first_elapsed = record.call_args_list[0][0][1]
        assert first_elapsed == 1.5


def test_crash_signals_shutdown():
    state = TelemetryState()
    cfg = make_config()
    shutdown_event = threading.Event()
    collector = AppCollector(state, cfg, poll_interval=0.01, shutdown_event=shutdown_event)

    with patch.object(collector, "_frontmost_app_name", side_effect=RuntimeError("boom")):
        collector.start()
        collector._thread.join(timeout=1.0)
        assert not collector._thread.is_alive()
        assert shutdown_event.is_set()
        collector.stop()
