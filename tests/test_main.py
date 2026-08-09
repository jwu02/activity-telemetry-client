import threading
import time
from unittest.mock import MagicMock, patch

from telemetry.config import Config
from main import Runner, run


def make_config(flush_interval_seconds: int = 0) -> Config:
    return Config(
        mongo_uri="mongodb://localhost/test",
        db_name="test",
        collection_name="telemetry",
        flush_interval_seconds=flush_interval_seconds,
        mouse_dpi=72,
        app_whitelist=set(),
    )


def _patched_runner(config, storage, missing_permissions=None):
    """Return a Runner constructed with patched external dependencies."""
    with patch("main.load_config", return_value=config), \
         patch("main.Storage", return_value=storage), \
         patch("main.MouseCollector") as MouseCollector, \
         patch("main.KeyboardCollector") as KeyboardCollector, \
         patch("main.signal.signal"):
        runner = Runner(missing_permissions=missing_permissions or [])
        runner._collectors = {
            "mouse": MouseCollector.return_value,
            "keyboard": KeyboardCollector.return_value,
        }
        return runner, MouseCollector, KeyboardCollector


def test_runner_start_flushes_at_least_once_and_stops_cleanly():
    config = make_config(flush_interval_seconds=0)
    storage = MagicMock()
    storage.flush.return_value = "fake-id"

    runner, MouseCollector, KeyboardCollector = _patched_runner(config, storage)
    runner.state.add_left_click()

    def stop_soon():
        time.sleep(0.05)
        runner._shutdown.set()

    threading.Thread(target=stop_soon).start()
    runner.start()

    assert storage.flush.call_count >= 1
    MouseCollector.return_value.start.assert_called_once()
    KeyboardCollector.return_value.start.assert_called_once()
    MouseCollector.return_value.stop.assert_called_once()
    KeyboardCollector.return_value.stop.assert_called_once()
    storage.close.assert_called_once()


def test_runner_disables_mouse_and_keyboard_when_permissions_missing():
    config = make_config(flush_interval_seconds=0)
    storage = MagicMock()
    storage.flush.return_value = "fake-id"

    runner, MouseCollector, KeyboardCollector = _patched_runner(
        config, storage, missing_permissions=["Input Monitoring", "Accessibility"]
    )

    def stop_soon():
        time.sleep(0.05)
        runner._shutdown.set()

    threading.Thread(target=stop_soon).start()
    runner.start()

    MouseCollector.return_value.start.assert_not_called()
    KeyboardCollector.return_value.start.assert_not_called()
    MouseCollector.return_value.stop.assert_not_called()
    KeyboardCollector.return_value.stop.assert_not_called()
    storage.close.assert_called_once()


def test_runner_preserves_state_when_flush_fails():
    config = make_config(flush_interval_seconds=0)
    storage = MagicMock()
    storage.flush.return_value = None

    runner, *_ = _patched_runner(config, storage)
    runner.state.add_left_click()
    runner.state.add_key_press("A")

    def stop_soon():
        time.sleep(0.05)
        runner._shutdown.set()

    threading.Thread(target=stop_soon).start()
    runner.start()

    snap = runner.state.snapshot()
    assert snap["leftClicks"] == 1
    assert snap["keyboard_heatmap"]["A"] == 1


def test_runner_sleeps_before_first_flush():
    config = make_config(flush_interval_seconds=300)
    storage = MagicMock()
    storage.flush.return_value = "fake-id"

    runner, *_ = _patched_runner(config, storage)
    runner.state.add_left_click()
    runner._shutdown.set()
    runner.start()

    # Only the final flush from stop() should have run.
    assert storage.flush.call_count == 1


def test_runner_does_not_flush_without_activity():
    config = make_config(flush_interval_seconds=300)
    storage = MagicMock()
    storage.flush.return_value = "fake-id"

    runner, *_ = _patched_runner(config, storage)
    runner._shutdown.set()
    runner.start()

    assert storage.flush.call_count == 0
    storage.close.assert_called_once()


def test_run_warns_and_starts_runner_when_permissions_missing():
    with patch("main.check_permissions", return_value=["Input Monitoring"]), \
         patch("main.Runner") as RunnerMock:
        run()
        RunnerMock.assert_called_once_with(missing_permissions=["Input Monitoring"])
        RunnerMock.return_value.start.assert_called_once()


def test_run_starts_runner_when_permissions_ok():
    with patch("main.check_permissions", return_value=[]), \
         patch("main.Runner") as RunnerMock:
        run()
        RunnerMock.assert_called_once_with(missing_permissions=[])
        RunnerMock.return_value.start.assert_called_once()
