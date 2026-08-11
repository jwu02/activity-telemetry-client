import threading
import time
from unittest.mock import MagicMock, call, patch

from telemetry.state import TelemetryState
from telemetry.config import Config
from telemetry.collectors.apps import AppCollector, BUNDLE_ID_TO_APP_NAME, PROCESS_NAME_TO_APP_NAME, _frontmost_app_name_windows


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


# --- Windows app collector tests ---
#
# All Windows-path tests patch `telemetry.collectors.apps._WINDLL` (the
# module-global that is None off-Windows) rather than ctypes.windll, so they
# run on any platform. ctypes.windll itself does not exist on macOS.


def _windll_context(exe_path=None, title="My App Window"):
    """Return a patched _WINDLL mock + its MagicMock, wired for a window."""
    mock_windll = MagicMock()
    mock_windll.user32.GetForegroundWindow.return_value = 0x12345
    mock_windll.user32.GetWindowTextLengthW.return_value = len(title)
    mock_windll.kernel32.OpenProcess.return_value = 0xABC  # truthy handle
    if exe_path is not None:
        # QueryFullProcessImageNameW writes the exe path into the unicode buffer.
        # It must also return TRUE (1): the implementation guards on the return
        # value (`if kernel32.QueryFullProcessImageNameW(...)`), and a side_effect
        # lambda that only calls setattr returns None, which is falsy.
        def _query_full_process_image_name(hproc, flags, buf, size):
            setattr(buf, "value", exe_path)
            return 1  # Win32 BOOL TRUE

        mock_windll.kernel32.QueryFullProcessImageNameW.side_effect = _query_full_process_image_name
    mock_windll.user32.GetWindowTextW.side_effect = (
        lambda hwnd, buf, length: setattr(buf, "value", title)
    )
    return patch("telemetry.collectors.apps._WINDLL", mock_windll), mock_windll


def test_process_name_mapping_targets_are_whitelisted():
    """Every Windows process name mapping must point to an app in the default whitelist."""
    from telemetry.config import APP_WHITELIST

    mapped = set(PROCESS_NAME_TO_APP_NAME.values())
    not_whitelisted = mapped - set(APP_WHITELIST)
    assert not not_whitelisted, f"Process name mapping targets not whitelisted: {not_whitelisted}"


def test_frontmost_app_name_windows_maps_known_process():
    """When the exe name matches a mapping, return the display name."""
    windll_patch, _mock_windll = _windll_context(
        exe_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    )
    with windll_patch, \
         patch("telemetry.collectors.apps._get_window_process_id", return_value=42):
        result = _frontmost_app_name_windows()
    assert result == "Google Chrome"


def test_frontmost_app_name_windows_falls_back_to_window_title():
    """When the exe name isn't mapped, fall back to the window title."""
    windll_patch, _mock_windll = _windll_context(
        exe_path=r"C:\Program Files\Spotify\spotify.exe", title="Spotify Premium"
    )
    with windll_patch, \
         patch("telemetry.collectors.apps._get_window_process_id", return_value=42):
        result = _frontmost_app_name_windows()
    assert result == "Spotify Premium"


def test_frontmost_app_name_windows_returns_none_when_no_window():
    """When there's no foreground window, return None."""
    windll_patch, mock_windll = _windll_context()
    mock_windll.user32.GetForegroundWindow.return_value = 0
    with windll_patch:
        result = _frontmost_app_name_windows()
    assert result is None


def test_frontmost_app_name_windows_handles_openprocess_failure():
    """When OpenProcess fails, fall back to window title."""
    windll_patch, mock_windll = _windll_context(title="My App Window")
    mock_windll.kernel32.OpenProcess.return_value = 0  # falsy handle
    with windll_patch, \
         patch("telemetry.collectors.apps._get_window_process_id", return_value=42):
        result = _frontmost_app_name_windows()
    assert result == "My App Window"


def test_frontmost_app_name_windows_returns_none_with_blank_title():
    """When the window title is empty, return None (no mapping, no title)."""
    windll_patch, _mock_windll = _windll_context(title="")
    with windll_patch, \
         patch("telemetry.collectors.apps._get_window_process_id", return_value=None):
        result = _frontmost_app_name_windows()
    assert result is None


def test_basename_exe_cross_platform():
    """Basename extraction works for Windows paths on any host OS."""
    from telemetry.collectors.apps import _basename_exe

    assert _basename_exe(r"C:\Program Files\Google\Chrome\Application\chrome.exe") == "chrome"
    assert _basename_exe("/usr/bin/code") == "code"
    assert _basename_exe("C:\\Windows\\System32\\notepad.exe") == "notepad"
